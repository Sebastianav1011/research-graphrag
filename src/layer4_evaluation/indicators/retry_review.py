"""Hash-bound independent review of contradictory prospective retry judgments.

No keyword classification, scoring, semantic repair or automatic human approval.
Public assessments keep their existing schema; this is private transport policy.
"""
import hashlib
import json

VERSION = 'PROSPECTIVE_RETRY_INDEPENDENT_REVIEW_V1'
ORDER = {'NOT_DEMONSTRATED': 0, 'PARTIAL': 1, 'CLEAR': 2}
DIMENSIONS = ('directness', 'specificity', 'clarity', 'temporal_alignment')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':')).encode('utf-8')).hexdigest()


CRITERION_RULES = ('V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE', 'P2_CRITERION:CONTEXT_ONLY_REFERENCES',
                   'P2_CRITERION:CONTEXT_OR_UNRELATED_IS_NOT_SUBSTANTIVE_SUPPORT', 'V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE')
STRENGTH_RULES = ('SK_STRENGTH:ZERO_ANCHOR_MISMATCH', 'SK_ZERO_SUPPORT:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',
                  'SK_STRENGTH:POSITIVE_REQUIRES_EVIDENCE')


def localized_details(issues, selection, request):
    """C2: name the criterion and field behind each rejected rule (derived protocol).

    Recomputes WHICH judgment violates an already reported rule from the model's
    own selection and the sent rubric/fragments. It never decides support, stages
    or citations and never repairs anything.
    """
    if not selection or not selection.get('assessments'):return issues
    item=selection['assessments'][0]
    rubric={c['criterion_id']:c for c in request['payload']['indicators'][0]['rubric']['criteria']}
    fields={f['fragment_id']:f['field'] for f in request['payload']['project']['fragments']}
    from .selection import substantive_fields
    substantive=substantive_fields(list(fields.values()))
    def offending(rule,c):
        refs=c.get('evidence_refs',[]);crit=rubric.get(c['criterion_id'],{})
        sub=[r for r in refs if fields.get(r['fragment_id']) in substantive]
        if rule=='V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE':
            return c['support']=='NOT_DEMONSTRATED' and bool(refs)
        if c['support']=='NOT_DEMONSTRATED':return False
        if rule=='V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE':
            return c['support']=='CLEAR' and not any(r['stage'] in crit.get('compatible_stages',()) for r in sub)
        if rule=='P2_CRITERION:CONTEXT_ONLY_REFERENCES':
            return crit.get('temporal_requirement')!='CONTEXT_ONLY' and not any(r['stage']!='CONTEXT' for r in sub)
        return False
    result=[];seen=set()
    for original in issues:
        issue=dict(original);rule=issue.get('rule')
        key=rule,issue.get('path')
        if key in seen:continue  # The same rule is reported once per offending judgment below.
        seen.add(key)
        if rule in CRITERION_RULES:
            ids=[c['criterion_id'] for c in item['criterion_assessments'] if offending(rule,c)]
            if ids:
                for cid in ids:
                    index=[c['criterion_id'] for c in item['criterion_assessments']].index(cid)
                    result.append(dict(issue,criterion_id=cid,path=f'$.criterion_assessments[{index}].evidence_refs'))
                continue
        elif rule in STRENGTH_RULES:
            issue['path']='$.strength_rubric'
        elif rule and rule.startswith('P2_APPLICABILITY:'):
            issue['path']='$.scope_exclusion'
        result.append(issue)
    return result


def diagnostic_details(issues,selection,request=None):
    """Locate an already-reported contradiction; never repair or assign support."""
    from . import prospective_v2 as p2
    if request is not None and request.get('component_protocol')==p2.DERIVED_PROTOCOL:
        return localized_details(issues,selection,request)
    if not selection or not selection.get('assessments'):return issues
    criteria=selection['assessments'][0].get('criterion_assessments',[])
    result=[]
    for original in issues:
        issue=dict(original)
        if issue.get('rule')=='V3_CRITERION:UNSUPPORTED_CANNOT_CLAIM_EVIDENCE':
            ids=[c['criterion_id'] for c in criteria if c.get('support')=='NOT_DEMONSTRATED' and c.get('evidence_refs')]
            if len(ids)==1:issue['criterion_id']=ids[0]
            elif ids:issue['criterion_ids']=ids
        if issue.get('rule')=='P2_APPLICABILITY:SUBSTANTIVE_SCOPE_EVIDENCE_REQUIRED':
            issue['path']='$.applicability.evidence_refs'
        result.append(issue)
    return result


