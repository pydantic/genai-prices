from datetime import date
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

MODELS_URL = 'https://router.huggingface.co/v1/models'
MIN_MODEL_COUNT = 50


def get_model_infos(models: list[dict[str, Any]], provider: str):
    for model in models:
        model_id_prefix = model['owned_by'] + '/'
        model_id = model['id']
        assert model_id.startswith(model_id_prefix)
        model_name = model_id.removeprefix(model_id_prefix)
        matching_providers = [p for p in model['providers'] if p['provider'] == provider]
        if not matching_providers:
            continue
        [provider_info] = matching_providers
        pricing = provider_info.get('pricing')
        if not pricing:
            continue
        yield ModelInfo(
            id=model_id,
            name=model_name,
            prices=ModelPrice(
                input_mtok=pricing['input'] or None,
                output_mtok=pricing['output'] or None,
            ),
            match=ClauseOr(
                or_=[  # pyright: ignore[reportCallIssue]
                    ClauseEquals(equals=model_id.lower()),
                    ClauseEquals(equals=model_id.lower() + '-fast'),
                ]
            ),
            context_window=provider_info.get('context_length'),
            prices_checked=date.today(),
        )


def main(providers_dir: Path | None = None) -> None:
    providers_dir = providers_dir or package_dir / 'providers'
    response = httpx2.get(MODELS_URL, timeout=30.0)
    response.raise_for_status()
    models = response.json()['data']
    providers = sorted({p['provider'] for model in models for p in model['providers']})
    model_infos = {provider: list(get_model_infos(models, provider)) for provider in providers}
    # Each sub-provider can legitimately list very few models, so only the router as a whole is checked.
    if (total := sum(map(len, model_infos.values()))) < MIN_MODEL_COUNT:
        raise RuntimeError(
            f'HuggingFace router returned only {total} priced models; expected at least {MIN_MODEL_COUNT}'
        )

    for provider, infos in model_infos.items():
        if not infos:
            continue
        path = providers_dir / f'huggingface_{provider}.yml'
        if not path.exists():
            # A new provider file also needs the price-check allowlists, which an unattended run can't update.
            print(f'HuggingFace ({provider}) skipped: {path.name} does not exist, add it with the add-provider skill')
            continue
        added, updated = ProviderYaml(path).upsert_models(infos, source=f'HuggingFace ({provider})', min_count=1)
        print(f'HuggingFace ({provider}) prices updated: {added} added, {updated} updated')


def get_huggingface_prices():  # pragma: no cover - thin CLI alias for main
    """Download and update HuggingFace provider prices."""
    main()


if __name__ == '__main__':
    main()
