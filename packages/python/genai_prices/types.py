from __future__ import annotations as _annotations

import dataclasses
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeGuard, TypeVar, cast, overload

import pydantic
from typing_extensions import Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from genai_prices.units import UnitDef, UnitRegistry

__all__ = (
    'ProviderID',
    'PriceCalculation',
    'PriceContext',
    'PriceContextValue',
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
    'ConditionOperators',
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
)


# Define MatchLogic after __all__ to avoid forward reference issues
def clause_discriminator(v: Any) -> str | None:
    assert isinstance(v, dict), f'Expected dict, got {type(v)}'
    return next(iter(v))  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


MatchLogic = Annotated[
    Annotated['ClauseStartsWith', pydantic.Tag('starts_with')]
    | Annotated['ClauseEndsWith', pydantic.Tag('ends_with')]
    | Annotated['ClauseContains', pydantic.Tag('contains')]
    | Annotated['ClauseRegex', pydantic.Tag('regex')]
    | Annotated['ClauseEquals', pydantic.Tag('equals')]
    | Annotated['ClauseOr', pydantic.Tag('or')]
    | Annotated['ClauseAnd', pydantic.Tag('and')],
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

PriceContextValue = str | int | bool
PriceContext = Mapping[str, PriceContextValue]
"""Request-level pricing context, e.g. `{'service_tier': 'batch'}`."""


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


ExtractPath = str | Sequence[str | ArrayMatch]


@dataclass(repr=False)
class PriceCalculation:
    input_price: Decimal
    output_price: Decimal
    total_price: Decimal
    model: ModelInfo = dataclasses.field(repr=False)
    provider: Provider = dataclasses.field(repr=False)
    model_price: ModelPrice
    auto_update_timestamp: datetime | None
    price_context: dict[str, PriceContextValue] = dataclasses.field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            'PriceCalculation('
            f'input_price={self.input_price!r}, '
            f'output_price={self.output_price!r}, '
            f'total_price={self.total_price!r}, '
            f'model={self.model.summary()}, '
            f'provider={self.provider.summary()}, '
            f'model_price=ModelPrice({self.model_price}), '
            f'auto_update_timestamp={self.auto_update_timestamp!r}'
            + (f', price_context={self.price_context!r}' if self.price_context else '')
            + ')'
        )


@dataclass(repr=False)
class ExtractedUsage:
    usage: Usage
    model: ModelInfo | None = dataclasses.field(repr=False)
    provider: Provider = dataclasses.field(repr=False)
    auto_update_timestamp: datetime | None

    def calc_price(
        self,
        *,
        genai_request_timestamp: datetime | None = None,
        model: ModelInfo | None = None,
        price_context: PriceContext | None = None,
    ) -> PriceCalculation:
        """Calculate the price for the given usage.

        Args:
            genai_request_timestamp: The timestamp of the request to the GenAI service, use `None` to use the current
                time.
            model: The model to calculate the price for, if `None` the model from the response data is used.
            price_context: Request-level pricing context, e.g. `{'service_tier': 'batch'}`.
        """
        model = model or self.model
        if model is None:
            raise ValueError('No model reference found in response data and model not provided')

        return model.calc_price(
            self.usage,
            self.provider,
            genai_request_timestamp=genai_request_timestamp,
            auto_update_timestamp=self.auto_update_timestamp,
            price_context=price_context,
        )

    def __repr__(self) -> str:
        return (
            'ExtractedUsage('
            f'usage={self.usage!r}, '
            f'model={self.model.summary() if self.model else None}, '
            f'provider={self.provider.summary()}, '
            f'auto_update_timestamp={self.auto_update_timestamp!r})'
        )

    def __add__(self, other: ExtractedUsage | Any) -> ExtractedUsage:
        """Accumulate inner Usage, handling nullable usage fields.

        Accumulating usage is useful for common streaming situations where user wants to save and compute costs for
        all the response chunks in a stream

        Args:
              other: The usage to accumulate with this usage extraction instance.
        """

        if not isinstance(other, ExtractedUsage):
            return NotImplemented  # will raise a TypeError

        models_match = self.model and other.model and other.model.id == self.model.id
        if not models_match:
            raise ValueError(f'Cannot add {other} to {self}, models do not match {other.model} != {self.model}')

        providers_match = self.provider and other.provider and other.provider.id == self.provider.id
        if not providers_match:
            raise ValueError(
                f'Cannot add {other} to {self}, providers do not match {other.provider} != {self.provider}'
            )

        return ExtractedUsage(
            model=self.model,
            provider=self.provider,
            auto_update_timestamp=self.auto_update_timestamp,
            usage=self.usage + other.usage,
        )

    def __radd__(self, other: ExtractedUsage | Any) -> ExtractedUsage:
        return self + other


