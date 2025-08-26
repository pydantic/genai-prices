from __future__ import annotations as _annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol, TypeVar, Union, cast, overload

import pydantic
from typing_extensions import TypedDict, TypeGuard

__all__ = (
    'ProviderID',
    'PriceCalculation',
    'AbstractUsage',
    'Usage',
    'Provider',
    'UsageExtractorMapping',
    'UsageExtractor',
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
    'ArrayMatch',
    'providers_schema',
)


# Define MatchLogic after __all__ to avoid forward reference issues
def clause_discriminator(v: Any) -> str | None:
    assert isinstance(v, dict), f'Expected dict, got {type(v)}'
    return next(iter(v))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


MatchLogic = Annotated[
    Union[
        Annotated['ClauseStartsWith', pydantic.Tag('starts_with')],
        Annotated['ClauseEndsWith', pydantic.Tag('ends_with')],
        Annotated['ClauseContains', pydantic.Tag('contains')],
        Annotated['ClauseRegex', pydantic.Tag('regex')],
        Annotated['ClauseEquals', pydantic.Tag('equals')],
        Annotated['ClauseOr', pydantic.Tag('or')],
        Annotated['ClauseAnd', pydantic.Tag('and')],
    ],
    pydantic.Discriminator(clause_discriminator),
]

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
class ArrayMatch:
    type: Literal['array-match']
    field: str
    match: MatchLogic

    def extract(self, items: Sequence[Any]) -> Mapping[str, Any] | None:
        for item in items:
            if _is_mapping(item) and (item_field := item.get(self.field)):
                if self.match.is_match(item_field):
                    return item


ExtractPath = Union[str, Sequence[Union[str, ArrayMatch]]]


@dataclass(repr=False)
class PriceCalculation:
    input_price: Decimal
    output_price: Decimal
    total_price: Decimal
    model: ModelInfo = dataclasses.field(repr=False)
    provider: Provider = dataclasses.field(repr=False)
    model_price: ModelPrice
    auto_update_timestamp: datetime | None

    def __repr__(self) -> str:
        return (
            'PriceCalculation('
            f'input_price={self.input_price!r}, '
            f'output_price={self.output_price!r}, '
            f'total_price={self.total_price!r}, '
            f'model={self.model.summary()}, '
            f'provider={self.provider.summary()}, '
            f'model_price=ModelPrice({self.model_price}), '
            f'auto_update_timestamp={self.auto_update_timestamp!r})'
        )


@dataclass(repr=False)
class ExtractedUsage:
    usage: Usage
    model: ModelInfo = dataclasses.field(repr=False)
    provider: Provider = dataclasses.field(repr=False)
    auto_update_timestamp: datetime | None

    def calc_price(self, genai_request_timestamp: datetime | None = None) -> PriceCalculation:
        return self.model.calc_price(
            self.usage,
            self.provider,
            genai_request_timestamp=genai_request_timestamp,
            auto_update_timestamp=self.auto_update_timestamp,
        )

    def __repr__(self) -> str:
        return (
            'ExtractedUsage('
            f'usage={self.usage!r}, '
            f'model={self.model.summary()}, '
            f'provider={self.provider.summary()}, '
            f'auto_update_timestamp={self.auto_update_timestamp!r})'
        )


class AbstractUsage(Protocol):
    """Abstract definition of data about token usage for a single LLM call."""

    @property
    def input_tokens(self) -> int | None:
        """Total number of text input/prompt tokens.

        Note this should INCLUDE both uncached and cached tokens.
        """

    @property
    def cache_write_tokens(self) -> int | None:
        """Number of tokens written to the cache."""

    @property
    def cache_read_tokens(self) -> int | None:
        """Number of tokens read from the cache.

        For many models this is described as just "cached tokens".
        """

    @property
    def output_tokens(self) -> int | None:
        """Number of text output/completion tokens."""

    @property
    def input_audio_tokens(self) -> int | None:
        """Number of audio input tokens."""

    @property
    def cache_audio_read_tokens(self) -> int | None:
        """Number of audio tokens read from the cache."""

    @property
    def output_audio_tokens(self) -> int | None:
        """Number of output audio tokens."""


