"""Historical Codex artifact/argument verification. New inference is disabled."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from jsonschema import ValidationError
from layer4_evaluation.indicators.contracts import validate_wrapper

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
    """Legacy metadata and argument contract; evaluate() is intentionally disabled."""
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
        raise CodexCliBlocked('Historical Codex transport is read-only. New inference requires run.py and local Ollama.')
