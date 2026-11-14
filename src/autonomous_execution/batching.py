"""Small, sealed batches with independent validation and durable single-job results."""
from copy import deepcopy
from jsonschema import Draft202012Validator, ValidationError
from layer4_evaluation.indicators import context_budget as cb
from layer4_evaluation.indicators.validation_diagnostics import AssessmentValidationError
from . import minimal as m, policy as p, store as s
from .engine import JobError, ScopeError, gate, result_row, identity
from .packing import pack
from layer4_evaluation.indicators.selection import canonical_hash

VERSION='GRAPH_SHARED_EVIDENCE_BATCH_V1'
INSTRUCTIONS=(m.INSTRUCTIONS+'\nLOTE: responde un objeto con una entrada por ID de indicador. '
    'Evalua sus criterios y conclusion de manera independiente. evidence_ids_per_indicator limita '
    'las fuentes permitidas para cada indicador; compartir un pasaje no acredita criterios diferentes. '
    'NOT_SUPPORTED solo si TODOS los criterios carecen de soporte pertinente. Si alguno tiene '
    'soporte parcial, considera INSUFFICIENT_EVIDENCE sin negar ese soporte. '
    'No omitas indicadores. Mantén las reglas individuales.\nINPUT_JSON:\n')


def transport_schema(items):
    """Factor repeated JSON schema definitions; individual stricter schemas still apply."""
    def obj(props):return dict(type='object',properties=props,required=list(props),additionalProperties=False)
    definitions={};props={}
    for item in items:
        individual=m.schema(item['rubric'],item['evidence'],version=item.get('assessment_version',m.v3.VERSION));criteria={}
        for cid,contract in individual['properties']['criteria']['properties'].items():
            key='C'+canonical_hash(contract)
            definitions[key]=contract;criteria[cid]={'$ref':'#/$defs/'+key}
        props[item['iid']]=obj(individual['properties']|dict(criteria=obj(criteria)))
    return obj(props)|{'$defs':definitions}


def item_for(data,manifest,iid,settings):
    rubric=manifest['rubrics'][iid];profile=manifest['profiles'][iid];evidence=m.registry(data,iid)
    version=manifest.get('schema_version',m.v3.VERSION)
    def factory(request,_):
        if manifest.get('batching',{}).get('tokenizer'):request['tokenizer_budget']=manifest['batching']['tokenizer']
        indicator=deepcopy(request['payload']['indicators'][0])
        if indicator.get('key_elements')==[c['criterion'] for c in rubric['criteria']]:indicator.pop('key_elements')
        request['semantic_input']=dict(indicator=indicator,evidence=[dict(id=k,field=v['field'],text=v['text']) for k,v in evidence.items()])
        request['prompt']=(m.SK_INSTRUCTIONS if version==m.v3.SK_VERSION else m.INSTRUCTIONS)+'INPUT_JSON:\n'+cb.compact(request['semantic_input'])
        request['evidence_registry']=evidence
    # Identical preserved GraphRAG intervals and provenance, no shortening for batching.
    request=pack(data,profile,rubric,settings,transport_schema([dict(iid=iid,rubric=rubric,evidence=evidence,assessment_version=version)]),preserve=True,prompt_factory=factory)
    return dict(iid=iid,profile=profile,rubric=rubric,evidence=evidence,request=request,assessment_version=version)


def request_for(items,settings):
    evidence={k:dict(id=k,field=v['field'],text=v['text']) for item in items for k,v in item['evidence'].items()}
    payload=dict(indicators=[item['request']['semantic_input']['indicator'] for item in items],
        evidence=list(evidence.values()),evidence_ids_per_indicator={item['iid']:list(item['evidence']) for item in items})
    schema=transport_schema(items)
    request=deepcopy(items[0]['request'])
    semantic=m.SK_INSTRUCTIONS if items[0].get('assessment_version')==m.v3.SK_VERSION else m.INSTRUCTIONS
    prompt=INSTRUCTIONS.replace(m.INSTRUCTIONS,semantic,1)+cb.compact(payload)
    if items[0].get('assessment_version') == m.v3.SK_VERSION:
        prompt = prompt.replace(
            'NOT_SUPPORTED solo si TODOS los criterios carecen de soporte pertinente.',
            'INSUFFICIENT_EVIDENCE__0 solo si TODOS los criterios carecen de soporte pertinente.')
    if len(items)==1:
        prompt=semantic+'Envuelve la respuesta bajo la clave '+items[0]['iid']+'.\nINPUT_JSON:\n'+cb.compact(items[0]['request']['semantic_input'])
    request.update(prompt=prompt,batch_version=VERSION,
                   batch_indicators=[i['iid'] for i in items],semantic_input=payload)
    request['context_budget']=cb.estimate(request['prompt'],schema,settings,tokenizer=request.get('tokenizer_budget'))
    return request,schema


