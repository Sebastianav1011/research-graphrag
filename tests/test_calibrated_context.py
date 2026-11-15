"""C1/M1/C2: calibrated token budget, consistent static threshold and material truncation.

Synthetic, offline: a hash-pinned word-level tokenizer stub replaces Qwen's
tokenizer; no model, server or embedding is used.
"""
import json

import pytest

from .test_ollama_provider import sample  # noqa: F401  (fixture)
from .test_context_budget import corpus, relational_fixture  # noqa: F401  (fixture)
from layer4_evaluation import live_execution as live
from layer4_evaluation.indicators import context_budget as cb, assessment_v3 as v3, ollama_provider as transport
from layer4_evaluation.indicators.evidence_references import response_schema, CORRECTIVE_INPUT_RESERVE
from layer4_evaluation.indicators.token_budget import count

WIDE = dict(num_ctx=16384, num_predict=4096, context_margin_tokens=1024)


def retrieved(corpus, texts, settings, tokenizer):
    """One methodology section split into ranked, contiguous chunks."""
    pid = corpus.project['project_id']
    section = ''.join(texts)
    corpus.project['fields']['methodology'] = section
    chunks, start = [], 0
    for n, text in enumerate(texts):
        chunks.append(dict(chunk_id=f'CHUNK_{n}', section_id='SECTION', source_id=pid, field_name='methodology',
            text=text, char_start=start, char_end=start + len(text)))
        start += len(text)
    sections = [dict(corpus.sections[0], text_original=section)]
    hits = [dict(candidate_id='C_I00', source_id=pid, source_type='PROJECT', indicator_id='I00', context_package_id='CTX',
        discovery_chunks=[dict(chunk_id=c['chunk_id'], field_name='methodology', vector_rank=n + 1,
            vector_score=.9 - n / 10, retrieval_origin='OWN_PROJECT_CACHED_RETRIEVAL_V1') for n, c in enumerate(chunks)])]
    requests, report = cb.prepare_contexts([corpus.project], {'I00': corpus.profiles['I00']}, corpus.rubrics,
        corpus.settings | settings, hits if texts else [], chunks, sections, evidence_references=True,
        assessment_version=v3.SK_VERSION, context_mode=v3.RETRIEVED_CONTEXT, tokenizer=tokenizer)
    return requests[pid]['I00'], report


def template_tokens(corpus, tokenizer):
    request, _ = retrieved(corpus, [], WIDE, tokenizer)
    assert request['context_selection']['status'] == 'NO_RETRIEVED_EVIDENCE'
    return request['context_budget']['estimated_input_tokens']


def window(base, room):
    """Settings whose evidence threshold leaves exactly ``room`` tokens above the template."""
    return dict(WIDE, num_ctx=4096 + 1024 + cb.RELATIONAL_RESERVE + CORRECTIVE_INPUT_RESERVE + base + room)


def test_calibrated_budget_is_exact_capped_and_reproduced_by_transport(corpus, tokenizer_stub):
    request, report = retrieved(corpus, ['Synthetic mechanism documented for the project. '], WIDE, tokenizer_stub)
    budget = request['context_budget']
    assert budget['estimator'] == 'PINNED_QWEN_TOKENIZER_AND_CALIBRATED_TEMPLATE_V1' and not budget['approximate']
    assert budget['estimated_input_tokens'] == count(request['prompt'], tokenizer_stub) + 12
    assert budget['input_cap'] == budget['input_budget'] == 8000  # 16384-4096-1024 > 8000: cap preserved
    assert budget['tokenizer']['sha256'] == tokenizer_stub['sha256']
    schema = response_schema(request, corpus.project['fields'])
    assert cb.rebudget(request['prompt'], schema, corpus.settings | WIDE, budget) == budget
    transport.context_guard(request['prompt'], schema, corpus.settings | WIDE, budget=budget)
    runtime = dict(digest='other', model_metadata_sha256='synthetic-metadata', template_bytes=0)
    with pytest.raises(transport.OllamaError, match='Tokenizer y plantilla'):
        transport.context_guard(request['prompt'], schema, corpus.settings | WIDE, runtime, budget)
    assert 'Pinned Qwen tokenizer' in report['estimator_note']


def test_historical_estimator_is_unchanged_without_tokenizer(corpus):
    request, report = retrieved(corpus, ['Synthetic mechanism documented for the project. '], WIDE, None)
    assert request['context_budget']['estimator'] == 'UTF8_DIV_2_PLUS_TEMPLATE_256_APPROX_V1'
    assert 'input_cap' not in request['context_budget'] and 'Approximate' in report['estimator_note']


