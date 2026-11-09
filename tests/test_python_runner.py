"""Small console/orchestration checks; no models, institutional ETL or LLM."""
from types import SimpleNamespace

import pytest

import run as console
from scripts import pipeline_coordinator as controller
from layer2_processing.preprocessing.adapters import file_configuration, read, write


@pytest.fixture
def environment(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    raw = root / 'data/layer1_sources/base'
    raw.mkdir(parents=True)
    (root / 'data/layer1_sources/incoming/delivery').mkdir(parents=True)
    config = dict(raw_base='data/layer1_sources', runs_base='outputs/runs',
                  reference_catalog='data/layer1_sources/reference/indicadores/catalog.xlsx', files={})
    write(root / 'config/pipeline_manual.json', config)
    calls = []

    def checked(root, run):
        state = read(run / 'run.json')
        if state['status'] not in ('PREPROCESSED', 'PREPARED'):
            raise ValueError('Checkpoint invalido')
        return state

    def prepared(root, run, raw, dataset, config, through):
        calls.append('preprocessing')
        if not (run / 'run.json').exists():
            write(run / 'run.json', dict(status='PREPROCESSED', dataset=dataset,
                configuration=config, raw_path=raw.relative_to(root).as_posix()))

    def knowledge(root, run):
        calls.append('knowledge')
        state = checked(root, run)
        write(run / 'run.json', state | dict(status='PREPARED'))

    monkeypatch.setattr(controller, 'check', checked)
    monkeypatch.setattr(controller, 'prepare', prepared)
    monkeypatch.setattr(controller, 'knowledge', knowledge)
    monkeypatch.setattr(controller, 'verify_sources', lambda *a: dict(status='READY_FOR_VALIDATION', discovery_status='READY_FOR_VALIDATION'))
    monkeypatch.setattr(controller, 'validated_graph', lambda *a: calls.append('validated_graph'))
    monkeypatch.setattr(controller, 'scope_projects', lambda root,run,selection,requested=None: requested or ['P1'])
    return root, root / 'outputs/runs/demo', calls


def test_controller_stops_for_build_then_resumes(environment, monkeypatch):
    root, run, calls = environment
    result = controller.execute_pipeline(root, run_id='demo', source='base', through='graphrag')
    assert result['status'] == 'BUILD_APPROVAL_REQUIRED'
    assert calls == ['preprocessing', 'knowledge']
    assert read(run / 'execution.json')['through'] == 'graphrag'
    monkeypatch.setattr(controller, 'graph', lambda *a, **kw: calls.append('graph'))
    result = controller.execute_pipeline(root, run_id='demo', resume=True, approve_build=True)
    assert result['status'] == 'COMPLETE'
    assert calls[-2:] == ['graph', 'validated_graph']
    assert read(run / 'run.json')['raw_path'].endswith('/base')


def test_stage_has_prerequisites(environment):
    root, _, calls = environment
    with pytest.raises(ValueError, match='checkpoint'):
        controller.execute_pipeline(root, run_id='demo', stage='knowledge')
    assert not calls


def test_invalid_source_blocks_before_preparing(environment, monkeypatch):
    root, run, calls = environment
    monkeypatch.setattr(controller, 'verify_sources', lambda *a: dict(status='PENDING_OR_INVALID'))
    with pytest.raises(ValueError, match='pendientes'):
        controller.execute_pipeline(root, run_id='demo')
    assert not (run / 'execution.json').exists() and not (run / 'run.json').exists() and not calls


def test_error_keeps_checkpoint_and_records_stage(environment, monkeypatch):
    root, run, _ = environment
    controller.execute_pipeline(root, run_id='demo', through='preprocessing')
    def broken(*a):
        raise RuntimeError('Dependencia ausente')
    monkeypatch.setattr(controller, 'knowledge', broken)
    with pytest.raises(RuntimeError, match='Dependencia'):
        controller.execute_pipeline(root, run_id='demo', stage='knowledge')
    assert read(run / 'run.json')['status'] == 'PREPROCESSED'
    assert read(run / 'progress.json')['stage'] == 'knowledge'


def test_resume_rejects_different_sources(environment):
    root, _, _ = environment
    controller.execute_pipeline(root, run_id='demo', source='base', through='preprocessing')
    with pytest.raises(ValueError, match='distintas'):
        controller.execute_pipeline(root, run_id='demo', resume=True, source='incoming')


def test_explicit_same_source_allows_llm_config_edit_without_rewriting_data_snapshot(environment):
    root, run, _ = environment
    controller.execute_pipeline(root, run_id='demo', source='base', through='preprocessing')
    frozen = read(run/'run.json')['configuration']
    config = read(root/'config/pipeline_manual.json')
    write(root/'config/pipeline_manual.json', config | {'llm':{'num_ctx':8192}})
    result = controller.execute_pipeline(root, run_id='demo', resume=True, source='base', through='preprocessing')
    assert result['status'] == 'COMPLETE'
    assert read(run/'run.json')['configuration'] == frozen


def evaluation_environment(environment, monkeypatch, complete=False):
    root, run, calls = environment
    controller.execute_pipeline(root, run_id='demo', through='knowledge')
    base = run / 'workspace/outputs/layer4'
    module = SimpleNamespace(BASE=base, verify_run=lambda p: dict(status='COMPLETE' if complete else 'PARTIAL', errors=[]))
    monkeypatch.setattr(controller, 'engine', lambda *a: module)
    monkeypatch.setattr(controller, 'projects_without_evidence', lambda *a: [])
    def evaluate(root, run, batch, authorize=False, execute=False):
        if execute:
            calls.append('llm')
            module.verify_run = lambda p: dict(status='COMPLETE', errors=[])
        directory = base / controller.batch_name(batch)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'review.txt').write_text('Review fixture', encoding='utf-8')
        return dict(status='REVIEW_REQUIRED', review=str(directory / 'review.txt'))
    monkeypatch.setattr(controller, 'evaluate', evaluate)
    return root, run, calls, module


