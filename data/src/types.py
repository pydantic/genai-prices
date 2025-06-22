from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Union

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    HttpUrl,
    PlainSerializer,
    Tag,
    TypeAdapter,
    WithJsonSchema,
    field_validator,
)


class _Model(BaseModel, extra='forbid', use_attribute_docstrings=True):
    """Custom abstract based model with config"""


class Provider(_Model):
    """Information about an LLM inference provider"""

    name: str
    """Common name of the organization"""
    id: str
    """Unique identifier for the provider"""
    pricing_url: HttpUrl | None = None
    """Link to pricing page for the provider"""
    api_pattern: str | None = None
    """Pattern to identify provider via HTTP API URL."""
    description: str | None = None
    """Description of the provider"""
    models: list[ModelInfo]
    """List of models provided by this organization"""

    @field_validator('models', mode='after')
    @classmethod
    def validate_id(cls, models: list[ModelInfo]) -> list[ModelInfo]:
        ids: set[str] = set()
        duplicates: list[str] = []
        for model in models:
            if model.id in ids:
                duplicates.append(model.id)
            ids.add(model.id)

        if duplicates:
            raise ValueError(f'Duplicate model ids: {duplicates}')
        return models


class ModelInfo(_Model):
    """Information about an LLM model"""

    id: str
    """Primary unique identifier for the model"""
    name: str | None = None
    """Name of the model"""
    description: str | None = None
    """Description of the model"""
    matches: LogicClause
    """Boolean logic for matching this model to any identifier which could be used to reference the model in API requests"""
    max_tokens: int | None = None
    """Maximum number of tokens allowed for this model"""
    prices: ModelPrice | list[ConditionalPrice]
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.
    """


DecimalFloat = Annotated[
    Decimal,
    WithJsonSchema({'type': 'number'}),
    PlainSerializer(float, return_type=float, when_used='json'),
]


class ModelPrice(_Model):
    """Set of prices for using a model"""

    input_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million text input/prompt token"""
    input_audio_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million audio input tokens"""

    cache_write_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million tokens written to the cache"""
    cache_read_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million tokens read from the cache"""

    output_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million output/completion tokens"""
    output_audio_mtok: DecimalFloat | TieredPrices | None = None
    """price in USD per million output audio tokens"""


class TieredPrices(_Model):
    """Pricing model when the amount paid varies by number of tokens"""

    base: DecimalFloat
    """Based price, e.g. price until the first tier."""
    tiers: list[Tier]


class Tier(_Model):
    """Price tier"""

    start: int
    """Start of the tier"""
    price: DecimalFloat
    """Price for this tier"""


class ConditionalPrice(_Model):
    """Pricing together with constraints that define with those prices should be used"""

    constraint: StartDateConstraint | None = None
    """Timestamp when this price starts, none means this price is always valid"""
    prices: ModelPrice


class StartDateConstraint(_Model):
    start: datetime
    """Timestamp when this price starts"""


class ClauseStartsWith(_Model):
    starts_with: str


class ClauseEndsWith(_Model):
    ends_with: str


class ClauseContains(_Model):
    contains: str


class ClauseRegex(_Model):
    regex: str
    any: list[str] | None = None


class ClauseEquals(_Model):
    equals: str


class ClauseOr(_Model):
    or_: list[LogicClause] = Field(alias='or')


class ClauseAnd(_Model):
    and_: list[LogicClause] = Field(alias='and')


def clause_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        # return the first key
        return next(iter(v))  # type: ignore
    else:
        return None


LogicClause = Annotated[
    Union[
        Annotated[ClauseStartsWith, Tag('starts_with')],
        Annotated[ClauseEndsWith, Tag('ends_with')],
        Annotated[ClauseContains, Tag('contains')],
        Annotated[ClauseRegex, Tag('regex')],
        Annotated[ClauseEquals, Tag('equals')],
        Annotated[ClauseOr, Tag('or')],
        Annotated[ClauseAnd, Tag('and')],
    ],
    Discriminator(clause_discriminator),
]
providers_schema = TypeAdapter(list[Provider])