def compare(before, candidate, original_request, request, original_schema, schema, decision):
    """Return facts; only supported semantic promotions require adjudication."""
    old, new = before['assessments'][0], candidate['assessments'][0]
    previous = {c['criterion_id']:c for c in old['criterion_assessments']}
    criteria = request['payload']['indicators'][0]['rubric']['criteria']
    essential = {c['criterion_id'] for c in criteria if c['role'] != 'COMPLEMENTARY'}
    promoted = [c['criterion_id'] for c in new['criterion_assessments'] if c['criterion_id'] in essential and c['criterion_id'] in previous and
        (ORDER[c['support']]>ORDER[previous[c['criterion_id']]['support']] or
         c.get('coverage',0)>previous[c['criterion_id']].get('coverage',0))]
    global_promotions = []
    if 'scope_exclusion' in old or 'scope_exclusion' in new:
        # Derived transport: withdrawing a claimed exclusion re-opens SUPPORTED.
        if old.get('scope_exclusion',{}).get('claimed') and not new.get('scope_exclusion',{}).get('claimed'):
            global_promotions.append('applicability')
    else:
        app = old.get('applicability',{}).get('status'), new.get('applicability',{}).get('status')
        if app[0] != 'APPLICABLE' and app[1] == 'APPLICABLE':global_promotions.append('applicability')
    # support_strength is Python-derived (absent) in the derived transport; criterion
    # promotions already cover it. Legacy transports keep the original comparison.
    stronger = ('support_strength' in new and 'support_strength' in old and
                new['support_strength']>old['support_strength'])
    if stronger or any(new['strength_rubric'][d]>old['strength_rubric'][d] for d in DIMENSIONS):
        global_promotions.append('strength_rubric')
    binding = dict(policy=VERSION,baseline_sha256=fingerprint(before),candidate_sha256=fingerprint(candidate),
        original_payload_sha256=fingerprint(original_request['payload']),payload_sha256=fingerprint(request['payload']),
        original_schema_sha256=fingerprint(original_schema),schema_sha256=fingerprint(schema))
    same_payload = binding['original_payload_sha256']==binding['payload_sha256']
    same_schema = binding['original_schema_sha256']==binding['schema_sha256']
    return dict(version=VERSION,binding=binding,review_fingerprint=fingerprint(binding),
        same_evidence=fingerprint(original_request['payload']['project'])==fingerprint(request['payload']['project']),
        same_payload=same_payload,same_schema=same_schema,
        original_instructions_sha256=fingerprint(original_request['prompt'].split('INPUT_JSON:\n',1)[0]),
        instructions_sha256=fingerprint(request['prompt'].split('INPUT_JSON:\n',1)[0]),
        promoted_criteria=promoted,promoted_global_fields=global_promotions,
        original_recommendation=old.get('decision'),candidate_recommendation=new.get('decision'),derived_decision=decision,
        review_required=decision=='SUPPORTED' and bool(promoted or global_promotions),
        status='PENDING_REVIEW' if decision=='SUPPORTED' and bool(promoted or global_promotions) else 'NO_REVIEW_REQUIRED')


def validate_review(report, review, candidate, request):
    """Validate independent adjudication metadata and exact documentary witnesses.

    A trusted human supplies this sidecar, never the model response. This checks
    its binding/provenance, not the truth of the human's semantic interpretation.
    """
    if not isinstance(review,dict):return False
    if (review.get('authority')!='HUMAN' or review.get('verdict')!='APPROVE_REINTERPRETATION' or
        review.get('review_fingerprint')!=report['review_fingerprint'] or
        not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip() or
        not isinstance(review.get('rationale'),str) or not review['rationale'].strip()):return False
    item=candidate['assessments'][0]
    judgments={c['criterion_id']:c for c in item['criterion_assessments']}
    judgments.update({k:item[k] for k in ('applicability','strength_rubric') if k in item})
    if 'scope_exclusion' in item:judgments['applicability']=item['scope_exclusion']
    fragments={f['fragment_id']:f for f in request['payload']['project']['fragments']}
    needed=set(report['promoted_criteria']+report['promoted_global_fields'])
    supplied=review.get('judgments')
    if not isinstance(supplied,list):return False
    if len(supplied)!=len(needed) or {s.get('field') for s in supplied if isinstance(s,dict)}!=needed:return False
    for judgment in supplied:
        if not isinstance(judgment.get('rationale'),str) or not judgment['rationale'].strip():return False
        witnesses=judgment.get('witnesses')
        if not isinstance(witnesses,list) or not witnesses:return False
        claimed=judgments[judgment['field']].get('evidence_refs',[])
        for witness in witnesses:
            if not isinstance(witness,dict):return False
            ref=dict(fragment_id=witness.get('fragment_id'),stage=witness.get('stage'))
            if not all(isinstance(v,str) for v in ref.values()):return False
            fragment=fragments.get(ref['fragment_id']);span=witness.get('span')
            if (ref not in claimed or not fragment or not isinstance(span,str) or not span.strip() or
                span not in fragment['text']):return False
    return True