def test_review_precedes_authorization_and_resume_reuses_selection(environment, monkeypatch):
    root, run, calls, module = evaluation_environment(environment, monkeypatch)
    result = controller.execute_pipeline(root, run_id='demo', stage='evaluation', project_ids=['P1'], authorize=True)
    assert result['status'] == 'REVIEW_REQUIRED' and 'llm' not in calls
    result = controller.execute_pipeline(root, run_id='demo', stage='evaluation', authorize=True)
    assert result['status'] == 'COMPLETE' and calls.count('llm') == 1
    controller.execute_pipeline(root, run_id='demo', stage='evaluation')
    assert calls.count('llm') == 1


def test_changed_review_requires_new_authorization_even_with_authorize_flag(environment, monkeypatch):
    root, run, calls, module = evaluation_environment(environment, monkeypatch)
    controller.execute_pipeline(root, run_id='demo', stage='evaluation', project_ids=['P1'])
    evaluate = controller.evaluate
    def updated_review(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        if not kwargs.get('execute'):
            (module.BASE/controller.batch_name(['P1'])/'review.txt').write_text('Revised context configuration', encoding='utf-8')
        return result
    monkeypatch.setattr(controller, 'evaluate', updated_review)
    result = controller.execute_pipeline(root, run_id='demo', stage='evaluation', authorize=True)
    assert result['status'] == 'REVIEW_REQUIRED'
    assert 'llm' not in calls


def test_export_never_overwrites_on_uncertain_evaluation(environment, monkeypatch):
    root, run, calls, module = evaluation_environment(environment, monkeypatch)
    (module.BASE / 'batch_test').mkdir(parents=True)
    module.verify_run = lambda p: dict(status='BLOCKED', errors=['UNCERTAIN_OUTCOME'])
    saved = run / 'resultado_indicadores.xlsx'
    saved.write_bytes(b'previous publication')
    monkeypatch.setattr(controller, 'export', lambda *a: pytest.fail('Must not export'))
    with pytest.raises(ValueError, match='No se sobrescribe'):
        controller.execute_pipeline(root, run_id='demo', stage='export')
    assert saved.read_bytes() == b'previous publication'


def test_partial_export_is_not_full_success(environment, monkeypatch):
    root, run, calls, module = evaluation_environment(environment, monkeypatch, complete=True)
    (module.BASE / 'batch_test').mkdir(parents=True)
    monkeypatch.setattr(controller, 'export', lambda *a: dict(status='PARTIAL', pending_projects=['P2']))
    result = controller.execute_pipeline(root, run_id='demo', stage='export')
    assert result['status'] == 'PARTIAL' and console.exit_code(result) == 3


@pytest.mark.parametrize('source', ['../outside', 'reference', '/outside'])
def test_reject_unsafe_source_folder(environment, source):
    root, _, _ = environment
    with pytest.raises(ValueError):
        controller.selected_configuration(root, 'config/pipeline_manual.json', source)


def test_selected_delivery_uses_existing_registry_rules():
    spec = dict(domain='proyectos', mapping=dict(source_project_id='id'))
    config = dict(source_prefix='incoming/delivery/', files={'incoming/delivery/*.xlsx': spec})
    assert file_configuration(config, 'new.xlsx') == spec


def test_real_discovery_of_selected_delivery(environment):
    root, _, _ = environment
    # Only a temporary test input; never installed in institutional intake.
    from .test_layer1_intake import official_project_file
    official_project_file(root, records=[dict(id_actividad='P1', resumen='Fixture additional text')],
                          relative='incoming/delivery/new.xlsx')
    write(root / 'config/sources.example.yaml', {})
    config, raw, _ = controller.selected_configuration(root, 'config/pipeline_manual.json', 'incoming/delivery')
    from layer2_processing.preprocessing.adapters import discover_sources
    result = discover_sources(root, config, raw)
    assert result['status'] == 'READY_FOR_VALIDATION'
    item = result['files'][0]
    assert item['records'][0]['original_values']['resumen'] == 'Fixture additional text'


def test_cli_dispatch_is_direct_and_does_not_authorize_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(console, 'coordinator', lambda: SimpleNamespace(execute_pipeline=lambda *a, **kw: calls.append(kw) or dict(status='COMPLETE')))
    assert console.main(['run', '--through', 'knowledge', '--source', 'base', '--limit', '3']) == 0
    assert calls[0]['through'] == 'knowledge' and not calls[0]['authorize']


def test_menu_invalid_choice_and_exit(monkeypatch, capsys):
    answers = iter(['bad', '0'])
    monkeypatch.setattr('builtins.input', lambda *a: next(answers))
    assert console.main([]) == 0
    assert 'Opcion invalida' in capsys.readouterr().out


def test_menu_dispatches_verification(monkeypatch):
    answers = iter(['4', 'base', '0'])
    calls = []
    monkeypatch.setattr('builtins.input', lambda *a: next(answers))
    monkeypatch.setattr(console, 'dispatch', lambda args: calls.append(args) or dict(status='READY_FOR_VALIDATION'))
    assert console.main([]) == 0
    assert calls[0].command == 'verify' and calls[0].source == 'base'


def test_cli_reports_missing_dependency(monkeypatch, capsys):
    def missing():
        raise ModuleNotFoundError('pyarrow')
    monkeypatch.setattr(console, 'coordinator', missing)
    assert console.main(['status']) == 2
    assert 'pyarrow' in capsys.readouterr().out


def test_resume_requires_id():
    assert console.main(['resume']) == 2


def test_stage_requires_name():
    with pytest.raises(SystemExit) as exc:
        console.main(['stage', '--run-id', 'demo'])
    assert exc.value.code == 2


def test_legacy_entry_uses_same_orchestration(monkeypatch):
    calls = []
    monkeypatch.setattr(controller, 'execute_pipeline', lambda *a, **kw: calls.append(kw) or dict(status='COMPLETE'))
    assert controller.main(['run', '--dataset', 'prueba_en_vivo', '--through', 'results', '--run-id', 'demo']) == 0
    assert calls[0]['through'] == 'export' and calls[0]['dataset'] == 'prueba_en_vivo'


def test_verify_reports_pending_and_hides_original_values(tmp_path, monkeypatch):
    (tmp_path / 'data/layer1_sources/base').mkdir(parents=True)
    write(tmp_path / 'config/pipeline_manual.json', dict(raw_base='data/layer1_sources',
          runs_base='outputs/runs', reference_catalog='data/layer1_sources/reference/indicadores/catalog.xlsx'))
    reference = tmp_path / 'data/layer1_sources/reference/indicadores/catalog.xlsx'
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b'not opened in metadata preview')
    for name in ('layer1', 'layer2', 'layer3'):
        (tmp_path / f'config/{name}.yaml').write_text('{}', encoding='utf-8')
    from layer2_processing.preprocessing import adapters
    monkeypatch.setattr(adapters, 'discover_sources', lambda *a: dict(status='PENDING_OR_INVALID',
        files=[dict(file='ambiguous.xlsx', status='PENDING_CONFIGURATION', records=['private values'])]))
    result = controller.verify_sources(tmp_path)
    assert result['status'] == 'PENDING_OR_INVALID'
    assert 'records' not in result['files'][0] and console.exit_code(result) == 3


