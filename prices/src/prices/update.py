from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from operator import itemgetter
from pathlib import Path
from typing import TypedDict, cast

from ruamel.yaml import YAML, CommentedMap
from ruamel.yaml.scalarstring import FoldedScalarString

from .types import ModelInfo, Provider
from .utils import package_dir

yaml = YAML()
yaml.preserve_quotes = True
yaml.map_indent = 2
yaml.sequence_indent = 4
yaml.sequence_dash_offset = 2
yaml.width = 200


@dataclass(init=False)
class ProvidersYaml:
    providers: dict[str, ProviderYaml]

    def __init__(self) -> None:
        providers_dir = package_dir / 'providers'
        self.providers = {}
        for file in providers_dir.iterdir():
            assert file.suffix in ('.yml', '.yaml'), f'All {providers_dir} files must be YAML files'

            provider = ProviderYaml(file)
            self.providers[provider.provider_id] = provider


@dataclass(init=False)
class ProviderYaml:
    path: Path
    data: ProviderYamlDict
    privder_id: str
    provider: Provider
    extra_prices: list[ModelInfo]

    def __init__(self, path: Path) -> None:
        self.path = path

        with path.open('rb') as f:
            self.data = cast(ProviderYamlDict, yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

        self.provider_id = self.data['id']
        assert isinstance(self.provider_id, str), 'Provider ID must be a string'
        self.provider = Provider.model_validate(self.data)
        self.extra_prices = []

    def update_model(self, lookup_id: str, model: ModelInfo) -> None:
        yaml_model = self._get_model(lookup_id)
        description = model.description
        if description:
            description = FoldedScalarString(description)
        for field, value, position in [
            ('name', model.name, 1),
            ('description', description, 2),
            ('max_tokens', model.max_tokens, 4),
        ]:
            if field not in yaml_model and value is not None:
                yaml_model.insert(position, field, value)  # pyright: ignore[reportUnknownMemberType]

    def add_model(self, model: ModelInfo) -> int:
        if next((m for m in self.extra_prices if m.id == model.id), None):
            return 0
        else:
            self.extra_prices.append(model)
            return 1

    def _get_model(self, model_id: str) -> CommentedMap:
        for model in self.data['models']:
            if model['id'] == model_id:
                return model
        raise KeyError(model_id)

    def save(self) -> None:
        new_models = [m.model_dump(by_alias=True, mode='json', exclude_none=True) for m in self.extra_prices]
        for m in new_models:
            if description := m.get('description'):
                m['description'] = FoldedScalarString(description.strip())

        self.data['models'] += new_models
        self.data['models'] = sorted(self.data['models'], key=itemgetter('id'))

        buffer = StringIO()
        yaml.dump(self.data, buffer)  # pyright: ignore[reportUnknownMemberType]
        yaml_data = buffer.getvalue()

        # remove new lines between item
        yaml_data = re.sub(r'\n\n( +\w+:)', r'\n\1', yaml_data)
        # inject a new line between models
        yaml_data = re.sub(r'(\d)\n( +- *id:)', r'\1\n\n\2', yaml_data)
        # replace fancy quotes with straight quotes
        yaml_data = re.sub(r'[""]', '"', yaml_data)
        yaml_data = re.sub(r'[' ']', "'", yaml_data)
        self.path.write_text(yaml_data)


class ProviderYamlDict(TypedDict):
    id: str
    models: list[CommentedMap]
