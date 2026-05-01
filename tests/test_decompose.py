from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import ruamel.yaml

from genai_prices import Usage
from genai_prices.decompose import compute_leaf_values, is_descendant_or_self
from genai_prices.units import UnitRegistry


def _load_units() -> dict[str, Any]:
    yaml = ruamel.yaml.YAML(typ='safe')
    with Path('prices/units.yml').open() as f:
        return cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]


def test_decomposition_descendant_helper_accepts_self() -> None:
    registry = UnitRegistry(_load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_accepts_parent_child_pairs() -> None:
    registry = UnitRegistry(_load_units())

    assert is_descendant_or_self(registry.units['input_tokens'], registry.units['cache_read_tokens'])
    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_siblings() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])


def test_decomposition_descendant_helper_rejects_cross_family_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['requests'], registry.units['input_tokens'])


def test_decomposition_descendant_helper_rejects_incompatible_units() -> None:
    registry = UnitRegistry(_load_units())

    assert not is_descendant_or_self(registry.units['input_tokens'], registry.units['output_tokens'])


def test_compute_leaf_values_handles_parent_child_decomposition() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens'},
        Usage(input_tokens=1_000, cache_read_tokens=250),
        registry.families['tokens'],
    ) == {'cache_read_tokens': 250, 'input_tokens': 750}


def test_compute_leaf_values_handles_cached_audio_overlap() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        ),
        registry.families['tokens'],
    ) == {
        'cache_audio_read_tokens': 100,
        'cache_read_tokens': 300,
        'input_audio_tokens': 200,
        'input_tokens': 400,
    }


def test_compute_leaf_values_handles_output_audio_decomposition() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'output_tokens', 'output_audio_tokens'},
        Usage(output_tokens=700, output_audio_tokens=200),
        registry.families['tokens'],
    ) == {'output_audio_tokens': 200, 'output_tokens': 500}


def test_compute_leaf_values_ignores_unpriced_reported_descendants() -> None:
    registry = UnitRegistry(_load_units())

    assert compute_leaf_values(
        {'input_tokens'},
        Usage(input_tokens=100, cache_read_tokens=80),
        registry.families['tokens'],
    ) == {'input_tokens': 100}


def test_compute_leaf_values_rejects_negative_leaf_values() -> None:
    registry = UnitRegistry(_load_units())

    with pytest.raises(ValueError, match='Impossible usage data for input_tokens'):
        compute_leaf_values(
            {'input_tokens', 'cache_read_tokens'},
            Usage(input_tokens=100, cache_read_tokens=200),
            registry.families['tokens'],
        )