def test_tampered_tokenizer_is_rejected(corpus, tokenizer_stub):
    with open(tokenizer_stub['path'], 'a', encoding='utf-8') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='TOKENIZER_CHANGED'):
        retrieved(corpus, ['Synthetic mechanism documented. '], WIDE, tokenizer_stub)


def test_template_without_room_is_static_limit_not_no_evidence(corpus, tokenizer_stub):
    base = template_tokens(corpus, tokenizer_stub)
    # Template fits the 8000-style ceiling but not the effective evidence threshold.
    request, _ = retrieved(corpus, ['Synthetic mechanism documented. '], window(base, -100), tokenizer_stub)
    selection = request['context_selection']
    assert selection['status'] == 'STATIC_CONTEXT_TOO_LONG'
    assert selection['truncation']['reason'] == 'TEMPLATE_EXCEEDS_EVIDENCE_THRESHOLD'
    assert request['context_budget']['estimated_input_tokens'] + CORRECTIVE_INPUT_RESERVE <= request['context_budget']['input_budget']


def test_brief_complete_evidence_stays_ready_and_unlimited(corpus, tokenizer_stub):
    request, _ = retrieved(corpus, ['One short documented sentence. '], WIDE, tokenizer_stub)
    selection = request['context_selection']
    assert selection['status'] == 'READY' and not selection['evidence_limited']
    assert selection['truncation'] | {} == dict(selection['truncation'], material=False, top_ranked_intact=True, reason=None)
    assert [f['text'] for f in request['payload']['project']['fragments']] == ['One short documented sentence. ']


def test_lower_ranked_omission_is_ready_but_audited(corpus, tokenizer_stub):
    base = template_tokens(corpus, tokenizer_stub)
    top = 'Top ranked documented mechanism. '
    tail = 'indivisible ' * 400  # no sentence boundary: cannot be cut
    request, report = retrieved(corpus, [top, tail], window(base, 60), tokenizer_stub)
    selection = request['context_selection']
    assert selection['status'] == 'READY' and selection['evidence_limited']
    assert selection['truncation']['reason'] == 'LOWER_RANKED_UNITS_OMITTED_BY_BUDGET'
    assert selection['truncation']['budget_omitted_chunk_ids'] == ['CHUNK_1'] and not selection['truncation']['material']
    assert report['requests'][0]['evidence_limited'] and report['requests'][0]['truncation'] == selection['truncation']


def test_top_ranked_unit_cut_to_a_sentence_is_truncated_and_never_dispatched(corpus, tokenizer_stub):
    base = template_tokens(corpus, tokenizer_stub)
    top = 'First documented sentence of the top unit. ' + 'Further supporting detail follows here. ' * 60
    request, _ = retrieved(corpus, [top], window(base, 40), tokenizer_stub)
    selection = request['context_selection']
    assert selection['status'] == cb.EVIDENCE_TRUNCATED
    assert selection['truncation'] | {} == dict(selection['truncation'], material=True, top_ranked_intact=False,
        reason='TOP_RANKED_UNIT_NOT_INTACT', subspan_chunk_ids=['CHUNK_0'])
    assert selection['evidence_limited'] and selection['selected'][0]['unit'] == 'ORIGINAL_SENTENCE_SPAN'
    # Any non-READY prepared status becomes a context limit: no Qwen call, no valid row.
    state = dict(project_id='P', blocked_indicators={}, context_limits={'I00': selection['status']})
    assert not live.runnable_indicator(state, 'I00', set())


def test_no_unit_fits_keeps_no_evidence_fits(corpus, tokenizer_stub):
    base = template_tokens(corpus, tokenizer_stub)
    request, _ = retrieved(corpus, ['indivisible ' * 400], window(base, 30), tokenizer_stub)
    assert request['context_selection']['status'] == 'NO_EVIDENCE_FITS'
    assert request['context_selection']['truncation']['reason'] == 'NO_RETRIEVED_UNIT_FITS'


def test_relations_use_the_same_calibrated_budget(corpus, tokenizer_stub):
    pid = corpus.project['project_id']
    text = 'Synthetic mechanism documented for the project. '
    corpus.project['fields']['methodology'] = text
    chunk = dict(chunk_id='CHUNK', section_id='SECTION', source_id=pid, field_name='methodology', text=text, char_start=0, char_end=len(text))
    hit = dict(corpus.hits[0], relational_context=relational_fixture(pid))
    requests, _ = cb.prepare_contexts([corpus.project], {'I00': corpus.profiles['I00']}, corpus.rubrics,
        corpus.settings | WIDE, [hit], [chunk], [dict(corpus.sections[0], text_original=text)], evidence_references=True,
        assessment_version=v3.SK_VERSION, context_mode=v3.RETRIEVED_CONTEXT, tokenizer=tokenizer_stub)
    request = requests[pid]['I00']
    assert request['context_selection']['status'] == 'READY'
    assert [r['relation_id'] for r in request['payload']['relational_context']['relations']] == ['E1', 'E2']
    assert request['context_budget']['estimated_input_tokens'] == count(request['prompt'], tokenizer_stub) + 12
    assert 'UNSELECTED' not in json.dumps(response_schema(request, corpus.project['fields']))


