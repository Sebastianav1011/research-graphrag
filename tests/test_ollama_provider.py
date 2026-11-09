"""Light local-provider integration checks. All HTTP and inference are mocked."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from layer4_evaluation.indicators import ollama_provider as transport, assessment_v3 as v3, global_discovery_v3_3 as gd
from layer4_evaluation import live_execution as live
from layer2_processing.preprocessing.adapters import read, write, sha
from scripts import pipeline_coordinator as coordinator
import tests.layer5_experiment.test_assessment_v3 as assessment_samples
import tests.layer5_experiment.test_global_discovery_v3_3 as discovery_samples


def runtime(settings=None):
    settings = transport.configuration(settings)
    return dict(provider='ollama', model=settings['model'], digest='test-local-digest', server_version='mock',
                configuration=settings, configuration_sha256=transport.canonical_hash(settings),
                quantization='Q4_K_M', capabilities=['completion', 'thinking'], think=False,
                template_bytes=0, model_metadata_sha256='test-metadata')


def response(wrapper):
    return dict(model=transport.DEFAULTS['model'], done=True, done_reason='stop',
                message=dict(role='assistant', content=json.dumps(wrapper), thinking='Not the final answer'),
                prompt_eval_count=100, eval_count=50)


@pytest.fixture
def sample():
    return assessment_samples.case.__wrapped__()


@pytest.fixture
def provider_case(tmp_path, sample):
    project = dict(project_id='TEST_PROJECT', siap_id='TEST', fields=sample['fields'])
    profile = sample['profile']
    request = v3.make_input(dict(project_id=project['project_id'], fields=project['fields']),
        [profile], {}, {profile['indicator_id']:sample['rubric']})
    wrapper = dict(project_id=project['project_id'], assessments=[dict(indicator_id=profile['indicator_id'], **deepcopy(sample['assessment']))])
    schema = tmp_path/'schema.json'
    write(schema, v3.schemas(project['fields'])['assessment_batch'])
    # Larger context is ONLY a mocked transport fixture; no model is loaded.
    binding = runtime({'num_ctx':131072})
    client = Mock(spec=transport.OllamaClient)
    client.inspect.return_value = binding
    client.request.return_value = response(wrapper)
    def gate(value, pid, ids):
        v3.validate_wrapper(value, pid, ids, project['fields'])
        for assessment in value['assessments']:
            errors = v3.validate(project['fields'], profile,
                {k:v for k,v in assessment.items() if k!='indicator_id'}, sample['rubric'])
            if errors:
                raise ValueError('Invalid evidence')
    provider = transport.OllamaAssessmentProvider(tmp_path/'runs', schema, lambda p,i:request,
        settings=binding['configuration'], client=client, wrapper_validator=gate, execution_id='test-execution')
    return provider, client, project, profile, request, wrapper


def test_valid_request_preserves_prompt_schema_contract_and_final_content(provider_case):
    provider, client, project, profile, request, wrapper = provider_case
    result = provider.evaluate(project, [profile])
    args = client.request.call_args.args
    assert args[:2] == ('POST', '/api/chat')
    payload = args[2]
    assert payload['messages'] == [dict(role='user', content=request['prompt'])]
    assert payload['format'] == read(provider.schema) and payload['stream'] is False and payload['think'] is False
    assert payload['truncate'] is False and payload['shift'] is False
    assert payload['options']['temperature'] == 0
    assert provider.last_output == wrapper and result[0]['assessment']['decision'] == 'SUPPORTED'
    call = provider.calls[0]
    assert call['provider'] == 'ollama' and call['runtime']['digest'] == 'test-local-digest' and call['retry'] == 0
    assert call['prompt_sha256'] == hashlib.sha256(request['prompt'].encode()).hexdigest()


@pytest.mark.parametrize('change', [
    lambda r:r['message'].update(content='not JSON'),
    lambda r:r['message'].update(content='{"project_id":"A","project_id":"B"}'),
    lambda r:r['message'].update(content='{"assessments": []}'),
    lambda r:r.update(done=False),
    lambda r:r.update(done_reason='length'),
    lambda r:r['message'].update(content=''),
])
def test_invalid_or_incomplete_response_is_error_not_not_supported(provider_case, change):
    provider, client, project, profile, _, _ = provider_case
    change(client.request.return_value)
    with pytest.raises(transport.OllamaError):
        provider.evaluate(project, [profile])
    assert provider.last_output is None and not provider.calls[0]['successful_transport']
    assert client.request.call_count == 1


def test_fabricated_quote_is_rejected_and_confidence_is_unchanged(provider_case, sample):
    provider, client, project, profile, _, wrapper = provider_case
    wrapper['assessments'][0]['evidence'][0]['text'] = 'A fabricated citation absent from the source'
    client.request.return_value = response(wrapper)
    with pytest.raises(transport.OllamaError, match='INVALID_ASSESSMENT'):
        provider.evaluate(project, [profile])
    original = v3.indicator_row(project, profile, sample['assessment'], sample['rubric'])
    plan = dict(runtime={'provider':'ollama'}, profiles={profile['indicator_id']:profile}, rubrics={profile['indicator_id']:sample['rubric']})
    local = live.indicator_row(plan, project, dict(indicator_id=profile['indicator_id'], **sample['assessment']))
    assert local == original | {'assessment_engine':'OLLAMA'}
    assert local['confidence_raw_score'] == 100


@pytest.mark.parametrize('endpoint', ['https://example.com', 'http://192.168.0.2:11434', 'http://localhost:11434/path', 'http://user:pass@localhost'])
def test_remote_or_unsafe_endpoint_rejected_without_network(endpoint):
    with pytest.raises(ValueError, match='Endpoint'):
        transport.OllamaClient({'endpoint':endpoint})


def test_initialization_and_metadata_never_download_or_infer():
    client = transport.OllamaClient()
    client.request = Mock(side_effect=[{'version':'mock'}, {'models':[dict(name=transport.DEFAULTS['model'], digest='local')]},
        dict(details=dict(format='gguf', quantization_level='Q4_K_M'), capabilities=['completion', 'thinking'], thinking={'values':[False, True]})])
    info = client.inspect()
    assert info['think'] is False and info['digest'] == 'local'
    assert [call.args[1] for call in client.request.call_args_list] == ['/api/version', '/api/tags', '/api/show']


@pytest.mark.parametrize('mode', ['missing', 'cloud'])
def test_model_must_be_installed_and_local(mode):
    client = transport.OllamaClient()
    model = dict(name=transport.DEFAULTS['model'], digest='local')
    info = dict(details=dict(format='gguf', quantization_level='Q4_K_M'))
    if mode == 'cloud':
        info['remote_host'] = 'https://remote.invalid'
    client.request = Mock(side_effect=[{'version':'mock'}, {'models':[] if mode=='missing' else [model]}, info])
    with pytest.raises(transport.OllamaError, match='MODEL_NOT_INSTALLED' if mode=='missing' else 'REMOTE_MODEL_BLOCKED'):
        client.inspect()


@pytest.mark.parametrize('exception,code', [(TimeoutError(), 'TIMEOUT'), (ConnectionRefusedError(), 'SERVER_UNAVAILABLE')])
def test_http_timeouts_and_unavailable_server(monkeypatch, exception, code):
    connection = Mock()
    connection.request.side_effect = exception
    monkeypatch.setattr(transport.http.client, 'HTTPConnection', Mock(return_value=connection))
    with pytest.raises(transport.OllamaError, match=code):
        transport.OllamaClient().request('GET', '/api/version')
    connection.close.assert_called_once()


def test_memory_error_and_redirect_are_not_remote_fallback(monkeypatch):
    connection = Mock()
    reply = connection.getresponse.return_value
    reply.status = 500
    reply.read.return_value = b'{"error":"out of memory"}'
    monkeypatch.setattr(transport.http.client, 'HTTPConnection', Mock(return_value=connection))
    with pytest.raises(transport.OllamaError, match='OUT_OF_MEMORY'):
        transport.OllamaClient().request('POST', '/api/chat', {})
    reply.status = 302
    reply.read.return_value = b'{}'
    with pytest.raises(transport.OllamaError, match='SERVER_ERROR'):
        transport.OllamaClient().request('GET', '/api/version')


def test_context_is_blocked_before_inference(provider_case):
    provider, client, project, profile, _, _ = provider_case
    provider.settings = transport.configuration()
    client.inspect.return_value = runtime()
    provider.input_factory = lambda p,i:dict(prompt='x'*10000)
    with pytest.raises(transport.OllamaError, match='CONTEXT_TOO_LONG'):
        provider.evaluate(project, [profile])
    client.request.assert_not_called()


def test_digest_drift_does_not_accept_response(provider_case):
    provider, client, project, profile, _, _ = provider_case
    binding = deepcopy(client.inspect.return_value)
    client.inspect.side_effect = [binding, binding | {'digest':'other-version'}]
    with pytest.raises(transport.OllamaError, match='RUNTIME_DRIFT'):
        provider.evaluate(project, [profile])
    assert provider.last_output is None


def test_codex_cannot_dispatch_new_inference():
    from layer4_evaluation.indicators.codex_cli import CodexCliAssessmentProvider, CodexCliBlocked
    provider = object.__new__(CodexCliAssessmentProvider)
    with pytest.raises(CodexCliBlocked, match='read-only'):
        provider.evaluate({}, [])


@pytest.fixture
def live_run(tmp_path, monkeypatch):
    project, profiles, make_response = discovery_samples.case.__wrapped__()
    project['siap_id'] = 'TEST'
    settings = transport.configuration({'num_ctx':131072})  # Mock capacity, not a hardware recommendation.
    plan = dict(execution_id='test-execution', projects=[project], profiles={p['indicator_id']:p for p in profiles},
        rubrics={}, rules={}, runtime=dict(provider='ollama', configuration=settings), requested_model=settings['model'],
        budgets=dict(discovery_reservation=80000, discovery_postcall_review_threshold=60000),
        maximum_calls=3, total_token_reservation_cap=170000, timeout_seconds=600, observed_character_ratio=.1,
        discovery_version=gd.VERSION, assessment_version=v3.VERSION, source_hashes={})
    monkeypatch.setattr(live, 'BASE', tmp_path)
    directory = tmp_path/'batch_test'
    write(directory/'plan.json', plan)
    write(directory/'cache.json', {})
    write(directory/'review.json', {'fixture':'reviewed synthetic text'})
    (directory/'review.txt').write_text('Synthetic review', encoding='utf-8')
    write(directory/'manifest.json', dict(plan_sha256=sha(directory/'plan.json'),
        files={name:sha(directory/name) for name in ('cache.json', 'review.json', 'review.txt')}))
    client = Mock(spec=transport.OllamaClient)
    client.inspect.return_value = runtime(settings)
    client.request.return_value = response(make_response(0))
    monkeypatch.setattr(live, 'OllamaClient', lambda settings:client)
    return directory, client


def test_existing_live_loop_authorizes_records_verifies_and_resumes_offline(live_run):
    directory, client = live_run
    with pytest.raises(ValueError, match='Falta autorizacion'):
        live.execute(SimpleNamespace(run='batch_test', authorize=False))
    client.inspect.assert_not_called()
    assert live.execute(SimpleNamespace(run='batch_test', authorize=True))['status'] == 'COMPLETE'
    assert client.request.call_count == 1
    assert read(directory/'provider.json')['provider'] == 'ollama'
    client.inspect.side_effect = AssertionError('Completed run must verify offline')
    assert live.execute(SimpleNamespace(run='batch_test', authorize=False))['status'] == 'COMPLETE'
    assert client.request.call_count == 1


def test_provider_unavailable_pre_dispatch_is_resumable_without_claim(live_run):
    directory, client = live_run
    client.inspect.side_effect = transport.OllamaError('SERVER_UNAVAILABLE', 'Fixture offline')
    with pytest.raises(transport.OllamaError):
        live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert not list(directory.rglob('dispatch.claim.json'))
    client.inspect.side_effect = None
    assert live.execute(SimpleNamespace(run='batch_test', authorize=False))['status'] == 'COMPLETE'


def test_timeout_claim_blocks_duplicate_dispatch(live_run):
    directory, client = live_run
    client.request.side_effect = transport.OllamaError('TIMEOUT', 'Fixture timeout')
    with pytest.raises(ValueError, match='BLOCKED_ERROR'):
        live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert list(directory.rglob('dispatch.claim.json'))
    with pytest.raises(ValueError, match='detenida'):
        live.execute(SimpleNamespace(run='batch_test', authorize=False))
    assert client.request.call_count == 1


def test_runtime_binding_rejects_replaced_model(live_run):
    directory, client = live_run
    write(directory/'provider.json', client.inspect.return_value | {'digest':'previous-version'})
    with pytest.raises(ValueError, match='RUNTIME_DRIFT'):
        live.execute(SimpleNamespace(run='batch_test', authorize=True))
    client.request.assert_not_called()


def test_two_phases_resume_after_metadata_failure_without_repeating_discovery(live_run, sample):
    directory, client = live_run
    plan = read(directory/'plan.json')
    project, profiles, make_selection = discovery_samples.case.__wrapped__()
    profiles[0] = sample['profile']
    project['fields'].update(sample['fields'])
    project['fields']['summary'] = sample['fields']['methodology']
    project['siap_id'] = 'TEST'
    plan.update(projects=[project], profiles={p['indicator_id']:p for p in profiles},
                rubrics={sample['profile']['indicator_id']:sample['rubric']})
    plan['budgets'].update(assessment_reservation=45000, assessment_postcall_review_threshold=30000)
    write(directory/'plan.json', plan)
    manifest = read(directory/'manifest.json')
    manifest['plan_sha256'] = sha(directory/'plan.json')
    write(directory/'manifest.json', manifest)
    selection = make_selection(1)
    selection['assessments'][0]['candidates'][0]['indicator_category'] = sample['profile']['indicator_category']
    assessment = dict(project_id=project['project_id'],
        assessments=[dict(indicator_id=sample['profile']['indicator_id'], **sample['assessment'])])
    client.request.side_effect = [response(selection), response(assessment)]
    binding = client.inspect.return_value
    client.inspect.side_effect = [binding, binding, binding, transport.OllamaError('SERVER_UNAVAILABLE', 'Mock offline between phases')]
    with pytest.raises(transport.OllamaError, match='SERVER_UNAVAILABLE'):
        live.execute(SimpleNamespace(run='batch_test', authorize=True))
    assert client.request.call_count == 1
    assert live.verify_run(directory)['projects'][0]['discovery_complete'] is True
    record = next(directory.glob('calls/*/discovery/records/discovery/*.json'))
    original_hash = sha(record)
    client.inspect.side_effect = None
    assert live.execute(SimpleNamespace(run='batch_test', authorize=False))['status']=='COMPLETE'
    state = live.verify_run(directory)
    assert client.request.call_count == 2 and sha(record) == original_hash
    assert state['projects'][0]['rows'][0]['assessment_engine'] == 'OLLAMA'


def test_legacy_cache_cannot_be_relabelled_as_ollama(live_run, monkeypatch):
    directory, _ = live_run
    plan = read(directory/'plan.json')
    write(directory/'cache.json', {plan['projects'][0]['project_id']:{'provider':'codex'}})
    monkeypatch.setattr(live, 'check', lambda path:plan)
    with pytest.raises(ValueError, match='Cache de proveedor incompatible'):
        live.verify_run(directory)


@pytest.fixture
def planning_environment(tmp_path, monkeypatch):
    run = tmp_path/'outputs/runs/test'
    projects = [dict(project_id='TEST_PROJECT', source_project_id='TEST', record_source='temporary-fixture', source_row=1)]
    profiles = {f'I{i:02d}':{} for i in range(48)}
    settings = dict(profiles=profiles, rubrics={}, rules={}, budgets={}, observed_character_ratio=1,
                    discovery_version=gd.VERSION, assessment_version=v3.VERSION, source_hashes={})
    frozen = tmp_path/'outputs/frozen.json'
    write(frozen, settings)
    for relative in ('src/layer4_evaluation/live_execution.py', 'src/layer4_evaluation/indicators/ollama_provider.py',
                     'src/layer4_evaluation/indicators/context_budget.py',
                     'outputs/runs/test/prepared_hashes.json', 'outputs/runs/test/workspace/outputs/layer3/publication/_manifest.json'):
        path=tmp_path/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}', encoding='utf-8')
    module = SimpleNamespace(BASE=run/'evaluation', FROZEN=frozen, check=lambda path:read(path/'plan.json'))
    monkeypatch.setattr(coordinator, 'engine', lambda *a:module)
    monkeypatch.setattr(coordinator, 'evaluation_settings', lambda *a:(settings,{}))
    monkeypatch.setattr(coordinator, 'check', lambda *a:{'configuration':{},'code_hashes':{}})
    monkeypatch.setattr(coordinator, 'validated_graph', lambda *a:{})
    def table(path):
        rows = projects if path.name=='proyectos.parquet' else [dict(indicator_id=i) for i in profiles] if path.name=='indicadores.parquet' else [dict(
            source_id='TEST_PROJECT', field_name='methodology', text_original='Synthetic authorized methodology.',
            section_id='SECTION', text_hash_original='synthetic', provenance_json='{"layer1":[]}')] if path.name=='source_sections.parquet' else []
        return SimpleNamespace(to_pylist=lambda:rows)
    from layer4_evaluation.indicators import context_budget
    monkeypatch.setattr(context_budget, 'prepare_contexts', lambda *a:({}, {'requests':[]}))
    monkeypatch.setattr(coordinator.pq, 'read_table', table)
    monkeypatch.setattr(coordinator.importlib.util, 'spec_from_file_location', lambda *a:SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None)))
    monkeypatch.setattr(coordinator.importlib.util, 'module_from_spec', lambda spec:SimpleNamespace(check=lambda:settings))
    return tmp_path, run, module


def test_coordinator_prepares_ollama_plan_offline_and_rejects_codex_reuse(planning_environment):
    tmp_path, run, module = planning_environment
    name = coordinator.prepare_evaluation(tmp_path, run, ['TEST'])
    plan = read(module.BASE/name/'plan.json')
    assert plan['runtime']['provider']=='ollama' and plan['requested_model']=='qwen3.5:4b-q4_K_M'
    assert read(module.BASE/name/'review.json')['llm']['num_ctx']==4096
    plan['runtime']={'command':['historical-codex']}
    write(module.BASE/name/'plan.json', plan)
    with pytest.raises(ValueError, match='historico'):
        coordinator.prepare_evaluation(tmp_path, run, ['TEST'])


def test_context_change_before_dispatch_archives_and_requires_new_review(planning_environment):
    root, run, module = planning_environment
    name = coordinator.prepare_evaluation(root, run, ['TEST'])
    directory = module.BASE/name
    old_plan = (directory/'plan.json').read_bytes()
    old_review = (directory/'review.txt').read_bytes()
    old_hash = sha(directory/'plan.json')
    write(directory/'authorization.json', {'authorized':True, 'fixture':'previous review'})
    write(directory/'provider.json', {'fixture':'metadata, no inference'})
    write(run/'execution.json', {'llm':{'num_ctx':8192}})
    assert coordinator.prepare_evaluation(root, run, ['TEST']) == name
    archived = module.BASE/'review_versions'/name/old_hash
    assert (archived/'plan.json').read_bytes() == old_plan
    assert (archived/'review.txt').read_bytes() == old_review
    assert read(archived/'authorization.json')['authorized'] is True
    assert read(directory/'plan.json')['runtime']['configuration']['num_ctx'] == 8192
    assert not (directory/'authorization.json').exists()
    assert not (directory/'provider.json').exists()


def test_context_change_with_prior_dispatch_is_blocked(planning_environment):
    root, run, module = planning_environment
    name = coordinator.prepare_evaluation(root, run, ['TEST'])
    directory = module.BASE/name
    original = sha(directory/'plan.json')
    write(directory/'calls/TEST/discovery/dispatch.claim.json', {'fixture':'uncertain'})
    write(run/'execution.json', {'llm':{'num_ctx':8192}})
    with pytest.raises(ValueError, match='llamadas/cache previos'):
        coordinator.prepare_evaluation(root, run, ['TEST'])
    assert sha(directory/'plan.json') == original
    assert not (module.BASE/'review_versions').exists()


def test_context_reports_approximation_and_8192_is_opt_in():
    settings = transport.configuration()
    assert settings['num_ctx'] == 4096
    assert transport.context_guard('fixture', {}, settings) == len('fixture') + 512 + 1024
    assert transport.configuration({'num_ctx':8192})['num_ctx'] == 8192
    with pytest.raises(transport.OllamaError, match='no tokenizacion exacta'):
        transport.context_guard('x'*4096, {}, settings)
