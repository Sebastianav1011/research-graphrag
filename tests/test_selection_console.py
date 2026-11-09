"""Interactive selection and large-output suppression, with no pipeline execution."""
from types import SimpleNamespace
import pytest
import run as console
from project_menu import select_projects, SelectionCancelled
from layer2_processing.preprocessing.project_selection import sample_projects


@pytest.mark.parametrize('count',[3,100])
def test_menu_count_reaches_existing_stratified_sampler(count,monkeypatch,capsys,tmp_path):
    features={f'PRIVATE_{i:05}':['A' if i%3 else 'B','2026','open','4'] for i in range(240)}
    calls=[]
    def execute(root,**kwargs):
        assert kwargs['limit']==count and kwargs['seed']==42 and not kwargs['all_projects']
        assert kwargs['single_authorization'] is True
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
    answers=iter(['1','1',str(count),'S','0'])
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