AbstractUsage = object


class Usage:
    """Simple token usage container."""

    _values: dict[str, int]

    def __init__(self, **kwargs: int | None) -> None:
        object.__setattr__(self, '_values', {})
        reported_usage_keys = _reported_usage_keys()
        unknown_keys = kwargs.keys() - reported_usage_keys
        if unknown_keys:
            bad_keys = ', '.join(sorted(unknown_keys))
            raise ValueError(f'Unknown usage key: {bad_keys}')

        self._store_values(kwargs)

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        if isinstance(obj, Usage):
            return obj

        values: dict[str, int] = {}
        for key in _reported_usage_keys():
            value = _raw_usage_value(obj, key)
            if value is not None:
                values[key] = value

        return cls(**values)

    def __setattr__(self, name: str, value: int | None) -> None:
        if name == '_values':
            object.__setattr__(self, name, value)
        elif name in _reported_usage_keys():
            self._store_values({name: value})
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> int:
        if name in _reported_usage_keys():
            if name in self._values:
                return self._values[name]

            return self._infer_missing_value(name)

        raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

    def _store_values(self, values: Mapping[str, int | None]) -> None:
        for key, value in values.items():
            if value is None:
                self._values.pop(key, None)
            else:
                self._values[key] = value

    def reported_value(self, usage_key: str) -> int:
        return self._values.get(usage_key, 0)

    def __add__(self, other: Usage | Any) -> Usage:
        if not isinstance(other, Usage):
            return NotImplemented

        return Usage(
            **{
                key: self._values.get(key, 0) + other._values.get(key, 0)
                for key in self._values.keys() | other._values.keys()
            }
        )

    def __radd__(self, other: Usage | int) -> Usage:
        if other == 0:
            return self
        if isinstance(other, Usage):
            return other + self
        return NotImplemented

    def __eq__(self, other: object) -> Any:
        if not isinstance(other, Usage):
            return NotImplemented

        return self._values == other._values

    def __repr__(self) -> str:
        values = ', '.join(f'{key}={value!r}' for key, value in self._ordered_values())
        return f'Usage({values})'

    def _ordered_values(self) -> list[tuple[str, int]]:
        return [(key, self._values[key]) for key in _reported_usage_key_order() if key in self._values]

    def _infer_missing_value(self, usage_key: str) -> int:
        from genai_prices.decompose import is_descendant_or_self
        from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

        registry = _get_registry()
        requested_unit = registry.units[usage_key]
        descendant_keys = [
            unit.usage_key
            for reported_key, value in self._values.items()
            if value > 0
            and (unit := registry.units.get(reported_key)) is not None
            and unit is not requested_unit
            and is_descendant_or_self(requested_unit, unit)
        ]
        if not descendant_keys:
            overlapping_keys = _reported_overlap_keys_for_join(
                requested_unit,
                [
                    unit
                    for reported_key, value in self._values.items()
                    if value > 0 and (unit := registry.units.get(reported_key)) is not None
                ],
            )
            if not overlapping_keys:
                return 0

            reported_keys = ', '.join(overlapping_keys)
            raise ValueError(
                f'Missing usage for {usage_key}: reported overlapping usage keys {reported_keys} '
                f'require explicit {usage_key}'
            )

        reported_keys = ', '.join(sorted(descendant_keys))
        raise ValueError(
            f'Missing usage for {usage_key}: reported descendant usage keys {reported_keys} '
            f'require explicit {usage_key}'
        )


