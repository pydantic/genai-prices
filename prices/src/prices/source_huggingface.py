from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx2
from pydantic import HttpUrl

from prices.prices_types import ClauseAnd, ClauseContains, ClauseEquals, ClauseOr, ModelInfo, ModelPrice, Provider
from prices.update import ProviderYaml, ProviderYamlDict, get_provider_yaml_string
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
            path.write_text(new_provider_yaml(provider, providers_dir))
        added, updated = ProviderYaml(path).upsert_models(infos, source=f'HuggingFace ({provider})', min_count=1)
        print(f'HuggingFace ({provider}) prices updated: {added} added, {updated} updated')


def new_provider_yaml(provider: str, providers_dir: Path) -> str:
    openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
    assert openai_extractors
    [chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']
    provider_info = Provider(
        id=f'huggingface_{provider}',
        name=f'HuggingFace ({provider})',
        api_pattern=rf'https://router\.huggingface\.co/{provider}',
        models=[],
        pricing_urls=[HttpUrl(MODELS_URL), HttpUrl('https://huggingface.co/inference/models')],
        # Only the chat completions API is served, so it is also the `default` flavor (#324).
        extractors=[chat_extractor.model_copy(update={'api_flavor': 'default'}), chat_extractor],
        provider_match=ClauseAnd(
            and_=[  # pyright: ignore[reportCallIssue]
                ClauseContains(contains='huggingface'),
                ClauseContains(contains=provider),
            ],
        ),
    )
    yaml_data = cast(
        ProviderYamlDict, provider_info.model_dump(mode='json', exclude_none=True, by_alias=True, warnings=False)
    )
    return '# yaml-language-server: $schema=.schema.json\n' + get_provider_yaml_string(yaml_data)


def get_huggingface_prices():  # pragma: no cover - thin CLI alias for main
    """Download and update HuggingFace provider prices."""
    main()


if __name__ == '__main__':
    main()
