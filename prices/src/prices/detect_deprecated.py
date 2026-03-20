from __future__ import annotations

from datetime import date, timedelta

from prices.source_prices import load_source_prices
from prices.update import get_providers_yaml


def detect_deprecated() -> None:
    """Detect models that may be deprecated or removed based on external source data."""
    source_prices = load_source_prices()
    providers_yml = get_providers_yaml()
    staleness_threshold = date.today() - timedelta(days=90)

    # Build a mapping of provider_id -> set of all model IDs present in any source.
    source_model_ids: dict[str, set[str]] = {}
    for source_data in source_prices.values():
        for provider_id, models in source_data.items():
            source_model_ids.setdefault(provider_id, set()).update(models.keys())

    candidates: list[tuple[str, str, str]] = []

    for provider_yml in providers_yml.values():
        provider_id = provider_yml.provider.id
        known_source_ids = source_model_ids.get(provider_id)
        if not known_source_ids:
            continue

        for model in provider_yml.provider.models:
            if model.deprecated or model.removed:
                continue

            # Only flag models that have been checked before but are now stale
            # and absent from sources. Models never checked are not actionable.
            if not model.prices_checked:
                continue

            if model.prices_checked >= staleness_threshold:
                continue

            found_in_source = any(model.is_match(sid) for sid in known_source_ids)

            if not found_in_source:
                candidates.append((provider_id, model.id, str(model.prices_checked)))

    if candidates:
        print(f'Found {len(candidates)} candidate(s) for deprecation/removal:\n')
        for provider_id, model_id, checked in candidates:
            print(f'  {provider_id}: {model_id} (last checked: {checked})')
    else:
        print('No deprecation/removal candidates found.')

    uncovered = set(providers_yml.keys()) - set(source_model_ids.keys())
    if uncovered:
        print(f'\nNote: {len(uncovered)} provider(s) have no external source coverage and were skipped:')
        print(f'  {", ".join(sorted(uncovered))}')
