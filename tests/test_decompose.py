from __future__ import annotations

from decimal import localcontext
from types import SimpleNamespace

import pytest

from genai_prices import Usage
from genai_prices.decompose import compute_leaf_values, is_descendant_or_self
from genai_prices.units import UnitRegistry

from .unit_registry_helpers import load_units


def test_decomposition_descendant_helper_accepts_self() -> None:
    registry = UnitRegistry(load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['cache_read_tokens'])
    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_siblings() -> None:
    registry = UnitRegistry(load_units())

    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])


def test_decomposition_descendant_helper_rejects_cross_family_units() -> None:
    registry = UnitRegistry(load_units())

    assert not is_descendant_or_self(registry.units['requests'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_incompatible_units() -> None:
    registry = UnitRegistry(load_units())

    assert not is_descendant_or_self(registry.units['input_tokens'], registry.units['output_tokens'])


def test_compute_leaf_values_handles_parent_child_decomposition() -> None:
    registry = UnitRegistry(load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens'},
        Usage(input_tokens=1_000, cache_read_tokens=250),
        registry.units,
    ) == {'cache_read_tokens': 250, 'input_tokens': 750}


def test_compute_leaf_values_handles_cached_audio_overlap() -> None:
    registry = UnitRegistry(load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        ),
        registry.units,
    ) == {
        'cache_audio_read_tokens': 100,
        'cache_read_tokens': 300,
        'input_audio_tokens': 200,
        'input_tokens': 400,
    }


def test_compute_leaf_values_handles_fractional_overlap() -> None:
    registry = UnitRegistry(load_units())

    leaf_values = compute_leaf_values(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        Usage(
            input_tokens=0.7,
            cache_read_tokens=0.3,
            input_audio_tokens=0.2,
            cache_audio_read_tokens=0.1,
        ),
        registry.units,
    )

    assert leaf_values == {
        'cache_audio_read_tokens': 0.1,
        'cache_read_tokens': 0.2,
        'input_audio_tokens': 0.1,
        'input_tokens': 0.3,
    }
    assert all(type(value) is float for value in leaf_values.values())


def test_compute_leaf_values_handles_exact_fractional_remainder() -> None:
    registry = UnitRegistry(load_units())

    leaf_values = compute_leaf_values(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'},
        Usage(input_tokens=0.3, cache_read_tokens=0.1, input_audio_tokens=0.2),
        registry.units,
    )

    assert leaf_values['input_tokens'] == 0.0
    assert type(leaf_values['input_tokens']) is float


def test_compute_leaf_values_handles_mixed_integer_and_fractional_values() -> None:
    registry = UnitRegistry(load_units())

    leaf_values = compute_leaf_values(
        {'input_tokens', 'cache_read_tokens'},
        Usage(input_tokens=1, cache_read_tokens=0.25),
        registry.units,
    )

    assert leaf_values == {'cache_read_tokens': 0.25, 'input_tokens': 0.75}
    assert type(leaf_values['input_tokens']) is float


def test_compute_leaf_values_ignores_ambient_decimal_context() -> None:
    registry = UnitRegistry(load_units())

    with localcontext() as context:
        context.prec = 1
        leaf_values = compute_leaf_values(
            {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'},
            Usage(input_tokens=0.31, cache_read_tokens=0.15, input_audio_tokens=0.16),
            registry.units,
        )

    assert leaf_values['input_tokens'] == 0.0


def test_compute_leaf_values_handles_conditional_dimension_chain() -> None:
    registry = UnitRegistry(load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_write_tokens', 'cache_write_1h_tokens'},
        Usage(input_tokens=400, cache_write_tokens=300, cache_write_1h_tokens=100),
        registry.units,
    ) == {
        'cache_write_1h_tokens': 100,
        'cache_write_tokens': 200,
        'input_tokens': 100,
    }


def test_compute_leaf_values_handles_output_audio_decomposition() -> None:
    registry = UnitRegistry(load_units())

    assert compute_leaf_values(
        {'output_tokens', 'output_audio_tokens'},
        Usage(output_tokens=700, output_audio_tokens=200),
        registry.units,
    ) == {'output_audio_tokens': 200, 'output_tokens': 500}


def test_compute_leaf_values_handles_deeper_non_boolean_chain() -> None:
    registry = UnitRegistry(
        {
            'tokens': {
                'per': 1,
                'dimensions': {'family': 'tokens'},
            },
            'input_tokens': {
                'per': 1,
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'cache_read_tokens': {
                'per': 1,
                'dimensions': {'family': 'tokens', 'direction': 'input', 'cache': 'read'},
            },
        }
    )

    assert compute_leaf_values(
        set(registry.units),
        SimpleNamespace(tokens=100, input_tokens=60, cache_read_tokens=20),
        registry.units,
    ) == {'cache_read_tokens': 20, 'input_tokens': 40, 'tokens': 40}


def test_compute_leaf_values_ignores_unpriced_reported_descendants() -> None:
    registry = UnitRegistry(load_units())

    assert compute_leaf_values(
        {'input_tokens'},
        Usage(input_tokens=100, cache_read_tokens=80),
        registry.units,
    ) == {'input_tokens': 100}


def test_compute_leaf_values_rejects_negative_leaf_values() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='cache_read_tokens .* cannot exceed input_tokens'):
        compute_leaf_values(
            {'input_tokens', 'cache_read_tokens'},
            Usage(input_tokens=100, cache_read_tokens=200),
            registry.units,
        )


def test_compute_leaf_values_rejects_materially_negative_fractional_leaf_values() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match=r'cache_read_tokens \(0\.2\) cannot exceed input_tokens \(0\.1\)'):
        compute_leaf_values(
            {'input_tokens', 'cache_read_tokens'},
            Usage(input_tokens=0.1, cache_read_tokens=0.2),
            registry.units,
        )


def test_compute_leaf_values_reports_overlapping_contradictions_in_usage_terms() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(
        ValueError,
        match=('more-specific usage for cache_read_tokens, input_audio_tokens totals 160, which exceeds input_tokens'),
    ):
        compute_leaf_values(
            {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
            Usage(input_tokens=100, cache_read_tokens=80, input_audio_tokens=80, cache_audio_read_tokens=0),
            registry.units,
        )