def _reported_overlap_keys_for_join(
    requested_unit: UnitDef, reported_units: Sequence[UnitDef]
) -> tuple[str, str] | None:
    from genai_prices.decompose import is_descendant_or_self

    sorted_units = sorted(reported_units, key=lambda unit: unit.usage_key)
    for index, left in enumerate(sorted_units):
        for right in sorted_units[index + 1 :]:
            if not left.is_compatible_with(right):
                continue
            if is_descendant_or_self(left, right) or is_descendant_or_self(right, left):
                continue
            if requested_unit.dimensions == {**left.dimensions, **right.dimensions}:
                return left.usage_key, right.usage_key

    return None


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
    fallback_model_providers: list[str] | None = None
    """List of provider identifiers to fallback to to get prices if this provider doesn't have a price.

    This is used when one provider offers another provider's models, e.g. Google and AWS offer Anthropic models,
    Azure offers OpenAI models, etc.
    """
    prices: ModelPrice | list[ConditionalPrice] | None = None
    """Prices inherited by every model in this provider.

    Model-level prices override provider-level prices for the same unit. Provider-level `when` clauses may
    additionally match on the `model` parameter using the same logic as `model_match`.
    """
    models: list[ModelInfo] = dataclasses.field(default_factory=list)
    """List of models supported by this provider"""

    def get_prices(
        self, request_timestamp: datetime, price_context: PriceContext | None = None, model_id: str | None = None
    ) -> ModelPrice:
        if self.prices is None:
            return ModelPrice()
        return _resolve_conditional_prices(self.prices, request_timestamp, price_context or {}, model_id)

    def find_model(self, model_ref: str, *, all_providers: list[Provider] | None = None) -> ModelInfo | None:
        model_ref = model_ref.lower()
        for model in self.models:
            if model.is_match(model_ref):
                return model
        if self.fallback_model_providers and all_providers:
            for provider_id in self.fallback_model_providers:
                provider = next((p for p in all_providers if p.id == provider_id), None)
                if provider:
                    # don't pass all_providers when falling back, so we can only have one step of fallback
                    if model := provider.find_model(model_ref):
                        return model
        return None

    def extract_usage(self, response_data: Any, *, api_flavor: str = 'default') -> tuple[str | None, Usage]:
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

        try:
            extractor = next(e for e in self.extractors if e.api_flavor == api_flavor)
        except StopIteration as e:
            fs = ', '.join(e.api_flavor for e in self.extractors)
            raise ValueError(f'Unknown api_flavor {api_flavor!r}, allowed values: {fs}') from e

        return extractor.extract(response_data)

    def summary(self) -> str:
        return f'Provider(id={self.id!r}, name={self.name!r}, ...)'


@dataclass
class UsageExtractorMapping:
    """Mappings from used to build usage."""

    path: ExtractPath
    """Path to the value to extract"""
    dest: str
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

    def __post_init__(self) -> None:
        _validate_usage_extractor_destinations(self.mappings)

    def extract(self, response_data: Any) -> tuple[str | None, Usage]:
        """Extract model name and usage information from a response.

        Args:
            response_data: The response data to extract usage information from, generally the decoded JSON response.

        Raises:
            ValueError: If no usage information is found at the root.

        Returns:
            tuple[str, Usage]: The extracted model name and usage information.
        """
        model_name = _extract_path(self.model_path, response_data, str, False, [])

        root = self.root
        if isinstance(root, str):
            root = [root]

        usage_obj = cast(dict[str, Any], _extract_path(root, response_data, Mapping, True, []))

        values: dict[str, int] = {}
        values_set = False
        for mapping in self.mappings:
            value = _extract_path(mapping.path, usage_obj, int, mapping.required, root)
            if value is not None:
                values[mapping.dest] = values.get(mapping.dest, 0) + value
                values_set = True
        if not values_set:
            raise ValueError(f'No usage information found at {self.root}')
        return model_name, Usage(**values)


