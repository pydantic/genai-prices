from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_URL = 'https://cursor.com/docs/models-and-pricing.md'
MIN_MODEL_COUNT = 6


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    section_match = re.search(r'^## Cursor Models\s*$\n(.*?)(?=^## |\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
    if section_match is None:
        return []

    model_ids = {
        'Grok 4.6': 'grok-4.6',
        'Grok 4.6 (Fast)': 'grok-4.6-fast',
        'Grok 4.5': 'grok-4.5',
        'Grok 4.5 (Fast)': 'grok-4.5-fast',
        'Composer 2.5': 'composer-2.5',
        'Composer 2.5 (Fast)': 'composer-2.5-fast',
    }
    models: list[ModelInfo] = []
    seen_ids: set[str] = set()
    for line in section_match.group(1).splitlines():
        cells = line.split('|')
        if len(cells) < 8 or cells[2].strip() != 'Cursor':
            continue

        source_name = re.sub(r'\[([^]]+)]\([^)]*\)', r'\1', cells[1].strip())
        model_id = model_ids.get(source_name)
        if model_id is None:
            raise RuntimeError(f'Unknown Cursor model in pricing data: {source_name}')
        if model_id in seen_ids:
            raise RuntimeError(f'Duplicate Cursor model in pricing data: {model_id}')
        seen_ids.add(model_id)

        prices = [None if value.strip() == '-' else Decimal(value.strip().removeprefix('$')) for value in cells[3:7]]
        models.append(
            ModelInfo(
                id=model_id,
                name=source_name.replace(' (Fast)', ' Fast'),
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice(
                    input_mtok=prices[0],
                    cache_write_mtok=prices[1],
                    cache_read_mtok=prices[2],
                    output_mtok=prices[3],
                ),
                prices_checked=date.today(),
            )
        )
    return models


def update_cursor_provider(provider_yaml: ProviderYaml, models: list[ModelInfo]) -> tuple[int, int]:
    if len(models) < MIN_MODEL_COUNT:
        raise RuntimeError(f'Cursor pricing returned only {len(models)} models; expected at least {MIN_MODEL_COUNT}')

    models_added = 0
    models_updated = 0
    for model in models:
        matching_model = provider_yaml.provider.find_model(model.id)
        if matching_model is None:
            models_added += provider_yaml.add_model(model)
        else:
            provider_yaml.update_model(matching_model.id, model, set_prices=True, preserve_price_history=True)
            models_updated += 1
    provider_yaml.save()
    return models_added, models_updated


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_pricing_markdown(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/cursor.yml')
    models_added, models_updated = update_cursor_provider(provider_yaml, models)
    print(f'Cursor prices updated: {models_added} added, {models_updated} updated')


def get_cursor_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Cursor model prices."""
    main()


if __name__ == '__main__':
    main()
