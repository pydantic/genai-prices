from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx2
from pydantic import BaseModel

from . import source_prices
from .prices_types import (
    ClauseEquals,
    ClauseOr,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
    TimeOfDateConstraint,
)
from .update import ProviderYaml, get_providers_yaml
from .utils import distinct_mtok, mtok, package_dir
from .variants import rate_pairs, shape

MODELS_URL = 'https://openrouter.ai/api/v1/models'
ENDPOINTS_URL = 'https://openrouter.ai/api/v1/models/{model_id}/endpoints'
MIN_MODEL_COUNT = 100
# Endpoints and official records round the same rate differently, and a host can nudge its rate by a cent.
PRICE_TOLERANCE = Decimal('0.05')
TIERED_PRICE_FIELDS = {
    'input_mtok': 'prompt',
    'cache_write_mtok': 'input_cache_write',
    'cache_read_mtok': 'input_cache_read',
    'output_mtok': 'completion',
}
# What `OpenRouterPricing.model_price` reports, so the only keys an official price may set on an `openrouter` record.
OPENROUTER_PRICE_KEYS = {*TIERED_PRICE_FIELDS, 'output_reasoning_mtok'}

map_providers = {
    'mistralai': 'mistral',
    'microsoft': 'azure',
    'amazon': 'aws',
}

