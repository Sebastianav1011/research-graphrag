"""Purposeful diversity sample, deterministic and independent of file order."""
from collections import Counter
from copy import deepcopy
import hashlib

from .selection import candidate_key

VERSION = 'DIVERSITY_GREEDY_V1'


def features(project, profiles):
    primary = profiles[project['candidates'][0]['indicator_id']]
    fields = project['fields']
    length = sum(len(v or '') for v in fields.values())
    return {
        'category': primary['indicator_category'],
        'dimension': primary.get('indicator_dimension') or 'UNAVAILABLE',
        'area': project.get('knowledge_area') or 'UNAVAILABLE',
        'primary_indicator': primary['indicator_id'],
        'field_pattern': ','.join(k for k in sorted(fields) if fields[k]),
        'length_band': 'SHORT_LT_2000' if length < 2000 else 'MEDIUM_LT_8000' if length < 8000 else 'LONG_GE_8000',
    }


def distribution(projects, profiles):
    result = {k: Counter() for k in ('category', 'dimension', 'area', 'primary_indicator', 'field_pattern', 'length_band')}
    for project in projects:
        for key, value in features(project, profiles).items():
            result[key][value] += 1
    return {k: dict(sorted(v.items())) for k, v in result.items()}


def select_sample(eligible, profiles, *, count=50, limit=2, seed='LAYER4A_50_V1', secondary_rank_window=3):
    if count < 1 or limit not in (1, 2) or secondary_rank_window < 1:
        raise ValueError('Positive sample count and one/two candidates required')
    if len({p['project_id'] for p in eligible}) != len(eligible):
        raise ValueError('Duplicate eligible PROJECT')
    if len(eligible) < count:
        raise ValueError(f'Only {len(eligible)} eligible PROJECTs, requested {count}')
    remaining = [deepcopy(p) for p in eligible]
    for p in remaining:
        p['candidates'].sort(key=candidate_key)
    selected = []
    counts = {k: Counter() for k in features(remaining[0], profiles)}
    indicators = Counter()
    while len(selected) < count:
        # New categories/areas first, then primary indicator, dimension and text
        # characteristics. Balance already represented strata; hash breaks ties.
        def priority(p):
            f = features(p, profiles)
            order = ('category', 'area', 'primary_indicator', 'dimension', 'field_pattern', 'length_band')
            return (tuple(int(counts[k][f[k]] > 0) for k in order),
                    tuple(counts[k][f[k]] for k in order),
                    hashlib.sha256((seed + ':' + p['project_id']).encode()).hexdigest(), p['project_id'])
        project = min(remaining, key=priority)
        remaining.remove(project)
        f = features(project, profiles)
        novel = [k + ':' + v for k, v in f.items() if not counts[k][v]]
        all_candidates = project['candidates']
        chosen = all_candidates[:1]
        if limit == 2 and len(all_candidates) > 1:
            pool = all_candidates[1:1 + secondary_rank_window]
            # Preserve the top candidate. Diversity chooses the second only
            # within a recorded, bounded window of the existing score ranking.
            second = min(pool, key=lambda c: (indicators[c['indicator_id']], candidate_key(c)))
            chosen.append(second)
        project.update(candidates=chosen, eligible_candidate_count=len(all_candidates),
                       eligible_candidates=all_candidates, selection_order=len(selected) + 1,
                       selection_method=VERSION, selection_features=f,
                       inclusion_criteria={'new_strata': novel, 'stratum_counts_before': {k: counts[k][v] for k, v in f.items()},
                                           'primary': 'highest published hybrid_retrieval_score; indicator_id tie break',
                                           'secondary': f'least selected indicator in next {secondary_rank_window} ranked candidates; score tie break'})
        for key, value in f.items():
            counts[key][value] += 1
        indicators.update(c['indicator_id'] for c in chosen)
        selected.append(project)
    return selected
