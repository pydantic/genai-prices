from __future__ import annotations

from datetime import date, timedelta

from .source_prices import load_source_prices
from .types import ModelPrice
from .update import get_providers_yaml


def update_price_discrepancies(check_threshold: date | None = None):
    """Find price discrepancies between providers and source prices, and write them to providers."""
    prices = load_source_prices()
    providers_yml = get_providers_yaml()
    if check_threshold is None:
        check_threshold = date.today() - timedelta(days=0)

    print(f'Checking price discrepancies since {check_threshold}')

    for provider_yml in providers_yml.values():
        discs = 0
        ai_updates = 0
        for source, source_prices in prices.items():
            if provider_prices := source_prices.get(provider_yml.provider.id):
                for model_id, price in provider_prices.items():
                    if model := provider_yml.provider.find_model(model_id):
                        if not model.prices_checked or model.prices_checked < check_threshold:
                            assert isinstance(model.prices, ModelPrice)
                            if prices_conflict(model.prices, price):
                                provider_yml.set_price_discrepency(model.id, source, price)
                                discs += 1
                            else:
                                provider_yml.set_model_field(model.id, 'prices_checked_ai', date.today())
                                ai_updates += 1

        if discs or ai_updates:
            if discs:
                print(f'{provider_yml.provider.name:>20}: {discs} discrepancies')
            if ai_updates:
                print(f'{provider_yml.provider.name:>20}: {ai_updates} AI updates')
            provider_yml.save()


def check_for_price_discrepancies() -> int:
    """List price discrepancies between providers and source prices.

    Returns:
        The number of price discrepancies found.
    """
    providers_yml = get_providers_yaml()

    found = 0
    for provider_yml in providers_yml.values():
        discs = sum(int(bool(model.price_discrepancies)) for model in provider_yml.provider.models)
        if discs:
            if not found:
                print('price discrepancies:')
            found += 1
            print(f'{provider_yml.provider.name:>20}: {discs}')

    if not found:
        print('no price discrepancies found')
    return found


def prices_conflict(current_price: ModelPrice, source_price: ModelPrice) -> bool:
    """Check if two prices are conflicting.

    Returns `True` if the prices conflict.

    we consider the prices to be conflicting if `current_price` is missing prices or has different prices.
    """
    if current_price == source_price:
        # prices are identical
        return False

    current_prices_dict = current_price.model_dump(exclude_none=True)
    for field, value in source_price.model_dump(exclude_none=True).items():
        if current_value := current_prices_dict.get(field):
            if current_value != value:
                return True
        else:
            return True
    return False
