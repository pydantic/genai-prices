from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

import httpx2
from pydantic import BaseModel

from . import source_prices
from .prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from .update import get_providers_yaml
from .utils import distinct_mtok, mtok

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

    def model_id(self, *, strip_provider: bool = True) -> str:
        if not strip_provider:
            return self.id
        return self.id.split('/', 1)[1]

    def model_name(self) -> str:
        return self.name.split(':', 1)[-1].strip()

    def model_info(
        self, inc_description: bool = True, *, strip_provider: bool = True, include_context_window: bool = False
    ) -> ModelInfo:
        model_id = self.model_id(strip_provider=strip_provider)
        match_clauses = [ClauseEquals(equals=model_id)]
        if not strip_provider and self.canonical_slug != self.id:
            match_clauses.append(ClauseEquals(equals=self.canonical_slug))
        match = (
            ClauseOr(or_=match_clauses)  # pyright: ignore[reportCallIssue]
            if len(match_clauses) > 1
            else match_clauses[0]
        )

        if inc_description:
            description = self.description.split('\n\n', 1)[0]
            # remove markdown links
            description = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', description)
        else:
            description = None

        return ModelInfo(
            id=model_id,
            name=self.model_name(),
            description=description,
            match=match,
            prices=self.pricing.model_price(),
            # Only for the `openrouter` provider's own records: OpenRouter's `context_length` describes
            # their offering, not what the model's native provider enforces.
            context_window=self.context_length if include_context_window else None,
        )


class OpenRouterPricing(BaseModel, extra='allow'):
    # extra='allow': OpenRouter adds pricing fields without notice; forbid used to abort the whole pull.
    # report_unknown_pricing_fields prints what was ignored.

    audio: Decimal | None = None
    prompt: Decimal | None = None
    completion: Decimal | None = None
    request: Decimal | None = None
    image: Decimal | None = None
    web_search: Decimal | None = None
    internal_reasoning: Decimal | None = None
    input_cache_write: Decimal | None = None
    input_cache_read: Decimal | None = None

    def model_price(self) -> ModelPrice:
        reasoning_price = distinct_mtok(self.internal_reasoning, self.completion)
        return ModelPrice(
            input_mtok=mtok(self.prompt),
            cache_write_mtok=mtok(self.input_cache_write),
            cache_read_mtok=mtok(self.input_cache_read),
            output_mtok=mtok(self.completion),
            **({'output_reasoning_mtok': reasoning_price} if reasoning_price is not None else {}),
        )

    def has_negative_price(self) -> bool:
        # OpenRouter reports a price of -1 for models whose cost is adaptive/dynamic rather than a
        # fixed per-token rate, so there is no single number we can store. Two kinds of model do this:
        #   - auto-routers / meta-models that pick an underlying model per request, e.g.
        #     `openrouter/auto`, `openrouter/fusion`, `openrouter/pareto-code`, `openrouter/bodybuilder`.
        #   - `~`-prefixed "latest" aliases that redirect to whatever the newest model in a family is,
        #     e.g. `~anthropic/claude-fable-latest` ("always redirects to the latest model in the Claude
        #     Fable family"). This one is what first tripped this and crashed the whole pull on
        #     ModelPrice validation.
        # In both cases the resolved model (and price) varies per request, so -1 is a sentinel.
        #
        # ModelPrice requires positive prices, so we skip these models entirely for now.
        # TODO: represent adaptive/dynamic pricing instead of dropping these models.
        return any(
            v is not None and v < 0
            for v in (
                self.audio,
                self.prompt,
                self.completion,
                self.request,
                self.image,
                self.web_search,
                self.internal_reasoning,
                self.input_cache_write,
                self.input_cache_read,
            )
        )


class OpenRouterResponse(BaseModel):
    data: list[OpenRouterModel]


def report_unknown_pricing_fields(models: list[OpenRouterModel]) -> dict[str, int]:
    """Count pricing fields OpenRouter sent that `OpenRouterPricing` doesn't model, and print them.

    These are dropped from the import. A field appearing here means OpenRouter has added a pricing
    dimension we may now be able to represent — see `prices/units.yml` for the ones v2 can express.
    """
    counts: dict[str, int] = {}
    for model in models:
        for field in model.pricing.model_extra or {}:
            counts[field] = counts.get(field, 0) + 1

    if counts:
        print('OpenRouter sent pricing fields we ignore:')
        for field, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'  {field}: {count} models')
        print('')
    return counts


def main(mode: Literal['metadata', 'prices']):  # noqa: C901
    """Update provider prices and metadata based on OpenRouter API."""
    r = httpx2.get('https://openrouter.ai/api/v1/models')
    r.raise_for_status()

    or_response = OpenRouterResponse.model_validate_json(r.content)
    report_unknown_pricing_fields(or_response.data)

    providers_yaml = get_providers_yaml()

    or_providers: dict[str, list[OpenRouterModel]] = {}

    # add all models to the openrouter provider
    or_provider_yaml = providers_yaml['openrouter']
    or_models_added = 0
    or_models_updated = 0
    for or_model in or_response.data:
        provider_id = or_model.provider_id()
        if provider_id == 'openrouter':
            # this model is invalid
            continue
        if or_model.pricing.has_negative_price():
            # variable/dynamic pricing we can't represent as a fixed price, skip it
            continue
        if models := or_providers.get(provider_id):
            models.append(or_model)
        else:
            or_providers[provider_id] = [or_model]

        # add all models to the openrouter provider
        model_info = or_model.model_info(inc_description=False, strip_provider=False, include_context_window=True)
        assert isinstance(model_info.prices, ModelPrice)
        try:
            or_provider_yaml.update_model(model_info.id, model_info)
        except LookupError:
            or_models_added += or_provider_yaml.add_model(model_info)
        else:
            or_models_updated += 1

    if mode == 'metadata' and (or_models_added or or_models_updated):
        print('Provider openrouter:')
        if or_models_added:
            print(f'  {or_models_added} models added')
        if or_models_updated:
            print(f'  {or_models_updated} models updated')
        print('')
        or_provider_yaml.save()

    prices: source_prices.SourcePricesType = {}

    for provider_id, or_models in or_providers.items():
        try:
            provider_yaml = providers_yaml[provider_id]
        except KeyError:
            # ignore other providers, we could add them later
            continue

        pyd_provider = provider_yaml.provider
        models_added = 0
        models_updated = 0
        provider_prices: source_prices.ProvidePrices = {}

        def add_prices(id: str, prices: ModelPrice):
            if existing := provider_prices.get(id):
                if existing == prices:
                    return
                elif existing.is_free():
                    provider_prices[id] = prices
                elif prices.is_free():
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
        if mode == 'metadata' and (models_added or models_updated):
            print(f'Provider {provider_id}:')
            if models_added:
                print(f'  {models_added} models added')
            if models_updated:
                print(f'  {models_updated} models updated')
            print('')
            provider_yaml.save()

    if mode == 'prices':
        source_prices.write_source_prices('openrouter', prices)


def update_from_openrouter():  # pragma: no cover - thin CLI alias for main
    """Update metadata and add new models based on OpenRouter API."""
    main('metadata')


def get_openrouter_prices():  # pragma: no cover - thin CLI alias for main
    """Get prices from OpenRouter API."""
    main('prices')
