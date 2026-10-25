"""Isolated Codex CLI transport only: no assessment rules, confidence or territory logic."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from jsonschema import ValidationError
from layer4.indicators.contracts import validate_wrapper

DISABLED_FEATURES = ('shell_tool','unified_exec','code_mode_host','apps','plugins','multi_agent',
    'multi_agent_v2','browser_use','browser_use_external','browser_use_full_cdp_access',
    'computer_use','in_app_browser','image_generation','view_image','skill_search','hooks','sleep_tool',
    'artifact','workspace_dependencies','memories','goals','tool_suggest','request_permissions_tool')


class CodexCliBlocked(RuntimeError):
    """No fallback engine is allowed."""


def inspect_runtime(command=None):
    """Local capability inspection only; no prompt, authentication or inference."""
    command = command or installed_command()
    def local(args):
        done = subprocess.run([*command, *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=30, check=True, shell=False)
        return done.stdout
    version = local(['--version']).strip()
    help_text = local(['exec', '--help'])
    features = local(['features', 'list'])
    for option in ('--ignore-user-config', '--ignore-rules', '--strict-config', '--ephemeral',
                   '--output-schema', '--output-last-message', '--json', '--sandbox'):
        if option not in help_text:
            raise CodexCliBlocked('Installed CLI lacks required option ' + option)
    feature_names = {line.split()[0] for line in features.splitlines() if line.split()}
    if (set(DISABLED_FEATURES) | {'skip_host_skill_discovery'}) - feature_names:
        raise CodexCliBlocked('Installed CLI cannot confirm required tool restrictions')
    paths = [Path(arg) for arg in command if Path(arg).is_file()]
    return {'cli_version': version, 'command': command,
            'executable_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'exec_help_sha256': hashlib.sha256(help_text.encode()).hexdigest(),
            'features_sha256': hashlib.sha256(features.encode()).hexdigest(),
            'exec_help': help_text, 'features': features,
            'effective_model': None, 'effective_model_status': 'NOT_OBSERVED_NO_INFERENCE',
            'user_config_loaded': False}


def installed_command():
    entry=shutil.which('codex')
    if not entry:raise CodexCliBlocked('Codex CLI is not installed')
    parent=Path(entry).parent
    candidates=list((parent/'node_modules/@openai/codex/node_modules').glob('@openai/codex-win32-*/vendor/*/bin/codex.exe'))
    if len(candidates)==1:return [str(candidates[0])]
    js=parent/'node_modules/@openai/codex/bin/codex.js'
    if js.is_file() and shutil.which('node'):return [shutil.which('node'),str(js)]
    if Path(entry).suffix.lower() not in ('.cmd','.bat','.ps1'):return [entry]
    raise CodexCliBlocked('Cannot resolve installed CLI without a shell wrapper')


class CodexCliAssessmentProvider:
    """One PROJECT per invocation, maxone retry only for technical failures.

    Prompt and schemas are supplied by the caller, keeping all domain decisions
    outside the adapter. subprocess uses an argument vector, stdin and no shell.
    """
    def __init__(self, run_directory, schema_path, input_factory, *, command=None, runner=None, timeout=600,
                 model=None, max_retries=1, max_indicators=2, wrapper_validator=None, execution_id=None,
                 stop_on_uncertain=False):
        self.directory=Path(run_directory).resolve();self.schema=Path(schema_path).resolve()
        self.input_factory=input_factory;self.command=command or installed_command()
        self.runner=runner or subprocess.run;self.timeout=timeout
        if max_retries not in (0, 1):raise ValueError('At most one technical retry')
        self.model=model;self.max_retries=max_retries
        if type(max_indicators) is not int or max_indicators not in (1,2,3,5):
            raise ValueError('Unsupported candidate cap')
        self.max_indicators=max_indicators;self.wrapper_validator=wrapper_validator or validate_wrapper
        self.execution_id=execution_id or uuid.uuid4().hex
        self.stop_on_uncertain=stop_on_uncertain
        self.calls=[];self.raw_outputs=[];self.last_output=None

    def arguments(self,cwd,output):
        args=[*self.command,'exec','--ignore-user-config','--ignore-rules','--strict-config',
              '--ephemeral','--skip-git-repo-check','--sandbox','read-only','--cd',str(cwd),
              '--output-schema',str(self.schema),'--output-last-message',str(output),'--json','--color','never',
              '-c','approval_policy="never"','-c','web_search="disabled"','-c','project_doc_max_bytes=0']
        for feature in DISABLED_FEATURES:
            args+=['--disable',feature]
        args+=['--enable','skip_host_skill_discovery','-']
        if self.model:
            args[-1:-1]=['--model',self.model]
        return args

    def evaluate(self, project, indicators):
        if not 1<=len(indicators)<=self.max_indicators:raise ValueError('Indicator count exceeds configured cap')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',project['project_id']):raise ValueError('Unsafe project run directory ID')
        payload=self.input_factory(project,indicators)
        prompt=payload['prompt'];ids=[i['indicator_id'] for i in indicators]
        for retry in range(self.max_retries+1):
            call_number=len(self.calls)+1
            cwd=self.directory/project['project_id']/('attempt_'+str(retry+1))
            cwd.mkdir(parents=True,exist_ok=False)
            (cwd/'prompt.txt').write_text(prompt,encoding='utf-8')
            output=cwd/'response.json'
            started=datetime.now(timezone.utc).isoformat();error=None;stdout='';stderr='';raw='';exit_status=None;fatal=False;events=[]
            args=self.arguments(cwd,output)
            from .performance import Measurement
            measurement=Measurement()
            try:
                with measurement:
                    done=self.runner(args,input=prompt,cwd=cwd,capture_output=True,text=True,
                                     encoding='utf-8',errors='replace',timeout=self.timeout,shell=False)
                exit_status=done.returncode;stdout=done.stdout;stderr=done.stderr
                raw=output.read_text(encoding='utf-8') if output.is_file() else ''
                for line in stdout.splitlines():
                    try:events.append(json.loads(line))
                    except json.JSONDecodeError:continue
                # Any actual tool use violates this transport's assessment-only scope.
                allowed_items={'agent_message','reasoning','error'}
                tool_used=any(isinstance(e.get('item'),dict) and e['item'].get('type')
                              and e['item']['type'] not in allowed_items
                              for e in events if isinstance(e,dict))
                failure_text=stderr+'\n'+'\n'.join(json.dumps(e) for e in events
                    if isinstance(e,dict) and e.get('type') in ('error','turn.failed'))
                fatal=tool_used or any(s in failure_text.lower() for s in
                    ('insufficient_quota','usage limit','rate limit','not authenticated','authentication failed',
                     'unauthorized','permission denied','unexpected argument','unrecognized feature','invalid configuration',
                     'error loading config','unknown variant','invalid json schema','invalid_json_schema'))
                if fatal:raise CodexCliBlocked('CLI permission/auth/limit/config/tool restriction failure')
                if exit_status!=0:raise RuntimeError('CLI process failed')
                parsed=json.loads(raw)
                self.wrapper_validator(parsed,project['project_id'],ids)
                self.last_output=parsed
            except CodexCliBlocked as exc:
                error=str(exc)
            except (OSError,subprocess.TimeoutExpired,RuntimeError,ValueError,ValidationError) as exc:
                error=type(exc).__name__+': '+str(exc)[:300]
                if isinstance(exc,subprocess.TimeoutExpired):
                    fatal=self.stop_on_uncertain
                    exit_status='TIMEOUT'
                    stdout=exc.stdout or '';stderr=exc.stderr or ''
                    if isinstance(stdout,bytes):stdout=stdout.decode('utf-8',errors='replace')
                    if isinstance(stderr,bytes):stderr=stderr.decode('utf-8',errors='replace')
                if output.is_file():raw=output.read_text(encoding='utf-8')
            finally:
                # Prompts/responses are institutional text under ignored outputs/.
                # No environment, credentials or auth files are recorded.
                (cwd/'events.jsonl').write_text(stdout,encoding='utf-8')
                (cwd/'stderr.txt').write_text(stderr,encoding='utf-8')
                call={'project_id':project['project_id'],'call_number':call_number,'retry':retry,
                      'execution_id':self.execution_id,'performance':getattr(measurement,'result',{}),
                      'exit_status':exit_status,'timestamp':started,'finished_at':datetime.now(timezone.utc).isoformat(),
                      'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                      'working_directory':cwd.relative_to(self.directory.parent).as_posix(),
                      'successful_transport':error is None,'technical_error':error,
                      'sandbox':'read-only','ignore_user_config':True,'tools_requested':False,
                      'arguments':args,'timeout_seconds':self.timeout,'requested_model':self.model,
                      'schema_sha256':hashlib.sha256(self.schema.read_bytes()).hexdigest() if self.schema.is_file() else None,
                      'response_sha256':hashlib.sha256(output.read_bytes()).hexdigest() if output.is_file() else None,
                      'events_sha256':hashlib.sha256((cwd/'events.jsonl').read_bytes()).hexdigest(),
                      'stderr_sha256':hashlib.sha256((cwd/'stderr.txt').read_bytes()).hexdigest(),
                      'usage_observations':[e['usage'] for e in events if isinstance(e,dict) and e.get('type')=='turn.completed' and isinstance(e.get('usage'),dict)],
                      'model_observations':[{k:e[k] for k in ('model','model_name','model_provider') if k in e}
                                            for e in events if isinstance(e,dict) and any(k in e for k in ('model','model_name','model_provider'))]}
                temporary=cwd/'call.json.pending'
                temporary.write_text(json.dumps(call,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                temporary.replace(cwd/'call.json')
                self.calls.append(call)
                self.raw_outputs.append({k:call[k] for k in ('project_id','call_number','retry','exit_status','timestamp')}|
                                        {'raw_output':raw,'technical_error':error})
            if error is None:
                by_id={a['indicator_id']:a for a in self.last_output['assessments']}
                return [{'indicator_id':iid,'assessment':{k:v for k,v in by_id[iid].items() if k!='indicator_id'}} for iid in ids]
            if fatal:
                raise CodexCliBlocked(error)
            if retry==self.max_retries:raise CodexCliBlocked('Technical failure persisted after retry budget: '+error)
