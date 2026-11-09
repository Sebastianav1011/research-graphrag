"""Hierarchical word windows over normalized text; offsets are half-open."""
import re
from .provenance import descendant, stable_id, text_hash
from .text_normalization import words


def boundary_indices(text, tokens, config):
    ends = {token.end(): i+1 for i, token in enumerate(tokens)}
    paragraphs, sentences = set(), set()
    for match in re.finditer(r'\n\s*\n', text):
        end = len(text[:match.start()].rstrip())
        if end in ends:
            paragraphs.add(ends[end])
    # Deterministic heuristic, not a linguistic parser. Abbreviations may form boundaries.
    for i, token in enumerate(tokens):
        if re.search(r'[.!?][\"\u201d\u2019\)\]]*$', token.group()):
            sentences.add(i+1)
    return paragraphs if config['preserve_paragraphs'] else set(), sentences if config['preserve_sentences'] else set()


def spans(text, config):
    tokens = words(text)
    if not tokens:
        return []
    maximum, target, overlap = (config[k] for k in ('max_words', 'target_words', 'overlap_words'))
    if not (0 <= overlap < target <= maximum):
        raise ValueError('Invalid chunk sizes')
    if len(tokens) <= maximum:
        return [(tokens[0].start(), tokens[-1].end(), 0)]
    paragraphs, sentences = boundary_indices(text, tokens, config)
    result, start, previous_end = [], 0, 0
    while start < len(tokens):
        limit = min(start + maximum, len(tokens))
        if limit == len(tokens):
            end = limit
        else:
            # Prefer paragraph ends, then sentence ends; never emit overlap-only windows.
            floor = max(start + overlap + 1, previous_end + 1)
            candidates = [p for p in paragraphs if floor <= p <= limit]
            if not candidates:
                candidates = [s for s in sentences if floor <= s <= limit]
            end = min(candidates, key=lambda n: (abs(n - (start + target)), n)) if candidates else min(start + target, limit)
            end = max(end, floor)
        actual_overlap = max(0, previous_end - start)
        result.append((tokens[start].start(), tokens[end-1].end(), actual_overlap))
        if end == len(tokens):
            break
        previous_end = end
        start = end - overlap
    return result


def build_chunks(sections, config, context):
    chunks = []
    for section in sections:
        for index, (start, end, overlap) in enumerate(spans(section['text_normalized'], config['chunking'])):
            text = section['text_normalized'][start:end]
            digest = text_hash(text)
            chunk_id = stable_id('CHUNK', section['source_type'], section['source_id'], section['field_name'], index, digest)
            chunks.append({'chunk_id': chunk_id, 'section_id': section['section_id'],
                'document_id': section['document_id'], 'source_id': section['source_id'],
                'source_type': section['source_type'], 'field_name': section['field_name'],
                'chunk_index': index, 'text': text, 'char_start': start, 'char_end': end,
                'word_count': len(words(text)), 'overlap_word_count': overlap, 'chunk_hash': digest,
                'provenance_json': descendant(section['provenance_json'], chunk_id=chunk_id,
                    chunk_hash=digest, char_start=start, char_end=end, offset_basis='text_normalized',
                    overlap_word_count=overlap), 'layer2_run_id': context['layer2_run_id']})
    return chunks
