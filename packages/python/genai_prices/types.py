from __future__ import annotations as _annotations

import dataclasses
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from fractions import Fraction
from itertools import combinations, product
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar, Union, cast, overload

import pydantic
from typing_extensions import TypedDict, TypeGuard

if TYPE_CHECKING:
    from genai_prices.units import UnitDef, UnitFamily, UnitRegistry

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
        reported_usage_keys = _reported_usage_keys()
        unknown_keys = values.keys() - reported_usage_keys
        if unknown_keys:
            bad_keys = ', '.join(sorted(unknown_keys))
            raise ValueError(f'Unknown usage key: {bad_keys}')

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
        from genai_prices.units import UnitRegistry, _get_registry  # pyright: ignore[reportPrivateUsage]

        registry = _get_registry()
        requested_unit = registry.units[usage_key]
        descendant_values = [
            (unit, value)
            for reported_key, value in self._values.items()
            if (unit := registry.units.get(reported_key)) is not None
            and unit is not requested_unit
            and UnitRegistry.is_ancestor_or_self(requested_unit, unit)
        ]
        if not descendant_values:
            return 0

        return _infer_usage_total(requested_unit, sorted(descendant_values, key=lambda item: item[0].usage_key))


def _infer_usage_total(requested_unit: UnitDef, descendant_values: Sequence[tuple[UnitDef, int]]) -> int:
    atoms = _usage_inference_atoms(requested_unit, descendant_values)
    equations = [
        [Fraction(1 if _atom_is_contained_in_unit(atom, unit, requested_unit) else 0) for atom in atoms]
        for unit, _ in descendant_values
    ]
    values = [Fraction(value) for _, value in descendant_values]

    possible_totals = _feasible_total_values(equations, values)
    if not possible_totals:
        raise ValueError(
            f'Contradictory usage data for {requested_unit.usage_key}: '
            f'reported descendant usage values cannot be reconciled'
        )

    reported_keys = ', '.join(unit.usage_key for unit, _ in descendant_values)
    if len(possible_totals) != 1:
        raise ValueError(
            f'Cannot infer {requested_unit.usage_key} from reported usage keys {reported_keys}: '
            f'missing overlap or more-specific usage data'
        )

    total = next(iter(possible_totals))
    if total.denominator != 1:
        raise ValueError(
            f'Contradictory usage data for {requested_unit.usage_key}: '
            f'reported descendant usage values cannot be reconciled'
        )
    return total.numerator


def _usage_inference_atoms(
    requested_unit: UnitDef, descendant_values: Sequence[tuple[UnitDef, int]]
) -> list[tuple[tuple[str, str | None], ...]]:
    dimension_values: dict[str, set[str]] = {}
    for unit, _ in descendant_values:
        for key, value in unit.dimensions.items():
            if key not in requested_unit.dimensions:
                dimension_values.setdefault(key, set()).add(value)

    axes = sorted(dimension_values)
    value_options = [sorted(dimension_values[axis]) + [None] for axis in axes]
    atoms: list[tuple[tuple[str, str | None], ...]] = []
    for values in product(*value_options):
        atom = tuple(zip(axes, values))
        if any(_atom_is_contained_in_unit(atom, unit, requested_unit) for unit, _ in descendant_values):
            atoms.append(atom)

    return atoms


def _atom_is_contained_in_unit(
    atom: tuple[tuple[str, str | None], ...], unit: UnitDef, requested_unit: UnitDef
) -> bool:
    atom_dimensions = dict(atom)
    return all(
        key in requested_unit.dimensions or atom_dimensions.get(key) == value for key, value in unit.dimensions.items()
    )


def _feasible_total_values(equations: Sequence[Sequence[Fraction]], values: Sequence[Fraction]) -> set[Fraction]:
    rank = _matrix_rank(equations)
    atom_count = len(equations[0]) if equations else 0
    possible_totals: set[Fraction] = set()

    for basis in combinations(range(atom_count), rank):
        basis_equations = [[row[column] for column in basis] for row in equations]
        if _matrix_rank(basis_equations) != rank:
            continue

        solution = _solve_linear_system(basis_equations, values)
        if solution is None or any(value < 0 for value in solution):
            continue

        possible_totals.add(sum(solution, start=Fraction(0)))

    return possible_totals


def _matrix_rank(matrix: Sequence[Sequence[Fraction]]) -> int:
    rows = [list(row) for row in matrix]
    if not rows:
        return 0

    row_count = len(rows)
    column_count = len(rows[0])
    rank = 0
    for column in range(column_count):
        pivot = next((row for row in range(rank, row_count) if rows[row][column] != 0), None)
        if pivot is None:
            continue

        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        pivot_value = rows[rank][column]
        rows[rank] = [value / pivot_value for value in rows[rank]]
        for row in range(row_count):
            if row == rank or rows[row][column] == 0:
                continue
            factor = rows[row][column]
            rows[row] = [value - factor * pivot_value for value, pivot_value in zip(rows[row], rows[rank])]

        rank += 1

    return rank