def _validate_usage_extractor_destinations(mappings: Sequence[UsageExtractorMapping]) -> None:
    from genai_prices.validation import validate_extractor_destinations

    validate_extractor_destinations(
        {mapping.dest for mapping in mappings},
        _reported_usage_keys(),
    )


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
                if required:
                    raise ValueError(
                        f'Expected `{_dot_path(data_path, error_path)}` value to be a sequence, got {_type_name(data)}'
                    )
                else:
                    return None
            if extracted_data := step.extract(data):
                data = extracted_data
            elif required:
                raise ValueError(f'Unable to find item at `{_dot_path(data_path, error_path)}`')
            else:
                return None
        else:
            if not _expect_mapping(data, required, data_path, error_path):
                return None
            try:
                data = data[step]
            except KeyError as e:
                if required:
                    raise ValueError(f'Missing value at `{_dot_path(data_path, error_path)}`') from e
                else:
                    return None

    if data is None and not required:
        return None

    if not _expect_mapping(data, required, data_path, error_path):
        return None

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
        elif required:
            error_path.append(last)
            raise ValueError(
                f'Expected `{_dot_path(data_path, error_path)}` value to be a {extract_type.__name__}, got {_type_name(value)}'
            )


def _expect_mapping(
    data: Any, required: bool, data_path: Sequence[str | ArrayMatch], error_path: Sequence[str | ArrayMatch]
) -> TypeGuard[Mapping[str, Any]]:
    if _is_mapping(data):
        return True
    if required:
        raise ValueError(f'Expected `{_dot_path(data_path, error_path)}` value to be a dict, got {_type_name(data)}')
    return False


def _is_mapping(item: Any) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(item, Mapping)


def _is_sequence(item: Any) -> TypeGuard[Sequence[Any]]:
    return isinstance(item, Sequence)


def _dot_path(data_path: Sequence[str | ArrayMatch], error_path: Sequence[str | ArrayMatch]) -> str:
    return '.'.join([str(p) for p in data_path] + [str(p) for p in error_path])


def _type_name(v: Any) -> str:
    return 'None' if v is None else type(v).__name__


def _reported_usage_keys() -> frozenset[str]:
    from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

    # Phase 5 should benchmark/cache this active-registry key set and the
    # corresponding registry-order tuple once registry validation identities exist.
    return _get_registry().reported_usage_keys()


def _reported_usage_key_order() -> tuple[str, ...]:
    from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

    registry = _get_registry()
    reported_keys = registry.reported_usage_keys()
    return tuple(key for key in registry.units if key in reported_keys)


def _raw_usage_value(obj: object, key: str) -> int | None:
    value = getattr(obj, key, None)
    if value is None:
        return None
    return cast(int, value)


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
    deprecated: bool | None = None
    """Flag indicating this model is deprecated by the provider but still functional."""

    prices: ModelPrice | list[ConditionalPrice] = dataclasses.field(default_factory=list)
    """Set of prices for using this model.

    When multiple `ConditionalPrice`s are used, they are tried last to first to find a pricing model to use.
    E.g. later conditional prices take precedence over earlier ones.

    If no conditional models match the conditions, the first one is used.
    """

    def is_match(self, model_ref: str) -> bool:
        return self.match.is_match(model_ref.lower())

    def get_prices(self, request_timestamp: datetime, price_context: PriceContext | None = None) -> ModelPrice:
        return _resolve_conditional_prices(self.prices, request_timestamp, price_context or {}, self.id)

    def calc_price(
        self,
        usage: AbstractUsage,
        provider: Provider,
        *,
        genai_request_timestamp: datetime | None = None,
        auto_update_timestamp: datetime | None = None,
        price_context: PriceContext | None = None,
    ) -> PriceCalculation:
        """Calculate the price for the given usage."""
        genai_request_timestamp = genai_request_timestamp or datetime.now(tz=timezone.utc)

        model_price = self.get_prices(genai_request_timestamp, price_context)
        provider_price = provider.get_prices(genai_request_timestamp, price_context, self.id)
        model_price = _merge_provider_prices(model_price, provider_price)
        price = model_price.calc_price(usage)
        return PriceCalculation(
            input_price=price['input_price'],
            output_price=price['output_price'],
            total_price=price['total_price'],
            model=self,
            provider=provider,
            model_price=model_price,
            price_context=dict(price_context or {}),
            auto_update_timestamp=auto_update_timestamp,
        )

    def summary(self) -> str:
        return f'Model(id={self.id!r}, name={self.name!r}, ...)'


