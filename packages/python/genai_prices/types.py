from __future__ import annotations as _annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

import pydantic
from typing_extensions import TypedDict

ProviderID = Literal[
    'avian',
    'groq',
    'openai',
    'novita',
    'fireworks',
    'deepseek',
    'mistral',
    'x-ai',
    'google',
    'perplexity',
    'aws',
    'together',
    'anthropic',
    'azure',
    'cohere',
    'openrouter',
]


class Usage(TypedDict, total=False):
    """Information about token usage for an LLM call"""

    requests: int
    """Number of requests made, defaults to 1 if omitted"""

    input_tokens: int
    """Number of text input/prompt token"""

    cache_write_tokens: int
    """Number of tokens written to the cache"""
    cache_read_tokens: int
    """Number of tokens read from the cache"""

    output_tokens: int
    """Number of text output/completion tokens"""

    input_audio_tokens: int
    """Number of audio input tokens"""
    cache_audio_read_tokens: int
    """Number of audio tokens read from the cache"""
    output_audio_tokens: int
    """Number of output audio tokens"""


@dataclass
class Provider:
    """Information about an LLM inference provider"""

    name: str
    """Common name of the organization"""
    id: ProviderID
    """Unique identifier for the provider"""
    pricing_urls: Annotated[list[str] | None, pydantic.Field(None)]
    """Link to pricing page for the provider"""
    api_pattern: str
    """Pattern to identify provider via HTTP API URL."""
    description: Annotated[str | None, pydantic.Field(None)]
    """Description of the provider"""
    price_comments: Annotated[str | None, pydantic.Field(None)]
    """Comments about the pricing of this provider's models, especially challenges in representing the provider's pricing model."""
    models: list[ModelInfo]
    """List of models provided by this organization"""

    def is_match(self, provider_id: str | None, provider_api_url: str | None) -> bool:
        if provider_id is not None:
            return self.id == provider_id
        else:
            assert provider_api_url is not None, 'Either provider_id or provider_api_url must be set'
            return bool(re.match(self.api_pattern, provider_api_url))

    def find_model(self, model_ref: str) -> ModelInfo | None:
        for model in self.models:
            if model.is_match(model_ref):
                return model
        return None


@dataclass
class ModelInfo:
    """Information about an LLM model"""

    id: str
    """Primary unique identifier for the model"""
    match: MatchLogic
    """Boolean logic for matching this model to any identifier which could be used to reference the model in API requests"""
    prices: ModelPrice | list[ConditionalPrice]
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.

    If no conditional models match the conditions, the first one is used.
    """
    name: str | None = None
    """Name of the model"""
    description: str | None = None
    """Description of the model"""
    context_window: int | None = None
    """Maximum number of input tokens allowed for this model"""
    price_comments: str | None = None
    """Comments about the pricing of the model, especially challenges in representing the provider's pricing model."""
    price_discrepancies: dict[str, Any] | None = None
    """List of price discrepancies based on external sources."""
    prices_checked: date | None = None
    """Date indicating when the prices were last checked for discrepancies."""
    collapse: bool = True
    """Flag indicating whether this price should be collapsed into other prices."""

    def is_match(self, model_ref: str) -> bool:
        return self.match.is_match(model_ref)

    def get_prices(self, request_timestamp: datetime) -> ModelPrice:
        if isinstance(self.prices, ModelPrice):
            return self.prices
        else:
            for conditional_price in self.prices:
                if conditional_price.constraint.active(request_timestamp):
                    return conditional_price.prices
            return self.prices[0].prices


