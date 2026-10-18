from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

DOCS_URL = 'https://docs.doubleword.ai'
MODELS_URL = f'{DOCS_URL}/inference-api/models.md'
MIN_MODEL_COUNT = 8
HEADER = '| Model | Realtime | Async | Batch (24h) |'
PRICE = r'\\?\$([0-9]+(?:\.[0-9]+)?)'


def parse_models(catalog: str, get_page: Callable[[str], str]) -> list[ModelInfo]:
    """Parse Realtime prices from the catalog; `get_page` fetches a model page, which holds the API model ID."""
    table = re.search(rf'^### Active Models\s*$\n\s*{re.escape(HEADER)}\n\|[-| ]+\|\n((?:\|.*\n?)*)', catalog, re.M)
    if table is None:
        raise RuntimeError('Doubleword models page has no Active Models table in the expected shape')
    models: list[ModelInfo] = []
    for line in table.group(1).splitlines():
        row = re.fullmatch(r'\| \[([^\]]+)\]\((/inference-api/models/[^)]+)\) \| (.+?) \|.*\|', line)
        if row is None:
            raise RuntimeError(f'Unexpected Doubleword models row: {line}')
        name, path, realtime = row.groups()
        if realtime == '—':
            continue
        rates = re.fullmatch(rf'{PRICE} / {PRICE} / {PRICE}', realtime)
        if rates is None:
            raise RuntimeError(f'Unexpected Doubleword Realtime price: {realtime}')
        page = get_page(f'{DOCS_URL}{path}.md')
        model_id = re.search(r'/playground\?model=([^&)]+)', page)
        if model_id is None:
            raise RuntimeError(f'Doubleword model page {path} has no playground model ID')
        context_window = re.search(r'Max Total Tokens: (\d+)', page)
        input_mtok, cache_read_mtok, output_mtok = (Decimal(rate) or None for rate in rates.groups())
        models.append(
            ModelInfo(
                id=unquote(model_id.group(1)),
                name=name.strip(),
                match=ClauseEquals(equals=unquote(model_id.group(1))),
                context_window=int(context_window.group(1)) if context_window else None,
                prices=ModelPrice(
                    input_mtok=input_mtok,
                    cache_read_mtok=cache_read_mtok if cache_read_mtok != input_mtok else None,
                    output_mtok=output_mtok,
                ),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_models(get_markdown(MODELS_URL), get_markdown)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/doubleword.yml')
    added, updated = provider_yaml.upsert_models(models, source='Doubleword', min_count=MIN_MODEL_COUNT)
    print(f'Doubleword prices updated: {added} added, {updated} updated')


def get_doubleword_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Doubleword Realtime prices."""
    main()
