"""Synthetic retention checks: no inference, corpus, real run or network."""
import hashlib
import json
import os
from pathlib import Path
import zipfile

import pytest
import run_retention as r


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.fixture
def setup(tmp_path):
    for name, stamp in [('old','2020-01-01T00:00:00+00:00'),('new','2026-01-01T00:00:00+00:00')]:
        run=tmp_path/'outputs/runs/local'/name
        put(run/'estado/progress.json',dict(status='PARTIAL',updated_at=stamp))
        put(run/'resultados/result.json',dict(value='unique evaluation',complete=False))
    policy=dict(version=1,keep_recent=1,pinned=[],reviewed={
        'local/old':dict(closed_for_retention=True,reason='Reviewed replaced development run',family='synthetic')})
    return tmp_path,policy


def candidate(root,policy):return next(a for a in r.plan(root,policy) if a['key']=='local/old')


def test_default_is_readonly_and_unreviewed_runs_do_not_expire(setup):
    root,policy=setup; before=sorted(str(p) for p in root.rglob('*'))
    policy['reviewed']={}
    assert all(x['action']=='KEEP' for x in r.plan(root,policy))
    assert before==sorted(str(p) for p in root.rglob('*'))


def test_configured_family_limit_protects_its_recent_representative(setup):
    root,policy=setup
    policy['keep_per_family']={'academic':1}
    assert candidate(root,policy)['action']=='KEEP'


def test_runtime_historical_reference_is_automatically_pinned(setup):
    root,policy=setup
    source=root/'src/comparison.py';source.parent.mkdir()
    source.write_text("HISTORY='outputs/runs/old'\n",encoding='utf-8')
    assert candidate(root,policy)['action']=='KEEP'


def test_inaccessible_recorded_process_is_not_assumed_dead(setup,monkeypatch):
    root,policy=setup
    put(root/'outputs/runs/local/old/estado/worker.json',dict(pid=123456789,creation=1))
    monkeypatch.setattr(r,'process_query_denied',lambda _:True)
    assert candidate(root,policy)['action']=='REVIEW'


@pytest.mark.parametrize('protection',['pinned','official','official_layer1','official_layer2','active','sqlite','uncertain','reuse'])
def test_protected_runs_cannot_be_retired(setup,monkeypatch,protection):
    root,policy=setup
    if protection=='pinned':policy['pinned']=['local/old']
    elif protection=='official':put(root/'outputs/layer3/publication/_manifest.json',dict(layer3_run_id='old'))
    elif protection=='official_layer1':put(root/'outputs/layer2/canonical/_manifest.json',dict(run_id='old'))
    elif protection=='official_layer2':put(root/'outputs/layer2/knowledge/_manifest.json',dict(layer2_run_id='old'))
    elif protection=='active':monkeypatch.setattr(r,'activity',lambda _:['ACTIVE_PROCESS'])
    elif protection=='sqlite':monkeypatch.setattr(r,'sqlite_idle',lambda _:False)
    elif protection=='uncertain':monkeypatch.setattr(r,'uncertain',lambda _:True)
    else:put(root/'outputs/runs/local/new/manifiestos/reuse.json',dict(source_run='old'))
    assert candidate(root,policy)['action']!='COMPACT'


def test_reviewed_partial_is_archived_without_claiming_complete(setup):
    root,policy=setup; row=candidate(root,policy)
    archive=root/'outputs/historico/compactados/test.zip'
    index=r.build_archive(root,[row],archive)
    assert index['status']=='HISTORICAL_NON_RESUMABLE'
    dest=root/'evidence';r.extract_evidence(archive,'local/old',dest)
    assert json.loads((dest/'estado/progress.json').read_text())['status']=='PARTIAL'
    assert (dest/'HISTORICAL_NON_RESUMABLE.json').exists()
    with pytest.raises(FileExistsError):r.extract_evidence(archive,'local/old',dest)


