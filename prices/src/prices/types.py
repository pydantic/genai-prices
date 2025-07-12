from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Union

from annotated_types import Gt, MaxLen
from pydantic import (
    AfterValidator,
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
from pydantic_core.core_schema import FieldValidationInfo

from .utils import check_unique


class _Model(BaseModel, extra='forbid', use_attribute_docstrings=True):
    """Custom abstract based model with config"""


IdField = Annotated[str, MaxLen(100), Field(pattern=r'^\S+$')]
NameField = Annotated[str, MaxLen(100)]
DescriptionField = Annotated[str, MaxLen(1000)]


class Provider(_Model):
    """Information about an LLM inference provider"""

    name: NameField
    """Common name of the organization"""
    id: IdField
    """Unique identifier for the provider"""
    pricing_urls: list[HttpUrl] | None = None
    """Link to pricing page for the provider"""
    api_pattern: str
    """Pattern to identify provider via HTTP API URL."""
    description: DescriptionField | None = None
    """Description of the provider"""
    price_comments: DescriptionField | None = None
    """Comments about the pricing of this provider's models, especially challenges in representing the provider's pricing model."""
    models: list[ModelInfo]
    """List of models provided by this organization"""

    @field_validator('models', mode='after')
    @classmethod
    def validate_id(cls, models: list[ModelInfo]) -> list[ModelInfo]:
        unique_ids: set[str] = set()
        duplicates: list[str] = []
        for model in models:
            if model.id in unique_ids:
                duplicates.append(model.id)
            unique_ids.add(model.id)

        if duplicates:
            raise ValueError(f'Duplicate model ids: {duplicates}')

        # check models are sorted by ID
        ids = [model.id for model in models]
        # try to find the first model id with the wrong position and point directly to that to fix
        sorted_ids = sorted(ids)
        for current_index, current_id in enumerate(ids):
            for expected_index, expected_id in enumerate(sorted_ids):
                if current_id == expected_id and current_index != expected_index:
                    msg = f'Models are not sorted by ID: move `{current_id}` {current_index} -> {expected_index}'
                    if expected_index > 0:
                        msg += f' after `{sorted_ids[expected_index - 1]}`'
                    raise ValueError(msg)

        return models

    def find_model(self, model_id: str) -> ModelInfo | None:
        for model in self.models:
            if model.is_match(model_id):
                return model
        return None

    def exclude_free(self):
        self.models[:] = [model for model in self.models if not model.is_free()]


class ModelInfo(_Model):
    """Information about an LLM model"""

    id: IdField
    """Primary unique identifier for the model"""
    name: NameField | None = None
    """Name of the model"""
    description: DescriptionField | None = None
    """Description of the model"""
    match: MatchLogic
    """Boolean logic for matching this model to any identifier which could be used to reference the model in API requests"""
    context_window: int | None = None
    """Maximum number of input tokens allowed for this model"""
    price_comments: DescriptionField | None = None
    """Comments about the pricing of the model, especially challenges in representing the provider's pricing model."""
    prices: ModelPrice | list[ConditionalPrice]
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.

    If no conditional models match the conditions, the first one is used.
    """
    price_discrepancies: dict[str, Any] | None = Field(default=None, exclude=True)
    """List of price discrepancies based on external sources."""
    prices_checked: date | None = Field(default=None, exclude=True)
    """Date indicating when the prices were last checked for discrepancies."""
    collapse: bool = Field(default=True, exclude=True)
    """Flag indicating whether this price should be collapsed into other prices."""

    def is_match(self, model_id: str) -> bool:
        return self.match.is_match(model_id)

    @field_validator('prices_checked', mode='after')
    @classmethod
    def validate_prices_checked(cls, prices_checked: date | None, info: FieldValidationInfo) -> date | None:
        if prices_checked is not None and info.data.get('price_discrepancies'):
            raise ValueError('`price_discrepancies` should be removed when `prices_checked` is set')
        return prices_checked

    @field_validator('prices', mode='after')
    @classmethod
    def prices_not_empty(cls, prices: ModelPrice | list[ConditionalPrice]) -> ModelPrice | list[ConditionalPrice]:
        if isinstance(prices, list) and len(prices) == 0:
            raise ValueError('model prices may not be empty')
        return prices

    def is_free(self) -> bool:
        if isinstance(self.prices, list):
            return all(price.prices.is_free() for price in self.prices)
        else:
            return self.prices.is_free()


def serialize_decimal(v: Decimal) -> float | int:
    return float(v) if v % 1 != 0 else int(v)


DollarPrice = Annotated[
    Decimal,
    Gt(0),
    WithJsonSchema({'type': 'number'}),
    PlainSerializer(serialize_decimal, return_type=Union[float, int], when_used='json'),
]


class ModelPrice(_Model):
    """Set of prices for using a model"""

    requests_kcount: DollarPrice | None = None
    """price in USD per thousand requests"""

    input_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million text input/prompt token"""

    cache_write_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million tokens written to the cache"""
    cache_read_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million tokens read from the cache"""

    output_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million output/completion tokens"""

    input_audio_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million audio input tokens"""
    cache_audio_read_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million audio tokens read from the cache"""
    output_audio_mtok: DollarPrice | TieredPrices | None = None
    """price in USD per million output audio tokens"""

    def is_free(self) -> bool:
        """Whether all values are zero or unset"""
        for field_name in self.__pydantic_fields__:
            if getattr(self, field_name):
                return False
        return True


class TieredPrices(_Model):
    """Pricing model when the amount paid varies by number of tokens"""

    base: DollarPrice
    """Based price in USD per million tokens, e.g. price until the first tier."""
    tiers: list[Tier]
    """Extra price tiers."""

    @field_validator('tiers', mode='after')
    @classmethod
    def tiers_assending(cls, data: list[Tier]) -> list[Tier]:
        if data != sorted(data, key=lambda t: t.start):
            raise ValueError('Tiers must be in ascending order by start')
        return data


class Tier(_Model):
    """Price tier"""

    start: int
    """Start of the tier"""
    price: DollarPrice
    """Price for this tier"""


class ConditionalPrice(_Model):
    """Pricing together with constraints that define with those prices should be used"""

    constraint: StartDateConstraint
    """Timestamp when this price starts, none means this price is always valid"""
    prices: ModelPrice


class StartDateConstraint(_Model):
    start: datetime
    """Timestamp when this price starts"""


class ClauseStartsWith(_Model):
    starts_with: str

    def is_match(self, text: str) -> bool:
        return text.startswith(self.starts_with)


class ClauseEndsWith(_Model):
    ends_with: str

    def is_match(self, text: str) -> bool:
        return text.endswith(self.ends_with)


class ClauseContains(_Model):
    contains: str

    def is_match(self, text: str) -> bool:
        return self.contains in text


class ClauseRegex(_Model):
    regex: re.Pattern[str]

    def is_match(self, text: str) -> bool:
        return bool(self.regex.search(text))


class ClauseEquals(_Model):
    equals: str

    def is_match(self, text: str) -> bool:
        return text == self.equals


class ClauseOr(_Model, populate_by_name=True):
    or_: Annotated[list[MatchLogic], AfterValidator(check_unique)] = Field(alias='or')

    def is_match(self, text: str) -> bool:
        return any(clause.is_match(text) for clause in self.or_)


class ClauseAnd(_Model, populate_by_name=True):
    and_: Annotated[list[MatchLogic], AfterValidator(check_unique)] = Field(alias='and')

    def is_match(self, text: str) -> bool:
        return all(clause.is_match(text) for clause in self.and_)


def clause_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        # return the first key
        return next(iter(v))  # type: ignore
    elif isinstance(v, BaseModel):
        tag = next(iter(v.__pydantic_fields__))
        if tag.endswith('_'):
            tag = tag[:-1]
        return tag
    else:
        return None


MatchLogic = Annotated[
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
match_logic_schema: TypeAdapter[MatchLogic] = TypeAdapter(MatchLogic)

providers_schema = TypeAdapter(list[Provider])
