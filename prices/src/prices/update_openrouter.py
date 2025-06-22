from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel

from . import source_prices
from .types import ClauseEquals, ModelInfo, ModelPrice
from .update import ProvidersYaml

map_providers = {
    'mistralai': 'mistral',
    'microsoft': 'azure',
    'amazon': 'aws',
}


class OpenRouterModel(BaseModel):
    id: str
    canonical_slug: str
    name: str
    created: datetime
    description: str
    context_length: int
    pricing: OpenRouterPricing
    supported_parameters: list[str]

    def provider_id(self) -> str:
        id = self.canonical_slug.split('/', 1)[0]
        return map_providers.get(id, id)

    def provider_name(self) -> str:
        return self.name.split(':', 1)[0].strip()

    def model_id(self) -> str:
        return self.id.split('/', 1)[1]

    def model_name(self) -> str:
        return self.name.split(':', 1)[-1].strip()

    def model_info(self) -> ModelInfo:
        model_id = self.model_id()

        description = self.description.split('\n\n', 1)[0]
        # remove markdown links
        description = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', description)
        return ModelInfo(
            id=model_id,
            name=self.model_name(),
            description=description,
            match=ClauseEquals(equals=model_id),
            prices=self.pricing.mmodel_price(),
        )


class OpenRouterPricing(BaseModel, extra='forbid'):
    prompt: Decimal | None = None
    completion: Decimal | None = None
    request: Decimal | None = None
    image: Decimal | None = None
    web_search: Decimal | None = None
    internal_reasoning: Decimal | None = None
    input_cache_write: Decimal | None = None
    input_cache_read: Decimal | None = None

    def mmodel_price(self) -> ModelPrice:
        return ModelPrice(
            input_mtok=mtok(self.prompt),
            cache_write_mtok=mtok(self.input_cache_write),
            cache_read_mtok=mtok(self.input_cache_read),
            output_mtok=mtok(self.completion),
        )


def mtok(v: Decimal | None) -> Decimal | None:
    if v is None:
        return None
    else:
        return v * 1_000_000


class OpenRouterResponse(BaseModel):
    data: list[OpenRouterModel]


def update_from_openrouter():
    r = httpx.get('https://openrouter.ai/api/v1/models')
    r.raise_for_status()

    or_response = OpenRouterResponse.model_validate_json(r.content)

    providers_yaml = ProvidersYaml()

    or_providers: dict[str, list[OpenRouterModel]] = {}
    for model in or_response.data:
        if models := or_providers.get(model.provider_id()):
            models.append(model)
        else:
            or_providers[model.provider_id()] = [model]

    prices: source_prices.SourcePricesType = {}

    for provider_id, or_models in or_providers.items():
        if provider_id == 'openrouter':
            continue
        if provider_yaml := providers_yaml.providers.get(provider_id):
            pyd_provider = provider_yaml.provider
            models_added = 0
            models_updated = 0
            provider_prices: source_prices.ProvidePrices = {}

            def add_prices(id: str, prices: ModelPrice):
                if existing := provider_prices.get(id):
                    if existing == prices:
                        return
                    elif existing.all_unset():
                        provider_prices[id] = prices
                    elif prices.all_unset():
                        return
                    else:
                        return
                        # debug('prices differ', id, existing, prices)
                else:
                    provider_prices[id] = prices

            for or_model in or_models:
                model_info = or_model.model_info()
                assert isinstance(model_info.prices, ModelPrice)
                if matching_model := pyd_provider.find_model(model_info.id):
                    add_prices(matching_model.id, model_info.prices)
                    models_updated += 1
                    provider_yaml.update_model(matching_model.id, model_info)
                else:
                    add_prices(model_info.id, model_info.prices)
                    models_added += provider_yaml.add_model(model_info)

            prices[pyd_provider.id] = provider_prices
            if models_added or models_updated:
                print(f'Provider {provider_id}:')
                if models_added:
                    print(f'  {models_added} models added')
                if models_updated:
                    print(f'  {models_updated} models updated')
                print('')
                provider_yaml.save()

    source_prices.write_source_prices('openrouter', prices)
