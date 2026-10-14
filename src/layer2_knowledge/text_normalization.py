"""Conservative normalization, retaining original text at section level."""
import re
import unicodedata


def words(text):
    return list(re.finditer(r'\S+', text))


def as_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return '\n'.join(value)
    raise ValueError('UPSTREAM_DATA_ISSUE: textual field must be string, list<string>, or null')


def normalize(text, options):
    if text is None:
        return ''
    text = unicodedata.normalize(options['unicode'], text)
    if options.get('linebreaks', True):
        text = text.replace('\r\n', '\n').replace('\r', '\n')
    if options.get('remove_invisible', True):
        # Keep ZWJ/ZWNJ: these may carry linguistic meaning.
        text = text.replace('\ufeff', '').replace('\u200b', '').replace('\u2060', '')
    if options.get('whitespace', True):
        text = '\n'.join(re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.split('\n'))
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text
