"""Inactive, lossless JSON serialization experiment for V3.3 discovery.

No provider/runner is registered here. The semantic policy, response contract,
all profile fields and all six original project fields remain unchanged.
"""
import json

from . import global_discovery_v3_3 as base

INPUT_VERSION = 'GLOBAL_DISCOVERY_V3_3_COMPACT_JSON_V1'
DELIMITER = '\nINPUT_JSON:\n'


def make_input(project, profiles, rules, max_assessments=base.historical.MAX_ASSESSMENTS):
    request = base.make_input(project, profiles, rules, max_assessments)
    instructions, original_json = request['prompt'].split(DELIMITER, 1)
    assert json.loads(original_json) == request['payload']
    request['prompt'] = instructions + DELIMITER + json.dumps(
        request['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    request['input_version'] = INPUT_VERSION
    return request
