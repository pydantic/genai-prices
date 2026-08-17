from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext

UsageValue = int | float


def validate_usage_value(usage_key: str, value: object) -> UsageValue:
    if isinstance(value, bool):
        raise _invalid_usage_value(usage_key)

    if isinstance(value, int):
        if value < 0:
            raise _invalid_usage_value(usage_key)
        return int(value)

    if type(value) is float:
        if not math.isfinite(value) or value < 0:
            raise _invalid_usage_value(usage_key)
        return value

    raise _invalid_usage_value(usage_key)


def usage_value_as_decimal(value: UsageValue) -> Decimal:
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(value))


def add_usage_values(left: UsageValue, right: UsageValue) -> UsageValue:
    return sum_usage_values((left, right))


def sum_usage_values(values: Iterable[UsageValue]) -> UsageValue:
    values = tuple(values)
    if all(isinstance(value, int) for value in values):
        return sum(values)

    decimal_values = tuple(usage_value_as_decimal(value) for value in values)
    with localcontext(_usage_context(decimal_values)):
        total = sum(decimal_values, start=Decimal(0))

    return _decimal_result_as_float(total)


def subtract_usage_values(minuend: UsageValue, subtrahends: Iterable[UsageValue]) -> UsageValue:
    subtrahends = tuple(subtrahends)
    if isinstance(minuend, int) and all(isinstance(value, int) for value in subtrahends):
        return minuend - sum(subtrahends)

    decimal_values = tuple(usage_value_as_decimal(value) for value in (minuend, *subtrahends))
    with localcontext(_usage_context(decimal_values)):
        result = decimal_values[0] - sum(decimal_values[1:], start=Decimal(0))

    return _decimal_result_as_float(result)


def _usage_context(values: tuple[Decimal, ...]) -> Context:
    exponents = tuple(int(value.as_tuple().exponent) for value in values)
    max_adjusted = max(value.adjusted() for value in values)
    precision = max_adjusted - min(exponents) + 1 + len(str(len(values)))
    return Context(prec=max(precision, 1), Emax=MAX_EMAX, Emin=MIN_EMIN)


def _decimal_result_as_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Usage arithmetic produced a non-finite float')
    return result


def _invalid_usage_value(usage_key: str) -> ValueError:
    return ValueError(f'Invalid usage value for {usage_key}: expected a finite non-negative int or float')