def test_v3_relations_show_provenance_digest_and_keep_full_provenance_out_of_prompt(corpus, tokenizer_stub):
    """RELATIONAL_PROVENANCE_DIGEST_V1: audit metadata (local paths, hashes) is not sent to the model."""
    import hashlib
    pid = corpus.project['project_id']
    text = 'Synthetic mechanism documented for the project. '
    corpus.project['fields'].update(methodology=text, title='Titulo')
    corpus.rubrics, _ = v3.catalog_for_mode(corpus.profiles, corpus.rubrics, v3.PROSPECTIVE)
    chunk = dict(chunk_id='CHUNK', section_id='SECTION', source_id=pid, field_name='methodology', text=text, char_start=0, char_end=len(text))
    package = relational_fixture(pid)
    hit = dict(corpus.hits[0], relational_context=package)
    def build(version):
        requests, _ = cb.prepare_contexts([corpus.project], {'I00': corpus.profiles['I00']}, corpus.rubrics,
            corpus.settings | WIDE, [hit], [chunk], [dict(corpus.sections[0], text_original=text)], evidence_references=True,
            assessment_version=v3.SK_VERSION, evaluation_mode=v3.PROSPECTIVE, context_mode=v3.RETRIEVED_CONTEXT,
            tokenizer=tokenizer_stub, prompt_version=version)
        return requests[pid]['I00']
    new, old = build(v3.PROSPECTIVE_PROMPT_V3), build(None)
    shown = new['payload']['relational_context']
    assert shown['provenance_projection'] == 'RELATIONAL_PROVENANCE_DIGEST_V1'
    assert 'base/members.csv' not in new['prompt'] and 'base/members.csv' in old['prompt']
    original = {r['relation_id']: r for r in package['relations']}
    for relation in shown['relations']:
        assert 'provenance' not in relation
        assert relation['provenance_sha256'] == hashlib.sha256(json.dumps(original[relation['relation_id']]['provenance'],
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert new['relational_context_receipt']['selected_relation_ids'] == ['E1', 'E2']


def test_input_cap_limits_only_the_local_model_and_api_receives_complete_ranked_evidence(corpus, tokenizer_stub):
    """Qwen keeps the 8000 cap; the API gets every ranked unit, in the same order, within its window."""
    texts = ['Top ranked documented mechanism. '] + [f'lower ranked documented activity {n} ' * 600 + '. ' for n in range(4)]
    local, _ = retrieved(corpus, texts, WIDE, tokenizer_stub)
    api, _ = retrieved(corpus, texts, dict(WIDE, provider='openai', num_ctx=32768), tokenizer_stub)
    assert local['context_budget']['input_cap'] == 8000 and local['context_selection']['evidence_limited']
    assert 'input_cap' not in api['context_budget'] and api['context_budget']['input_budget'] == 32768 - 4096 - 1024
    assert not api['context_selection']['evidence_limited'] and api['context_selection']['status'] == 'READY'
    whole = ''.join(f['text'] for f in api['payload']['project']['fragments'])
    assert whole == corpus.project['fields']['methodology']  # complete, literal, original order
    seen = [f['text'] for f in local['payload']['project']['fragments']]
    assert seen == [f['text'] for f in api['payload']['project']['fragments']][:len(seen)]  # local = prefix of the same ranking


def test_api_binding_sizes_window_for_retrieved_graph_and_local_binding_is_unchanged(tmp_path, monkeypatch):
    import experiment_runtime as er
    token = er.options.set(dict(provider='openai', budget_usd=15))
    import shutil; (tmp_path / 'config').mkdir(); shutil.copyfile('config/openai.json', tmp_path / 'config/openai.json')
    policy = dict(context_mode='BASE_RETRIEVED_GRAPH_V1')
    run = tmp_path / 'run'; run.mkdir()
    api = er.binding(tmp_path, run, dict(num_ctx=16384, context_margin_tokens=1024), evaluation=policy)['llm']
    assert api['provider'] == 'openai' and api['num_ctx'] == er.API_RETRIEVED_CONTEXT == 32768 and api['context_margin_tokens'] == 1024
    er.options.reset(token); token = er.options.set(dict(provider='ollama'))
    local = er.binding(tmp_path, run, dict(num_ctx=16384, context_margin_tokens=1024), evaluation=policy)['llm']
    er.options.reset(token)
    assert local['provider'] == 'ollama' and local['num_ctx'] == 16384
