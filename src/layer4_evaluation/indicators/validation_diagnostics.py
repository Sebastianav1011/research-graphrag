"""Safe structured diagnostics: never include source text or model narratives."""
import re


class AssessmentValidationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(i['rule'] + ' at ' + i['path'] for i in issues))


def semantic_issues(errors, assessment, indicator_id, rubric=None, project_fields=None):
    issues = []
    for code in dict.fromkeys(errors):
        path = '$'
        match = re.match(r'(evidence\[\d+\](?:\.[a-z_]+)?|[a-z_]+):', code)
        if match:
            path += '.' + match[1]
        category = ('EVIDENCE_NOT_VERIFIABLE' if 'QUOTE_NOT_FOUND' in code else
                    'DECISION_CRITERIA_INCONSISTENCY' if 'NOT_SUPPORTED' in code or 'ZERO_SUPPORT' in code or 'INCONSISTENT_DECISION' in code else
                    'INVALID_FIELD_VALUE')
        if code=='V3_CRITERION:CLEAR_REQUIRES_COMPATIBLE_SUBSTANTIVE_EVIDENCE' and rubric is not None:
            from .assessment_v3 import TEMPORAL
            from .selection import substantive_fields
            criteria={c['criterion_id']:c for c in rubric['criteria']}
            evidence=assessment['evidence']
            for index,item in enumerate(assessment['criterion_assessments']):
                criterion=criteria.get(item['criterion_id'])
                if item['support']!='CLEAR' or criterion is None:continue
                refs=[evidence[i] for i in item['evidence_indices'] if 0<=i<len(evidence)]
                if not any(e['stage'] in TEMPORAL[criterion['temporal_requirement']] and
                           e['field'] in substantive_fields(project_fields) for e in refs):
                    issues.append(dict(category=category,rule=code,path=f'$.criterion_assessments[{index}].support',
                        indicator_id=indicator_id,criterion_id=item['criterion_id'],evidence_indices=item['evidence_indices'],
                        temporal_requirement=criterion['temporal_requirement'],observed_stages=[e['stage'] for e in refs]))
            continue
        if code == 'V3_CRITERION:EVIDENCE_INDEX_OUT_OF_RANGE':
            for index, criterion in enumerate(assessment['criterion_assessments']):
                invalid = [i for i in criterion['evidence_indices'] if i < 0 or i >= len(assessment['evidence'])]
                if invalid:
                    issues.append(dict(category='EVIDENCE_ID_NOT_FOUND', rule=code,
                        path=f'$.criterion_assessments[{index}].evidence_indices', indicator_id=indicator_id,
                        criterion_id=criterion['criterion_id'], evidence_indices=invalid,
                        evidence_count=len(assessment['evidence'])))
            continue
        if code == 'V3_CRITERION:POSITIVE_SUPPORT_REQUIRES_QUOTE':
            for index, criterion in enumerate(assessment['criterion_assessments']):
                if criterion['support'] != 'NOT_DEMONSTRATED' and not criterion['evidence_indices']:
                    issues.append(dict(category='INVALID_FIELD_VALUE', rule=code,
                        path=f'$.criterion_assessments[{index}].evidence_indices',
                        indicator_id=indicator_id, criterion_id=criterion['criterion_id']))
            continue
        if code == 'SK_CRITERION:COVERAGE_SUPPORT_MISMATCH':
            # Name the exact criteria and values; never suggest a direction.
            allowed = {'CLEAR': [4], 'PARTIAL': [1, 2, 3], 'NOT_DEMONSTRATED': [0]}
            found = False
            for index, item in enumerate(assessment.get('criterion_assessments', [])):
                if item.get('support') in allowed and item.get('coverage') not in allowed[item['support']]:
                    found = True
                    issues.append(dict(category=category, rule=code, path=f'$.criterion_assessments[{index}].coverage',
                        indicator_id=indicator_id, criterion_id=item.get('criterion_id'), support=item['support'],
                        coverage=item.get('coverage'), allowed_coverage=allowed[item['support']]))
            if found:
                continue
        issue = dict(category=category, rule=code, path=path, indicator_id=indicator_id)
        if code.startswith('SK_STRENGTH:') or code == 'V3_POSITIVE_STRENGTH:REQUIRES_EVIDENCE':
            strength = assessment.get('strength_rubric') or {}
            dims = [strength.get(k) for k in ('directness', 'specificity', 'clarity', 'temporal_alignment')]
            issue.update(support_strength=assessment.get('support_strength'),
                strength_total=sum(v for v in dims if type(v) is int),
                positive_criterion_ids=[c.get('criterion_id') for c in assessment.get('criterion_assessments', [])
                                        if c.get('support') != 'NOT_DEMONSTRATED'])
        if code == 'V3_POSITIVE_STRENGTH:REQUIRES_EVIDENCE':
            issue.update(path='$.support_strength',
                correction_hint='La fuerza positiva requiere referencias literales. Reevalua decision y criterios; '
                    'no inventes evidencia ni conviertas un fallo tecnico en NOT_SUPPORTED.')
        if code in ('V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT',
                    'SK_ZERO_SUPPORT:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT'):
            issue.update(path='$.decision', criterion_ids=[c['criterion_id'] for c in
                assessment['criterion_assessments'] if c['support'] != 'NOT_DEMONSTRATED'])
        elif code.startswith(('V3_CRITERION:', 'V3_CRITERIA:', 'V3_SUPPORTED:')):
            issue['path'] = '$.criterion_assessments'
        issues.append(issue)
    return issues
