from __future__ import annotations

import pytest

from genai_prices import data, data_units
from genai_prices.types import ConditionalPrice, _collect_effective_model_price_keys
from genai_prices.units import UnitRegistry
from genai_prices.validation import (
    validate_ancestor_coverage,
    validate_extractor_destinations,
    validate_join_coverage,
    validate_model_price,
    validate_price_keys,
)

from .unit_registry_helpers import load_units


def _missing_write_audio_join_registry() -> UnitRegistry:
    return UnitRegistry(
        {
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                    'cache_write_tokens': {
                        'price_key': 'cache_write_mtok',
                        'dimensions': {'direction': 'input', 'cache': 'write'},
                    },
                    'input_audio_tokens': {
                        'price_key': 'input_audio_mtok',
                        'dimensions': {'direction': 'input', 'modality': 'audio'},
                    },
                },
            },
        }
    )


def test_validate_price_keys_accepts_current_price_keys() -> None:
    registry = UnitRegistry(load_units())

    validate_price_keys({'input_mtok', 'output_mtok', 'requests_kcount'}, registry)


def test_validate_price_keys_rejects_unknown_price_key() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Unknown price key: inptu_mtok'):
        validate_price_keys({'input_mtok', 'inptu_mtok'}, registry)


def test_validate_ancestor_coverage_accepts_parent_child_pricing() -> None:
    registry = UnitRegistry(load_units())

    validate_ancestor_coverage(
        {'input_tokens', 'cache_read_tokens'},
        registry.families['tokens'],
        registry,
    )


def test_validate_ancestor_coverage_rejects_missing_ancestor_price() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Missing ancestor price for cache_read_tokens: input_tokens'):
        validate_ancestor_coverage(
            {'cache_read_tokens'},
            registry.families['tokens'],
            registry,
        )


def test_validate_join_coverage_rejects_missing_join_price() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(
        ValueError,
        match='Missing join price for cache_read_tokens and input_audio_tokens: cache_audio_read_tokens',
    ):
        validate_join_coverage(
            {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'},
            registry.families['tokens'],
        )


def test_validate_join_coverage_rejects_missing_registered_join_unit() -> None:
    registry = _missing_write_audio_join_registry()

    with pytest.raises(
        ValueError,
        match='Missing registered join unit for priced units cache_write_tokens and input_audio_tokens',
    ):
        validate_join_coverage(
            {'input_tokens', 'cache_write_tokens', 'input_audio_tokens'},
            registry.families['tokens'],
        )


def test_validate_join_coverage_accepts_priced_join() -> None:
    registry = UnitRegistry(load_units())

    validate_join_coverage(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens', 'cache_audio_read_tokens'},
        registry.families['tokens'],
    )


def test_validate_model_price_accepts_valid_current_price_sets() -> None:
    registry = UnitRegistry(load_units())

    validate_model_price({'input_mtok', 'cache_read_mtok', 'requests_kcount'}, registry)


def test_validate_model_price_rejects_unknown_price_keys() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Unknown price key: inptu_mtok'):
        validate_model_price({'input_mtok', 'inptu_mtok'}, registry)


def test_validate_model_price_rejects_missing_ancestor_prices() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Missing ancestor price for cache_read_tokens: input_tokens'):
        validate_model_price({'cache_read_mtok'}, registry)


def test_validate_model_price_rejects_required_join_prices() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(
        ValueError,
        match='Missing join price for cache_read_tokens and input_audio_tokens: cache_audio_read_tokens',
    ):
        validate_model_price({'input_mtok', 'cache_read_mtok', 'input_audio_mtok'}, registry)


def test_validate_model_price_rejects_missing_join_units() -> None:
    registry = _missing_write_audio_join_registry()

    with pytest.raises(
        ValueError,
        match='Missing registered join unit for priced units cache_write_tokens and input_audio_tokens',
    ):
        validate_model_price({'input_mtok', 'cache_write_mtok', 'input_audio_mtok'}, registry)


def test_bundled_provider_model_prices_pass_registry_validation() -> None:
    registry = UnitRegistry(data_units.unit_families_data)
    failures: list[str] = []

    for provider in data.providers:
        for model in provider.models:
            prices = model.prices if isinstance(model.prices, list) else [model.prices]
            for index, maybe_conditional_price in enumerate(prices):
                price = (
                    maybe_conditional_price.prices
                    if isinstance(maybe_conditional_price, ConditionalPrice)
                    else maybe_conditional_price
                )
                price_keys = _collect_effective_model_price_keys(price, registry)
                try:
                    validate_model_price(price_keys, registry)
                except ValueError as exc:
                    failures.append(f'{provider.id}/{model.id}[{index}]: {exc}')

    assert failures == []


def test_validate_extractor_destinations_accepts_current_reported_usage_keys() -> None:
    registry = UnitRegistry(load_units())

    validate_extractor_destinations(
        {'input_tokens', 'cache_read_tokens', 'cache_audio_read_tokens'},
        registry.reported_usage_keys(),
    )


def test_validate_extractor_destinations_rejects_price_keys() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: input_mtok'):
        validate_extractor_destinations({'input_mtok'}, registry.reported_usage_keys())


def test_validate_extractor_destinations_rejects_unknown_strings() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: imaginary_tokens'):
        validate_extractor_destinations({'imaginary_tokens'}, registry.reported_usage_keys())


def test_validate_extractor_destinations_rejects_pricing_only_requests() -> None:
    registry = UnitRegistry(load_units())

    with pytest.raises(ValueError, match='Invalid extractor destination: requests'):
        validate_extractor_destinations({'requests'}, registry.reported_usage_keys())
