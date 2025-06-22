from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel

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
        return self.canonical_slug.split('/', 1)[1]

    def model_name(self) -> str:
        return self.name.split(':', 1)[-1].strip()

    def model_info(self) -> ModelInfo:
        model_id = self.model_id()
        return ModelInfo(
            id=model_id,
            name=self.model_name(),
            description=self.description,
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

    for provider_id, or_models in or_providers.items():
        if provider_yaml := providers_yaml.providers.get(provider_id):
            pyd_provider = provider_yaml.provider
            models_added = 0
            models_updated = 0
            models_price_changed = 0
            for or_model in or_models:
                model_info = or_model.model_info()
                if matching_model := pyd_provider.find_model(model_info.id):
                    models_updated += 1
                    price_changed = provider_yaml.update_model(matching_model.id, model_info)
                    if price_changed:
                        models_price_changed += 1
                else:
                    models_added += provider_yaml.add_model(model_info)

            if models_added or models_updated:
                print(f'Provider {provider_id}:')
                if models_added:
                    print(f'  {models_added} models added')
                if models_updated:
                    print(f'  {models_updated} models updated')
                    print(f'  {models_price_changed} prices changed')
                print('')
                provider_yaml.save()