def test_resume_after_stage_failure_retries_requested_stage(environment, monkeypatch):
    root, run, calls = environment
    controller.execute_pipeline(root, run_id='demo', through='preprocessing')
    knowledge = controller.knowledge
    def fail(*a):
        raise RuntimeError('Interrupted stage')
    monkeypatch.setattr(controller, 'knowledge', fail)
    with pytest.raises(RuntimeError):
        controller.execute_pipeline(root, run_id='demo', stage='knowledge')
    monkeypatch.setattr(controller, 'knowledge', knowledge)
    controller.execute_pipeline(root, run_id='demo', resume=True)
    assert read(run / 'run.json')['status'] == 'PREPARED'


def test_verify_missing_layer_config_reports_blocked(tmp_path, monkeypatch):
    (tmp_path / 'data/layer1_sources/base').mkdir(parents=True)
    write(tmp_path / 'config/pipeline_manual.json', dict(raw_base='data/layer1_sources',
          runs_base='outputs/runs', reference_catalog='data/layer1_sources/reference/indicadores/missing.xlsx'))
    from layer2_processing.preprocessing import adapters
    monkeypatch.setattr(adapters, 'discover_sources', lambda *a: dict(status='READY_FOR_VALIDATION', files=[]))
    result = controller.verify_sources(tmp_path)
    assert result['status'] == 'BLOCKED' and 'config/layer1.yaml' in result['missing']


