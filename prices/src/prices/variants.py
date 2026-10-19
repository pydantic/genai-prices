from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .prices_types import ModelPrice, PriceVariant, Tier, TieredPrices

PriceValue = Decimal | TieredPrices


def follow_standard_change(
    variants: list[PriceVariant], old: ModelPrice, new: ModelPrice
) -> list[tuple[dict[str, str], ModelPrice | None]]:
    """For each request context, the rates its current variant implies after a standard rate change.

    A variant whose every rate is the same share of the old standard rate (a 50% batch discount, a 2x priority
    surcharge) gets that share of the new standard rates, rounded the way the provider rounded the old ones.
    One with no single share comes back as `None`, since its new rates can't be derived. Contexts whose rates
    don't change are left out.
    """
    followed: list[tuple[dict[str, str], ModelPrice | None]] = []
    seen: list[dict[str, str]] = []
    old_rates, new_rates = dict(old), dict(new)
    for variant in variants:
        # Variants resolve first to last, so the first one for a context is the one in effect.
        if variant.when in seen:
            continue
        seen.append(variant.when)
        rates: dict[str, PriceValue] = {key: value for key, value in variant.prices if value is not None}
        if not rates:
            # Lists no rates of its own, so it already inherits every standard rate.
            continue
        pairs = [pair for key, rate in rates.items() for pair in rate_pairs(rate, old_rates.get(key))]
        share = common_share(pairs)
        # A share only exists when every listed key has an old standard rate, so the shapes can be compared.
        if share is None or any(
            shape(new_rates[key]) != shape(old_rates[key]) for key in rates if new_rates.get(key) is not None
        ):
            followed.append((variant.when, None))
            continue
        derived = ModelPrice.model_validate(
            {
                key: scale(new_rates[key], share, like=rate, old=old_rates[key])
                for key, rate in rates.items()
                if new_rates.get(key) is not None
            }
        )
        if derived != variant.prices:
            followed.append((variant.when, derived))
    return followed


def shape(value: PriceValue) -> list[int]:
    """The tier starts of a rate (`[]` when flat), so a rate that gains, loses or moves a tier can't be scaled."""
    return [tier.start for tier in value.tiers] if isinstance(value, TieredPrices) else []


def rate_pairs(rate: PriceValue, standard: PriceValue | None) -> list[tuple[Decimal, Decimal | None]]:
    """Each variant rate next to the standard rate it discounts, or `None` where the two don't line up."""
    if isinstance(rate, Decimal):
        return [(rate, standard if isinstance(standard, Decimal) else None)]
    if not isinstance(standard, TieredPrices) or [t.start for t in rate.tiers] != [t.start for t in standard.tiers]:
        return [(rate.base, None)]
    return [(rate.base, standard.base), *((t.price, s.price) for t, s in zip(rate.tiers, standard.tiers))]


def common_share(pairs: list[tuple[Decimal, Decimal | None]]) -> Decimal | None:
    """The one share of the standard rate every variant rate is, allowing for each rate's published rounding."""
    if any(not standard for _, standard in pairs):
        return None
    # The largest rate carries the most precision, so it fixes the share the smaller, rounded ones are checked against.
    rate, standard = max(pairs, key=lambda pair: pair[1] or 0)
    assert standard
    share = rate / standard
    if all(rounded_like(standard * share, rate) == rate for rate, standard in pairs if standard):
        return share
    return None


def scale(value: PriceValue, share: Decimal, *, like: PriceValue, old: PriceValue) -> PriceValue:
    if isinstance(value, Decimal):
        assert isinstance(like, Decimal) and isinstance(old, Decimal)
        return scaled(value, share, like, old)
    assert isinstance(like, TieredPrices) and isinstance(old, TieredPrices)
    return TieredPrices(
        base=scaled(value.base, share, like.base, old.base),
        tiers=[
            Tier(start=tier.start, price=scaled(tier.price, share, like_tier.price, old_tier.price))
            for tier, like_tier, old_tier in zip(value.tiers, like.tiers, old.tiers)
        ],
    )


def scaled(value: Decimal, share: Decimal, like: Decimal, old: Decimal) -> Decimal:
    exact = value * share
    # Round only where the provider rounded the rate it replaces, e.g. $0.125 published as $0.13.
    return (rounded_like(exact, like) if old * share != like else exact).normalize()


def rounded_like(value: Decimal, like: Decimal) -> Decimal:
    exponent = like.normalize().as_tuple().exponent
    assert isinstance(exponent, int)
    # Providers publish to the cent or finer, so `20` still means $20.00, not "to the nearest ten".
    return value.quantize(Decimal(1).scaleb(min(exponent, -2)), rounding=ROUND_HALF_UP)