@dataclass
class ModelPrice:
    """Set of prices for using a model"""

    requests_kcount: Decimal | None = None
    """price in USD per thousand requests"""

    input_mtok: Decimal | TieredPrices | None = None
    """price in USD per million text input/prompt token"""

    cache_write_mtok: Decimal | TieredPrices | None = None
    """price in USD per million tokens written to the cache"""
    cache_read_mtok: Decimal | TieredPrices | None = None
    """price in USD per million tokens read from the cache"""

    output_mtok: Decimal | TieredPrices | None = None
    """price in USD per million output/completion tokens"""

    input_audio_mtok: Decimal | TieredPrices | None = None
    """price in USD per million audio input tokens"""
    cache_audio_read_mtok: Decimal | TieredPrices | None = None
    """price in USD per million audio tokens read from the cache"""
    output_audio_mtok: Decimal | TieredPrices | None = None
    """price in USD per million output audio tokens"""

    def calc_price(self, usage: Usage) -> Decimal:
        """Calculate the price of usage in USD."""
        price = Decimal(0)
        if self.requests_kcount is not None:
            price += self.requests_kcount * usage.get('requests_kcount', 1) / 1000

        price += _calc_price(self.input_mtok, usage.get('input_tokens'))
        price += _calc_price(self.cache_write_mtok, usage.get('cache_write_tokens'))
        price += _calc_price(self.cache_read_mtok, usage.get('cache_read_tokens'))
        price += _calc_price(self.output_mtok, usage.get('output_tokens'))
        price += _calc_price(self.input_audio_mtok, usage.get('input_audio_tokens'))
        price += _calc_price(self.cache_audio_read_mtok, usage.get('cache_audio_read_tokens'))
        price += _calc_price(self.output_audio_mtok, usage.get('output_audio_tokens'))
        return price

    def is_free(self) -> bool:
        """Whether all values are zero or unset"""
        for f in dataclasses.fields(self):
            if getattr(self, f.name):
                return False
        return True


def _calc_price(field_mtok: Decimal | TieredPrices | None, token_count: int | None) -> Decimal:
    if field_mtok is None or token_count is None:
        return Decimal(0)

    if isinstance(field_mtok, TieredPrices):
        price = Decimal(0)
        remaining = token_count
        for tier in reversed(field_mtok.tiers):
            if remaining > tier.start:
                price += tier.price * (remaining - tier.start)
                remaining = tier.start
        price += field_mtok.base * remaining
    else:
        price = field_mtok * token_count
    return price / 1000000


@dataclass
class TieredPrices:
    """Pricing model when the amount paid varies by number of tokens"""

    base: Decimal
    """Based price in USD per million tokens, e.g. price until the first tier."""
    tiers: list[Tier]
    """Extra price tiers."""


@dataclass
class Tier:
    """Price tier"""

    start: int
    """Start of the tier"""
    price: Decimal
    """Price for this tier"""


@dataclass
class ConditionalPrice:
    """Pricing together with constraints that define with those prices should be used"""

    constraint: StartDateConstraint
    """Timestamp when this price starts, none means this price is always valid"""
    prices: ModelPrice


@dataclass
class StartDateConstraint:
    start: pydantic.AwareDatetime
    """Timestamp when this price starts"""

    def active(self, request_timestamp: datetime) -> bool:
        return request_timestamp >= self.start


@dataclass
class ClauseStartsWith:
    starts_with: str

    def is_match(self, text: str) -> bool:
        return text.startswith(self.starts_with)


@dataclass
class ClauseEndsWith:
    ends_with: str

    def is_match(self, text: str) -> bool:
        return text.endswith(self.ends_with)


@dataclass
class ClauseContains:
    contains: str

    def is_match(self, text: str) -> bool:
        return self.contains in text


@dataclass
class ClauseRegex:
    regex: str

    def is_match(self, text: str) -> bool:
        return bool(re.search(self.regex, text))


@dataclass
class ClauseEquals:
    equals: str

    def is_match(self, text: str) -> bool:
        return text == self.equals


@dataclass
class ClauseOr:
    or_: Annotated[list[MatchLogic], pydantic.Field(validation_alias='or')]

    def is_match(self, text: str) -> bool:
        return any(clause.is_match(text) for clause in self.or_)


@dataclass
class ClauseAnd:
    and_: Annotated[list[MatchLogic], pydantic.Field(validation_alias='and')]

    def is_match(self, text: str) -> bool:
        return all(clause.is_match(text) for clause in self.and_)


def clause_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        # return the first key
        return next(iter(v))  # type: ignore
    elif dataclasses.is_dataclass(v):
        tag = next(iter(dataclasses.fields(v))).name
        if tag.endswith('_'):
            tag = tag[:-1]
        return tag
    else:
        return None


MatchLogic = Annotated[
    Union[
        Annotated[ClauseStartsWith, pydantic.Tag('starts_with')],
        Annotated[ClauseEndsWith, pydantic.Tag('ends_with')],
        Annotated[ClauseContains, pydantic.Tag('contains')],
        Annotated[ClauseRegex, pydantic.Tag('regex')],
        Annotated[ClauseEquals, pydantic.Tag('equals')],
        Annotated[ClauseOr, pydantic.Tag('or')],
        Annotated[ClauseAnd, pydantic.Tag('and')],
    ],
    pydantic.Discriminator(clause_discriminator),
]
providers_schema = pydantic.TypeAdapter(list[Provider], config=pydantic.ConfigDict(defer_build=True))