def test_discovery_finds_base_and_incoming_without_reference(environment):
    root, _, _ = environment
    intake = root / 'data/layer1_sources'
    from .test_layer1_intake import official_project_file
    official_project_file(root, records=[dict(id_actividad='B1', resumen='Base fixture')], relative='base/first.xlsx')
    official_project_file(root, records=[dict(id_actividad='I1', resumen='Incoming fixture')], relative='incoming/delivery/second.xlsx')
    write(intake / 'reference/ignored.json', {'not': 'an institutional record'})
    write(root / 'config/sources.example.yaml', {'proyectos': {'mapping': {'source_project_id': ['id'], 'title': ['title']}}})
    config, raw, _ = controller.selected_configuration(root, 'config/pipeline_manual.json', 'all')
    from layer2_processing.preprocessing.adapters import discover_sources
    result = discover_sources(root, config, raw)
    assert result['status'] == 'READY_FOR_VALIDATION'
    assert {item['file'] for item in result['files']} == {'base/first.xlsx', 'incoming/delivery/second.xlsx'}


def test_graph_reuses_verified_publication_without_building(environment, monkeypatch):
    root, run, _ = environment
    controller.execute_pipeline(root, run_id='demo', through='knowledge')
    write(run / 'workspace/config/layer3.yaml', {})
    write(run / 'workspace/outputs/layer3/publication/_manifest.json', {'test': 'must be verified'})
    from layer3_graphrag import pipeline
    monkeypatch.setattr(pipeline, 'run', lambda *a, **kw: pytest.fail('Existing publication must not be rebuilt'))
    monkeypatch.setattr(controller, 'validated_graph', lambda *a: {'status': 'VERIFIED_TEST_MANIFEST'})
    assert controller.graph(root, run, build=True)['status'] == 'VERIFIED_TEST_MANIFEST'


