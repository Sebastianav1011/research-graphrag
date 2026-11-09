"""Aggregate console output only; persisted manifests and results stay complete."""
from collections import Counter

IDS = {'projects', 'project_ids', 'requested_projects', 'pending_projects', 'eligible_projects',
       'blocked_projects', 'affected_projects', 'identity_links', 'project_indicators',
       'project_features', 'project_inputs', 'selected_ids'}


def compact(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in IDS and isinstance(item, (list, dict)):
                result[key+'_count'] = len(item)
                if isinstance(item,list) and item and isinstance(item[0],dict):
                    result[key+'_states'] = dict(Counter(r.get('status',r.get('state','UNKNOWN')) for r in item))
            else:
                result[key] = compact(item)
        return result
    if isinstance(value,list):
        return [compact(item) for item in value] if len(value) <= 12 else {'count':len(value)}
    return value
