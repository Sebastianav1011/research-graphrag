"""Bounded per-indicator evaluation and recovery; no decision or score inference in Python."""
from run_paths import file_path as run_file
from copy import deepcopy
import gc
import json
from pathlib import Path
import sqlite3
import shutil
import threading
import time

from jsonschema import Draft202012Validator
from layer4_evaluation.indicators import assessment_v3 as v3, context_budget as cb
from layer4_evaluation.indicators.ollama_provider import OllamaAssessmentProvider, OllamaError, create_client
from layer4_evaluation.indicators.selection import canonical_hash
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError, semantic_issues
from layer4_evaluation.live_execution import validate_context_evidence
from . import store as s, policy as p, scope, phase1, phase11, phase12
from .packing import pack
from .transport import AdaptiveClient


class JobError(RuntimeError):
    def __init__(self, code, *, budget=None):
        self.code = code
        self.budget = budget
        message=code
        if budget and code in ('STATIC_CONTEXT_TOO_LONG','CONTEXT_TOO_LONG'):
            message+=(f': entrada estimada {budget["estimated_input_tokens"]} tokens; '
                      f'presupuesto {budget["input_budget"]} con contexto {budget["num_ctx"]}. '
                      'No se envía la solicitud ni se recorta evidencia. Consulte diagnostics para los niveles probados.')
        super().__init__(message)


class ScopeError(JobError):
    def __init__(self,code,*,detail=None):
        super().__init__(code)
        if detail:self.args=(str(self)+'; '+detail,)


def identity(runtime):
    return {k:runtime.get(k) for k in ('provider','model','digest','server_version','quantization','think','model_metadata_sha256','sdk_version')}


def gate(project, profile, rubric, request, wrapper, ids=None, decision_only=False, coherent=False, integral=False):
    if integral:
        issues=phase12.diagnose(project,profile,rubric,request,wrapper,ids,decision_only)
        if issues:raise AssessmentValidationError(issues)
        return
    iid = profile['indicator_id']
    if wrapper.get('project_id') != project['project_id'] or len(wrapper.get('assessments',[])) != 1 or wrapper['assessments'][0]['indicator_id'] != iid:
        raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE',rule='EXACT_IDS',path='$.assessments')])
    if decision_only:
        return
    item = wrapper['assessments'][0]
    validate_context_evidence(request,wrapper)
    a = {k:v for k,v in item.items() if k!='indicator_id'}
    if ids is None:
        issues = semantic_issues(v3.validate(project['fields'],profile,a,rubric),a,iid,rubric,project['fields'])
        if issues:
            raise AssessmentValidationError(issues)
    else:
        if coherent:
            issues=semantic_issues(v3.validate_criteria(project['fields'],profile,a,rubric,ids),a,iid,rubric,project['fields'])
            if issues:raise AssessmentValidationError(issues)
        actual = [c['criterion_id'] for c in item['criterion_assessments']]
        if len(actual) != len(set(actual)) or set(actual) != set(ids):
            raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE',rule='SHARD_CRITERIA_IDS',path='$.criterion_assessments')])
        for c in item['criterion_assessments']:
            indices = c['evidence_indices']
            if len(indices) != len(set(indices)) or any(i<0 or i>=len(item['evidence']) for i in indices):
                raise AssessmentValidationError([dict(category='EVIDENCE_ID_NOT_FOUND',rule='SHARD_EVIDENCE_INDEX',path='$.criterion_assessments',criterion_id=c['criterion_id'])])
            if (c['support']=='NOT_DEMONSTRATED') != (not indices):
                raise AssessmentValidationError([dict(category='INVALID_FIELD_VALUE',rule='SHARD_SUPPORT_EVIDENCE',path='$.criterion_assessments',criterion_id=c['criterion_id'])])


