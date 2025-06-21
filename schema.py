from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Discriminator, Field, HttpUrl, Tag


class Model(BaseModel, extra='forbid', use_attribute_docstrings=True):
    """Custom abstract based model with config"""


class Provider(Model):
    """Information about an LLM inference provider"""

    name: str
    """Common name of the organization"""
    info_url: HttpUrl
    """URL to get more information about the provider"""
    description: str | None = None
    """Description of the provider"""
    models: list[ModelInfo]
    """List of models provided by this organization"""


class ModelInfo(Model):
    """Information about an LLM model"""

    name: str
    """Name of the model"""
    description: str | None = None
    """Description of the model"""
    matches: LogicClause
    """Logic clause to match this model to an identifier"""
    max_tokens: int | None = None
    """Maximum number of tokens allowed for this model"""
    prices: ModelPrice | list[ConditionalPrice]
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.
    """


class ModelPrice(Model):
    """Set of prices for using a model"""

    input_mtok: float | TieredPrices | None = None
    """price in USD per million text input/prompt token"""
    input_audio_mtok: float | TieredPrices | None = None
    """price in USD per million audio input tokens"""

    cache_write_mtok: float | TieredPrices | None = None
    """price in USD per million tokens written to the cache"""
    cache_read_mtok: float | TieredPrices | None = None
    """price in USD per million tokens read from the cache"""

    output_mtok: float | TieredPrices | None = None
    """price in USD per million output/completion tokens"""
    response_audio_mtok: float | TieredPrices | None = None
    """price in USD per million output audio tokens"""


class TieredPrices(Model):
    """Pricing model when the amount paid varies by number of tokens"""

    base: float
    """Based price, e.g. price until the first tier."""
    tiers: list[Tier]


class Tier(Model):
    """Price tier"""

    start: int
    """Start of the tier"""
    price: float
    """Price for this tier"""


class ConditionalPrice(Model):
    """Pricing together with constraints that define with those prices should be used"""

    constraint: StartDateConstraint | None = None
    """Timestamp when this price starts, none means this price is always valid"""
    prices: ModelPrice


class StartDateConstraint(Model):
    start: datetime
    """Timestamp when this price starts"""


class ClauseStartsWith(Model):
    starts_with: str


class ClauseEndsWith(Model):
    ends_with: str


class ClauseContains(Model):
    contains: str


class ClauseRegex(Model):
    regex: str
    any: list[str] | None = None


class ClauseEquals(Model):
    equals: str


class ClauseOr(Model):
    or_: list[LogicClause] = Field(alias='or')


class ClauseAnd(Model):
    and_: list[LogicClause] = Field(alias='and')


def clause_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        # return the first key
        return next(iter(v))  # type: ignore
    else:
        return None


LogicClause = Annotated[
    Annotated[ClauseStartsWith, Tag('starts_with')]
    | Annotated[ClauseEndsWith, Tag('ends_with')]
    | Annotated[ClauseContains, Tag('contains')]
    | Annotated[ClauseRegex, Tag('regex')]
    | Annotated[ClauseEquals, Tag('equals')]
    | Annotated[ClauseOr, Tag('or')]
    | Annotated[ClauseAnd, Tag('and')],
    Discriminator(clause_discriminator),
]


def write_schema():
    this_dir = Path(__file__).parent
    (this_dir / 'schema.json').write_text(json.dumps(Provider.model_json_schema(), indent=2))


if __name__ == '__main__':
    write_schema()
