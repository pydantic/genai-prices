from .source_prices import load_source_prices
from .types import ModelPrice
from .update import get_providers_yaml


def update_price_discrepancies():
    """Find price discrepancies between providers and source prices, and write them to providers."""
    prices = load_source_prices()
    providers_yml = get_providers_yaml()

    for provider_yml in providers_yml.values():
        discs = 0
        for source, source_prices in prices.items():
            if provider_prices := source_prices.get(provider_yml.provider.id):
                for model_id, price in provider_prices.items():
                    if model := provider_yml.provider.find_model(model_id):
                        if not model.prices_checked:
                            assert isinstance(model.prices, ModelPrice)
                            if prices_conflict(model.prices, price):
                                provider_yml.set_price_discrepency(model.id, source, price)
                                discs += 1

        if discs:
            print(f'{provider_yml.provider.name:>20}: {discs} price discrepancies')
            provider_yml.save()


def list_price_discrepancies():
    """List price discrepancies between providers and source prices."""
    providers_yml = get_providers_yaml()

    for provider_yml in providers_yml.values():
        discs = sum(int(bool(model.price_discrepancies)) for model in provider_yml.provider.models)
        if discs:
            print(f'{provider_yml.provider.name:>20}: {discs} price discrepancies')


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
