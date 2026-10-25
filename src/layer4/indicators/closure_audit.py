"""Read-only diagnosis of real publications. Never reinterpret historical decisions."""
from collections import Counter
from pathlib import Path

from .experiment_inputs import read, protected_snapshot, verify_hashes, load_inputs
from .experiment import read_jsonl, write_json
from .assessment import validate_structured_assessment
from .confidence import calculate_raw_confidence


def historical_records(root, name='experiment_20'):
    """The later 20-project run reused five pilot responses without copying records."""
    folder = Path(root)/'outputs/layer4'/name
    projects = read(folder/'selection_manifest.json')['projects']
    result = []
    for project in projects:
        own = folder/'records'/(project['project_id']+'.json')
        origin = folder if own.exists() else Path(root)/'outputs/layer4/pruebas/piloto_v2/original_5'
        path = origin/'records'/(project['project_id']+'.json')
        if not path.exists():
            continue
        record = read(path)
        response = origin/record['raw_response_path']
        verify_hashes(origin, {record['raw_response_path']: record['raw_response_sha256'],
                              str(response.parent.relative_to(origin)/'call.json'): record['call_sha256']})
        if read(response) != record['wrapper']:
            raise ValueError('Historical wrapper differs from raw response')
        call = read(response.parent/'call.json')
        verify_hashes(response.parent, {n:call[k] for n,k in (
            ('events.jsonl','events_sha256'),('stderr.txt','stderr_sha256'),('response.json','response_sha256'))})
        result.append((project, record, origin, call))
    return projects, result


def closure_snapshot(root):
    root = Path(root)
    snapshot = protected_snapshot(root)
    # Protect every canonical byte, configs/tests upstream, and all existing history.
    folders = ['data/canonical', 'tests/layer1', 'tests/layer2', 'tests/layer3',
               'config/layer1', 'config/layer2', 'config/layer3', 'schemas/layer1',
               'schemas/layer2', 'schemas/layer3', 'outputs/layer4/pruebas/piloto_v2/muestra_20',
               'outputs/layer4/auditoria/historicos/experimento_50', 'outputs/layer4/pruebas/piloto_v2/original_5',
               'outputs/layer4/auditoria/historicos/entrega_20', 'outputs/layer4/auditoria/historicos/entrega_piloto_5']
    from .experiment_inputs import sha256
    paths = [p for d in folders for p in (root/d).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts]
    paths += [p for p in (root/'config').glob('layer[123]*') if p.is_file()]
    snapshot.update({p.relative_to(root).as_posix():sha256(p) for p in paths})
    return snapshot


