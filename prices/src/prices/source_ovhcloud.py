from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

MODELS_URL = 'https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models'
MIN_MODEL_COUNT = 8


def get_model_infos(models: list[dict[str, Any]]):
    """Extract model information from OVHcloud AI Endpoints API response."""
    for model in models:
        model_id = model['id']
        pricing = model.get('pricing')

        if not pricing:
            continue

        # Extract pricing information (convert from per-token to per-million-tokens)
        prompt_price = pricing.get('prompt')
        completion_price = pricing.get('completion')

        # Convert to per-million-token pricing as Decimal
        input_mtok = Decimal(prompt_price) * 1_000_000 if prompt_price and float(prompt_price) > 0 else None
        output_mtok = (
            Decimal(completion_price) * 1_000_000 if completion_price and float(completion_price) > 0 else None
        )

        # Skip if no valid pricing
        if input_mtok is None and output_mtok is None:
            continue

        # Create match clauses, avoiding duplicates
        match_clauses = [ClauseEquals(equals=model_id)]
        if model_id.lower() != model_id:
            match_clauses.append(ClauseEquals(equals=model_id.lower()))

        yield ModelInfo(
            id=model_id,
            name=model_id,
            prices=ModelPrice(
                input_mtok=input_mtok,
                output_mtok=output_mtok,
            ),
            match=ClauseOr(
                or_=match_clauses  # pyright: ignore[reportCallIssue]
            )
            if len(match_clauses) > 1
            else match_clauses[0],
            context_window=model.get('context_length'),
            prices_checked=date.today(),
        )


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(MODELS_URL, timeout=30.0)
    response.raise_for_status()
    models = list(get_model_infos(response.json()['data']))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/ovhcloud.yml')
    added, updated = provider_yaml.upsert_models(models, source='OVHcloud AI Endpoints', min_count=MIN_MODEL_COUNT)
    print(f'OVHcloud prices updated: {added} added, {updated} updated')


def get_ovhcloud_prices():  # pragma: no cover - thin CLI alias for main
    """Download and update OVHcloud AI Endpoints provider prices."""
    main()


if __name__ == '__main__':
    main()