# OpenRouter author -> the genai-prices provider with the official rates for its models, and the tag prefixes of that
# provider's own OpenRouter endpoints.
ORIGINAL_PROVIDERS: dict[str, tuple[str, tuple[str, ...]]] = {
    'amazon': ('aws', ('amazon-bedrock',)),
    'anthropic': ('anthropic', ('anthropic',)),
    'arcee-ai': ('arcee', ('arcee-ai',)),
    'cohere': ('cohere', ('cohere',)),
    'deepseek': ('deepseek', ('deepseek',)),
    'google': ('google', ('google-ai-studio', 'google-vertex')),
    'meta': ('meta', ('meta',)),
    'meta-llama': ('meta', ('meta',)),
    'minimax': ('minimax', ('minimax',)),
    'mistralai': ('mistral', ('mistral',)),
    'moonshotai': ('moonshotai', ('moonshotai',)),
    'openai': ('openai', ('openai',)),
    'perplexity': ('perplexity', ('perplexity',)),
    'x-ai': ('x-ai', ('xai',)),
    'z-ai': ('zai', ('z-ai',)),
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
    discount: Decimal = Decimal(0)
    """Share taken off an endpoint's rates, which already include it; a temporary promotion."""

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


class OpenRouterEndpoint(BaseModel):
    tag: str
    """The host's slug, then any variant: `z-ai/fp8`, `google-vertex/us`, `anthropic/fast`."""
    service_tier: str | None = None
    pricing: OpenRouterPricing

    def host(self) -> str:
        return self.tag.split('/', 1)[0]


class OpenRouterEndpoints(BaseModel):
    endpoints: list[OpenRouterEndpoint]


class OpenRouterEndpointsResponse(BaseModel):
    data: OpenRouterEndpoints


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
    r = httpx2.get(MODELS_URL)
    r.raise_for_status()

    or_response = OpenRouterResponse.model_validate_json(r.content)
    if not or_response.data:
        raise SystemExit('OpenRouter returned no models; nothing written')
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


def parse_provider_models(models: list[OpenRouterModel]) -> list[ModelInfo]:
    """Build the `openrouter` provider's records, with prompt-length overrides as tiers."""
    by_id = {model.id: model for model in models}
    model_infos: list[ModelInfo] = []
    for model in models:
        if not importable(model):
            continue
        if (base := by_id.get(model.id.removesuffix(':batch'))) and model.id.endswith(':batch'):
            model = with_batch_cache_writes(model, base)
        overrides: list[dict[str, Any]] = (model.pricing.model_extra or {}).get('overrides') or []
        if any(key.startswith('utc_') for override in overrides for key in override):
            # Time-of-day rates can't be expressed as one dated price; leave these models curated by hand.
            continue
        for override in overrides:
            if 'min_prompt_tokens' not in override or 'internal_reasoning' in override:
                raise RuntimeError(f'Unexpected OpenRouter price override for {model.id}: {override}')
        model_info = model.model_info(inc_description=False, strip_provider=False, include_context_window=True)
        if ':' in model.id:
            # A `:batch` or `:free` route shares its base model's canonical slug, which must match only the base.
            model_info = model_info.model_copy(update={'match': ClauseEquals(equals=model.id)})
        prices = model_info.prices
        assert isinstance(prices, ModelPrice)
        tiered: dict[str, TieredPrices] = {}
        for key, field in TIERED_PRICE_FIELDS.items():
            tiers = [
                Tier(start=override['min_prompt_tokens'], price=Decimal(override[field]) * 1_000_000)
                for override in overrides
                if field in override
            ]
            if not tiers:
                continue
            base = dict(prices).get(key)
            if base is None:
                raise RuntimeError(f'OpenRouter overrides {field} for {model.id} without a base rate')
            tiered[key] = TieredPrices(base=base, tiers=sorted(tiers, key=lambda tier: tier.start))
        model_infos.append(
            model_info.model_copy(update={'prices': prices.model_copy(update=tiered), 'prices_checked': date.today()})
        )
    return model_infos


def with_batch_cache_writes(batch: OpenRouterModel, base: OpenRouterModel) -> OpenRouterModel:
    """Fill the cache-write rates OpenRouter omits on a batch route, at the route's input discount."""
    if batch.pricing.input_cache_write is not None or base.pricing.input_cache_write is None:
        return batch
    if not batch.pricing.prompt or not base.pricing.prompt:
        return batch
    ratio = batch.pricing.prompt / base.pricing.prompt
    batch_overrides: list[dict[str, Any]] = (batch.pricing.model_extra or {}).get('overrides') or []
    base_overrides: list[dict[str, Any]] = (base.pricing.model_extra or {}).get('overrides') or []
    starts = [override.get('min_prompt_tokens') for override in batch_overrides]
    if starts != [override.get('min_prompt_tokens') for override in base_overrides]:
        return batch
    overrides = [
        {**override, 'input_cache_write': Decimal(base_override['input_cache_write']) * ratio}
        if 'input_cache_write' in base_override
        else override
        for override, base_override in zip(batch_overrides, base_overrides)
    ]
    pricing = batch.pricing.model_copy(
        update={'input_cache_write': base.pricing.input_cache_write * ratio, 'overrides': overrides}
    )
    return batch.model_copy(update={'pricing': pricing})


def importable(model: OpenRouterModel) -> bool:
    """Whether a listed model routes to one model at fixed rates, so the `openrouter` provider can record it."""
    # A `~...-latest` alias redirects to another model, and its reported rates flip within minutes.
    return not (model.provider_id() == 'openrouter' or model.pricing.has_negative_price() or model.id.startswith('~'))


def update_openrouter_provider(provider_path: Path | None = None) -> None:
    """Update only the `openrouter` provider's prices, keeping a dated entry for every rate change.

    The model list reports a model's cheapest endpoint, whose rate flips whenever a discounted host comes or goes. A
    model is priced at its original provider's official rate where its own endpoint confirms it, and otherwise at the
    rate most of its endpoints charge.
    """
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/openrouter.yml')
    providers = {provider_id: yaml.provider for provider_id, yaml in get_providers_yaml().items()}
    with httpx2.Client(timeout=30.0) as client:
        response = client.get(MODELS_URL)
        response.raise_for_status()
        listed = [model for model in OpenRouterResponse.model_validate_json(response.content).data if importable(model)]
        endpoints = {model.id: fetch_endpoints(client, model.id) for model in listed}
    models = parse_provider_models(
        [with_endpoint_pricing(model, endpoints[model.id], provider_yaml) for model in listed]
    )
    models = [with_official_price(model, endpoints[model.id], providers) for model in models]
    models = [settled(model, provider_yaml) for model in models]
    added, updated = provider_yaml.upsert_models(models, source='OpenRouter', min_count=MIN_MODEL_COUNT)
    print(f'OpenRouter prices updated: {added} added, {updated} updated')


def fetch_endpoints(client: httpx2.Client, model_id: str) -> list[OpenRouterEndpoint]:
    response = client.get(ENDPOINTS_URL.format(model_id=model_id))
    response.raise_for_status()
    return OpenRouterEndpointsResponse.model_validate_json(response.content).data.endpoints


def with_endpoint_pricing(
    model: OpenRouterModel, endpoints: list[OpenRouterEndpoint], provider_yaml: ProviderYaml
) -> OpenRouterModel:
    """Price a model at the input and output rates most hosts of its standard, full-price endpoints charge.

    A host counts once per rate, however many regions or quantizations it lists at it. Flex and priority tiers and
    discounted endpoints only count when the model has no other endpoint. Among equally common rates the recorded one
    wins, then the full set of rates most hosts charge, then the cheapest, which OpenRouter routes to most.
    """
    standard = [endpoint for endpoint in endpoints if endpoint.service_tier is None] or endpoints
    full_price = [endpoint for endpoint in standard if not endpoint.pricing.discount] or standard
    if not full_price:
        return model
    rates: dict[str, OpenRouterPricing] = {}
    hosts: dict[str, set[str]] = {}
    headline_hosts: dict[tuple[Decimal | None, Decimal | None], set[str]] = {}
    for endpoint in full_price:
        rate = endpoint.pricing.model_dump_json(exclude={'discount'})
        rates[rate] = endpoint.pricing
        hosts.setdefault(rate, set()).add(endpoint.host())
        headline_hosts.setdefault((endpoint.pricing.prompt, endpoint.pricing.completion), set()).add(endpoint.host())
    record = provider_yaml.provider.find_model(model.id)

    def rank(rate: str) -> tuple[int, bool, int, Decimal, Decimal]:
        pricing = rates[rate]
        recorded = record is not None and within_tolerance(latest_price(record), pricing.model_price())
        headline = len(headline_hosts[pricing.prompt, pricing.completion])
        return (
            -headline,
            not recorded,
            -len(hosts[rate]),
            pricing.prompt or Decimal(0),
            pricing.completion or Decimal(0),
        )

    return model.model_copy(update={'pricing': rates[min(rates, key=rank)]})


def with_official_price(
    model: ModelInfo, endpoints: list[OpenRouterEndpoint], providers: dict[str, Provider]
) -> ModelInfo:
    """Take the original provider's current token rates, when its own OpenRouter endpoint charges them.

    The original provider's match logic can resolve an OpenRouter id to another model, e.g. `deepseek-r1-0528`
    to the `deepseek-reasoner` alias that now serves a newer model, and its record can lag a price change. So the
    record counts only when one of the provider's own standard endpoints charges its input and output rates.
    """
    assert isinstance(model.prices, ModelPrice)
    author, slug = model.id.split('/', 1)
    if ':' in slug or (original := ORIGINAL_PROVIDERS.get(author)) is None:
        return model
    provider_id, tags = original
    record = providers[provider_id].find_model(slug)
    if record is None or (official := current_price(record)) is None or official.is_free():
        return model
    own = [endpoint.pricing for endpoint in endpoints if endpoint.host() in tags and endpoint.service_tier is None]
    if not any(charges(pricing, official) for pricing in own):
        return model
    rates = {key: rate for key, rate in official if key in OPENROUTER_PRICE_KEYS and rate is not None}
    return model.model_copy(update={'prices': ModelPrice(**(dict(model.prices) | rates))})


def current_price(record: ModelInfo) -> ModelPrice | None:
    """A record's price today, or `None` when it depends on the time of day."""
    if isinstance(record.prices, ModelPrice):
        return record.prices
    if any(isinstance(price.constraint, TimeOfDateConstraint) for price in record.prices):
        return None
    return next(
        price.prices
        for price in reversed(record.prices)
        if not isinstance(price.constraint, StartDateConstraint) or price.constraint.start_date <= date.today()
    )


def charges(pricing: OpenRouterPricing, price: ModelPrice) -> bool:
    """Whether an endpoint's input and output rates, as charged or before its discount, are a price's base rates.

    A record can hold either: some providers' promotions are dated official prices, others only OpenRouter discounts.
    """
    rates: list[tuple[Decimal, Decimal]] = []
    for reported, official in ((pricing.prompt, price.input_mtok), (pricing.completion, price.output_mtok)):
        rate = mtok(reported)
        base = official.base if isinstance(official, TieredPrices) else official
        if rate is None or base is None:
            return False
        rates.append((rate, base))
    shares = {Decimal(1), 1 - pricing.discount} - {Decimal(0)}
    return any(all(abs(rate / share - base) <= PRICE_TOLERANCE * base for rate, base in rates) for share in shares)


def latest_price(record: ModelInfo) -> ModelPrice:
    return record.prices[-1].prices if isinstance(record.prices, list) else record.prices


def settled(model: ModelInfo, provider_yaml: ProviderYaml) -> ModelInfo:
    """Keep a tracked record's context window, and its rates when the reported ones only drifted."""
    if (record := provider_yaml.provider.find_model(model.id)) is None:
        return model
    # `context_length` varies by endpoint, so an existing record's window, or its deliberate absence, is curated.
    update: dict[str, Any] = {'context_window': None}
    current = latest_price(record)
    assert isinstance(model.prices, ModelPrice)
    if within_tolerance(current, model.prices):
        update['prices'] = current
    return model.model_copy(update=update)


def within_tolerance(current: ModelPrice, reported: ModelPrice) -> bool:
    """Whether every reported rate is within `PRICE_TOLERANCE` of the current one, tiered the same way."""
    curated = dict(current)
    for key, value in reported:
        if value is None:
            continue
        if (previous := curated.get(key)) is None or shape(value) != shape(previous):
            return False
        for rate, base in rate_pairs(value, previous):
            assert base is not None
            if abs(rate - base) > PRICE_TOLERANCE * base:
                return False
    return True


def get_openrouter_provider_prices():  # pragma: no cover - thin CLI alias for update_openrouter_provider
    """Update the openrouter provider's prices from the OpenRouter API."""
    update_openrouter_provider()


def update_from_openrouter():  # pragma: no cover - thin CLI alias for main
    """Update metadata and add new models based on OpenRouter API."""
    main('metadata')


def get_openrouter_prices():  # pragma: no cover - thin CLI alias for main
    """Get prices from OpenRouter API."""
    main('prices')
