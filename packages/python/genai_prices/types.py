from __future__ import annotations as _annotations

import dataclasses
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol, Union

import pydantic

__all__ = (
    'ProviderID',
    'PriceCalculation',
    'AbstractUsage',
    'Usage',
    'Provider',
    'ModelInfo',
    'ModelPrice',
    'TieredPrices',
    'Tier',
    'ConditionalPrice',
    'StartDateConstraint',
    'TimeOfDateConstraint',
    'ClauseStartsWith',
    'ClauseEndsWith',
    'ClauseContains',
    'ClauseRegex',
    'ClauseEquals',
    'ClauseOr',
    'ClauseAnd',
    'MatchLogic',
    'providers_schema',
)

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


@dataclass
class PriceCalculation:
    price: Decimal
    provider: Provider
    model: ModelInfo
    auto_update_timestamp: datetime | None

    def __repr__(self) -> str:
        return (
            f'PriceCalculation(price={self.price!r}, '
            f'provider=Provider(id={self.provider.id!r}, name={self.provider.name!r}, ...), '
            f'model=Model(id={self.model.id!r}, name={self.model.name!r}, ...), '
            f'auto_update_timestamp={self.auto_update_timestamp!r})'
        )


class AbstractUsage(Protocol):
    """Abstract definition of data about token usage for an LLM call"""

    @property
    def requests(self) -> int | None:
        """Number of requests made, defaults to 1 if omitted"""

    @property
    def input_tokens(self) -> int | None:
        """Number of text input/prompt token"""

    @property
    def cache_write_tokens(self) -> int | None:
        """Number of tokens written to the cache"""

    @property
    def cache_read_tokens(self) -> int | None:
        """Number of tokens read from the cache"""

    @property
    def output_tokens(self) -> int | None:
        """Number of text output/completion tokens"""

    @property
    def input_audio_tokens(self) -> int | None:
        """Number of audio input tokens"""

    @property
    def cache_audio_read_tokens(self) -> int | None:
        """Number of audio tokens read from the cache"""

    @property
    def output_audio_tokens(self) -> int | None:
        """Number of output audio tokens"""


@dataclass
class Usage:
    """Simple implementation of `AbstractUsage` as a dataclass."""

    requests: int | None = None

    input_tokens: int | None = None

    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None

    output_tokens: int | None = None

    input_audio_tokens: int | None = None
    cache_audio_read_tokens: int | None = None
    output_audio_tokens: int | None = None


@dataclass
class Provider:
    """Information about an LLM inference provider"""

    id: str
    """Unique identifier for the provider"""
    name: str
    """Link to pricing page for the provider"""
    api_pattern: str
    """Common name of the organization"""
    pricing_urls: list[str] | None = None
    """Pattern to identify provider via HTTP API URL."""
    description: str | None = None
    """Description of the provider"""
    price_comments: str | None = None
    """Comments about the pricing of this provider's models, especially challenges in representing the provider's pricing model."""
    model_match: MatchLogic | None = None
    """Logic to find a provider based on the model reference."""
    models: list[ModelInfo] = dataclasses.field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    """List of models provided by this organization"""

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
    name: str | None = None
    """Name of the model"""
    description: str | None = None
    """Description of the model"""
    context_window: int | None = None
    """Maximum number of input tokens allowed for this model"""
    price_comments: str | None = None
    """Comments about the pricing of the model, especially challenges in representing the provider's pricing model."""

    prices: ModelPrice | list[ConditionalPrice] = dataclasses.field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.

    If no conditional models match the conditions, the first one is used.
    """

    def is_match(self, model_ref: str) -> bool:
        return self.match.is_match(model_ref)

    def get_prices(self, request_timestamp: datetime) -> ModelPrice:
        if isinstance(self.prices, ModelPrice):
            return self.prices
        else:
            # reversed because the last price takes precedence
            for conditional_price in reversed(self.prices):
                if conditional_price.constraint is None or conditional_price.constraint.active(request_timestamp):
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

    def calc_price(self, usage: AbstractUsage) -> Decimal:
        """Calculate the price of usage in USD with this model price."""
        price = Decimal(0)
        if self.requests_kcount is not None:
            requests = 1 if usage.requests is None else usage.requests
            price += self.requests_kcount * requests / 1000

        price += calc_mtok_price(self.input_mtok, usage.input_tokens)
        price += calc_mtok_price(self.cache_write_mtok, usage.cache_write_tokens)
        price += calc_mtok_price(self.cache_read_mtok, usage.cache_read_tokens)
        price += calc_mtok_price(self.output_mtok, usage.output_tokens)
        price += calc_mtok_price(self.input_audio_mtok, usage.input_audio_tokens)
        price += calc_mtok_price(self.cache_audio_read_mtok, usage.cache_audio_read_tokens)
        price += calc_mtok_price(self.output_audio_mtok, usage.output_audio_tokens)
        return price


def calc_mtok_price(field_mtok: Decimal | TieredPrices | None, token_count: int | None) -> Decimal:
    """Calculate the price for a given number of tokens based on the price in USD per million tokens (mtok)."""
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
    return price / 1_000_000


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
    """Pricing together with constraints that define with those prices should be used.

    The last price that is active is used.
    """

    constraint: StartDateConstraint | TimeOfDateConstraint | None = None
    """Timestamp when this price starts, None means this price is always valid."""

    prices: ModelPrice = dataclasses.field(default_factory=ModelPrice)
    """Prices for this condition.

    This field is really required, the default factory is a hack until we can drop 3.9 and use kwonly on the dataclass.
    """


@dataclass
class StartDateConstraint:
    """Constraint that defines when this price starts, e.g. when a new price is introduced."""

    start_date: date
    """Date when this price starts"""

    def active(self, request_timestamp: datetime) -> bool:
        return request_timestamp.date() >= self.start_date


@dataclass
class TimeOfDateConstraint:
    """Constraint that defines a daily interval when a price applies, useful for off-peak pricing like deepseek."""

    start_time: time
    """Start time of the interval."""
    end_time: time
    """End time of the interval."""

    def active(self, request_timestamp: datetime) -> bool:
        return self.start_time <= request_timestamp.timetz() < self.end_time


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
    assert isinstance(v, dict), f'Expected dict, got {type(v)}'
    return next(iter(v))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


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
