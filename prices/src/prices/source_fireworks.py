from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import takewhile
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://docs.fireworks.ai/serverless/pricing.md'
MIN_MODEL_COUNT = 8
TABLE_HEADER = '| Model | Standard | Priority |'
MODEL_CELL = re.compile(
    r'\[(?P<name>[^]]+?)(?P<fast> Fast)?(?P<us> \(US\))?]\(https://app\.fireworks\.ai/models/fireworks/(?P<slug>[\w.-]+)\)'
)
STANDARD_CELL = re.compile(r'\\\$(\d+(?:\.\d+)?) / \\\$(\d+(?:\.\d+)?) / \\\$(\d+(?:\.\d+)?)')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    """Parse the Standard serverless rates; Fast and US-only rows are separate router models."""
    lines = markdown.splitlines()
    if TABLE_HEADER not in lines:
        raise RuntimeError('Fireworks pricing page has no text and vision models table')

    models: list[ModelInfo] = []
    for line in takewhile(lambda line: line.startswith('|'), lines[lines.index(TABLE_HEADER) + 2 :]):
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        model = MODEL_CELL.fullmatch(cells[0]) if len(cells) == 3 else None
        rates = STANDARD_CELL.fullmatch(cells[1]) if model else None
        if model is None or rates is None:
            raise RuntimeError(f'Unexpected Fireworks pricing row: {line}')
        suffix = ('-fast' if model['fast'] else '') + ('-us' if model['us'] else '')
        # https://docs.fireworks.ai/serverless/serverless-modes and /serverless/us-only-serverless name these routers.
        api_id = f'accounts/fireworks/{"routers" if suffix else "models"}/{model["slug"]}{suffix}'
        if any(existing.id == api_id for existing in models):
            raise RuntimeError(f'Duplicate Fireworks pricing row: {line}')
        input_mtok, cache_read_mtok, output_mtok = (Decimal(rate) for rate in rates.groups())
        models.append(
            ModelInfo(
                id=api_id,
                name=f'{model["name"]}{model["fast"] or ""}{" US" if model["us"] else ""}',
                match=ClauseEquals(equals=api_id),
                prices=ModelPrice(input_mtok=input_mtok, cache_read_mtok=cache_read_mtok, output_mtok=output_mtok),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/fireworks.yml')
    # Tracked models are found by API id; a new one takes the short id the YAML uses, e.g. `kimi-k3-fast`.
    models = [
        model
        if provider_yaml.provider.find_model(model.id)
        else model.model_copy(update={'id': model.id.rsplit('/', 1)[1]})
        for model in models
    ]
    added, updated = provider_yaml.upsert_models(models, source='Fireworks', min_count=MIN_MODEL_COUNT)
    print(f'Fireworks prices updated: {added} added, {updated} updated')


def get_fireworks_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Fireworks serverless prices."""
    main()
