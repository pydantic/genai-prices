from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

CATALOG_URL = 'https://docs.baseten.co/inference/model-apis/overview.md'
PRICING_URL = 'https://www.baseten.co/pricing/'
MIN_MODEL_COUNT = 15
PRICING_ID_ALIASES = {
    'deepseek-v4-pro': 'deepseek-ai/DeepSeek-V4-Pro',
    'deepseek-v4-pro-0813': 'deepseek-ai/DeepSeek-V4-Pro-0813',
    'glm-4-7': 'zai-org/GLM-4.7',
    'inkling': 'thinkingmachines/inkling',
    'inkling-small': 'thinkingmachines/inkling-small',
}


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    context_window: int


def parse_catalog(markdown: str) -> list[CatalogModel]:
    table = re.search(r'export const SupportedModelsTable.*?const rows = \[(.*?)\];', markdown, re.DOTALL)
    if table is None:
        raise RuntimeError('Baseten model catalog table was not found')
    rows = re.findall(r'model: "([^"]+)",\s*slug: "([^"]+)",\s*context: ([0-9]+),\s*maxOutput: [0-9]+', table.group(1))
    models = [
        CatalogModel(id=model_id, name=name, context_window=int(context) * 1000) for name, model_id, context in rows
    ]
    if len({model.id for model in models}) != len(models):
        raise RuntimeError('Baseten model catalog contains duplicate model IDs')
    return models


def parse_pricing_page(page: str) -> dict[str, ModelPrice]:
    prices: dict[str, ModelPrice] = {}
    for record in page.split(r'\"__typename\":\"LibraryModelRecord\"')[1:]:
        model_match = re.search(
            r'\\\"tryModelApiLink\\\":\\\"https://app\.baseten\.co/model-apis/([^\"\\]+)\\\"', record
        )
        input_match = re.search(r'\\\"perfCost\\\":([0-9]+(?:\.[0-9]+)?)', record)
        output_match = re.search(r'\\\"perfCostOutput\\\":([0-9]+(?:\.[0-9]+)?)', record)
        if model_match is None or input_match is None or output_match is None:
            continue
        pricing_id = unquote(model_match.group(1))
        model_id = PRICING_ID_ALIASES.get(pricing_id, pricing_id)
        if model_id in prices:
            raise RuntimeError(f'Duplicate Baseten pricing model: {model_id}')
        cache_match = re.search(r'\\\"perfCostCacheInput\\\":([0-9]+(?:\.[0-9]+)?)', record)
        prices[model_id] = ModelPrice(
            input_mtok=Decimal(input_match.group(1)),
            cache_read_mtok=Decimal(cache_match.group(1)) if cache_match else None,
            output_mtok=Decimal(output_match.group(1)),
        )
    return prices


def parse_models(catalog_markdown: str, pricing_page: str) -> list[ModelInfo]:
    catalog = parse_catalog(catalog_markdown)
    prices = parse_pricing_page(pricing_page)
    catalog_ids = {model.id for model in catalog}
    if catalog_ids != prices.keys():
        missing_prices = sorted(catalog_ids - prices.keys())
        missing_catalog = sorted(prices.keys() - catalog_ids)
        raise RuntimeError(
            f'Baseten catalog/pricing mismatch: missing prices={missing_prices}, missing catalog={missing_catalog}'
        )
    return [
        ModelInfo(
            id=model.id,
            name=model.name,
            match=ClauseEquals(equals=model.id),
            context_window=model.context_window,
            price_comments=(
                'The pricing table does not publish a separate cached-input rate for this model.'
                if prices[model.id].cache_read_mtok is None
                else None
            ),
            prices=prices[model.id],
            prices_checked=date.today(),
        )
        for model in catalog
    ]


def update_baseten_provider(provider_yaml: ProviderYaml, models: list[ModelInfo]) -> tuple[int, int]:
    if len(models) < MIN_MODEL_COUNT:
        raise RuntimeError(f'Baseten sources returned only {len(models)} models; expected at least {MIN_MODEL_COUNT}')
    existing_count = len(provider_yaml.provider.models)
    if len(models) * 2 < existing_count:
        raise RuntimeError(f'Baseten sources returned only {len(models)} models; tracked provider has {existing_count}')
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
    catalog_response = httpx2.get(CATALOG_URL, timeout=30.0)
    catalog_response.raise_for_status()
    pricing_response = httpx2.get(PRICING_URL, timeout=30.0)
    pricing_response.raise_for_status()
    models = parse_models(catalog_response.text, pricing_response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/baseten.yml')
    models_added, models_updated = update_baseten_provider(provider_yaml, models)
    print(f'Baseten prices updated: {models_added} added, {models_updated} updated')


def get_baseten_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Baseten model prices."""
    main()


if __name__ == '__main__':
    main()
