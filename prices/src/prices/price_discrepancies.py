from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from prices.source_prices import load_source_prices
from prices.types import ModelPrice, TieredPrices
from prices.update import get_providers_yaml


def update_price_discrepancies(check_threshold: date | None = None):
    """Find price discrepancies between providers and source prices, and write them to providers."""
    prices = load_source_prices()
    providers_yml = get_providers_yaml()
    if check_threshold is None:
        check_threshold = date.today() - timedelta(days=30)

    print(f'Checking price discrepancies since {check_threshold}')
    found = False

    for provider_yml in providers_yml.values():
        if provider_yml.provider.id != 'openai':
            continue
        print(f'Checking {provider_yml.provider.name}...')
        print('------------\n\n')
        discs = 0
        missing: dict[str, Any] = {}
        for source, source_prices in prices.items():
            if provider_prices := source_prices.get(provider_yml.provider.id):
                for model_id, price in provider_prices.items():
                    if model := provider_yml.provider.find_model(model_id):
                        if not model.prices_checked or model.prices_checked < check_threshold:
                            if not isinstance(model.prices, ModelPrice):
                                continue  # TODO
                            if prices_conflict(model.prices, price):
                                # TODO the current workflow is not sustainable as these discrepancies
                                #   will 'reappear' every 30 days.
                                #   Commenting this out for now while I use this code for *missing* models.
                                continue
                                # provider_yml.set_price_discrepency(model.id, source, price)
                                # discs += 1
                    else:
                        new = missing.setdefault(model_id, [])
                        for other in new:
                            if not prices_conflict(price, other['price']) or not prices_conflict(other['price'], price):
                                other['sources'].append(source)
                                break
                        else:
                            new.append(dict(price=price, sources=[source]))
        # for model_id, entries in missing.items():
        #     # if provider_yml.provider.id == 'openai' and len(entries) == 1 and entries[0]['sources'] == ['openrouter']:
        #     if 'batch' in model_id or model_id.startswith(('gpt-oss-',)):
        #         continue
        #     if len(entries) == 1:
        #         [entry] = entries
        #         if len(entry['sources']) > 1:
        #             provider_yml.add_price(model_id, entry['price'])
        #             continue
        #     print(model_id)
        #     for entry in entries:
        #         sources = ', '.join(entry['sources'])
        #         if len(entry['sources']) > 1:
        #             print(model_id)
        #             print(f'  missing from {sources}: {entry["price"]}')
        #     # print('------------\n')
        #     # break
        provider_yml.save()

        break

        if discs:
            if not found:
                found = True
                print('price discrepancies:')
            print(f'{provider_yml.provider.name:>20}: {discs}')
            provider_yml.save()

    if not found:
        print('no price discrepancies found')


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

    for field, value in source_price.model_dump(exclude_none=True).items():
        if current_value := getattr(current_price, field):
            if isinstance(current_value, TieredPrices) and current_value.base == value:
                continue
            if current_value != value:
                return True
        else:
            return True
    return False


if __name__ == '__main__':
    update_price_discrepancies()