def result_row(project, profile, rubric, wrapper, provider='ollama'):
    a = {k:v for k,v in wrapper['assessments'][0].items() if k!='indicator_id'}
    errors = v3.validate(project['fields'],profile,a,rubric)
    if errors:
        raise JobError('FINAL_SEMANTIC_VALIDATION')
    row = v3.indicator_row(project,profile,a,rubric)
    row['assessment_engine'] = 'OPENAI_API' if provider=='openai' else 'OLLAMA'
    return row


class Worker:
    def __init__(self, directory, manifest, stop=None, client_factory=None, ram=None, sleep=None):
        self.directory, self.manifest = Path(directory), manifest
        self.policy = manifest['policy']
        self.stop = stop or threading.Event()
        self.client_factory = client_factory or (create_client if manifest['llm'].get('provider')=='openai' else AdaptiveClient)
        self.ram = ram or p.free_ram_mb
        self.sleep = sleep or time.sleep
        self.db = s.connect(directory)
        self.inventory_cache={}
        self.candidate_hashes=s.read(self.directory/'graph.binding.json').get('project_sha256',{}) if (self.directory/'graph.binding.json').exists() else {}

    def close(self):
        self.db.close()

    def load_project(self, pid):
        from layer4_evaluation.indicators.performance import span
        try:
            with span('preparacion'):
                scope.check(self.manifest['repository_root'],self.manifest['source_inventory'],self.inventory_cache)
        except ValueError:
            raise ScopeError('DOCUMENTARY_SCOPE_CHANGED') from None
        ref = self.db.execute('SELECT * FROM projects WHERE pid=?',(pid,)).fetchone()
        approved = self.manifest['projects'][pid]
        if not ref or ref['digest'] != approved['sha256'] or ref['path'] != approved['path']:
            raise ScopeError('PROJECT_CHECKPOINT_CHANGED')
        path = self.directory/approved['path']
        if s.sha(path) != approved['sha256']:
            raise ScopeError('UNAUTHORIZED_PROJECT_TEXT')
        data=s.read(path)
        index=self.directory/'candidate_index.sqlite'
        if index.exists():
            db=sqlite3.connect(index)
            try:
                data['candidates']=[json.loads(r[0]) for r in db.execute("SELECT value FROM rows WHERE kind='candidates' AND pid=?",(pid,))]
                if canonical_hash(data['candidates'])!=self.candidate_hashes.get(pid):
                    raise ScopeError('RETRIEVAL_CHECKPOINT_CHANGED')
            finally:
                db.close()
        return data

    def _usage(self,pid,iid,name,attempt,call):
        obs = call.get('usage_observations',[{}])[0]
        wall = call.get('performance',{}).get('wall_seconds',{}).get('value')
        self.db.execute('INSERT OR REPLACE INTO usage VALUES(?,?,?,?,?,?,?,?)',
            (pid,iid,name,attempt,obs.get('input_tokens'),obs.get('output_tokens'),wall,
             str(call['exit_status']) if call['exit_status'] else None))

    def _step(self, project, profile, rubric, name, build, *, ids=None, decision_only=False, first_tier=0, extra_gate=None,
              adapter=None, max_attempts=None):
        pid,iid=project['project_id'],profile['indicator_id']
        last = 'STEP_BUDGET_EXHAUSTED'
        last_tier=first_tier-1
        corrected=p.coherent(self.policy)
        preserving=p.preserving(self.policy) and adapter is None
        integral=self.policy['version']==p.PHASE12 and adapter is None
        attempts=self.policy['attempts_per_step'] if max_attempts is None else max_attempts
        if type(attempts) is not int or not 1<=attempts<=self.policy['attempts_per_step']:
            raise ValueError('Cantidad de intentos fuera de la politica autorizada')
        repair_calls=0
        repair=[]
        prior=None
        semantic_attempted=False
        previous_source=None
        budget_checks=[]
        for attempt in range(1,attempts+1):
            if self.stop.is_set():
                raise JobError('STOP_REQUESTED')
            next_tier=last_tier if corrected and last=='INVALID_ASSESSMENT' else last_tier+1
            for tier in range(max(0,min(next_tier,len(self.policy['tiers'])-1)),len(self.policy['tiers'])):
                settings = p.settings(self.manifest['llm'],self.policy,tier,decision_only=decision_only)
                try:
                    request, schema = build(settings,attempt)
                except JobError as exc:
                    if exc.code in ('STATIC_CONTEXT_TOO_LONG','CONTEXT_TOO_LONG','NO_EVIDENCE_FITS','EVIDENCE_COVERAGE_BUDGET'):
                        budget_checks.append(dict(attempt=attempt,tier=tier,reason=exc.code,**(exc.budget or {})))
                        last=exc.code;continue
                    raise
                if preserving:
                    current_source=canonical_hash(request['payload']['project'].get('fields',request['payload'].get('source_spans')))
                    if previous_source is not None and current_source!=previous_source:
                        raise ScopeError('REPAIR_SOURCE_COVERAGE_CHANGED')
                    if prior is not None and repair:
                        patched=(phase12.patch_request(request,schema,prior,repair,project,profile,rubric,
                            reevaluate=repair_calls>0,ids=ids,decision_only=decision_only) if integral else
                            phase11.patch_request(request,schema,prior,repair,project))
                        if patched:
                            request,schema=patched;semantic_attempted=True
                        elif semantic_attempted:
                            raise JobError('SEMANTIC_REPAIR_UNRESOLVED')
                    elif repair:
                        request['prompt']+=phase1.feedback(repair)
                        request['repair_information']=dict(prior_unavailable_or_schema_invalid=True,
                            sources_removed=[],source_hash=current_source)
                elif corrected and repair:
                    request['prompt']+=phase1.feedback(repair)
                request['context_budget'] = cb.estimate(request['prompt'],schema,settings,tokenizer=request.get('tokenizer_budget'))
                budget_checks.append(dict(attempt=attempt,tier=tier,**request['context_budget']))
                if request['context_budget']['fits']:
                    break
                last='CONTEXT_TOO_LONG'
            else:
                s.write(self.directory/'diagnostics'/pid/iid/(name+'.budget.json'),dict(
                    code=last,stage=name,model=self.manifest['llm']['model'],project_count=1,
                    checks=budget_checks,information_removed=False,this_attempt_dispatched=False,
                    reason='Ningún nivel autorizado admite la solicitud completa. No se recorta evidencia ni se asigna un resultado; revise el presupuesto y la memoria disponibles.'))
                if preserving and last=='EVIDENCE_COVERAGE_BUDGET':
                    s.write(self.directory/'diagnostics'/pid/iid/(name+'.coverage.json'),dict(
                        code='EVIDENCE_COVERAGE_BLOCKED',information_removed=False,policy=self.policy,
                        criteria=ids or [c['criterion_id'] for c in rubric['criteria']]))
                    raise JobError('EVIDENCE_COVERAGE_BLOCKED')
                if corrected and decision_only:
                    s.write(self.directory/'diagnostics'/pid/iid/(name+'.budget.json'),dict(
                        code='SYNTHESIS_CONTEXT_TOO_LONG',checks=budget_checks,
                        strategy=phase1.VERSION,information_dropped=False,this_attempt_dispatched=False))
                    raise JobError('SYNTHESIS_CONTEXT_TOO_LONG')
                raise JobError(last,budget=budget_checks[-1] if budget_checks and 'estimated_input_tokens' in budget_checks[-1] else None)
            last_tier=tier
            out=self.directory/'attempts'/pid/iid/name/str(attempt)
            original=self.db.execute('SELECT * FROM steps WHERE pid=? AND iid=? AND name=? AND attempt=?',
                (pid,iid,name,attempt)).fetchone()
            native_dir=out/'transport'/pid/'attempt_1'
            def decoded(value):
                if adapter is not None:return adapter(value)
                if 'repair_contract' not in request:return value
                return (phase12.apply_patch(request,value,project,profile,rubric,ids,decision_only) if integral
                        else phase11.apply_patch(request,value))
            def validate(value,*args):
                try:
                    value=decoded(value)
                    gate(project,profile,rubric,request,value,ids,decision_only,coherent=corrected,integral=integral)
                    if extra_gate:extra_gate(value)
                except AssessmentValidationError as exc:
                    if integral:
                        receipt=getattr(exc,'diagnostics',dict(version=phase12.VERSION,
                            before=request.get('repair_contract',{}).get('before',exc.issues),after=exc.issues,
                            source_hash=canonical_hash(request['payload']['project'].get('fields',request['payload'].get('source_spans'))),sources_removed=[]))
                        s.write(out/'validation.diagnostics.json',receipt)
                    raise
            def remember(call):
                nonlocal prior,previous_source,semantic_attempted,repair_calls
                if not preserving:return
                previous_source=canonical_hash(request['payload']['project'].get('fields',request['payload'].get('source_spans')))
                if call['exit_status']!='INVALID_ASSESSMENT':return
                if 'repair_contract' in request:
                    prior=request['repair_contract']['prior'];semantic_attempted=True;repair_calls+=1;return
                path=native_dir/'response.raw.txt'
                try:value=s.read(path)
                except (ValueError,FileNotFoundError):return
                if Draft202012Validator(schema).is_valid(value):
                    prior=value;semantic_attempted=True
            def accepted(value):
                result=decoded(value)
                if 'repair_contract' in request:
                    receipt=(phase12.repair_receipt(request,value,result) if integral else phase11.repair_receipt(request,value,result))
                    s.write(out/'repair.receipt.json',receipt)
                return result,request
            # A completed transport is recovered offline if the process died before
            # its step receipt or job transaction. An in-flight call is never guessed.
            if original:
                descriptor=s.read(out/'step.json')
                if descriptor != dict(request=request,schema=schema,settings=settings):
                    raise ScopeError('STEP_POLICY_OR_TEXT_CHANGED')
                if (native_dir/'call.json').exists():
                    call=s.read(native_dir/'call.json'); self._usage(pid,iid,name,attempt,call)
                    if call['successful_transport']:
                        value=s.read(native_dir/'response.json')
                        native=s.read(native_dir/'native_response.json')
                        payload=s.read(native_dir/'request.json')
                        if (call['response_sha256']!=s.sha(native_dir/'response.json') or
                            native.get('done') is not True or native.get('done_reason')!='stop' or
                            json.loads(native['message']['content'])!=value or payload['messages'][0]['content']!=request['prompt'] or
                            payload['format']!=schema or identity(call['runtime'])!=identity(self.manifest['runtime'])):
                            raise ScopeError('COMPLETED_TRANSPORT_CHANGED')
                        Draft202012Validator(schema).validate(value);validate(value)
                        self.db.execute("UPDATE steps SET status='PASS' WHERE pid=? AND iid=? AND name=? AND attempt=?",(pid,iid,name,attempt))
                        return accepted(value)
                    last=str(call['exit_status'])
                    repair=call.get('validation_issues',[])
                    remember(call)
                    if last in ('TIMEOUT','INTERRUPTED','SERVER_UNAVAILABLE','INFERENCE_ERROR'):
                        raise JobError('UNCERTAIN_OUTCOME')
                    if last.startswith('API_'):
                        if 'UNCERTAIN' in last:raise JobError('UNCERTAIN_OUTCOME')
                        self.stop.set();raise JobError(last)
                    if last in ('OUT_OF_MEMORY','RUNTIME_DRIFT'):
                        raise JobError(last)
                    continue
                if (out/'dispatch.claim.json').exists():
                    raise JobError('UNCERTAIN_OUTCOME')
            available_ram=self.ram()
            if available_ram < self.policy['min_free_ram_mb']:
                raise JobError('RESOURCE_RAM_FLOOR')
            available_disk=shutil.disk_usage(self.directory).free//(1024*1024)
            if available_disk < self.policy['min_free_disk_mb']:
                raise JobError('RESOURCE_DISK_FLOOR')
            client=self.client_factory(settings)
            try:
                for inspection in range(self.policy['metadata_attempts']):
                    try:
                        runtime=client.inspect()  # Idempotent metadata; never inference.
                        break
                    except OllamaError as exc:
                        if exc.code not in ('SERVER_UNAVAILABLE','SERVER_ERROR','SERVER_BUSY','TIMEOUT') or inspection+1==self.policy['metadata_attempts']:
                            raise
                        s.event(self.db,'preflight','METADATA_RETRY_'+exc.code,pid,iid)
                        self.sleep(self.policy['cooldown_seconds'])
            except OllamaError as exc:
                if exc.code=='CONTEXT_TOO_LONG':
                    last='MODEL_CONTEXT_CAP';continue
                raise
            if identity(runtime)!=identity(self.manifest['runtime']):
                raise ScopeError('RUNTIME_DRIFT')
            out.mkdir(parents=True,exist_ok=True)
            s.write(out/'resources.json',dict(free_ram_mb=available_ram,free_disk_mb=available_disk,
                context=settings['num_ctx'],output=settings['num_predict'],workers=self.policy['workers'],
                stage=name,model=settings['model'],project_count=1,
                fragment_count=len(request.get('context_selection',{}).get('selected',[])),
                context_budget_checks=budget_checks))
            s.write(out/'step.json',dict(request=request,schema=schema,settings=settings))
            s.write(out/'schema.json',schema)
            with s.transaction(self.db):
                self.db.execute('INSERT OR REPLACE INTO steps VALUES(?,?,?,?,?,?,?)',
                    (pid,iid,name,attempt,'RUNNING',out.relative_to(self.directory).as_posix(),None))
                self.db.execute('UPDATE jobs SET attempts=attempts+1,updated=? WHERE pid=? AND iid=?',(s.now(),pid,iid))
                s.event(self.db,'evaluation','DISPATCH',pid,iid)
            s.write(out/'dispatch.claim.json',dict(manifest_sha256=s.sha(self.directory/'manifest.json'),request_sha256=canonical_hash(request)))
            provider=OllamaAssessmentProvider(out/'transport',out/'schema.json',lambda *_:request,
                settings=settings,client=client,runtime=runtime,wrapper_validator=validate,max_indicators=1,
                execution_id=self.manifest['execution_id'],output_adapter=adapter)
            error=None
            try:
                provider.evaluate(project,[profile])
            except OllamaError as exc:
                error=exc.code
            finally:
                if provider.calls:
                    self._usage(pid,iid,name,attempt,provider.calls[0])
                    repair=provider.calls[0].get('validation_issues',[])
                    remember(provider.calls[0])
            if not error:
                self.db.execute("UPDATE steps SET status='PASS' WHERE pid=? AND iid=? AND name=? AND attempt=?",(pid,iid,name,attempt))
                return accepted(provider.last_output)
            self.db.execute("UPDATE steps SET status='ERROR',error=? WHERE pid=? AND iid=? AND name=? AND attempt=?",(error,pid,iid,name,attempt))
            if error in ('TIMEOUT','INTERRUPTED','SERVER_UNAVAILABLE','INFERENCE_ERROR'):
                raise JobError('UNCERTAIN_OUTCOME')
            if error.startswith('API_') or error=='STOP_REQUESTED':
                if 'UNCERTAIN' in error or error=='API_OUTCOME_UNCERTAIN':raise JobError('UNCERTAIN_OUTCOME')
                self.stop.set()
                raise JobError(error)
            if error=='RUNTIME_DRIFT':
                raise ScopeError(error)
            if error=='OUT_OF_MEMORY':
                raise JobError(error)
            last=error
            if not corrected or attempt<attempts:
                self.sleep(self.policy['cooldown_seconds'])
        raise JobError('SEMANTIC_REPAIR_UNRESOLVED' if preserving and semantic_attempted else last)

    def evaluate(self, data, iid, round_number):
        project=data['project'];profile=self.manifest['profiles'][iid];rubric=self.manifest['rubrics'][iid]
        prefix='r'+str(round_number)+'_'
        corrected=p.coherent(self.policy)
        preserving=p.preserving(self.policy)
        integral=self.policy['version']==p.PHASE12
        schema=p.schema(project['fields'],self.policy,criterion_ids=[c['criterion_id'] for c in rubric['criteria']] if corrected else None)
        def full(settings,attempt):
            return pack(data,profile,rubric,settings,schema,concise=corrected,preserve=preserving,integral=integral),schema
        first=p.start_tier(self.policy,len(rubric['criteria']))
        try:
            wrapper,request=self._step(project,profile,rubric,prefix+'full',full,first_tier=first)
            return dict(wrapper=wrapper,row=result_row(project,profile,rubric,wrapper,self.manifest['llm']['provider']),request=request)
        except ScopeError:
            raise
        except JobError as exc:
            if exc.code not in ('INCOMPLETE_RESPONSE','INVALID_ASSESSMENT','CONTEXT_TOO_LONG','CONTEXT_EXHAUSTED','STATIC_CONTEXT_TOO_LONG','MODEL_CONTEXT_CAP','NO_EVIDENCE_FITS','EVIDENCE_COVERAGE_BLOCKED'):
                raise
        # Shards retain every original criterion, with exact IDs and the same sources.
        criteria=rubric['criteria'];size=self.policy['criteria_per_shard']
        evidence=[];judgments=[];requests=[]
        groups=[(offset,criteria[offset:offset+size],False) for offset in range(0,len(criteria),size)]
        while groups:
            offset,selected,divided=groups.pop(0);ids=[c['criterion_id'] for c in selected]
            shard_schema=p.schema(project['fields'],self.policy,ids=ids)
            def shard(settings,attempt):
                return pack(data,profile,rubric,settings,shard_schema,criterion_ids=ids,concise=corrected,preserve=preserving,integral=integral),shard_schema
            name=prefix+'shard_'+str(offset)+('_n'+str(len(selected)) if divided else '')
            try:wrapper,request=self._step(project,profile,rubric,name,shard,ids=ids)
            except JobError as exc:
                if preserving and exc.code in ('EVIDENCE_COVERAGE_BLOCKED','STATIC_CONTEXT_TOO_LONG') and len(selected)>1:
                    middle=len(selected)//2
                    groups[0:0]=[(offset,selected[:middle],True),(offset+middle,selected[middle:],True)]
                    continue
                raise
            item=wrapper['assessments'][0];base=len(evidence)
            evidence.extend(item['evidence'])
            judgments.extend([{**c,'evidence_indices':[i+base for i in c['evidence_indices']]} for c in item['criterion_assessments']])
            requests.append(request)
        if corrected:
            evidence,judgments=phase1.merge(evidence,judgments)
            issues=semantic_issues(v3.validate_criteria(project['fields'],profile,
                dict(criterion_assessments=judgments,evidence=evidence),rubric,[c['criterion_id'] for c in criteria]),
                dict(criterion_assessments=judgments,evidence=evidence),iid,rubric,project['fields'])
            if issues:raise AssessmentValidationError(issues)
        decision_schema=p.schema(project['fields'],self.policy,decision_only=True)
        def synthesis(settings,attempt):
            if corrected:
                request=phase1.synthesis(project,profile,rubric,requests,judgments,evidence)
                if preserving:
                    phase11.compact_catalog(request,rubric)
                    request['prompt']=p.NORMATIVE+p.REPAIR+phase11.FIDELITY+phase1.INSTRUCTIONS+'\nINPUT_JSON:\n'+cb.compact(request['payload'])
                    if integral:
                        request['prompt']=p.NORMATIVE+phase12.CLASSIFICATION+phase1.INSTRUCTIONS+'\nINPUT_JSON:\n'+cb.compact(request['payload'])
                return request,decision_schema
            request=cb.make_request(project,profile,rubric,requests[0]['payload']['project']['fields'])
            request['context_selection']=requests[0]['context_selection']
            payload=deepcopy(request['payload'])
            payload['verified_criterion_assessments']=judgments
            payload['verified_evidence']=evidence
            request['prompt']=p.NORMATIVE+p.REPAIR+p.SYNTHESIS+'\nINPUT_JSON:\n'+cb.compact(payload)
            request['payload']=payload
            return request,decision_schema
        def decision_gate(value):
            a={k:v for k,v in value['assessments'][0].items() if k!='indicator_id'}
            a.update(assessment_version=v3.VERSION,criterion_assessments=judgments,evidence=evidence)
            issues=semantic_issues(v3.validate(project['fields'],profile,a,rubric),a,profile['indicator_id'],rubric,project['fields'])
            if issues:
                raise AssessmentValidationError(issues)
        wrapper,request=self._step(project,profile,rubric,prefix+'synthesis',synthesis,decision_only=True,extra_gate=decision_gate)
        final=wrapper['assessments'][0]
        final.update(assessment_version=v3.VERSION,criterion_assessments=judgments,evidence=evidence)
        # Every quote must have been sent in a verified shard; final normative
        # validation enforces all roles, temporalities and decision consistency.
        for item in evidence:
            if not any(item['text'] in (r['payload']['project']['fields'].get(item['field']) or '') for r in requests):
                raise JobError('MERGED_QUOTE_NOT_IN_CONTEXT')
        row=result_row(project,profile,rubric,wrapper,self.manifest['llm']['provider'])
        return dict(wrapper=wrapper,row=row,request=request,shard_requests=requests)

    def adopt(self, job, data, *, commit=True):
        path=self.directory/'results'/job['pid']/(job['iid']+'.json')
        if not path.exists():
            return False
        if job.get('result_hash') and s.sha(path)!=job['result_hash']:
            raise ScopeError('RESULT_RECEIPT_CHANGED')
        bundle=s.read(path)
        # Revalidate a durable receipt before skipping inference, even after restart.
        if bundle.get('manifest_sha256')!=s.sha(self.directory/'manifest.json'):
            raise ScopeError('RESULT_FROM_ANOTHER_MANIFEST')
        profile=self.manifest['profiles'][job['iid']];rubric=self.manifest['rubrics'][job['iid']]
        row=result_row(data['project'],profile,rubric,bundle['wrapper'],self.manifest['llm']['provider'])
        if row!=bundle['row']:
            raise ScopeError('RESULT_SCORE_CHANGED')
        for name,digest in bundle.get('artifact_hashes',{}).items():
            target=(self.directory/name).resolve()
            if not target.is_relative_to(self.directory.resolve()) or s.sha(target)!=digest:
                raise ScopeError('RESULT_TRANSPORT_CHANGED')
        if bundle.get('shard_requests'):
            for e in bundle['wrapper']['assessments'][0]['evidence']:
                if not any(e['text'] in (r['payload']['project']['fields'].get(e['field']) or '') for r in bundle['shard_requests']):
                    raise ScopeError('RESULT_QUOTE_CONTEXT_CHANGED')
        else:
            validate_context_evidence(bundle['request'],bundle['wrapper'])
        if commit:
            self.db.execute("UPDATE jobs SET status='PASS',result_path=?,result_hash=?,error=NULL,updated=? WHERE pid=? AND iid=?",
                (path.relative_to(self.directory).as_posix(),s.sha(path),s.now(),job['pid'],job['iid']))
        return True

    def loop(self):
        from layer4_evaluation.indicators.performance import span
        service_errors=0
        try:
            while not self.stop.is_set():
                if (run_file(self.directory.parents[1], 'stop.request.json')).exists():
                    self.stop.set();return
                job=s.claim(self.db)
                if not job:
                    return
                interval=span(project=job['pid']);interval.__enter__()
                try:
                    data=self.load_project(job['pid'])
                    if not self.adopt(job,data):
                        bundle=self.evaluate(data,job['iid'],job['rounds'])
                        bundle['manifest_sha256']=s.sha(self.directory/'manifest.json')
                        bundle['artifact_hashes']=bundle.get('artifact_hashes',{})|{f.relative_to(self.directory).as_posix():s.sha(f) for f in
                            (self.directory/'attempts'/job['pid']/job['iid']).rglob('*') if f.is_file()}
                        s.write(self.directory/'results'/job['pid']/(job['iid']+'.json'),bundle)
                        self.adopt(job,data)
                    service_errors=0
                    s.event(self.db,'evaluation','PASS',job['pid'],job['iid'])
                except ScopeError as exc:
                    self.stop.set()
                    self.db.execute("UPDATE jobs SET status='BLOCKED',error=?,updated=? WHERE pid=? AND iid=?",(exc.code,s.now(),job['pid'],job['iid']))
                    s.event(self.db,'paused',exc.code,job['pid'],job['iid'])
                    raise
                except JobError as exc:
                    state='UNCERTAIN' if exc.code=='UNCERTAIN_OUTCOME' else 'BLOCKED'
                    self.db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE pid=? AND iid=?',(state,exc.code,s.now(),job['pid'],job['iid']))
                    s.event(self.db,'evaluation',exc.code,job['pid'],job['iid'])
                    if exc.code in ('OUT_OF_MEMORY','RESOURCE_RAM_FLOOR','RESOURCE_DISK_FLOOR','STOP_REQUESTED'):
                        self.stop.set()
                    if exc.code in ('UNCERTAIN_OUTCOME','SERVER_UNAVAILABLE','SERVER_BUSY','SERVER_ERROR'):
                        service_errors+=1
                        if service_errors>=self.policy['consecutive_service_failures']:
                            self.stop.set()
                except OllamaError as exc:  # Pre-dispatch metadata, never a guessed decision.
                    state='PENDING' if exc.code in ('SERVER_UNAVAILABLE','SERVER_ERROR','SERVER_BUSY','TIMEOUT') else 'BLOCKED'
                    self.db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE pid=? AND iid=?',(state,exc.code,s.now(),job['pid'],job['iid']))
                    s.event(self.db,'paused',exc.code,job['pid'],job['iid'])
                    self.stop.set()
                except KeyboardInterrupt:
                    self.stop.set();raise
                except Exception:
                    self.stop.set()
                    self.db.execute("UPDATE jobs SET status='BLOCKED',error='INTERNAL_ERROR',updated=? WHERE pid=? AND iid=?",(s.now(),job['pid'],job['iid']))
                    s.event(self.db,'paused','INTERNAL_ERROR',job['pid'],job['iid'])
                    raise JobError('INTERNAL_ERROR') from None
                finally:
                    interval.__exit__(None,None,None)
                    self.db.execute("INSERT OR REPLACE INTO meta VALUES('stage',?)",('paused' if self.stop.is_set() else 'evaluation',))
                    if time.monotonic()-getattr(self,'last_console_progress',0)>=10 or self.stop.is_set():
                        from .monitor import snapshot
                        state=snapshot(self.directory)
                        print(f"[GraphRAG] {state['evaluated']}/{state['indicators_total']} indicadores válidos "
                              f"({state['progress_percent']} %); proyectos completos {state['projects_completed']}/{state['projects_total']}; "
                              f"actual {job['pid']}; bloqueados {state['blocked']}; llamadas {state['calls']}",flush=True)
                        self.last_console_progress=time.monotonic()
                    gc.collect()
        finally:
            self.close()
