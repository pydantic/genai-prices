from __future__ import annotations

import difflib
import gzip
from datetime import datetime
from operator import attrgetter
from pathlib import Path
from typing import Annotated, Any

import devtools
import pydantic_core
from pydantic import BaseModel, Discriminator, Field, HttpUrl, Tag, TypeAdapter, ValidationError
from yaml import safe_load


class Model(BaseModel, extra='forbid', use_attribute_docstrings=True):
    """Custom abstract based model with config"""


class Provider(Model):
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


class ModelInfo(Model):
    """Information about an LLM model"""

    name: str | None = None
    """Name of the model"""
    description: str | None = None
    """Description of the model"""
    id: str
    """Primary unique identifier for the model"""
    matches: LogicClause
    """Boolean logic for matching this model to any identifier which could be used to reference the model in API requests"""
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
    output_audio_mtok: float | TieredPrices | None = None
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
providers_schema = TypeAdapter(list[Provider])


def file_size(file: Path) -> str:
    size = file.stat().st_size
    if size < 1024:
        return f'{size} bytes'
    elif size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    else:
        return f'{size / (1024 * 1024):.1f} MB'


def main():
    this_dir = Path(__file__).parent
    root_dir = this_dir.parent
    # write the schema JSON file used by the yaml language server
    schema_json_path = this_dir / 'schema.json'
    json_schema = Provider.model_json_schema()
    if schema_json_path.exists():
        current_json_schema = pydantic_core.from_json(schema_json_path.read_bytes())
    else:
        current_json_schema = None

    if current_json_schema != json_schema:
        schema_json_path.write_bytes(pydantic_core.to_json(json_schema, indent=2) + b'\n')
        print('Prices schema written to', schema_json_path.relative_to(root_dir))
    else:
        print('Prices schema unchanged')

    providers: list[Provider] = []

    providers_dir = this_dir / 'providers'
    for file in providers_dir.iterdir():
        if file.suffix not in ('.yml', '.yaml'):
            raise ValueError(f'All {providers_dir} files must be YAML files')
        data = safe_load(file.read_bytes())
        try:
            provider = Provider.model_validate_json(pydantic_core.to_json(data), strict=True)
        except ValidationError as e:
            raise ValueError(f'Error validating provider {file.name}:\n{e}') from e
        else:
            providers.append(provider)

    providers.sort(key=attrgetter('id'))
    prices_json_path = this_dir / 'prices.json'
    if prices_json_path.exists():
        try:
            current_prices = providers_schema.validate_json(prices_json_path.read_bytes())
        except ValidationError as e:
            print(f'warning, error loading current prices:\n{e}')
            current_prices = None
    else:
        current_prices = None

    if current_prices != providers:
        if current_prices is not None:
            diff = difflib.unified_diff(
                str(devtools.pformat(current_prices)).splitlines(keepends=True),
                str(devtools.pformat(providers)).splitlines(keepends=True),
                fromfile='current_prices',
                tofile='new_prices',
            )
            print(f'Prices have the following changes:')
            print('=' * 80)
            print(''.join(diff))
            print('=' * 80)

        json_data = providers_schema.dump_json(providers, by_alias=True)
        prices_json_path.write_bytes(json_data + b'\n')
        gz_path = prices_json_path.with_suffix('.json.gz')
        with gzip.open(gz_path, 'wb') as f:
            f.write(json_data)

        print(
            f'Prices data written to {prices_json_path.relative_to(root_dir)} ({file_size(prices_json_path)}) and {gz_path.relative_to(root_dir)} ({file_size(gz_path)})'
        )
    else:
        print('Prices data unchanged')


if __name__ == '__main__':
    main()