class CalcPrice(TypedDict):
    input_price: Decimal
    output_price: Decimal
    total_price: Decimal


class ModelPrice:
    """Set of prices for using a model"""

    def __init__(
        self,
        **price_kwargs: Decimal | TieredPrices | None,
    ) -> None:
        for key, value in price_kwargs.items():
            object.__setattr__(self, key, value)

    def __repr__(self) -> str:
        parts = [f'{key}={value!r}' for key, value in self.__dict__.items() if value is not None]
        return f'{type(self).__name__}({", ".join(parts)})'

    def calc_price(self, usage: AbstractUsage) -> CalcPrice:
        """Calculate the price of usage in USD with this model price."""
        from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]
        from genai_prices.validation import validate_model_price

        registry = _get_registry()
        validate_model_price(_collect_effective_model_price_keys(self, registry), registry)

        usage_data = Usage.from_raw(usage)
        priced_units = _collect_model_price_units(self, registry)
        priced_counts = _compute_registry_priced_counts(priced_units, usage_data)

        input_price = Decimal(0)
        output_price = Decimal(0)
        total_price = Decimal(0)
        # Reading input_tokens can trigger lazy inference errors; only do it when
        # tiered pricing actually needs the threshold.
        total_input_tokens = usage_data.input_tokens if _model_price_uses_tiered_prices(self, registry) else 0

        for unit in priced_units:
            unit_price = calc_unit_price(
                getattr(self, unit.price_key),
                priced_counts[unit.usage_key],
                total_input_tokens,
                unit.per,
            )
            total_price += unit_price

            direction = unit.dimensions.get('direction')
            if direction == 'input':
                input_price += unit_price
            elif direction == 'output':
                output_price += unit_price

        return {'input_price': input_price, 'output_price': output_price, 'total_price': total_price}

    def __str__(self) -> str:
        from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

        registry = _get_registry()
        parts: list[str] = []
        for price_key in _iter_effective_model_price_keys(self, registry):
            value = getattr(self, price_key)
            if value is not None:
                if price_key == 'requests_kcount':
                    parts.append(f'${value} / K requests')
                else:
                    name = price_key.replace('_mtok', '').replace('_', ' ')
                    if isinstance(value, TieredPrices):
                        parts.append(f'${value.base}/{name} MTok (+tiers)')
                    else:
                        parts.append(f'${value}/{name} MTok')

        return ', '.join(parts)

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        if _is_registered_price_key(name):
            return None

        raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')


def _is_registered_price_key(name: str) -> bool:
    from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

    try:
        _get_registry().unit_for_price_key(name)
    except KeyError:
        return False
    else:
        return True


def calc_mtok_price(
    field_mtok: Decimal | TieredPrices | None, token_count: int | None, total_input_tokens: int
) -> Decimal:
    """Calculate the price for a given number of tokens based on the price in USD per million tokens (mtok).

    For tiered pricing, uses threshold-based pricing where crossing a tier applies that rate to ALL tokens.
    This is the industry standard used by Anthropic, Google, OpenAI, and most other providers.

    Args:
        field_mtok: Price per million tokens, either flat rate or tiered
        token_count: Number of tokens of this specific type to price
        total_input_tokens: Total input tokens for tier determination (used only for tiered pricing)
    """
    return calc_unit_price(field_mtok, token_count, total_input_tokens, 1_000_000)


