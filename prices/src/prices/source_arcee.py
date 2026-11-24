from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml, UnreadableRowError, report_manual_update, skipping_unreadable_row
from prices.utils import package_dir

PRICING_URL = 'https://docs.arcee.ai/get-started/pricing.md'
MIN_MODEL_COUNT = 6


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    section_match = re.search(r'^#### Text Models\s*$\n(.*?)(?=^#{1,4} |\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
    if section_match is None:
        return []

    model_names = {
        'deepseek/deepseek-v4-flash-latest': 'DeepSeek V4 Flash',
        'deepseek/deepseek-v4-pro': 'DeepSeek V4 Pro',
        'moonshotai/kimi-k3': 'Kimi K3',
        'thinkingmachines/inkling-small': 'Inkling Small',
        'trinity-large-thinking': 'Trinity Large Thinking',
        'zai-org/glm-5.2': 'GLM 5.2',
    }
    models: list[ModelInfo] = []
    seen_ids: set[str] = set()
    duplicates: set[str] = set()
    for row in re.findall(r'<tr>(.*?)</tr>', section_match.group(1), flags=re.DOTALL):
        with skipping_unreadable_row('Arcee'):
            cells = [
                html.unescape(re.sub(r'<[^>]+>', '', cell)).strip() for cell in re.findall(r'<td[^>]*>(.*?)</td>', row)
            ]
            # The header row is built from `<th>` cells.
            if not cells:
                continue
            if len(cells) != 4:
                raise UnreadableRowError(f'Unexpected Arcee pricing row: {row}')

            model_id = cells[0]
            if model_id in seen_ids:
                duplicates.add(model_id)
                continue
            seen_ids.add(model_id)
            models.append(
                ModelInfo(
                    id=model_id,
                    name=model_names.get(model_id, model_id),
                    match=ClauseEquals(equals=model_id),
                    prices=ModelPrice(
                        input_mtok=_parse_price(cells[1]),
                        cache_read_mtok=_parse_price(cells[3]),
                        output_mtok=_parse_price(cells[2]),
                    ),
                    prices_checked=date.today(),
                )
            )
    for model_id in sorted(duplicates):
        report_manual_update(
            f'Arcee: kept {model_id} unchanged, the pricing page lists it more than once; update it by hand'
        )
    return [model for model in models if model.id not in duplicates]


def update_arcee_provider(provider_yaml: ProviderYaml, models: list[ModelInfo]) -> tuple[int, int]:
    if len(models) < MIN_MODEL_COUNT:
        raise RuntimeError(f'Arcee pricing returned only {len(models)} models; expected at least {MIN_MODEL_COUNT}')
    existing_count = len(provider_yaml.provider.models)
    if len(models) * 2 < existing_count:
        raise RuntimeError(f'Arcee pricing returned only {len(models)} models; tracked provider has {existing_count}')

    models_added = 0
    models_updated = 0
    for model in models:
        matching_model = provider_yaml.provider.find_model(model.id)
        if matching_model is None:
            models_added += provider_yaml.add_model(model)
        else:
            models_updated += provider_yaml.update_model(matching_model.id, model, set_prices=True)
    provider_yaml.save()
    return models_added, models_updated


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    models = parse_pricing_markdown(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/arcee.yml')
    models_added, models_updated = update_arcee_provider(provider_yaml, models)
    print(f'Arcee prices updated: {models_added} added, {models_updated} updated')


def get_arcee_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Arcee model prices."""
    main()


def _parse_price(value: str) -> Decimal | None:
    if value == '-':
        return None
    if re.fullmatch(r'\$[0-9]+(?:\.[0-9]+)?', value) is None:
        raise UnreadableRowError(f'Invalid Arcee price: {value}')
    return Decimal(value.removeprefix('$'))


if __name__ == '__main__':
    main()