@dataclass
class Usage:
    """Simple implementation of `AbstractUsage` as a dataclass."""

    input_tokens: int | None = None
    """Number of text input/prompt tokens."""

    cache_write_tokens: int | None = None
    """Number of tokens written to the cache."""
    cache_read_tokens: int | None = None
    """Number of tokens read from the cache."""

    output_tokens: int | None = None
    """Number of text output/completion tokens."""

    input_audio_tokens: int | None = None
    """Number of audio input tokens."""
    cache_audio_read_tokens: int | None = None
    """Number of audio tokens read from the cache."""
    output_audio_tokens: int | None = None
    """Number of output audio tokens."""


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
    provider_match: MatchLogic | None = None
    """Logic to find a provider based on the provider identifier."""
    extractors: list[UsageExtractor] | None = None
    """Logic to extract usage information from the provider's API responses."""
    models: list[ModelInfo] = dataclasses.field(default_factory=list)
    """List of models supported by this provider"""

    def find_model(self, model_ref: str) -> ModelInfo | None:
        model_ref = model_ref.lower()
        for model in self.models:
            if model.is_match(model_ref):
                return model
        return None

    def extract_usage(self, response_data: Any, *, api_flavor: str | None = None) -> tuple[str, Usage]:
        """Extract model name and usage information from a response.

        Args:
            response_data: The response data from the provider's API.
            api_flavor: The flavor of API used for this request.

        Raises:
            ValueError: If the response data is invalid or the API flavor is not found.

        Returns:
            tuple[str, Usage]: The extracted model name and usage information.
        """
        if self.extractors is None:
            raise ValueError('No extraction logic defined for this provider')

        if api_flavor is None:
            if len(self.extractors) == 1:
                extractor = self.extractors[0]
            else:
                raise ValueError('No api_flavor specified and multiple extractors available')
        else:
            try:
                extractor = next(e for e in self.extractors if e.api_flavor == api_flavor)
            except StopIteration as e:
                fs = ', '.join(e.api_flavor for e in self.extractors)
                raise ValueError(f'Unknown api_flavor {api_flavor!r}, allowed values: {fs}') from e

        return extractor.extract(response_data)

    def summary(self) -> str:
        return f'Provider(id={self.id!r}, name={self.name!r}, ...)'


UsageField = Literal[
    'input_tokens',
    'cache_write_tokens',
    'cache_read_tokens',
    'output_tokens',
    'input_audio_tokens',
    'cache_audio_read_tokens',
    'output_audio_tokens',
]


@dataclass
class UsageExtractorMapping:
    """Mappings from used to build usage."""

    path: ExtractPath
    """Path to the value to extract"""
    dest: UsageField
    """Destination field to store the extracted value.

    If multiple mappings point to the same destination, the values are summed.
    """
    required: bool = True
    """Whether the value is required to be present in the response"""


@dataclass
class UsageExtractor:
    """Logic for extracting usage information from a response."""

    root: ExtractPath
    """Path to the root of the usage information in the response, generally `usage`."""
    mappings: list[UsageExtractorMapping]
    """Mappings from used to build usage."""
    api_flavor: str = 'default'
    """Name of the API flavor, only needed when a provider has multiple flavors, e.g. OpenAI has `chat` and `responses`."""
    model_path: ExtractPath = 'model'
    """Path to the model name in the response."""

    def extract(self, response_data: Any) -> tuple[str, Usage]:
        """Extract model name and usage information from a response.

        Args:
            response_data: The response data to extract usage information from, generally the decoded JSON response.

        Raises:
            ValueError: If no usage information is found at the root.

        Returns:
            tuple[str, Usage]: The extracted model name and usage information.
        """
        model_name = _extract_path(self.model_path, response_data, str, True, [])

        root = self.root
        if isinstance(root, str):
            root = [root]

        usage_obj = cast(dict[str, Any], _extract_path(root, response_data, Mapping, True, []))

        usage = Usage()
        values_set = False
        for mapping in self.mappings:
            value = _extract_path(mapping.path, usage_obj, int, mapping.required, root)
            if value is not None:
                current_value = getattr(usage, mapping.dest) or 0
                setattr(usage, mapping.dest, current_value + value)
                values_set = True
        if not values_set:
            raise ValueError(f'No usage information found at {self.root}')
        return model_name, usage


E = TypeVar('E')


@overload
def _extract_path(
    path: ExtractPath, data: Any, extract_type: type[E], required: Literal[True], data_path: Sequence[str | ArrayMatch]
) -> E: ...


@overload
def _extract_path(
    path: ExtractPath,
    data: Any,
    extract_type: type[E],
    required: Literal[False],
    data_path: Sequence[str | ArrayMatch],
) -> E | None: ...


