"""Eligibility is provider-neutral and immutable; no models or private inputs."""
from copy import deepcopy

import pytest

from evaluation_contracts import create,load,resolve,evaluable_features,ELIGIBILITY
from layer2_processing.preprocessing.project_selection import digest,sample_projects
from tests.test_manual_pipeline import sandbox


def population():
    features={f'{i:04}':['A' if i%2 else 'B','2026','active','0' if i<10 else '4'] for i in range(70)}
    return dict(project_features=features,evaluable_project_features={k:v for k,v in features.items() if v[-1]!='0'},
        population_sha256=digest(features),sources={'data/synthetic.csv':'synthetic'},selection_configuration_sha256='mapping')


def test_evaluable_contract_reproducibility_additions_and_legacy_compatibility(tmp_path):
    pop=population()
    path=create(tmp_path,'evaluable',30,42,pop,'catalog',require_evaluable=True)
    original=path.read_bytes();value=load(path)
    assert value['eligibility']['rule']==ELIGIBILITY
    assert value['eligibility']['population_count']==60
    assert value['project_ids']==sample_projects(pop['evaluable_project_features'],30,42)
    assert len(set(value['project_ids']))==30
    selected=resolve(value,pop,'catalog',5)
    assert selected['project_ids'][:30]==value['project_ids']
    assert len(set(selected['project_ids']))==35
    assert set(selected['project_ids'])<=pop['evaluable_project_features'].keys()
    reverse=deepcopy(pop)
    reverse['evaluable_project_features']=dict(reversed(list(pop['evaluable_project_features'].items())))
    assert resolve(value,reverse,'catalog',5)==selected
    assert path.read_bytes()==original
    legacy=load(create(tmp_path,'legacy',30,42,pop,'catalog'))
    assert 'eligibility' not in legacy
    assert resolve(legacy,pop,'catalog')['project_ids']==sample_projects(pop['project_features'],30,42)


@pytest.mark.parametrize('change',['missing_text','unknown_rule'])
def test_evaluable_population_drift_is_rejected(tmp_path,change):
    pop=population();value=load(create(tmp_path,'sample',30,42,pop,'catalog',require_evaluable=True))
    if change=='missing_text':pop['evaluable_project_features'].pop(value['project_ids'][0])
    else:value['eligibility']['rule']='UNKNOWN'
    with pytest.raises(ValueError,match='evaluable|elegibilidad'):resolve(value,pop,'catalog')


def test_native_text_authorization_filters_title_only_and_preserves_extra_evidence(tmp_path,monkeypatch):
    from layer2_processing.preprocessing import adapters as a
    records=[dict(row=i,original_values=dict(id=pid,titulo='Metadata only',resumen=text,hallazgos=extra))
        for i,(pid,text,extra) in enumerate([('P1','Authorized synthetic project narrative',''),('P2','',''),
            ('P3','','An authorized synthetic additional finding')],2)]
    item=dict(domain='proyectos',file='projects.csv',headers=['id','titulo','resumen','hallazgos'],records=records,
        mapping=dict(source_project_id=['id'],title=['titulo'],summary=['resumen']))
    monkeypatch.setattr(a,'discover_sources',lambda *_:dict(status='READY_FOR_VALIDATION',files=[item]))
    monkeypatch.setattr(a,'source_registry',lambda *_:{})
    monkeypatch.setattr(a,'file_configuration',lambda *_:{})
    features={pid:['A','2026','active','0'] for pid in ['P1','P2','P3']}
    config=dict(text_columns=dict(include=['hallazgos'],auto_keywords=[]))
    assert set(evaluable_features(tmp_path,tmp_path,config,features))=={'P1','P3'}


def test_insufficient_evaluable_projects_does_not_create_contract(tmp_path):
    pop=population();pop['evaluable_project_features']={}
    with pytest.raises(ValueError):create(tmp_path,'blocked',30,42,pop,'catalog',require_evaluable=True)
    assert not (tmp_path/'data').exists()


def test_contract_run_uses_native_selection_validation(sandbox,monkeypatch):
    from scripts import pipeline_coordinator as runner
    from tests.test_scoped_identity import setup_sources,paper
    from experiment_runtime import options
    from evaluation_contracts import inventory
    monkeypatch.setattr('evaluation_contracts.catalog_hash',lambda root:'catalog')
    from autonomous_execution import store
    root,_,config=sandbox
    setup_sources(root,[paper()])
    store.write(root/'config/pipeline_manual.json',config)
    pop=inventory(root,runner)
    path=create(root,'shared',2,42,pop,'catalog',require_evaluable=True)
    selected=resolve(load(path),pop,'catalog')
    token=options.set(dict(provider='ollama',contract=selected))
    try:
        result=runner.execute_pipeline(root,source='base',project_ids=selected['project_ids'],run_id='contract',through='preprocessing')
    finally:options.reset(token)
    assert result['status']=='COMPLETE'
    run=root/'outputs/runs/contract'
    assert store.read(run/'run.json')['configuration']['project_selection']['project_ids']==selected['project_ids']
    assert store.read(run/'preprocess/selection_manifest.json')['status']=='VALIDATED_SELECTION'
    assert store.read(run/'execution.json')['evaluation_contract']==selected
