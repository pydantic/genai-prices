from __future__ import annotations

from genai_prices.units import UnitDef

__all__ = ('is_descendant_or_self',)


def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
    return ancestor.family is descendant.family and ancestor.dimensions.items() <= descendant.dimensions.items()
