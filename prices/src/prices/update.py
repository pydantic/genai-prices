from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import StringIO
from operator import itemgetter
from pathlib import Path
from typing import Any, TypedDict, cast

from pydantic import ValidationError
from ruamel.yaml import YAML, CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import FoldedScalarString

from .prices_types import (
    ClauseEquals,
    ClauseOr,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    TieredPrices,
    match_logic_schema,
)
from .utils import package_dir
from .variants import follow_standard_change

yaml = YAML()
yaml.preserve_quotes = True
yaml.map_indent = 2
yaml.sequence_indent = 4
yaml.sequence_dash_offset = 2
yaml.width = 120
# A dated price shares its `date` object with `prices_checked`; without this ruamel emits `&id001` anchors.
yaml.representer.ignore_aliases = lambda *_: True  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]


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
    provider: Provider
    _extra_prices: list[ModelInfo]
    _removed_models: set[str]

    def __init__(self, path: Path) -> None:
        self.path = path

        with path.open('rb') as f:
            self.data = cast(ProviderYamlDict, yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

        self.provider_id = self.data['id']
        assert isinstance(self.provider_id, str), 'Provider ID must be a string'
        try:
            self.provider = Provider.model_validate(self.data)
        except ValidationError as e:
            raise ValueError(f'Invalid provider data for {path.name}:\n{e}') from e
        self._extra_prices = []
        self._removed_models = set()

    def update_model(self, lookup_id: str, model: ModelInfo, *, set_prices: bool = False) -> bool:
        yaml_model = self._get_model(lookup_id)
        current_model = ModelInfo.model_validate(yaml_model)
        price_update_blocked = set_prices and self._same_day_change(current_model, model)
        description = model.description
        if description:
            description = FoldedScalarString(description)
        for field, value, position in [
            ('name', model.name, 1),
            ('description', description, 2),
            ('context_window', model.context_window, 4),
        ]:
            if field not in yaml_model and value is not None:
                yaml_model.insert(position, field, value)  # pyright: ignore[reportUnknownMemberType]

        if set_prices and not price_update_blocked:
            prices = cast(Any, yaml_model['prices'])
            assert isinstance(model.prices, ModelPrice)
            new_prices = model.prices.model_dump(by_alias=True, mode='json', exclude_none=True)
            current_prices = (
                current_model.prices[-1].prices if isinstance(current_model.prices, list) else current_model.prices
            )
            if current_prices != model.prices:
                conditional_price = {'constraint': {'start_date': model.prices_checked}, 'prices': new_prices}
                if isinstance(prices, CommentedMap):
                    yaml_model['prices'] = [{'prices': prices}, conditional_price]
                else:
                    cast(CommentedSeq, prices).append(conditional_price)  # pyright: ignore[reportUnknownMemberType]
            assert model.prices_checked is not None, 'a price update needs the date it was checked'
            yaml_model['prices_checked'] = model.prices_checked
            if 'price_discrepancies' in yaml_model:
                del yaml_model['price_discrepancies']

        current_match_yaml = cast(CommentedMap, yaml_model['match'])
        current_match = match_logic_schema.validate_python(current_match_yaml)
        if model.match == current_match:
            # matches are the same, nothing to do
            return not price_update_blocked

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
            clauses = model.match.or_ if isinstance(model.match, ClauseOr) else [model.match]
            match_or = ClauseOr.model_validate({'or': [current_match, *(c for c in clauses if c != current_match)]})
            yaml_model['match'] = match_or.model_dump(by_alias=True, mode='json')
        return not price_update_blocked

    def add_id_to_model(self, lookup_id: str, new_model_id: str) -> None:
        [model] = [m for m in self.provider.models if m.id == lookup_id]
        model = model.model_copy(update=dict(match=ClauseEquals(equals=new_model_id)))
        self.update_model(lookup_id, model)

    def add_model(self, model: ModelInfo) -> int:
        if next((m for m in self._extra_prices if m.id == model.id), None):
            return 0
        else:
            self._extra_prices.append(model)
            return 1

    def upsert_models(self, models: list[ModelInfo], *, source: str, min_count: int) -> tuple[int, int]:
        """Add models and date representable rate changes; report intraday changes for manual review."""
        if len(models) < min_count:
            raise RuntimeError(f'{source} returned only {len(models)} priced models; expected at least {min_count}')
        self.provider = Provider.model_validate(self.data)
        models_added = 0
        models_updated = 0
        updated_prices: dict[str, ModelPrice] = {}
        matches = [(model, self.provider.find_model(model.id)) for model in models]
        # A source model whose id is the record's own id outranks one that only matches it as an alias.
        matches.sort(key=lambda match: match[1] is not None and match[1].id != match[0].id)
        for model, matching_model in matches:
            if matching_model is None:
                assert isinstance(model.prices, ModelPrice)
                models_added += self.add_model(
                    model.model_copy(update={'prices': without_redundant_cache_rates(model.prices)})
                )
                continue
            current = matching_model.prices
            curated = dict(current[-1].prices if isinstance(current, list) else current)
            assert isinstance(model.prices, ModelPrice)
            reported = {
                # A rate written as a float (0.08333333333333334) is the same rate as its exact decimal.
                key: rate
                if isinstance(rate := curated.get(key), Decimal)
                and isinstance(value, Decimal)
                and abs(rate - value) < Decimal('1e-12')
                else value
                for key, value in model.prices
                if value is not None
            }
            tiered = {
                key: tiers
                for key, value in reported.items()
                if isinstance(tiers := curated.get(key), TieredPrices) and not isinstance(value, TieredPrices)
            }
            if any(reported[key] != tiers.base for key, tiers in tiered.items()):
                print(
                    f'{source}: kept {matching_model.id} unchanged, {model.id} reports a flat rate where it is tiered'
                )
                continue
            # A source that doesn't report a key (e.g. cache writes) must not drop the curated rate for it.
            prices = without_redundant_cache_rates(ModelPrice(**(curated | reported | tiered)))
            if previous := updated_prices.get(matching_model.id):
                if previous != prices:
                    print(f'{source}: kept {matching_model.id} at its own rates, alias {model.id} reports others')
                continue
            updated_prices[matching_model.id] = prices
            model = model.model_copy(update={'prices': prices})
            price_update_blocked = self._same_day_change(matching_model, model)
            if model.match == ClauseEquals(equals=model.id):
                # The existing match already covers this id, so an `equals` clause for it would only add noise.
                current_match = match_logic_schema.validate_python(self._get_model(matching_model.id)['match'])
                model = model.model_copy(update={'match': current_match})
            self.update_model(matching_model.id, model, set_prices=not price_update_blocked)
            if not price_update_blocked and matching_model.price_variants and prices != ModelPrice(**curated):
                assert model.prices_checked is not None, 'a price update needs the date it was checked'
                self._follow_price_variants(matching_model, ModelPrice(**curated), prices, model.prices_checked, source)
            models_updated += not price_update_blocked
        self.save()
        return models_added, models_updated

    def add_price(self, model_id: str, price: ModelPrice) -> None:
        self.add_model(ModelInfo(id=model_id, prices=price, match=ClauseEquals(equals=model_id)))

    def remove_model(self, model_id: str) -> None:
        self._removed_models.add(model_id)

    def _same_day_change(self, record: ModelInfo, model: ModelInfo) -> bool:
        old = record.prices[-1].prices if isinstance(record.prices, list) else record.prices
        assert isinstance(model.prices, ModelPrice)
        if old == model.prices:
            return False
        constraints = [record.prices[-1].constraint] if isinstance(record.prices, list) else []
        if record.price_variants:
            changed_contexts = [when for when, _ in follow_standard_change(record.price_variants, old, model.prices)]
            constraints.extend(
                next(variant.constraint for variant in record.price_variants if variant.when == when)
                for when in changed_contexts
            )
        if (model.prices_checked is not None and record.prices_checked == model.prices_checked) or any(
            isinstance(c, StartDateConstraint) and c.start_date == model.prices_checked for c in constraints
        ):
            print(
                f'{self.provider_id}: kept {record.id} unchanged: another price change on {model.prices_checked} cannot be represented '
                f'by date-only constraints; update them by hand. Reported rates: '
                f'{model.prices.model_dump(mode="json", exclude_none=True)}'
            )
            return True
        return False

    def _follow_price_variants(
        self, record: ModelInfo, old: ModelPrice, new: ModelPrice, start: date, source: str
    ) -> None:
        """Date a new batch/flex/priority rate for every variant that is a fixed share of the standard rate."""
        assert record.price_variants is not None
        yaml_variants = cast(CommentedSeq, self._get_model(record.id)['price_variants'])
        changes: list[tuple[int, CommentedMap]] = []
        for when, prices in follow_standard_change(record.price_variants, old, new):
            if prices is None:
                print(
                    f'{source}: {record.id} {when} rates are not one share of the standard rates; update them by hand'
                )
                continue
            index = next(i for i, variant in enumerate(record.price_variants) if variant.when == when)
            entry = CommentedMap(
                when=flow_map(when),
                constraint=flow_map({'start_date': start}),
                prices=prices.model_dump(by_alias=True, mode='json', exclude_none=True),
            )
            changes.append((index, entry))
        # Variants resolve first to last, so the dated entry goes ahead of the one it supersedes.
        for index, entry in sorted(changes, key=lambda change: change[0], reverse=True):
            yaml_variants.insert(index, entry)  # pyright: ignore[reportUnknownMemberType]

    def _get_model(self, model_id: str) -> CommentedMap:
        for model in self.data['models']:
            if model['id'] == model_id:
                return model
        raise LookupError(f"Model with ID '{model_id}' not found")

    def save(self) -> None:
        existing_models = self.data['models']
        if self._removed_models:
            existing_models = [m for m in existing_models if m['id'] not in self._removed_models]

        new_models: list[dict[str, Any]] = []
        for model in self._extra_prices:
            new_model = model.model_dump(by_alias=True, mode='json', exclude_none=True)
            if model.prices_checked is not None:
                new_model['prices_checked'] = model.prices_checked
            if description := new_model.get('description'):
                new_model['description'] = FoldedScalarString(description.strip())
            new_models.append(new_model)

        existing_models += new_models
        self.data['models'] = existing_models

        self.path.write_text(get_provider_yaml_string(self.data))


def flow_map(values: dict[str, Any]) -> CommentedMap:
    mapping = CommentedMap(values)
    mapping.fa.set_flow_style()  # pyright: ignore[reportUnknownMemberType]
    return mapping


def without_redundant_cache_rates(prices: ModelPrice) -> ModelPrice:
    """Drop a cache rate equal to the input rate: the input rate already prices those tokens."""
    keys = ['cache_read_mtok']
    if not any(key.startswith('cache_write_') for key in prices.model_extra or {}):
        keys.append('cache_write_mtok')
    return prices.model_copy(update={key: None for key in keys if dict(prices)[key] == prices.input_mtok})


class ProviderYamlDict(TypedDict):
    id: str
    models: list[CommentedMap]


def get_provider_yaml_string(data: ProviderYamlDict) -> str:
    data['models'].sort(key=itemgetter('id'))

    buffer = StringIO()
    yaml.dump(data, buffer)  # pyright: ignore[reportUnknownMemberType]
    yaml_data = buffer.getvalue()

    # remove new lines between item
    yaml_data = re.sub(r'\n\n( +\w+:)', r'\n\1', yaml_data)
    # inject a new line between models
    yaml_data = re.sub(r'(\d|})\n( +- *id:)', r'\1\n\n\2', yaml_data)
    # ruamel leaves a trailing space where it wraps a long scalar
    yaml_data = re.sub(r'[ \t]+\n', '\n', yaml_data)
    # ruamel keeps a model's trailing blank line on the price entry that used to end it
    yaml_data = re.sub(r'\n\n( +- constraint:)', r'\n\1', yaml_data)
    # match prettier, so an unchanged file round-trips byte for byte
    yaml_data = re.sub(r"(?<=[-:{,] )'([^'\"\\\n]*)'(?=$| ?[,}])", r'"\1"', yaml_data, flags=re.MULTILINE)
    return re.sub(r'^( *(?:- )?[\w-]+: )\{([^{} \n][^{}\n]*)\}$', r'\1{ \2 }', yaml_data, flags=re.MULTILINE)