def _extract_path(
    path: ExtractPath, data: Any, extract_type: type[E], required: bool, data_path: Sequence[str | ArrayMatch]
) -> E | None:
    if isinstance(path, str):
        path = [path]

    *steps, last = path
    last = cast(str, last)

    error_path: list[str | ArrayMatch] = []
    for step in steps:
        error_path.append(step)
        if isinstance(step, ArrayMatch):
            if not _is_sequence(data):
                raise ValueError(
                    f'Expected `{_dot_path(data_path, error_path)}` value to be a sequence, got {_type_name(data)}'
                )
            if extracted_data := step.extract(data):
                data = extracted_data
            elif required:
                raise ValueError(f'Unable to find item at `{_dot_path(data_path, error_path)}`')
            else:
                return None
        else:
            if not _is_mapping(data):
                raise ValueError(
                    f'Expected `{_dot_path(data_path, error_path)}` value to be a dict, got {_type_name(data)}'
                )
            try:
                data = data[step]
            except KeyError as e:
                if required:
                    raise ValueError(f'Missing value at `{_dot_path(data_path, error_path)}`') from e
                else:
                    return None

    if not _is_mapping(data):
        raise ValueError(f'Expected `{_dot_path(data_path, error_path)}` value to be a dict, got {_type_name(data)}')

    try:
        value = data[last]
    except KeyError as e:
        if required:
            error_path.append(last)
            raise ValueError(f'Missing value at `{_dot_path(data_path, error_path)}`') from e
        else:
            return None
    else:
        if isinstance(value, extract_type):
            return value
        else:
            error_path.append(last)
            raise ValueError(
                f'Expected `{_dot_path(data_path, error_path)}` value to be a {extract_type.__name__}, got {_type_name(value)}'
            )


def _is_mapping(item: Any) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(item, Mapping)


def _is_sequence(item: Any) -> TypeGuard[Sequence[Any]]:
    return isinstance(item, Sequence)


def _dot_path(data_path: Sequence[str | ArrayMatch], error_path: Sequence[str | ArrayMatch]) -> str:
    return '.'.join([str(p) for p in data_path] + [str(p) for p in error_path])


def _type_name(v: Any) -> str:
    return 'None' if v is None else type(v).__name__


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

    prices: ModelPrice | list[ConditionalPrice] = dataclasses.field(default_factory=list)
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

    def calc_price(
        self,
        usage: AbstractUsage,
        provider: Provider,
        *,
        genai_request_timestamp: datetime | None = None,
        auto_update_timestamp: datetime | None = None,
    ) -> PriceCalculation:
        """Calculate the price for the given usage."""
        genai_request_timestamp = genai_request_timestamp or datetime.now(tz=timezone.utc)

        model_price = self.get_prices(genai_request_timestamp)
        price = model_price.calc_price(usage)
        return PriceCalculation(
            input_price=price['input_price'],
            output_price=price['output_price'],
            total_price=price['total_price'],
            model=self,
            provider=provider,
            model_price=model_price,
            auto_update_timestamp=auto_update_timestamp,
        )

    def summary(self) -> str:
        return f'Model(id={self.id!r}, name={self.name!r}, ...)'


class CalcPrice(TypedDict):
    input_price: Decimal
    output_price: Decimal
    total_price: Decimal


@dataclass
class ModelPrice:
    """Set of prices for using a model"""

    input_mtok: Decimal | TieredPrices | None = None
    """price in USD per million uncached text input/prompt token"""

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

    requests_kcount: Decimal | None = None
    """price in USD per thousand requests"""

    def calc_price(self, usage: AbstractUsage) -> CalcPrice:
        """Calculate the price of usage in USD with this model price."""
        input_price = Decimal(0)
        output_price = Decimal(0)

        if uncached_input_tokens := usage.input_tokens:
            if cache_write_tokens := usage.cache_write_tokens:
                uncached_input_tokens -= cache_write_tokens
            if cache_read_tokens := usage.cache_read_tokens:
                uncached_input_tokens -= cache_read_tokens

            if uncached_input_tokens < 0:
                raise ValueError('uncached_input_tokens cannot be negative')
            input_price += calc_mtok_price(self.input_mtok, uncached_input_tokens)

        input_price += calc_mtok_price(self.cache_write_mtok, usage.cache_write_tokens)
        input_price += calc_mtok_price(self.cache_read_mtok, usage.cache_read_tokens)
        output_price += calc_mtok_price(self.output_mtok, usage.output_tokens)
        input_price += calc_mtok_price(self.input_audio_mtok, usage.input_audio_tokens)
        input_price += calc_mtok_price(self.cache_audio_read_mtok, usage.cache_audio_read_tokens)
        output_price += calc_mtok_price(self.output_audio_mtok, usage.output_audio_tokens)

        total_price = input_price + output_price

        if self.requests_kcount is not None:
            total_price += self.requests_kcount / 1000

        return {'input_price': input_price, 'output_price': output_price, 'total_price': total_price}

    def __str__(self) -> str:
        parts: list[str] = []
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if value is not None:
                if field.name == 'requests_kcount':
                    parts.append(f'${value} / K requests')
                else:
                    name = field.name.replace('_mtok', '').replace('_', ' ')
                    if isinstance(value, TieredPrices):
                        parts.append(f'{value.base}/{name} MTok (+tiers)')
                    else:
                        parts.append(f'${value}/{name} MTok')

        return ', '.join(parts)


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
    """Pricing together with constraints that define when those prices should be used.

    The last price active price (price where the constraints are met) is used.
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


providers_schema = pydantic.TypeAdapter(list[Provider], config=pydantic.ConfigDict(defer_build=True))
