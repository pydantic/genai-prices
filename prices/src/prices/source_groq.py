from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import takewhile
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

MODELS_URL = 'https://console.groq.com/docs/models.md'
MIN_MODEL_COUNT = 5
TABLE_HEADER = [
    'MODEL ID',
    'SPEED (T/SEC)',
    'PRICE PER 1M TOKENS',
    'RATE LIMITS (DEVELOPER PLAN)',
    'CONTEXT WINDOW (TOKENS)',
    'MAX COMPLETION TOKENS',
    'MAX FILE SIZE',
]
MODEL_CELL = re.compile(r'\[!\[[^\]]*\]\([^)]*\)(?P<name>[^\]]+)\]\(/docs/model/(?P<id>[^)]+)\)(?:Enterprise)?(?P=id)')
PRICE = r'\$(\d+(?:\.\d+)?)'


def parse_models_markdown(markdown: str) -> list[ModelInfo]:
    models: list[ModelInfo] = []
    for section in ('Production', 'Preview'):
        table = re.search(rf'^## \[{section} Models\].*?^(\|.*)', markdown, flags=re.MULTILINE | re.DOTALL)
        lines = table[1].splitlines() if table else []
        if not lines or [cell.strip() for cell in lines[0].strip('|').split('|')] != TABLE_HEADER:
            raise RuntimeError(f'Groq models page has no {section} models table in the expected shape')
        for line in takewhile(lambda line: line.startswith('|'), lines[2:]):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            model = MODEL_CELL.fullmatch(cells[0]) if len(cells) == len(TABLE_HEADER) else None
            if model is None:
                raise RuntimeError(f'Unexpected Groq model row: {line}')
            price = cells[2]
            if price == 'ContactSales':
                continue
            # Cached rates are left to the YAML: model pages round them to 3 decimals ($0.037 for $0.0375).
            if tokens := re.fullmatch(f'{PRICE} input{PRICE} output', price):
                prices = ModelPrice(input_mtok=Decimal(tokens[1]), output_mtok=Decimal(tokens[2]))
            elif hourly := re.fullmatch(f'{PRICE} per hour', price):
                prices = ModelPrice.model_validate({'audio_hours': hourly[1], 'input_audio_hours': hourly[1]})
            elif characters := re.fullmatch(f'{PRICE} per 1M characters', price):
                prices = ModelPrice.model_validate({'input_mchars': characters[1]})
            else:
                raise RuntimeError(f'Unexpected Groq price {price!r} in row: {line}')
            context = cells[4].replace(',', '')
            models.append(
                ModelInfo(
                    id=model['id'],
                    name=model['name'].strip(),
                    match=ClauseEquals(equals=model['id']),
                    context_window=int(context) if context.isdigit() else None,
                    prices=prices,
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_models_markdown(get_markdown(MODELS_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/groq.yml')
    added, updated = provider_yaml.upsert_models(models, source='Groq', min_count=MIN_MODEL_COUNT)
    print(f'Groq prices updated: {added} added, {updated} updated')


def get_groq_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Groq prices."""
    main()