def test_identical_content_has_one_object_and_two_verified_paths(setup):
    root,policy=setup; run=root/'outputs/runs/local/old'
    (run/'copy.json').write_bytes((run/'resultados/result.json').read_bytes())
    archive=root/'outputs/historico/compactados/test.zip'
    index=r.build_archive(root,[candidate(root,policy)],archive)
    record=index['runs']['local/old']['files_preserved']
    assert record['copy.json'][0]==record['resultados/result.json'][0]
    assert len(index['objects'])==2


def test_change_after_review_or_shared_hardlink_blocks_archive(setup):
    root,policy=setup; row=candidate(root,policy);run=root/'outputs/runs/local/old'
    (run/'new.txt').write_text('changed')
    with pytest.raises(ValueError,match='changed'):
        r.build_archive(root,[row],root/'outputs/historico/compactados/test.zip')
    os.link(run/'new.txt',root/'outside.txt')
    assert candidate(root,policy)['action']=='REVIEW'


@pytest.mark.parametrize('path',['../outside','C:/outside','local/../../outside','local\\escape'])
def test_unsafe_manifest_paths_rejected(path):
    with pytest.raises(ValueError):r.safe_relative(path)


def test_omissions_need_exact_proof_and_queries_are_protected(setup):
    root,policy=setup;row=candidate(root,policy)
    with pytest.raises(ValueError,match='query cache'):
        r.build_archive(root,[row],root/'outputs/historico/compactados/test.zip',{
            'local/old/workspace/query_cache/q.npy':dict(reason='cache',sha256='0'*64)})


def test_archive_tampering_detected_before_extraction(setup):
    root,policy=setup;archive=root/'outputs/historico/compactados/test.zip'
    r.build_archive(root,[candidate(root,policy)],archive)
    with zipfile.ZipFile(archive,'a') as z:z.writestr('unexpected','tamper')
    with pytest.raises(ValueError,match='Unregistered'):r.verify_archive(archive)


def test_apply_archives_before_recycling_and_preserves_on_failure(setup,monkeypatch):
    root,policy=setup;archive=root/'outputs/historico/compactados/test.zip'
    journal=root/'outputs/runs/.storage-events/test.json'
    def fail(path):
        assert r.verify_archive(archive)['runs']['local/old']
        assert json.loads(journal.read_text())['operations'][0]['state']=='BEFORE_RECYCLE'
        raise OSError('Recycle Bin unavailable')
    monkeypatch.setattr(r,'recycle',fail)
    with pytest.raises(OSError,match='unavailable'):r.apply(root,policy,archive,journal)
    assert (root/'outputs/runs/local/old/resultados/result.json').exists()


def test_archive_cannot_be_written_inside_source_run(setup):
    root,policy=setup
    with pytest.raises(ValueError,match='outside runs'):
        r.build_archive(root,[candidate(root,policy)],root/'outputs/runs/local/old/unsafe.zip')


def test_document_cache_requires_real_vector_coverage_and_keeps_queries(tmp_path):
    import numpy as np
    cache=tmp_path/'outputs/layer3/cache/fingerprint';cache.mkdir(parents=True)
    vector=np.array([0.25,0.75],dtype=np.float32)
    np.save(cache/'key.npy',vector,allow_pickle=False)
    h=hashlib.sha256(vector.tobytes()).hexdigest()
    put(cache/'key.json',dict(key='key',dimensions=2,embedding_hash=h,file_hash=r.sha(cache/'key.npy')))
    pub=tmp_path/'outputs/layer3/publication/embeddings/source'
    put(pub/'records.json',[dict(embedding_hash=h)])
    np.save(pub/'vectors.npy',np.array([vector]),allow_pickle=False)
    put(pub/'metadata.json',dict(file_hashes={p:r.sha(pub/p) for p in ('records.json','vectors.npy')}))
    query=tmp_path/'outputs/layer3/query_cache/unique.json';put(query,dict(unique=True))
    policy=dict(document_cache_max_files=0)
    row=r.document_cache_plan(tmp_path,policy)
    assert row['action']=='RECYCLE_CACHE' and row['files']==2 and query.exists()
    meta=json.loads((cache/'key.json').read_text());meta['embedding_hash']='0'*64;put(cache/'key.json',meta)
    assert r.document_cache_plan(tmp_path,policy)['action']=='REVIEW'