def calc_unit_price(
    price: Decimal | TieredPrices | None, count: int | None, total_input_tokens: int, per: int
) -> Decimal:
    """Calculate the price for a unit count normalized by the unit's ``per`` value."""
    if price is None or count is None:
        return Decimal(0)

    if isinstance(price, TieredPrices):
        # Threshold-based pricing: tier is determined by total_input_tokens
        # Find the highest tier that applies based on total input tokens
        # When total_input_tokens is 0, no tier condition is met, so base rate is used
        applicable_price = price.base
        for tier in reversed(price.tiers):
            if total_input_tokens > tier.start:
                applicable_price = tier.price
                break
        unit_price = applicable_price * count
    else:
        unit_price = price * count
    return unit_price / per


def _collect_effective_model_price_keys(model_price: ModelPrice, registry: UnitRegistry) -> set[str]:
    return set(_iter_effective_model_price_keys(model_price, registry))


def _model_price_uses_tiered_prices(model_price: ModelPrice, registry: UnitRegistry) -> bool:
    return any(
        isinstance(getattr(model_price, price_key), TieredPrices)
        for price_key in _iter_effective_model_price_keys(model_price, registry)
    )


def _collect_model_price_units(model_price: ModelPrice, registry: UnitRegistry) -> tuple[UnitDef, ...]:
    return tuple(_iter_priced_registered_units(model_price, registry))


def _compute_registry_priced_counts(priced_units: Sequence[UnitDef], usage: Usage) -> dict[str, int]:
    from genai_prices.decompose import compute_leaf_values

    counts: dict[str, int] = {}
    priced_units_by_usage_key = {unit.usage_key: unit for unit in priced_units if unit.usage_key != 'requests'}
    if priced_units_by_usage_key:
        counts.update(compute_leaf_values(set(priced_units_by_usage_key), usage, priced_units_by_usage_key))
    if any(unit.usage_key == 'requests' for unit in priced_units):
        counts['requests'] = 1

    return counts


def _iter_effective_model_price_keys(model_price: ModelPrice, registry: UnitRegistry) -> Iterator[str]:
    yielded_price_keys: set[str] = set()
    for unit in _iter_priced_registered_units(model_price, registry):
        yielded_price_keys.add(unit.price_key)
        yield unit.price_key

    for price_key, value in _iter_model_price_attr_items(model_price, registry):
        if value is not None and price_key not in yielded_price_keys:
            yield price_key


def _iter_priced_registered_units(model_price: ModelPrice, registry: UnitRegistry) -> Iterator[UnitDef]:
    yield from (unit for unit in registry.units.values() if getattr(model_price, unit.price_key) is not None)


def _iter_model_price_attr_items(model_price: ModelPrice, registry: UnitRegistry) -> Iterator[tuple[str, object]]:
    registry_price_keys = {unit.price_key for unit in registry.units.values()}
    for key, value in model_price.__dict__.items():
        if key.startswith('_'):
            continue
        if type(model_price) is not ModelPrice and key not in registry_price_keys:
            continue
        yield key, value


def _iter_defined_price_values(model_price: ModelPrice) -> Iterator[tuple[str, Decimal | TieredPrices | None]]:
    """Yield the price keys explicitly set on a conditional entry's values."""
    for key, value in model_price.__dict__.items():
        if not key.startswith('_'):
            yield key, value


