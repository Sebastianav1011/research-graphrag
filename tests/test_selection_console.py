"""Interactive selection and large-output suppression, with no pipeline execution."""
from types import SimpleNamespace
import pytest
import run as console
from project_menu import select_projects, SelectionCancelled
from layer2_processing.preprocessing.project_selection import sample_projects


@pytest.mark.parametrize('answer,expected', [('si', True), ('sí', True), ('N', False), ('', False)])
def test_fingerprint_warning_changes_only_text(monkeypatch, capsys, answer, expected):
    prompts = []
    monkeypatch.setattr(console.sys.stdin, 'isatty', lambda: True)
    def respond(prompt):
        prompts.append(prompt)
        return answer
    monkeypatch.setattr('builtins.input', respond)
    assert console.confirm_action('knowledge_rebuild', {
        'message': 'No hay conocimiento compatible: Fingerprint mismatch: synthetic.py'}) is expected
    assert capsys.readouterr().out == (
        '\nADVERTENCIA: KNOWLEDGE EXISTENTE INCOMPATIBLE\n\n'
        'El Knowledge guardado no coincide con la configuración actual.\n\n'
        'Motivo: Fingerprint mismatch.\n\n'
        'El conocimiento existente no puede reutilizarse de forma segura.\n\n')
    assert prompts == ['¿Deseas reconstruir el Knowledge para continuar? (s/N): ']


def test_other_rebuild_warning_and_noninteractive_behavior_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(console.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('Noninteractive input'))
    assert console.confirm_action('knowledge_rebuild', {'message': 'No hay version activa'}) is False
    assert capsys.readouterr().out == 'No hay version activa\n'


@pytest.mark.parametrize('count',[3,100])
@pytest.mark.parametrize('knowledge',['reuse','rebuild'])
def test_menu_count_reaches_existing_stratified_sampler(count,knowledge,monkeypatch,capsys,tmp_path):
    features={f'PRIVATE_{i:05}':['A' if i%3 else 'B','2026','open','4'] for i in range(240)}
    calls=[]
    def execute(root,**kwargs):
        assert kwargs['limit']==count and kwargs['seed']==42 and not kwargs['all_projects']
        assert kwargs['single_authorization'] is True
        assert kwargs['knowledge_action']==knowledge
        assert kwargs['confirm']('run',dict(run_id='synthetic',provider='ollama',model='mock',
            project_count=count,sources=['data/layer1_sources/base/synthetic.json'],contract=None,
            stages=list(console.STAGES),destination='http://127.0.0.1:11434')) is True
        chosen=sample_projects(features,kwargs['limit'],kwargs['seed'])
        assert len(chosen)==len(set(chosen))==count
        assert chosen==sample_projects(dict(reversed(list(features.items()))),count,42)
        calls.append(chosen)
        return dict(status='COMPLETE',projects=chosen)
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace(execute_pipeline=execute,
        configuration=lambda root,path:({},root,root/'outputs/runs'),
        find_run=lambda root,runs,name:runs/name))
    monkeypatch.setattr(console.sys.stdin,'isatty',lambda:True)
    monkeypatch.setattr(console,'ROOT',tmp_path)
    # 'N': the V5 question '¿Desea procesar también artículos?' follows the knowledge choice.
    answers=iter(['1','2','1',str(count),'' if knowledge=='reuse' else '2','N','S','0'])
    monkeypatch.setattr('builtins.input',lambda prompt:next(answers))
    assert console.main([])==0 and len(calls)==1
    output=capsys.readouterr().out
    assert 'Seleccionar cantidad de proyectos.' in output
    assert 'PRIVATE_' not in output and 'identificadores' not in output


def test_all_and_cancellation_are_explicit(monkeypatch):
    monkeypatch.setattr('builtins.input',lambda prompt:'2')
    assert select_projects(17)==dict(limit=None,all_projects=True,seed=17)
    monkeypatch.setattr('builtins.input',lambda prompt:'0')
    with pytest.raises(SelectionCancelled):select_projects()


def test_progress_keeps_counts_and_not_thousands_of_ids(capsys):
    ids=[f'PRIVATE_{n}' for n in range(10000)]
    console.show(dict(status='READY',project_ids=ids,summary=dict(requested_projects=ids,
        identity_links={pid:{'member_occurrences':2} for pid in ids},selected_counts={'proyectos':10000,'articulos':120})))
    output=capsys.readouterr().out
    assert len(output)<600 and 'PRIVATE_' not in output
    assert '10000' in output and '120' in output


