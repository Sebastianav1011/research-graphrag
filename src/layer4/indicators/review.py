"""Human review exchange and candidate-conditional metrics. No invented labels."""
from collections import Counter, defaultdict
from itertools import combinations
import unicodedata

DECISIONS = ('SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'NOT_SUPPORTED')
COMPONENTS = ('key_element_coverage', 'field_relevance_score', 'corroboration_score', 'support_strength_score')


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def evidence_locations(project, assessment):
    locations = []
    for evidence in assessment.get('evidence', []):
        field, quote = evidence['field'], evidence['text']
        original = project['fields'].get(field) or ''
        start = original.find(quote)
        coordinate = 'original_unicode_codepoints_0_based_half_open'
        if start < 0:
            original, quote = normalize(original), normalize(quote)
            start = original.find(quote)
            coordinate = 'NFC_whitespace_collapsed_codepoints_0_based_half_open'
        locations.append({'field': field, 'text': evidence['text'],
                          'section_id': project.get('field_provenance', {}).get(field, {}).get('section_id'),
                          'start': start if start >= 0 else None,
                          'end': start + len(quote) if start >= 0 else None, 'coordinate_system': coordinate,
                          'match_valid': start >= 0})
    return locations


def component_summary(rows):
    result = {}
    for key in (*COMPONENTS, 'confidence_raw_score'):
        values = sorted(r[key] for r in rows if r.get(key) is not None)
        n = len(values)
        result[key] = {'n': n, 'missing_or_not_applicable': len(rows) - n,
                       'min': min(values) if n else None, 'max': max(values) if n else None,
                       'mean': sum(values) / n if n else None,
                       'median': (values[(n-1)//2] + values[n//2]) / 2 if n else None,
                       'histogram': dict(sorted(Counter(str(v) for v in values).items()))}
    return result


def classification_metrics(truth, predicted):
    n = len(truth)
    if not n:
        return None
    matrix = {a: {b: 0 for b in DECISIONS} for a in DECISIONS}
    for a, b in zip(truth, predicted):
        matrix[a][b] += 1
    accuracy = sum(matrix[c][c] for c in DECISIONS) / n
    per_class = {}
    for c in DECISIONS:
        tp = matrix[c][c]
        actual = sum(matrix[c].values())
        assigned = sum(matrix[a][c] for a in DECISIONS)
        precision = tp / assigned if assigned else 0.0
        recall = tp / actual if actual else 0.0
        per_class[c] = dict(support=actual, precision=precision, recall=recall,
                            f1=2*precision*recall/(precision+recall) if precision+recall else 0.0)
    expected = sum(sum(matrix[c].values()) * sum(matrix[a][c] for a in DECISIONS) for c in DECISIONS) / n**2
    return {'n': n, 'accuracy': accuracy, 'confusion_matrix': matrix,
            'macro_f1': sum(r['f1'] for r in per_class.values()) / len(DECISIONS),
            'per_class': per_class, 'cohen_kappa': (accuracy-expected)/(1-expected) if expected < 1 else None,
            'zero_division': 0, 'macro_classes': list(DECISIONS)}


def human_metrics(rows, labels):
    predictions = {(r['project_id'], r['indicator_id']): r for r in rows}
    reviewers = defaultdict(dict)
    evidence = []
    evidence_keys = set()
    for label in labels:
        decision = label.get('human_label')
        if not decision and label.get('evidence_valid') is None:
            continue
        key = label['project_id'], label['indicator_id']
        if key not in predictions:
            raise ValueError('Human label has no valid assessed candidate')
        if not label.get('reviewer_id') or label.get('independent') is not True:
            raise ValueError('Reviewer identity and explicit independent review required')
        if decision:
            if decision not in DECISIONS:
                raise ValueError('Unknown human label')
            group = reviewers[label['reviewer_id']]
            if key in group:
                raise ValueError('Duplicate human label for reviewer/candidate')
            group[key] = decision
        validity = label.get('evidence_valid')
        if validity is not None:
            if type(validity) is not bool:
                raise ValueError('evidence_valid must be boolean or null')
            evidence_key = (label['reviewer_id'], *key)
            if evidence_key in evidence_keys:
                raise ValueError('Duplicate evidence review for reviewer/candidate')
            evidence_keys.add(evidence_key)
            evidence.append(validity)
    per_reviewer = {name: classification_metrics(list(group.values()), [predictions[k]['decision'] for k in group])
                    for name, group in sorted(reviewers.items())}
    agreement = []
    for left, right in combinations(sorted(reviewers), 2):
        common = sorted(reviewers[left].keys() & reviewers[right].keys())
        agreement.append({'reviewers': [left, right], 'metrics': classification_metrics(
            [reviewers[left][k] for k in common], [reviewers[right][k] for k in common])})
    return {'status': 'AVAILABLE_PARTIAL' if reviewers else 'PENDING_HUMAN_LABELS',
            'scope': 'conditional_on_selected_published_candidates; not end_to_end_recall',
            'per_reviewer': per_reviewer, 'inter_reviewer_agreement': agreement,
            'evidence_validity': {'n': len(evidence), 'valid': sum(evidence),
                                  'rate': sum(evidence)/len(evidence) if evidence else None},
            'automatic_decision_strength_consistency': {'n': len(rows),
                'valid': sum(r['support_strength'] in {'SUPPORTED': (3,4), 'INSUFFICIENT_EVIDENCE': (1,2), 'NOT_SUPPORTED': (0,)}[r['decision']] for r in rows)},
            'calibration_status': 'NOT_CALIBRATED', 'confidence_is_probability': False}