@dataclass
class TieredPrices:
    """Pricing model when the amount paid varies by number of tokens.

    Uses threshold-based pricing where crossing a tier applies that rate to ALL tokens.
    This is the industry standard "cliff" model used by most providers (Anthropic, Google, OpenAI, etc.).

    Example: For a tier starting at 200K tokens:
    - Using 199,999 tokens: all tokens pay base rate
    - Using 200,001 tokens: all tokens pay tier rate (not just the tokens above 200K)
    """

    base: Decimal
    """Base price in USD per million tokens, e.g. price until the first tier."""
    tiers: list[Tier]
    """Extra price tiers."""

    def __post_init__(self) -> None:
        """Ensure tiers are sorted in ascending order by start threshold."""
        self.tiers.sort(key=lambda tier: tier.start)


@dataclass
class Tier:
    """Price tier"""

    start: int
    """Start of the tier"""
    price: Decimal
    """Price for this tier"""


@dataclass
class ConditionOperators:
    """Comparison operators for a single `when` parameter.

    An empty operator set matches anything; multiple operators are ANDed (e.g. `gte` and `lte` form a range).
    """

    eq: PriceContextValue | None = None
    gte: PriceContextValue | None = None
    lte: PriceContextValue | None = None
    gt: PriceContextValue | None = None
    lt: PriceContextValue | None = None
    in_: list[PriceContextValue] | None = None

    def matches(self, actual: PriceContextValue | None) -> bool:
        if self.eq is not None and not _context_values_equal(actual, self.eq):
            return False
        if self.in_ is not None and not any(_context_values_equal(actual, item) for item in self.in_):
            return False
        for operator, expected in (('gte', self.gte), ('lte', self.lte), ('gt', self.gt), ('lt', self.lt)):
            if expected is not None and not _compare(operator, actual, expected):
                return False
        return True


Condition = PriceContextValue | ConditionOperators
"""A literal value (equality shorthand) or an explicit operator expression."""


def _context_values_equal(actual: PriceContextValue | None, expected: object) -> bool:
    return type(actual) is type(expected) and actual == expected


def _compare(operator: str, actual: PriceContextValue | None, expected: PriceContextValue) -> bool:
    if not isinstance(actual, int | float) or isinstance(actual, bool) or isinstance(expected, bool):
        return False
    if not isinstance(expected, int | float):
        return False
    if operator == 'gte':
        return actual >= expected
    if operator == 'lte':
        return actual <= expected
    if operator == 'gt':
        return actual > expected
    return actual < expected


def _when_matches(
    when: Mapping[str, Condition | MatchLogic] | None, price_context: PriceContext, model_id: str | None
) -> bool:
    if not when:
        return True
    for key, condition in when.items():
        if key == 'model':
            if model_id is None or not _model_condition_matches(condition, model_id):
                return False
            continue
        actual = price_context.get(key)
        if isinstance(condition, ConditionOperators):
            if not condition.matches(actual):
                return False
        elif not _context_values_equal(actual, condition):
            return False
    return True


@runtime_checkable
class _ModelMatcher(Protocol):
    def is_match(self, text: str) -> bool: ...


def _model_condition_matches(condition: object, model_id: str) -> bool:
    if isinstance(condition, str):
        return condition.lower() == model_id.lower()
    if isinstance(condition, _ModelMatcher):
        return condition.is_match(model_id.lower())
    return False


@dataclass
class ConditionalPrice:
    """Prices gated by an optional `when` clause and/or date/time constraint.

    For each unit, the first entry (top to bottom) that both matches and defines a price for the unit wins.
    """

    when: dict[str, Condition | MatchLogic] | None = None
    """Conditions ANDed together. None matches anything. The `model` key matches the model id via `MatchLogic`."""

    constraint: StartDateConstraint | TimeOfDateConstraint | None = None
    """Date/time constraint. None means this entry is not gated by date/time."""

    _: dataclasses.KW_ONLY

    values: ModelPrice
    """Prices that apply under this condition. Only the units that differ need to be listed."""

    def eligible(self, request_timestamp: datetime, price_context: PriceContext, model_id: str | None = None) -> bool:
        if self.constraint is not None and not self.constraint.active(request_timestamp):
            return False
        return _when_matches(self.when, price_context, model_id)


