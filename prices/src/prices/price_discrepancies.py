from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from prices.source_prices import load_source_prices
from prices.types import ModelPrice, TieredPrices
from prices.update import ProviderYaml, get_providers_yaml


def update_price_discrepancies(check_threshold: date | None = None):
    """Find price discrepancies between providers and source prices, and write them to providers."""
    prices = load_source_prices()
    providers_yml = get_providers_yaml()
    if check_threshold is None:
        check_threshold = date.today() - timedelta(days=30)

    print(f'Checking price discrepancies since {check_threshold}')
    found = False

    for provider_yml in providers_yml.values():
        discs = 0
        missing: dict[str, Any] = {}
        provider_id = provider_yml.provider.id
        for source, source_prices in prices.items():
            if provider_prices := source_prices.get(provider_id):
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

        for model_id, entries in missing.items():
            if provider_id == 'openai' and ('batch' in model_id or model_id.startswith(('gpt-oss-', 'openai/'))):
                continue

            if provider_id == 'google' and (
                'gecko' in model_id
                or 'bison' in model_id
                or 'multimodalembedding' in model_id
                or model_id in ['gemini-flash-experimental', 'gemini-pro-experimental', 'gemini-pro-vision']
                or model_id.startswith(
                    (
                        'gemma-2-',
                        'gemini/',
                        'vertex_ai/',
                        'gemini-1.0-',
                        'gemini-2.0-pro',
                        'text-embedding-',
                        'text-multilingual-embedding-',
                        'text-unicorn',
                    )
                )
            ):
                continue

            [entry] = entries
            print('Unrecognized model:', model_id)
            print('Sources:', ', '.join(entry['sources']))
            discs += handle_missing_model(entry['price'], model_id, provider_yml)

        if discs:
            if not found:
                found = True
                print('price discrepancies:')
            print(f'{provider_yml.provider.name:>20}: {discs}')
            provider_yml.save()

    if not found:
        print('no price discrepancies found')


def handle_missing_model(price: ModelPrice, model_id: str, provider_yml: ProviderYaml):
    matching_by_price = [
        m
        for m in provider_yml.provider.models
        if isinstance(m.prices, ModelPrice)
        and (not prices_conflict(m.prices, price) or not prices_conflict(price, m.prices))
    ]
    new_price = price.model_dump(exclude_none=True, mode='json')
    print('Price:', new_price)
    for i, model in enumerate(matching_by_price):
        print('  Possible match:', i, model.id)
        if model.prices == price:
            print('    Exact price match')
        else:
            old_price = model.prices.model_dump(exclude_none=True, mode='json')  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
            print('    Old price:', old_price)  # pyright: ignore[reportUnknownArgumentType]
            print('    Differences:', new_price.items() ^ old_price.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
    print()

    action = input('Action? ')
    if action == 'n':
        provider_yml.add_price(model_id, price)
        return True

    if action.isnumeric():
        index = int(action)
        model = matching_by_price[index]
        provider_yml.add_id_to_model(model.id, model_id)
        return True

    return False


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

    if current_price.is_free() != source_price.is_free():
        return True

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
