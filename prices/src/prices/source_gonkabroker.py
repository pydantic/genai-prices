from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
from pydantic import BaseModel

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import distinct_mtok, mtok, package_dir
from prices.write_guard import check_model_count

CATALOG_URL = 'https://proxy.gonkabroker.com/v1/models'


class GonkaBrokerPricing(BaseModel):
    # USD per token, as decimal strings. The catalog's per-1M `input` and `output` fields are floats, so they are not read.
    prompt: Decimal
    completion: Decimal
    input_cache_read: Decimal | None = None


class GonkaBrokerModel(BaseModel):
    id: str
    name: str
    context_length: int
    output_modalities: list[str]
    pricing: GonkaBrokerPricing


class GonkaBrokerCatalog(BaseModel):
    data: list[GonkaBrokerModel]


def parse_catalog(payload: bytes) -> list[ModelInfo]:
    catalog = GonkaBrokerCatalog.model_validate_json(payload)
    models: list[ModelInfo] = []
    seen_ids: set[str] = set()
    for model in catalog.data:
        if model.id in seen_ids:
            raise RuntimeError(f'Duplicate Gonka Broker model in catalog: {model.id}')
        seen_ids.add(model.id)

        pricing = model.pricing
        if 'embeddings' in model.output_modalities:
            # Embeddings are billed on input tokens only, although the catalog also lists a completion rate.
            prices = ModelPrice(input_mtok=mtok(pricing.prompt))
        else:
            prices = ModelPrice(
                input_mtok=mtok(pricing.prompt),
                cache_read_mtok=distinct_mtok(pricing.input_cache_read, pricing.prompt),
                output_mtok=mtok(pricing.completion),
            )
        models.append(
            ModelInfo(
                id=model.id,
                name=model.name,
                match=ClauseEquals(equals=model.id),
                context_window=model.context_length,
                prices=prices,
                prices_checked=date.today(),
            )
        )
    return models


def update_gonkabroker_provider(provider_yaml: ProviderYaml, models: list[ModelInfo]) -> tuple[int, int]:
    check_model_count(provider_yaml.path, len(models), source='Gonka Broker catalog')
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
    response = httpx2.get(CATALOG_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_catalog(response.content)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/gonkabroker.yml')
    models_added, models_updated = update_gonkabroker_provider(provider_yaml, models)
    print(f'Gonka Broker prices updated: {models_added} added, {models_updated} updated')


def get_gonkabroker_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Gonka Broker model prices."""
    main()


if __name__ == '__main__':
    main()
