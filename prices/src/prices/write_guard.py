from __future__ import annotations

import os
from pathlib import Path

from .update import ProviderYaml

ALLOW_MODEL_COUNT_DROP_ENV = 'PRICES_ALLOW_MODEL_COUNT_DROP'


def check_model_count(path: Path, new_count: int, *, source: str) -> None:
    """Refuse to overwrite a tracked provider YAML with an implausibly small catalog.

    The importers rewrite files under `prices/providers/` from live third-party APIs, and those files feed
    `build.py` and both packages. A truncated or empty upstream response must fail loudly rather than
    land as a diff that a reviewer has to spot by eye. Set `PRICES_ALLOW_MODEL_COUNT_DROP=1` to override
    when a provider really did retire most of its catalog.
    """
    if not path.exists():
        return
    existing = len(ProviderYaml(path).provider.models)
    if new_count == 0:
        raise SystemExit(f'{source} returned no priced models but {path.name} has {existing}; refusing to write')
    if new_count * 2 < existing and os.environ.get(ALLOW_MODEL_COUNT_DROP_ENV) != '1':
        raise SystemExit(
            f'{source} returned {new_count} priced models but {path.name} has {existing}; refusing to write. '
            f'Set {ALLOW_MODEL_COUNT_DROP_ENV}=1 to override.'
        )
