import json
from operator import attrgetter
from pathlib import Path
from typing import Any, cast

from pydantic import HttpUrl

from prices.collapse import collapse_provider
from prices.types import ClauseEquals, ModelInfo, ModelPrice, Provider
from prices.update import ProviderYaml, ProviderYamlDict, get_provider_yaml_string


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
            match=ClauseEquals(equals=model_id),
            context_window=provider_info.get('context_length'),
        )


def main():
    # TODO
    with open('/Users/alex/Downloads/models (1).json') as f:
        models = json.load(f)['data']

    providers = {p['provider'] for model in models for p in model['providers']}
    providers_dir = Path(__file__).parent / '../../providers'

    for provider in providers:
        provider_id = f'huggingface_{provider}'
        model_infos = sorted(get_model_infos(models, provider), key=attrgetter('id'))
        if not model_infos:
            continue

        provider_info = Provider(
            id=provider_id,
            name=f'HuggingFace ({provider})',
            api_pattern=rf'https://router\.huggingface\.co/{provider}',
            models=model_infos,
            pricing_urls=[
                HttpUrl('https://router.huggingface.co/v1/models'),
                HttpUrl('https://huggingface.co/inference/models'),
            ],
        )
        yaml_data = cast(ProviderYamlDict, provider_info.model_dump(mode='json', exclude_none=True))

        yaml_string = '# yaml-language-server: $schema=.schema.json\n' + get_provider_yaml_string(yaml_data)

        path = providers_dir / f'{provider_id}.yml'
        path.write_text(yaml_string)
        provider_yaml = ProviderYaml(path)
        if collapse_provider(provider_yaml):
            provider_yaml.save()


main()
