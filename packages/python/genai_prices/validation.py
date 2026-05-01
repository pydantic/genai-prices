from __future__ import annotations

from collections.abc import Mapping

__all__ = ('validate_price_keys',)


def validate_price_keys(price_keys: set[str], price_key_index: Mapping[str, str]) -> None:
    unknown_price_keys = price_keys - price_key_index.keys()
    if unknown_price_keys:
        bad_keys = ', '.join(sorted(unknown_price_keys))
        raise ValueError(f'Unknown price key: {bad_keys}')
