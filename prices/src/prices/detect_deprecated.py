from __future__ import annotations

from datetime import date, timedelta

from prices.source_prices import load_source_prices
from prices.update import get_providers_yaml


def detect_deprecated() -> None:
    """Detect models that may be deprecated or removed based on external source data."""
    source_prices = load_source_prices()
    providers_yml = get_providers_yaml()
    staleness_threshold = date.today() - timedelta(days=90)

    candidates: list[tuple[str, str, str]] = []

    for provider_yml in providers_yml.values():
        provider_id = provider_yml.provider.id
        for model in provider_yml.provider.models:
            if model.deprecated or model.removed:
                continue

            if model.prices_checked and model.prices_checked >= staleness_threshold:
                continue

            found_in_source = False
            for source_data in source_prices.values():
                provider_prices = source_data.get(provider_id, {})
                for source_model_id in provider_prices:
                    if model.is_match(source_model_id):
                        found_in_source = True
                        break
                if found_in_source:
                    break

            if not found_in_source:
                checked_str = str(model.prices_checked) if model.prices_checked else 'never'
                candidates.append((provider_id, model.id, checked_str))

    if candidates:
        print(f'Found {len(candidates)} candidate(s) for deprecation/removal:\n')
        for provider_id, model_id, checked in candidates:
            print(f'  {provider_id}: {model_id} (last checked: {checked})')
    else:
        print('No deprecation/removal candidates found.')
