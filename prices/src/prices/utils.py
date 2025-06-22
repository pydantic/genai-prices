from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TypeVar

package_dir = Path(__file__).parent.parent.parent


def pretty_size(size: int) -> str:
    if size < 1024:
        return f'{size} bytes'
    elif size < 1024 * 1024:
        return f'{size / 1024:.2f} KB'
    else:
        return f'{size / (1024 * 1024):.2f} MB'


def mtok(v: Decimal | None) -> Decimal | None:
    """Convert a token price to mtok."""
    if v is None:
        return None
    else:
        return v * 1_000_000


T = TypeVar('T')


def check_unique(items: list[T]) -> list[T]:
    unique: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        s = str(item)
        if s in unique:
            duplicates.append(s)
        unique.add(s)

    if duplicates:
        raise ValueError(f'Duplicates found: {", ".join(duplicates)}')
    return items
