"""Historical run artifacts for tests: resolved, never moved, copied or recreated.

Historical runs moved from ``outputs/runs/<name>`` into provider buckets
(``outputs/runs/local|api|anteriores/<name>``); some were compacted by the
retention policy. Tests resolve locators with the existing ``run_paths.relocate``
and read nothing at import time. A missing artifact skips the test with an
explicit reason instead of breaking collection or silently dropping cases.

Runs that only survive as compacted evidence are replayed only on explicit
opt-in (``GRAPHRAG_HISTORICAL_RUNS=1``), like the other real-data integrations.
"""
import os
from pathlib import Path

import pytest

from run_paths import relocate

ROOT = Path(__file__).resolve().parents[1]
OPT_IN = 'GRAPHRAG_HISTORICAL_RUNS'


def locate(locator):
    """Real location of a historical locator (flat or bucketed); None when absent."""
    path = relocate(ROOT / locator)
    return path if path.exists() else None


def require(locator, *, compacted=False):
    """Inside a test: the resolved artifact, or an explicit skip with its reason."""
    if compacted and os.environ.get(OPT_IN) != '1':
        pytest.skip(f'{OPT_IN}=1 habilita la reproduccion de {locator}: run compactado por la politica de retencion')
    path = locate(locator)
    if path is None:
        pytest.skip(f'Artefacto historico ausente: {locator} (ni en su ruta original ni en outputs/runs/<bucket>)')
    return path


class Lazy:
    """Read-on-first-use stand-in for a module-level historical constant."""

    def __init__(self, loader):
        self._loader = loader
        self._value = None

    def _get(self):
        if self._value is None:
            self._value = self._loader()
        return self._value

    def __getitem__(self, key):
        return self._get()[key]

    def __iter__(self):
        return iter(self._get())

    def __len__(self):
        return len(self._get())

    def __contains__(self, key):
        return key in self._get()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._get(), name)


def params(locator, build, *, label='historical'):
    """Parametrize values computed at collection; never an empty (silently dropped) set."""
    path = locate(locator)
    values = build(path) if path is not None else []
    if values:
        return values
    reason = (f'Artefacto historico ausente: {locator}' if path is None
              else f'{locator} no contiene casos para {label}')
    return [pytest.param(None, marks=pytest.mark.skip(reason=reason), id='missing-' + label)]
