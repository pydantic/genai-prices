from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from operator import itemgetter
from pathlib import Path
from typing import Any, TypedDict, cast

from ruamel.yaml import YAML, CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import FoldedScalarString

from .types import ClauseOr, ModelInfo, ModelPrice, Provider, match_logic_schema
from .utils import package_dir

yaml = YAML()
yaml.preserve_quotes = True
yaml.map_indent = 2
yaml.sequence_indent = 4
yaml.sequence_dash_offset = 2
yaml.width = 120


def get_providers_yaml() -> dict[str, ProviderYaml]:
    providers_dir = package_dir / 'providers'
    providers: dict[str, ProviderYaml] = {}
    for file in providers_dir.iterdir():
        if file.suffix not in ('.yml', '.yaml'):
            continue

        provider = ProviderYaml(file)
        providers[provider.provider_id] = provider
    return providers


@dataclass(init=False)
class ProviderYaml:
    path: Path
    data: ProviderYamlDict
    privder_id: str
    provider: Provider
    _extra_prices: list[ModelInfo]
    _removed_models: set[str]

    def __init__(self, path: Path) -> None:
        self.path = path

        with path.open('rb') as f:
            self.data = cast(ProviderYamlDict, yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

        self.provider_id = self.data['id']
        assert isinstance(self.provider_id, str), 'Provider ID must be a string'
        self.provider = Provider.model_validate(self.data)
        self._extra_prices = []
        self._removed_models = set()

    def update_model(self, lookup_id: str, model: ModelInfo, *, set_prices: bool = False) -> None:
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

        if set_prices:
            prices = cast(Any, yaml_model['prices'])
            assert isinstance(model.prices, ModelPrice)
            if isinstance(prices, CommentedMap):
                prices.clear()  # pyright: ignore[reportUnknownMemberType]
                prices.update(model.prices.model_dump(by_alias=True, mode='json'))  # pyright: ignore[reportUnknownMemberType]
            else:
                yaml_model['prices'] = model.prices.model_dump(by_alias=True, mode='json')

        current_match_yaml = cast(CommentedMap, yaml_model['match'])
        current_match = match_logic_schema.validate_python(current_match_yaml)
        if model.match == current_match:
            # matches are the same, nothing to do
            return

        if isinstance(current_match, ClauseOr):
            or_list = cast(CommentedSeq, current_match_yaml['or'])
            if isinstance(model.match, ClauseOr):
                for clause in model.match.or_:
                    if clause not in current_match.or_:
                        clause_yml = clause.model_dump(by_alias=True, mode='json')
                        or_list.append(clause_yml)  # pyright: ignore[reportUnknownMemberType]
            elif model.match not in current_match.or_:
                clause_yml = model.match.model_dump(by_alias=True, mode='json')
                or_list.append(clause_yml)  # pyright: ignore[reportUnknownMemberType]
        else:
            match_or = ClauseOr.model_validate({'or': [current_match, model.match]})
            yaml_model['match'] = match_or.model_dump(by_alias=True, mode='json')

    def set_price_discrepency(self, lookup_id: str, source: str, price: ModelPrice) -> None:
        yaml_model = self._get_model(lookup_id)
        data = price.model_dump(by_alias=True, mode='json', exclude_none=True)
        if disc := yaml_model.get('price_discrepancies'):  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            disc[source] = data
        else:
            yaml_model['price_discrepancies'] = {source: data}

    def add_model(self, model: ModelInfo) -> int:
        if next((m for m in self._extra_prices if m.id == model.id), None):
            return 0
        else:
            self._extra_prices.append(model)
            return 1

    def remove_model(self, model_id: str) -> None:
        self._removed_models.add(model_id)

    def _get_model(self, model_id: str) -> CommentedMap:
        for model in self.data['models']:
            if model['id'] == model_id:
                return model
        raise LookupError(f"Model with ID '{model_id}' not found")

    def save(self) -> None:
        existing_models = self.data['models']
        if self._removed_models:
            existing_models = [m for m in existing_models if m['id'] not in self._removed_models]

        new_models = [m.model_dump(by_alias=True, mode='json', exclude_none=True) for m in self._extra_prices]
        for m in new_models:
            if description := m.get('description'):
                m['description'] = FoldedScalarString(description.strip())

        existing_models += new_models
        self.data['models'] = sorted(existing_models, key=itemgetter('id'))

        buffer = StringIO()
        yaml.dump(self.data, buffer)  # pyright: ignore[reportUnknownMemberType]
        yaml_data = buffer.getvalue()

        # remove new lines between item
        yaml_data = re.sub(r'\n\n( +\w+:)', r'\n\1', yaml_data)
        # inject a new line between models
        yaml_data = re.sub(r'(\d|\})\n( +- *id:)', r'\1\n\n\2', yaml_data)
        self.path.write_text(yaml_data)


class ProviderYamlDict(TypedDict):
    id: str
    models: list[CommentedMap]