def audit(root):
    root = Path(root)
    out = root/'outputs/layer4/auditoria/cierre_v2/audit'
    out.mkdir(parents=True, exist_ok=True)
    baseline = out/'protected_before.json'
    if not baseline.exists():
        write_json(baseline, closure_snapshot(root))
    verify_hashes(root, read(baseline))
    config = read(root/'outputs/layer4/auditoria/historicos/experimento_50/experiment_manifest.json')['config']
    data = load_inputs(root, config)
    projects, records = historical_records(root)
    rows = [r for _, record, _, _ in records for r in record['rows']]
    projected = read_jsonl(root/'outputs/layer4/pruebas/piloto_v2/muestra_20/technical_results.jsonl')
    key = lambda r:(r['project_id'],r['indicator_id'])
    if sorted(rows,key=key) != sorted(projected,key=key):
        raise ValueError('Historical combined technical results differ from raw records')
    errors = []
    details = []
    for p, record, _, call in records:
        for a in record['wrapper']['assessments']:
            value = {k:v for k,v in a.items() if k!='indicator_id'}
            profile = data['profiles'][a['indicator_id']]
            validation = validate_structured_assessment(p['fields'], profile, value)
            historical = next(r for r in record['rows'] if r['indicator_id']==a['indicator_id'])
            confidence = calculate_raw_confidence(p['fields'],profile,value)
            score = confidence['confidence_raw_score']
            if (float(score) if score is not None else None) != historical['confidence_raw_score']:
                raise ValueError('Historical confidence cannot be reproduced')
            errors.extend(validation)
            details.append({'project_id':p['project_id'],'siap_id':p['siap_id'],
                'indicator_id':a['indicator_id'],'decision':a['decision'],
                'strength':a['support_strength'],'evidence_fields':sorted({e['field'] for e in a['evidence']}),
                'validation_errors':validation,'confidence_v1':historical['confidence_raw_score'],
                'model_explanation':a['explanation'], 'human_cause_review':None})
    eligible = {p['project_id']:p for p in data['eligible']}
    coverage = []
    for cap in (2,3,5):
        counts = [min(cap,len(eligible[p['project_id']]['candidates'])) for p in projects]
        coverage.append({'candidate_cap':cap,'projects':len(projects),'published_pairs':sum(counts),
            'additional_pairs_vs_2':sum(counts)-sum(min(2,len(eligible[p['project_id']]['candidates'])) for p in projects),
            'projects_with_extra_candidates':sum(len(eligible[p['project_id']]['candidates'])>2 for p in projects),
            'new_supported':None,'human_confirmed_relevant':None,'inference_seconds':None,
            'inference_cost':None,'status':'PUBLISHED_CANDIDATE_COUNTS_ONLY_NO_NEW_INFERENCE'})
    all_counts = Counter(len(p['candidates']) for p in data['eligible'])
    result = {'status':'TECHNICAL_AUDIT_COMPLETE_HUMAN_CAUSE_REVIEW_PENDING',
        'historical_20':{'projects':len(records),'assessments':len(rows),'decisions':dict(Counter(r['decision'] for r in rows)),
            'invalid_assessments':sum(bool(d['validation_errors']) for d in details),
            'projects_supported':len({r['project_id'] for r in rows if r['decision']=='SUPPORTED'}),
            'actual_pairs':sum(len(p['candidates']) for p in projects),
            'pairs_available_cap2':coverage[0]['published_pairs'],
            'projects_limited_to_one_despite_more_available':sum(len(p['candidates'])==1 and len(eligible[p['project_id']]['candidates'])>1 for p in projects)},
        'pilot':{'projects':5,'assessments':8,'decisions':{'SUPPORTED':2,'INSUFFICIENT_EVIDENCE':4,'NOT_SUPPORTED':2}},
        'preliminary_20_historical':read(root/'outputs/layer4/auditoria/historicos/preliminar_20/preliminary_summary.json'),
        'prepared_50':{'projects':50,'assessments':read(root/'outputs/layer4/auditoria/historicos/experimento_50/selection_manifest.json')['assessment_count']},
        'layer3':{'candidate_distribution':data['candidate_distribution'],'eligible_projects':len(eligible),
                  'candidate_count_histogram':dict(sorted(all_counts.items()))},
        'candidate_caps_same_20':coverage,
        'causes':{
            'retrieval_coverage':'Only published ASSESSMENT_READY PROJECT candidates eligible; absent candidates cannot be assessed here.',
            'candidate_limit':'Measured separately above; more candidates do not establish support.',
            'semantic_restrictiveness':'Cannot quantify causal errors without independent human labels; model reasons are in private pair audit.',
            'literal_requirements':'V1 requires exact catalog labels, not lexical matching of those labels within project text. Quotes must remain literal in V2.',
            'insufficient_evidence':'15 partial and 6 unsupported are model decisions, not human-confirmed causes.',
            'invalid_assessments':len(errors),
            'confidence':'Post-classification only. Existing SUPPORTED scores 94 and 100; no confidence-based decision gate.',
            'post_filters':'Existing delivery retains all 23 valid decisions. No score cutoff; historical NULLs affect diagnostics if filtered as numeric.'},
        'v2_authorization':'Existing attestations cover historical pilot and 15 new V1 calls only; no V2-specific selection authorization.',
        'human_review_status':'PENDING','formula_v2_status':'CANDIDATE_NOT_APPROVED',
        'invariance':{'status':'PASS','protected_files':len(read(baseline))}}
    write_json(out/'diagnosis.json', result)
    write_json(out/'historical_pairs_private.json', details)
    return result
