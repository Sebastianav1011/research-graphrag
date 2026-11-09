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
                    'DECISION_CRITERIA_INCONSISTENCY' if 'NOT_SUPPORTED' in code or 'INCONSISTENT_DECISION' in code else
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
                invalid = [i for i in criterion['evidence_indices'] if i >= len(assessment['evidence'])]
                if invalid:
                    issues.append(dict(category='EVIDENCE_ID_NOT_FOUND', rule=code,
                        path=f'$.criterion_assessments[{index}].evidence_indices', indicator_id=indicator_id,
                        criterion_id=criterion['criterion_id'], evidence_indices=invalid,
                        evidence_count=len(assessment['evidence'])))
            continue
        issue = dict(category=category, rule=code, path=path, indicator_id=indicator_id)
        if code == 'V3_NOT_SUPPORTED:CANNOT_CLAIM_POSITIVE_CONCEPTUAL_SUPPORT':
            issue.update(path='$.decision', criterion_ids=[c['criterion_id'] for c in
                assessment['criterion_assessments'] if c['support'] != 'NOT_DEMONSTRATED'])
        elif code.startswith(('V3_CRITERION:', 'V3_CRITERIA:', 'V3_SUPPORTED:')):
            issue['path'] = '$.criterion_assessments'
        issues.append(issue)
    return issues
