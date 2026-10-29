from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://docs.mistral.ai/inference/pricing.md'
MIN_MODEL_COUNT = 8
ROW = re.compile(r'\| \[(?P<name>[^\]]+)\]\([^)]*\) \| `(?P<id>[\w.-]+)` \| (?P<price>.+) \|')
RATE = re.compile(
    r'(?P<label>Input|Cached input|Output) \$(?P<rate>\d+(?:\.\d+)?) /(?P<unit>M Tokens|1000 Pages|1000 Annotated Pages'
    r'|Min|M Chars)(?: \(sale price, regular \$\d+(?:\.\d+)?\))?'
)
PRICE_KEYS: dict[tuple[str, str], tuple[str, ...]] = {
    ('Input', 'M Tokens'): ('input_mtok',),
    ('Cached input', 'M Tokens'): ('cache_read_mtok',),
    ('Output', 'M Tokens'): ('output_mtok',),
    ('Input', '1000 Pages'): ('input_document_kpages',),
    ('Input', '1000 Annotated Pages'): ('input_annotated_document_kpages',),
    ('Input', 'Min'): ('audio_hours', 'input_audio_hours'),
}


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    models: list[ModelInfo] = []
    for line in markdown.splitlines():
        if not line.startswith('| [') or line.endswith('|  |  |'):
            continue
        if not (row := ROW.fullmatch(line)):
            raise RuntimeError(f'Unexpected Mistral pricing row: {line}')
        parts = row['price'].split('<br>')
        if 'Free' in parts:
            continue
        prices: dict[str, Decimal] = {}
        for part in parts:
            if not (rate := RATE.fullmatch(part)):
                raise RuntimeError(f'Unexpected Mistral price {part!r} in row: {line}')
            # Sale prices are what Mistral bills today; the regular rate returns as a dated change.
            value = Decimal(rate['rate']) * (60 if rate['unit'] == 'Min' else 1)
            if value == 0:
                continue
            keys = PRICE_KEYS.get((rate['label'], rate['unit']))
            if keys is None:
                # e.g. TTS output per million characters, which the unit registry has no key for.
                prices = {}
                break
            prices |= dict.fromkeys(keys, value.normalize())
        if not prices:
            continue
        models.append(
            ModelInfo(
                id=row['id'],
                name=row['name'],
                match=ClauseEquals(equals=row['id']),
                prices=ModelPrice(**prices),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/mistral.yml')
    added, updated = provider_yaml.upsert_models(models, source='Mistral', min_count=MIN_MODEL_COUNT)
    print(f'Mistral prices updated: {added} added, {updated} updated')


def get_mistral_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Mistral prices."""
    main()
