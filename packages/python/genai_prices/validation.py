from __future__ import annotations

from collections.abc import Mapping

from genai_prices.units import UnitFamily, UnitRegistry

__all__ = 'validate_ancestor_coverage', 'validate_price_keys'


def validate_price_keys(price_keys: set[str], price_key_index: Mapping[str, str]) -> None:
    unknown_price_keys = price_keys - price_key_index.keys()
    if unknown_price_keys:
        bad_keys = ', '.join(sorted(unknown_price_keys))
        raise ValueError(f'Unknown price key: {bad_keys}')


def validate_ancestor_coverage(priced_usage_keys: set[str], family: UnitFamily, registry: UnitRegistry) -> None:
    family_priced_usage_keys = priced_usage_keys & family.units.keys()
    for usage_key in sorted(family_priced_usage_keys):
        missing_ancestors = registry.ancestor_usage_keys(usage_key) - family_priced_usage_keys
        if missing_ancestors:
            bad_keys = ', '.join(sorted(missing_ancestors))
            raise ValueError(f'Missing ancestor price for {usage_key}: {bad_keys}')