def test_partial_console_distinguishes_processing_coverage_and_export(capsys):
    console.report_progress(dict(status='EVALUATION_PROGRESS',projects_evaluated=1,projects_processed=5,
        projects_completed=1,total_projects=5,indicators_completed=235))
    console.render_result(dict(status='PARTIAL',result=dict(selected_projects=5,processed_projects=5,completed_projects=1,
        expected_assessments=240,valid_assessments=235,supported=0,insufficient_evidence=235,
        blocked_assessments=5,pending_assessments=0,exported_rows=0,note='Excel vacio: no hay evaluaciones SUPPORTED.')))
    output=capsys.readouterr().out
    assert 'Proyectos procesados: 5/5' in output and 'Completamente evaluados: 1' in output
    for fragment in ('Estado: PARTIAL','esperados: 240','validas: 235','SUPPORTED: 0',
        'INSUFFICIENT_EVIDENCE: 235','Bloqueados: 5','pendientes: 0','filas exportadas: 0','Excel vacio:'):
        assert fragment in output


@pytest.mark.parametrize('flags',[
    ['run','--limit','3','--seed','42'], ['run','--limit','100','--seed','17'],['run','--all']])
def test_cli_sampling_flags_remain_available(flags):
    args=console.parser().parse_args(flags)
    assert args.limit in (None,3,100)
    assert args.all_projects==('--all' in flags)


def test_noninteractive_autonomous_requires_explicit_selection(tmp_path,monkeypatch):
    from autonomous_execution import cli
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace())
    coordinator=SimpleNamespace(configuration=lambda root,path:({},root,root/'outputs/runs'),
                                find_run=lambda root,runs,name:runs/name)
    args=console.parser().parse_args(['prepare','--autonomous','--non-interactive'])
    # Bypass only console adapters; exercise the original selection guard.
    from autonomous_execution import prepare_menu
    original=cli.dispatch
    while hasattr(original,'__wrapped__'):original=original.__wrapped__
    with pytest.raises(ValueError,match='Seleccion explicita'):
        original(tmp_path,args,coordinator)


def test_pre_registration_interrupt_keeps_original_trace(monkeypatch,capsys):
    def execute(*args,**kwargs):raise KeyboardInterrupt('SELECTING_SOURCE')
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace(execute_pipeline=execute))
    assert console.main(['run','--limit','5','--non-interactive'])==130
    output=capsys.readouterr()
    assert 'KeyboardInterrupt: SELECTING_SOURCE' in output.err
    assert 'anterior al registro' in output.out and 'Continuar:' not in output.out


@pytest.mark.parametrize('mode',['file','delivery'])
def test_main_menu_incoming_uses_existing_source_selector(tmp_path,monkeypatch,mode,capsys):
    from autonomous_execution import prepare_menu
    calls=[]
    path=tmp_path/'data/layer1_sources/incoming/example/project.txt'
    path.parent.mkdir(parents=True);path.write_text('Synthetic source',encoding='utf-8')
    monkeypatch.setattr(console,'ROOT',tmp_path)
    monkeypatch.setattr(console,'dispatch',lambda args:calls.append(args) or dict(status='CANCELLED'))
    answers=iter(['1','1','1','1','2','0'] if mode=='file' else ['1','1','2','1','0'])
    monkeypatch.setattr('builtins.input',lambda prompt:next(answers))
    assert console.main([])==0
    assert len(calls)==1 and calls[0].source is None
    assert calls[0].input_file==('data/layer1_sources/incoming/example/project.txt' if mode=='file' else None)
    assert calls[0].delivery==('example' if mode=='delivery' else None)
    assert calls[0].through=='export'
    assert calls[0].evaluation_mode is None and calls[0].context_mode=='graphrag'
    from layer4_evaluation.indicators import assessment_v3 as v3, prospective_v2 as p2
    policy=v3.evaluation_policy(calls[0].evaluation_mode,calls[0].context_mode)
    assert policy['evaluation_mode']==p2.MODE and policy['decision_policy']==p2.DECISION_POLICY
    output=capsys.readouterr().out
    assert 'MODO DE EVALUACION' not in output and 'MODO DE CONTEXTO' not in output


@pytest.mark.parametrize('mode',['prospective','demonstrated'])
@pytest.mark.parametrize('context',['full-descriptor','graphrag'])
def test_cli_mode_selection_reaches_existing_coordinator(mode,context,monkeypatch):
    args=console.parser().parse_args(['run','--source','base','--projects','21750,21736,22022,21869,21844',
        '--evaluation-mode',mode,'--context-mode',context])
    monkeypatch.setattr(console,'coordinator',lambda:SimpleNamespace())
    monkeypatch.setattr(console,'execute_with_console',lambda engine,**kw:kw)
    call=console.dispatch_pipeline(args)
    assert call['evaluation_mode']==mode and call['context_mode']==context
    assert call['project_ids']==['21750','21736','22022','21869','21844']


def test_new_mode_menu_back_never_starts_pipeline(monkeypatch,tmp_path):
    monkeypatch.setattr(console,'ROOT',tmp_path)
    monkeypatch.setattr(console,'dispatch',lambda *a:pytest.fail('Cancelled mode selection'))
    answers=iter(['1','2','0','0','0'])
    monkeypatch.setattr('builtins.input',lambda _:next(answers))
    assert console.main([])==0
