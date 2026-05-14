from __future__ import annotations as _annotations

import dataclasses
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar, Union, cast, overload

import pydantic
from pydantic_core import core_schema
from typing_extensions import TypedDict, TypeGuard

if TYPE_CHECKING:
    from genai_prices.units import UnitDef, UnitRegistry

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
    model: ModelInfo | None = dataclasses.field(repr=False)
    provider: Provider = dataclasses.field(repr=False)
    auto_update_timestamp: datetime | None

    def calc_price(
        self, *, genai_request_timestamp: datetime | None = None, model: ModelInfo | None = None
    ) -> PriceCalculation:
        """Calculate the price for the given usage.

        Args:
            genai_request_timestamp: The timestamp of the request to the GenAI service, use `None` to use the current
                time.
            model: The model to calculate the price for, if `None` the model from the response data is used.
        """
        model = model or self.model
        if model is None:
            raise ValueError('No model reference found in response data and model not provided')

        return model.calc_price(
            self.usage,
            self.provider,
            genai_request_timestamp=genai_request_timestamp,
            auto_update_timestamp=self.auto_update_timestamp,
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
    models: list[ModelInfo] = dataclasses.field(default_factory=list)
    """List of models supported by this provider"""

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

    if data is None and not required:
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
        elif required:
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


class ModelPriceMeta(type):
    """Let dataclass subclasses accept dynamic registry-backed price kwargs."""

    def __call__(cls: ModelPriceMeta, *args: Any, **kwargs: Any) -> ModelPrice:
        model_price_type = cast(type[ModelPrice], cls)
        if model_price_type is ModelPrice or not dataclasses.is_dataclass(model_price_type):
            return cast(ModelPrice, type.__call__(cls, *args, **kwargs))

        declared_fields = _model_price_declared_fields_for(model_price_type)
        stored_prices = kwargs.pop('_extra_prices', None)
        dynamic_prices = _pop_dynamic_price_kwargs(kwargs, declared_fields)
        instance = cast(ModelPrice, type.__call__(cls, *args, **kwargs))
        extra_prices = dict(instance.__dict__.get('_extra_prices', {}))
        extra_prices.update(_model_price_mapping_from_constructor(stored_prices))
        extra_prices.update(dynamic_prices)
        object.__setattr__(instance, '_extra_prices', extra_prices)
        return instance


class ModelPrice(metaclass=ModelPriceMeta):
    """Set of prices for using a model"""

    _extra_prices: dict[str, Decimal | TieredPrices | None]

    def __init__(self, **prices: Decimal | TieredPrices | None) -> None:
        raw_stored_prices = cast(Any, prices).pop('_extra_prices', None)
        stored_prices = _model_price_mapping_from_constructor(raw_stored_prices)
        stored_prices.update(prices)
        object.__setattr__(self, '_extra_prices', stored_prices)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(cls._validate)

    @classmethod
    def _validate(cls, data: Any) -> ModelPrice:
        if isinstance(data, cls):
            return data

        if not isinstance(data, Mapping):
            raise ValueError('ModelPrice must be a mapping')

        try:
            return cls(**_validate_model_price_data(cast(Mapping[str, Any], data)))
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    def __repr__(self) -> str:
        parts: list[str] = []
        for field in _model_price_fields_for(type(self)):
            value = getattr(self, field.name)
            if value is not None:
                parts.append(f'{field.name}={value!r}')

        if self._extra_prices:
            parts.extend(f'{key}={value!r}' for key, value in self._extra_prices.items())

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
        extra_prices = self.__dict__.get('_extra_prices', {})
        if name in extra_prices:
            return extra_prices[name]

        if _is_registered_price_key(name):
            return None

        raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _model_price_declared_fields_for(type(self)) or not _is_registered_price_key(name):
            object.__setattr__(self, name, value)
            return

        self.__dict__.setdefault('_extra_prices', {})[name] = value

    def __delattr__(self, name: str) -> None:
        extra_prices = self.__dict__.get('_extra_prices', {})
        if name in extra_prices:
            del extra_prices[name]
            return
        if name not in _model_price_declared_fields_for(type(self)) and _is_registered_price_key(name):
            raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')
        object.__delattr__(self, name)


def _model_price_declared_fields_for(model_price_type: type[ModelPrice]) -> frozenset[str]:
    return frozenset(field.name for field in _model_price_fields_for(model_price_type))


def _model_price_fields_for(model_price_type: type[ModelPrice]) -> tuple[dataclasses.Field[Any], ...]:
    if not dataclasses.is_dataclass(model_price_type):
        return ()
    return dataclasses.fields(model_price_type)


def _pop_dynamic_price_kwargs(
    kwargs: dict[str, Any], declared_fields: frozenset[str]
) -> dict[str, Decimal | TieredPrices | None]:
    return {
        key: kwargs.pop(key) for key in tuple(kwargs) if key not in declared_fields and _is_registered_price_key(key)
    }


def _model_price_mapping_from_constructor(data: Any) -> dict[str, Decimal | TieredPrices | None]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TypeError('_extra_prices must be a mapping')
    return dict(cast(Mapping[str, Union[Decimal, TieredPrices, None]], data))


def _validate_model_price_data(data: Mapping[str, Any]) -> dict[str, Decimal | TieredPrices | None]:
    prices = {
        key: _validate_model_price_value(value)
        for key, value in _model_price_mapping_from_constructor(data.get('_extra_prices')).items()
    }
    for key, value in data.items():
        if key != '_extra_prices':
            prices[key] = _validate_model_price_value(value)
    return prices


_model_price_value_adapter: pydantic.TypeAdapter[Decimal | TieredPrices | None] | None = None


def _validate_model_price_value(value: Any) -> Decimal | TieredPrices | None:
    global _model_price_value_adapter

    if _model_price_value_adapter is None:
        _model_price_value_adapter = pydantic.TypeAdapter(Union[Decimal, TieredPrices, None])
    return _model_price_value_adapter.validate_python(value)


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

    for price_key, value in model_price._extra_prices.items():  # pyright: ignore[reportPrivateUsage]
        if value is not None and price_key not in yielded_price_keys:
            yield price_key


def _iter_priced_registered_units(model_price: ModelPrice, registry: UnitRegistry) -> Iterator[UnitDef]:
    yield from (unit for unit in registry.units.values() if getattr(model_price, unit.price_key) is not None)


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


providers_schema = pydantic.TypeAdapter(list[Provider], config=pydantic.ConfigDict(defer_build=True))