def _solve_linear_system(equations: Sequence[Sequence[Fraction]], values: Sequence[Fraction]) -> list[Fraction] | None:
    rows = [list(row) + [value] for row, value in zip(equations, values)]
    if not rows:
        return []

    variable_count = len(rows[0]) - 1
    row_count = len(rows)
    rank = 0
    pivot_columns: list[int] = []
    for column in range(variable_count):
        pivot = next((row for row in range(rank, row_count) if rows[row][column] != 0), None)
        if pivot is None:
            continue

        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        pivot_value = rows[rank][column]
        rows[rank] = [value / pivot_value for value in rows[rank]]
        for row in range(row_count):
            if row == rank or rows[row][column] == 0:
                continue
            factor = rows[row][column]
            rows[row] = [value - factor * pivot_value for value, pivot_value in zip(rows[row], rows[rank])]

        pivot_columns.append(column)
        rank += 1

    for row in rows:
        if all(value == 0 for value in row[:variable_count]) and row[-1] != 0:
            return None

    if rank != variable_count:
        return None

    solution = [Fraction(0) for _ in range(variable_count)]
    for row_index, column in enumerate(pivot_columns):
        solution[column] = rows[row_index][-1]

    return solution


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


_USAGE_REPR_ORDER = (
    'input_tokens',
    'cache_write_tokens',
    'cache_read_tokens',
    'output_tokens',
    'input_audio_tokens',
    'cache_audio_read_tokens',
    'output_audio_tokens',
)


def _reported_usage_keys() -> frozenset[str]:
    from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

    return _get_registry().reported_usage_keys()


def _reported_usage_key_order() -> tuple[str, ...]:
    from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

    registry_keys = tuple(_get_registry().reported_usage_keys())
    extra_keys = tuple(key for key in registry_keys if key not in _USAGE_REPR_ORDER)
    return _USAGE_REPR_ORDER + extra_keys


def _raw_usage_value(obj: object, key: str) -> int | None:
    if isinstance(obj, Mapping):
        value = cast(Mapping[str, object], obj).get(key)
        if value is None:
            return None
        return cast(int, value)

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
        from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]
        from genai_prices.validation import validate_model_price

        registry = _get_registry()
        validate_model_price(_collect_effective_model_price_keys(self, registry), registry)

        usage_data = Usage.from_raw(usage)
        grouped_units = _group_model_price_units_by_family(self, registry)
        priced_counts = _compute_registry_priced_counts(grouped_units, usage_data)

        input_price = Decimal(0)
        output_price = Decimal(0)
        total_price = Decimal(0)
        total_input_tokens = usage_data.input_tokens

        for family, units in grouped_units.items():
            for unit in units:
                unit_price = calc_unit_price(
                    getattr(self, unit.price_key),
                    priced_counts[unit.usage_key],
                    total_input_tokens,
                    family.per,
                )
                total_price += unit_price

                direction = unit.dimensions.get('direction')
                if direction == 'input':
                    input_price += unit_price
                elif direction == 'output':
                    output_price += unit_price

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
                        parts.append(f'${value.base}/{name} MTok (+tiers)')
                    else:
                        parts.append(f'${value}/{name} MTok')

        return ', '.join(parts)

    def is_free(self) -> bool:
        return all(_price_value_is_free(getattr(self, field.name)) for field in dataclasses.fields(self))

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        from genai_prices.units import _get_registry  # pyright: ignore[reportPrivateUsage]

        if name in _get_registry().price_keys:
            return None

        raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')


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
    """Calculate the price for a unit count normalized by the unit family's ``per`` value."""
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


def _price_value_is_free(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, TieredPrices):
        return value.base == 0 and all(tier.price == 0 for tier in value.tiers)
    if isinstance(value, Decimal):
        return value == 0
    return not value


def _collect_effective_model_price_keys(model_price: ModelPrice, registry: UnitRegistry) -> set[str]:
    return set(_iter_effective_model_price_keys(model_price, registry))


def _group_model_price_units_by_family(
    model_price: ModelPrice, registry: UnitRegistry
) -> dict[UnitFamily, set[UnitDef]]:
    groups: dict[UnitFamily, set[UnitDef]] = {}
    for price_key in _iter_effective_model_price_keys(model_price, registry):
        unit = registry.units[registry.price_keys[price_key]]
        groups.setdefault(unit.family, set()).add(unit)

    return groups


def _compute_registry_priced_counts(grouped_units: Mapping[UnitFamily, set[UnitDef]], usage: Usage) -> dict[str, int]:
    from genai_prices.decompose import compute_leaf_values

    counts: dict[str, int] = {}
    for family, units in grouped_units.items():
        usage_keys = {unit.usage_key for unit in units}
        if family.id == 'requests':
            counts.update({usage_key: 1 for usage_key in usage_keys})
        else:
            counts.update(compute_leaf_values(usage_keys, usage, family))

    return counts


def _iter_effective_model_price_keys(model_price: ModelPrice, registry: UnitRegistry) -> Iterator[str]:
    for field in dataclasses.fields(model_price):
        if field.name in registry.price_keys and getattr(model_price, field.name) is not None:
            yield field.name


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