def _resolve_conditional_prices(
    prices: ModelPrice | list[ConditionalPrice],
    request_timestamp: datetime,
    price_context: PriceContext,
    model_id: str | None,
) -> ModelPrice:
    if isinstance(prices, ModelPrice):
        return prices

    if not prices:
        return ModelPrice()

    # Per-unit first-match: for each price key, the first eligible entry that defines it wins.
    resolved: dict[str, Decimal | TieredPrices | None] = {}
    for entry in prices:
        if not entry.eligible(request_timestamp, price_context, model_id):
            continue
        for price_key, value in _iter_defined_price_values(entry.values):
            resolved.setdefault(price_key, value)

    return type(prices[0].values)(**resolved)


def _merge_provider_prices(model_price: ModelPrice, provider_price: ModelPrice) -> ModelPrice:
    """Fill in units the model does not price from provider-level prices; model wins per unit."""
    merged: dict[str, Decimal | TieredPrices | None] = {
        key: value for key, value in _iter_defined_price_values(provider_price) if value is not None
    }
    if not merged:
        return model_price

    for key, value in _iter_defined_price_values(model_price):
        merged[key] = value
    return type(model_price)(**merged)


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
        return text.lower().startswith(self.starts_with.lower())


@dataclass
class ClauseEndsWith:
    ends_with: str

    def is_match(self, text: str) -> bool:
        return text.lower().endswith(self.ends_with.lower())


@dataclass
class ClauseContains:
    contains: str

    def is_match(self, text: str) -> bool:
        return self.contains.lower() in text.lower()


@dataclass
class ClauseRegex:
    regex: str

    def is_match(self, text: str) -> bool:
        return bool(re.search(self.regex, text))


@dataclass
class ClauseEquals:
    equals: str

    def is_match(self, text: str) -> bool:
        return text.lower() == self.equals.lower()


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


_model_price_mapping_schema = pydantic.TypeAdapter(dict[str, Decimal | TieredPrices | None])
_providers_schema = pydantic.TypeAdapter(
    list[Provider], config=pydantic.ConfigDict(defer_build=True, arbitrary_types_allowed=True)
)


def _providers_from_raw(raw_providers: Any) -> list[Provider]:  # pyright: ignore[reportUnusedFunction]
    return _providers_schema.validate_python(_normalize_model_prices(raw_providers))


def _normalize_model_prices(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_model_prices(item) for item in cast(list[Any], value)]
    if not isinstance(value, Mapping):
        return value

    normalized: dict[str, Any] = {}
    raw_mapping = cast(Mapping[str, Any], value)
    for key, raw_value in raw_mapping.items():
        if key == 'prices':
            normalized[key] = _normalize_prices_field(raw_value)
        elif key == 'values':
            normalized[key] = _normalize_values_field(raw_value)
        elif key == 'when':
            normalized[key] = _normalize_when_field(raw_value)
        else:
            normalized[key] = _normalize_model_prices(raw_value)
    return normalized


def _normalize_when_field(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    normalized: dict[str, Any] = {}
    for param, condition in cast(Mapping[str, Any], value).items():
        # `model` conditions are MatchLogic; leave them raw so pydantic's discriminated union parses them.
        if param != 'model' and isinstance(condition, Mapping):
            operators = {
                ('in_' if op == 'in' else op): operand for op, operand in cast(Mapping[str, Any], condition).items()
            }
            normalized[param] = ConditionOperators(**operators)
        else:
            normalized[param] = condition
    return normalized


def _normalize_prices_field(value: Any) -> ModelPrice | list[Any]:
    if isinstance(value, list):
        return [_normalize_model_prices(item) for item in cast(list[Any], value)]
    return _normalize_values_field(value)


def _normalize_values_field(value: Any) -> ModelPrice:
    if isinstance(value, ModelPrice):
        return value
    prices = _model_price_mapping_schema.validate_python(value)
    return ModelPrice(**cast(Any, prices))