def validate_item(data,item,answer):
    version=item.get('assessment_version',m.v3.VERSION)
    Draft202012Validator(m.schema(item['rubric'],item['evidence'],version=version)).validate(answer)
    wrapper=m.assemble(data['project'],item['iid'],item['rubric'],item['evidence'],answer,version=version)
    gate(data['project'],item['profile'],item['rubric'],item['request'],wrapper)
    return dict(wrapper=wrapper,row=result_row(data['project'],item['profile'],item['rubric'],wrapper),
        request=item['request'],semantic_answer=answer,evidence_registry=item['evidence'])


class BatchWorker(m.MinimalWorker):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.policy=deepcopy(self.policy)
        self.policy['tiers']=[t for t in self.policy['tiers'] if t['num_ctx']<=6144]
        if not self.policy['tiers']:raise ValueError('Se necesita un presupuesto autorizado <=6144')
        self.policy['tiers']=self.policy['tiers'][-1:]  # Stable context avoids Ollama reallocations between tiers.
        self.policy['max_context']=6144
        self.tokenizer_budget=self.manifest.get('batching',{}).get('tokenizer')
        if self.tokenizer_budget:self.policy['context_margin_tokens']=self.manifest['batching']['context_margin_tokens']
        self.max_output=self.policy['tiers'][0]['num_predict']
        self.project_cache=None
        self.item_cache={}

    def load_project(self,pid):
        # Keep source validation on every job; reuse parsed project and candidate rows.
        if self.project_cache and self.project_cache[0]==pid:
            from . import scope
            scope.check(self.manifest['repository_root'],self.manifest['source_inventory'],self.inventory_cache)
            approved=self.manifest['projects'][pid]
            if s.sha(self.directory/approved['path'])!=approved['sha256']:raise ScopeError('UNAUTHORIZED_PROJECT_TEXT')
            return self.project_cache[1]
        value=super().load_project(pid);self.project_cache=(pid,value);self.item_cache={};return value

    def item(self,data,iid,settings):
        key=(data['project']['project_id'],iid,canonical_hash(settings))
        if key not in self.item_cache:self.item_cache[key]=item_for(data,self.manifest,iid,settings)
        return self.item_cache[key]

    def evaluate(self,data,iid,round_number):
        if round_number:return super().evaluate(data,iid,0)
        size=self.manifest['batching']['size'];pid=data['project']['project_id']
        fallback=self.directory/'batch_fallback'/pid/(iid+'.json')
        if fallback.exists():
            prior=s.read(fallback)
            if prior['manifest_sha256']!=s.sha(self.directory/'manifest.json'):raise ScopeError('BATCH_PRIOR_MANIFEST_CHANGED')
            for path,digest in prior['artifact_hashes'].items():
                if s.sha(self.directory/path)!=digest:raise ScopeError('BATCH_PRIOR_CHANGED')
            return super().evaluate(data,iid,0,prior=prior)
        plan_path=self.directory/'batch_plans'/pid/(iid+'.json')
        previous_plan=s.read(plan_path) if plan_path.exists() else None
        if previous_plan and previous_plan.get('resolved'):return super().evaluate(data,iid,0)
        def settings_for(members):
            import math
            criteria=sum(len(self.manifest['rubrics'][member]['criteria']) for member in members)
            output=min(self.max_output,max(512,math.ceil((128+80*criteria)/64)*64)) if self.tokenizer_budget else self.max_output
            return p.settings(self.manifest['llm'],self.policy,0)|dict(num_predict=output)
        settings=settings_for([iid])
        try:first=self.item(data,iid,settings)
        except JobError:return super().evaluate(data,iid,0)
        # Related indicators first by overlap of verified retrieved source intervals.
        candidates=[]
        for row in self.db.execute("SELECT iid FROM jobs WHERE pid=? AND status='PENDING' AND rounds=0 ORDER BY iid",(pid,)):
            other=row[0]
            if (self.directory/'results'/pid/(other+'.json')).exists():continue
            if (self.directory/'batch_fallback'/pid/(other+'.json')).exists():continue
            # A prior dispatch must be recovered in its own deterministic job, never regrouped.
            if (self.directory/'attempts'/pid/other).exists():continue
            try:item=self.item(data,other,settings)
            except JobError:continue
            overlap=len(set(first['evidence']) & set(item['evidence']))
            if overlap:candidates.append((-overlap,other,item))
        items=[first]
        for _,_,item in sorted(candidates,key=lambda r:(r[0],r[1])):
            trial=items+[item]
            trial_settings=settings_for([i['iid'] for i in trial])
            request,schema=request_for(trial,trial_settings)
            criteria=sum(len(i['rubric']['criteria']) for i in trial)
            # Reserve output as well as input. Never fit by dropping source evidence.
            if request['context_budget']['fits'] and (self.tokenizer_budget or criteria*120+128<=trial_settings['num_predict']):
                items=trial
            if len(items)>=size:break
        if previous_plan:
            items=[self.item(data,member,settings) for member in previous_plan['members']]
        settings=settings_for([i['iid'] for i in items])
        self.policy['tiers'][0]['num_predict']=settings['num_predict']
        request,schema=request_for(items,settings)
        if not request['context_budget']['fits']:return super().evaluate(data,iid,0)
        if self.tokenizer_budget:
            available=settings['num_ctx']-settings['context_margin_tokens']-request['context_budget']['estimated_input_tokens']
            settings['num_predict']=min(self.max_output,int(available//64*64))
            self.policy['tiers'][0]['num_predict']=settings['num_predict']
            request,schema=request_for(items,settings)
        if len(items)==1 and not previous_plan:return super().evaluate(data,iid,0)
        name='batch_'+canonical_hash([i['iid'] for i in items])[:12]
        plan=dict(owner=iid,members=[i['iid'] for i in items],resolved=False,request_sha256=canonical_hash(request))
        if previous_plan and previous_plan!=plan:raise ScopeError('BATCH_PLAN_CHANGED')
        if not previous_plan:s.write(plan_path,plan)
        def build(current,attempt):
            built,transport=request_for(items,current)
            return built,transport
        def adapter(value):return validate_item(data,first,value[iid])['wrapper']
        try:
            self._step(data['project'],first['profile'],first['rubric'],name,build,adapter=adapter,max_attempts=1,
                       first_tier=len(self.policy['tiers'])-1)
        except JobError as exc:
            if exc.code!='INVALID_ASSESSMENT':
                if exc.code=='UNCERTAIN_OUTCOME':self.uncertain_members(pid,iid,items)
                raise
        except KeyboardInterrupt:
            self.uncertain_members(pid,iid,items)
            raise
        native=self.directory/'attempts'/pid/iid/name/'1/transport'/pid/'attempt_1'
        call=s.read(native/'call.json')
        if call['exit_status'] not in (0,'INVALID_ASSESSMENT'):raise JobError(str(call['exit_status']))
        raw=s.read(native/'response.raw.txt')
        native_response=s.read(native/'native_response.json');sent=s.read(native/'request.json')
        if (native_response.get('done') is not True or native_response.get('done_reason')!='stop' or
                __import__('json').loads(native_response['message']['content'])!=raw or
                sent['messages'][0]['content']!=request['prompt'] or sent['format']!=schema or
                identity(call['runtime'])!=identity(self.manifest['runtime'])):
            raise ScopeError('BATCH_TRANSPORT_CHANGED')
        # No incomplete/context-exhausted response can enter this path.
        # A malformed or missing member cannot discard valid sibling answers.
        # Each present member still passes its full individual schema and gates.
        if not isinstance(raw,dict) or set(raw)-{i['iid'] for i in items}:
            return super().evaluate(data,iid,0)
        artifacts={f.relative_to(self.directory).as_posix():s.sha(f) for f in native.parents[2].rglob('*') if f.is_file()}
        accepted={};errors={}
        for item in items:
            member=item['iid']
            try:bundle=validate_item(data,item,raw.get(member))
            except (ValidationError,AssessmentValidationError,JobError,KeyError,TypeError,ValueError) as exc:
                errors[member]=str(exc)
                prior=dict(manifest_sha256=s.sha(self.directory/'manifest.json'),answer=raw.get(member),
                    issues=getattr(exc,'issues',[]),request=item['request'],artifact_hashes=artifacts,
                    shared_call=dict(owner_indicator=iid,step=name,members=[i['iid'] for i in items]))
                s.write(self.directory/'batch_fallback'/pid/(member+'.json'),prior)
                continue
            bundle.update(manifest_sha256=s.sha(self.directory/'manifest.json'),artifact_hashes=artifacts,
                shared_call=dict(owner_indicator=iid,step=name,members=[i['iid'] for i in items],
                    usage_attribution='100% al indicador propietario; demas miembros 0; una llamada por proyecto'))
            s.write(self.directory/'results'/pid/(member+'.json'),bundle);accepted[member]=bundle
        s.write(self.directory/'batch_receipts'/pid/(name+'.json'),dict(members=[i['iid'] for i in items],
            accepted=list(accepted),fallback=list(errors),shared_usage_owner=iid,information_removed=False))
        s.write(plan_path,plan|dict(resolved=True))
        # Only failed members fall back to the unchanged individual adapter.
        return accepted[iid] if iid in accepted else super().evaluate(data,iid,0,prior=s.read(fallback))

    def uncertain_members(self,pid,owner,items):
        for item in items:
            if item['iid']!=owner:
                self.db.execute("UPDATE jobs SET status='UNCERTAIN',error='UNCERTAIN_SHARED_CALL',updated=? WHERE pid=? AND iid=? AND status!='PASS'",
                                (s.now(),pid,item['iid']))
