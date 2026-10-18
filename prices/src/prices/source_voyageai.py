from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://docs.voyageai.com/docs/pricing.md'
MIN_MODEL_COUNT = 10
SECTIONS = ('Text Embeddings', 'Older models')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    models: list[ModelInfo] = []
    for title in SECTIONS:
        section = re.search(rf'^#+ {title}\s*$\n(.*?)(?=^#|\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
        rows = [_cells(line) for line in section.group(1).splitlines() if line.startswith('|')] if section else []
        if len(rows) < 3:
            raise RuntimeError(f'Voyage pricing page has no "{title}" table')
        price_column = rows[0].index('Price per million tokens')
        for row in rows[2:]:
            model_ids = re.findall(r'`([^`]+)`', row[0])
            price = re.fullmatch(r'\$([0-9]+(?:\.[0-9]+)?)', row[price_column])
            if not model_ids or price is None:
                raise RuntimeError(f'Unexpected Voyage pricing row: {row}')
            for model_id in model_ids:
                if not model_id.startswith('voyage-') or 'multimodal' in model_id:
                    continue
                if any(model.id == model_id for model in models):
                    raise RuntimeError(f'Duplicate Voyage model in pricing data: {model_id}')
                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_id.replace('-', ' ').title(),
                        match=ClauseEquals(equals=model_id),
                        prices=ModelPrice(input_mtok=Decimal(price.group(1))),
                        prices_checked=date.today(),
                    )
                )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/voyageai.yml')
    added, updated = provider_yaml.upsert_models(models, source='Voyage AI', min_count=MIN_MODEL_COUNT)
    print(f'Voyage AI prices updated: {added} added, {updated} updated')


def get_voyageai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Voyage AI prices."""
    main()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip('|').split('|')]