def test_layer4_python_interface_preserves_authorization(environment, monkeypatch):
    root, run, _ = environment
    calls = []
    monkeypatch.setattr(controller, 'prepare_evaluation', lambda *a: 'batch_test')
    module = SimpleNamespace(execute=lambda args: calls.append(args) or {'status': 'COMPLETE'})
    monkeypatch.setattr(controller, 'engine', lambda *a: module)
    assert controller.evaluate(root, run, ['P1'], execute=True, authorize=False)['status'] == 'COMPLETE'
    assert calls[0].run == 'batch_test' and calls[0].authorize is False


@pytest.mark.parametrize('complete', [False, True])
def test_native_evaluator_blocks_without_authorization_or_reuses_complete(tmp_path, monkeypatch, complete):
    from contextlib import nullcontext
    from layer4_evaluation import live_execution
    directory = tmp_path / 'batch_test'
    directory.mkdir()
    monkeypatch.setattr(live_execution, 'run_dir', lambda name: directory)
    monkeypatch.setattr(live_execution, 'execution_lock', nullcontext)
    monkeypatch.setattr(live_execution, 'check', lambda path: {})
    monkeypatch.setattr(live_execution, 'verify_run', lambda path: {'status': 'COMPLETE' if complete else 'PARTIAL', 'errors': []})
    monkeypatch.setattr(live_execution, 'summary', lambda state: state)
    monkeypatch.setattr(live_execution, 'OllamaClient', lambda *a: pytest.fail('Must not invoke any provider'))
    if complete:
        assert live_execution.execute(SimpleNamespace(run='batch_test', authorize=False))['status'] == 'COMPLETE'
    else:
        with pytest.raises(ValueError, match='Falta autorizacion'):
            live_execution.execute(SimpleNamespace(run='batch_test', authorize=False))
        assert not (directory / 'authorization.json').exists()


def test_shared_lock_prevents_duplicate_execution(environment):
    root, run, calls = environment
    with controller.lock(root / 'outputs/runs'):
        with pytest.raises(OSError):
            controller.execute_pipeline(root, run_id='demo', through='preprocessing')
    assert not calls and not (run / 'execution.json').exists() and not (run / 'run.json').exists()


@pytest.mark.parametrize('arguments,interface', [
    (['run', '--through', 'knowledge', '--limit', '3'], 'execute'),
    (['stage', 'knowledge', '--run-id', 'demo'], 'execute'),
    (['resume', '--run-id', 'demo'], 'execute'),
    (['verify', '--source', 'base'], 'verify'),
    (['status', '--run-id', 'demo'], 'status'),
])
def test_all_console_commands_use_python_interfaces(monkeypatch, arguments, interface):
    calls = []
    module = SimpleNamespace(
        configuration=lambda root, path: ({}, root/'data/layer1_sources', root/'outputs/runs'),
        find_run=lambda root, runs, name: runs/name,
        execute_pipeline=lambda *a, **kw: calls.append('execute') or {'status': 'COMPLETE'},
        verify_sources=lambda *a: calls.append('verify') or {'status': 'READY_FOR_VALIDATION'},
        execution_status=lambda *a: calls.append('status') or {'status': 'VERIFIED'})
    monkeypatch.setattr(console, 'coordinator', lambda: module)
    assert console.main(arguments) == 0 and calls == [interface]
