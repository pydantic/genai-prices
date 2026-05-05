from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from genai_prices import data
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import Usage
from genai_prices.units import UnitRegistry


@contextmanager
def _active_registry(raw_families: dict[str, Any]) -> Iterator[UnitRegistry]:
    registry = UnitRegistry(raw_families)
    set_custom_snapshot(DataSnapshot(providers=data.providers, from_auto_update=False, unit_registry=registry))
    try:
        yield registry
    finally:
        set_custom_snapshot(None)


def test_usage_direct_construction_is_strict_for_reported_usage_keys() -> None:
    usage = Usage(input_tokens=100, output_tokens=None)

    assert usage.input_tokens == 100
    assert usage.output_tokens == 0


def test_usage_direct_construction_rejects_unknown_keywords() -> None:
    with pytest.raises(ValueError, match='Unknown usage key: imaginary_tokens'):
        Usage(imaginary_tokens=1)


def test_usage_direct_construction_rejects_pricing_only_requests() -> None:
    with pytest.raises(ValueError, match='Unknown usage key: requests'):
        Usage(requests=1)


def test_usage_assignment_preserves_regular_object_attributes() -> None:
    usage = Usage()

    usage.imaginary_tokens = 1

    assert usage.imaginary_tokens == 1
    assert 'imaginary_tokens' not in usage._values


def test_usage_assignment_updates_registered_reported_values() -> None:
    usage = Usage()

    usage.input_tokens = 100
    assert usage.input_tokens == 100
    assert usage._values['input_tokens'] == 100

    usage.input_tokens = None
    assert 'input_tokens' not in usage._values
    assert usage.input_tokens == 0


def test_usage_missing_registered_reads_return_zero() -> None:
    usage = Usage()

    assert usage.input_tokens == 0
    assert usage.cache_audio_read_tokens == 0


def test_usage_addition_operates_on_reported_values() -> None:
    assert Usage(input_tokens=10, output_tokens=10) + Usage(output_tokens=5) == Usage(
        input_tokens=10,
        output_tokens=15,
    )


def test_usage_equality_operates_on_reported_values() -> None:
    assert Usage(input_tokens=0) != Usage()
    assert Usage(input_tokens=0) == Usage(input_tokens=0)


def test_usage_repr_uses_registry_order() -> None:
    assert repr(Usage(input_tokens=10, cache_write_tokens=1, cache_read_tokens=0, output_tokens=2)) == (
        'Usage(input_tokens=10, output_tokens=2, cache_read_tokens=0, cache_write_tokens=1)'
    )


def test_usage_repr_orders_extra_registered_keys_by_registry_order() -> None:
    with _active_registry(
        {
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                    'sausage_tokens': {
                        'dimensions': {'direction': 'input', 'ingredient': 'sausage'},
                    },
                    'cheese_tokens': {
                        'dimensions': {'direction': 'input', 'ingredient': 'cheese'},
                    },
                },
            },
        }
    ):
        usage = Usage(cheese_tokens=2, input_tokens=3, sausage_tokens=1)

        assert repr(usage) == 'Usage(input_tokens=3, sausage_tokens=1, cheese_tokens=2)'


def test_usage_from_raw_reads_known_mapping_keys() -> None:
    usage = Usage.from_raw({'input_tokens': 100, 'output_tokens': 50})

    assert usage == Usage(input_tokens=100, output_tokens=50)


def test_usage_from_raw_reads_known_object_attributes() -> None:
    usage = Usage.from_raw(SimpleNamespace(input_tokens=100, output_tokens=50))

    assert usage == Usage(input_tokens=100, output_tokens=50)


def test_usage_from_raw_reads_known_dataclass_attributes() -> None:
    @dataclass
    class RawUsage:
        input_tokens: int
        output_tokens: int

    usage = Usage.from_raw(RawUsage(input_tokens=100, output_tokens=50))

    assert usage == Usage(input_tokens=100, output_tokens=50)


def test_usage_from_raw_ignores_unknown_extras() -> None:
    usage = Usage.from_raw({'input_tokens': 100, 'sausage_tokens': 50})

    assert usage == Usage(input_tokens=100)


def test_usage_from_raw_skips_explicit_none_values() -> None:
    usage = Usage.from_raw({'input_tokens': 100, 'output_tokens': None})

    assert usage == Usage(input_tokens=100)


def test_usage_from_raw_does_not_loosen_direct_construction() -> None:
    with pytest.raises(ValueError, match='Unknown usage key: sausage_tokens'):
        Usage(input_tokens=100, sausage_tokens=50)


def test_usage_missing_ancestor_read_rejects_positive_descendant() -> None:
    usage = Usage(input_audio_tokens=300)

    with pytest.raises(
        ValueError,
        match='Missing usage for input_tokens: reported descendant usage keys input_audio_tokens',
    ):
        _ = usage.input_tokens


def test_usage_returns_stored_value_without_auditing_descendants() -> None:
    usage = Usage(input_tokens=100, input_audio_tokens=300)

    assert usage.input_tokens == 100


def test_usage_safe_missing_read_returns_zero_without_reporting() -> None:
    usage = Usage(output_tokens=100)

    assert usage.input_tokens == 0
    assert usage.cache_read_tokens == 0
    assert 'input_tokens' not in usage._values
    assert 'cache_read_tokens' not in usage._values


def test_usage_missing_join_read_rejects_overlapping_ancestors() -> None:
    usage = Usage(input_audio_tokens=300, cache_read_tokens=200)

    with pytest.raises(
        ValueError,
        match=(
            'Missing usage for cache_audio_read_tokens: reported overlapping usage keys '
            'cache_read_tokens, input_audio_tokens'
        ),
    ):
        _ = usage.cache_audio_read_tokens
