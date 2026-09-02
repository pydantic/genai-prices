from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .types import Provider, _providers_from_raw  # pyright: ignore[reportPrivateUsage]
from .units import UnitRegistry, _validate_unit_evolution  # pyright: ignore[reportPrivateUsage]


@dataclass(frozen=True)
class _DecodedProviderData:
    providers: list[Provider]
    registry: UnitRegistry | None
    compatibility_warnings: tuple[str, ...]


def _decode_provider_data(  # pyright: ignore[reportUnusedFunction]
    raw: object, compatibility_registry: UnitRegistry
) -> _DecodedProviderData:
    if isinstance(raw, list):
        return _decode_legacy_provider_array(cast(list[object], raw))
    if isinstance(raw, Mapping):
        return _decode_wrapped_provider_data(cast(Mapping[str, object], raw), compatibility_registry)
    raise ValueError('Invalid provider data root: expected a wrapped object or provider array')


def _decode_wrapped_provider_data(
    raw: Mapping[str, object], compatibility_registry: UnitRegistry
) -> _DecodedProviderData:
    if 'units' not in raw:
        raise ValueError('Invalid provider data: missing units')
    if 'providers' not in raw:
        raise ValueError('Invalid provider data: missing providers')
    raw_providers = raw['providers']
    if not isinstance(raw_providers, list):
        raise ValueError('Invalid provider data at providers: expected an array')

    registry = UnitRegistry._from_untrusted(raw['units'])  # pyright: ignore[reportPrivateUsage]
    _validate_unit_evolution(compatibility_registry, registry)
    projected_providers, compatibility_warnings = _project_providers(cast(list[object], raw_providers))
    try:
        providers = _providers_from_raw(projected_providers)
    except (AssertionError, ValueError) as exc:
        raise ValueError(f'Invalid provider data at providers: {exc}') from exc
    return _DecodedProviderData(providers, registry, compatibility_warnings)


def _decode_legacy_provider_array(raw: list[object]) -> _DecodedProviderData:
    return _DecodedProviderData(_providers_from_raw(raw), None, ())


class _ProviderProjector:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def project_provider(self, raw: object, provider_index: int) -> object:
        if not isinstance(raw, Mapping):
            return raw
        provider = dict(cast(Mapping[str, Any], raw))
        context = _provider_context(provider, provider_index)

        for field in ('model_match', 'provider_match'):
            if field in provider:
                path = f'providers[{provider_index}].{field}'
                supported, projected = self._project_match(provider[field], path)
                if supported:
                    provider[field] = projected
                else:
                    self._warn('match', path, context)
                    del provider[field]

        raw_extractors = provider.get('extractors')
        if isinstance(raw_extractors, list):
            extractors: list[object] = []
            for extractor_index, raw_extractor in enumerate(cast(list[object], raw_extractors)):
                path = f'providers[{provider_index}].extractors[{extractor_index}]'
                projected = self._project_extractor(raw_extractor, path, context)
                if projected is not None:
                    extractors.append(projected)
            provider['extractors'] = extractors

        raw_models = provider.get('models')
        if isinstance(raw_models, list):
            models: list[object] = []
            for model_index, raw_model in enumerate(cast(list[object], raw_models)):
                projected = self._project_model(raw_model, provider_index, model_index, context)
                if projected is not None:
                    models.append(projected)
            provider['models'] = models
        return provider

    def _project_extractor(self, raw: object, path: str, context: str) -> object | None:
        if not isinstance(raw, Mapping):
            return raw
        extractor = dict(cast(Mapping[str, Any], raw))
        if 'type' in extractor or not ({'root', 'mappings'} & extractor.keys()):
            self._warn('extractor', path, context)
            return None

        for field in ('root', 'model_path'):
            if field in extractor:
                field_path = f'{path}.{field}'
                supported, projected = self._project_extract_path(extractor[field], field_path)
                if not supported:
                    self._warn('extractor', field_path, context)
                    return None
                extractor[field] = projected

        raw_mappings = extractor.get('mappings')
        if isinstance(raw_mappings, list):
            mappings: list[object] = []
            for mapping_index, raw_mapping in enumerate(cast(list[object], raw_mappings)):
                mapping_path = f'{path}.mappings[{mapping_index}]'
                if isinstance(raw_mapping, Mapping):
                    mapping = dict(cast(Mapping[str, Any], raw_mapping))
                    if 'type' in mapping or not ({'path', 'dest'} & mapping.keys()):
                        self._warn('extractor mapping', mapping_path, context)
                        continue
                    if 'path' in mapping:
                        path_path = f'{mapping_path}.path'
                        supported, projected = self._project_extract_path(mapping['path'], path_path)
                        if not supported:
                            self._warn('extractor mapping', path_path, context)
                            continue
                        mapping['path'] = projected
                    mappings.append(mapping)
                else:
                    mappings.append(raw_mapping)
            extractor['mappings'] = mappings
        return extractor

    def _project_extract_path(self, raw: object, path: str) -> tuple[bool, object]:
        if isinstance(raw, str):
            return True, raw
        if not isinstance(raw, list):
            return not isinstance(raw, Mapping), raw
        projected_steps: list[object] = []
        for index, step in enumerate(cast(list[object], raw)):
            if isinstance(step, str):
                projected_steps.append(step)
                continue
            if not isinstance(step, Mapping):
                projected_steps.append(step)
                continue
            array_match = dict(cast(Mapping[str, object], step))
            if array_match.get('type') != 'array-match':
                return False, cast(object, raw)
            if 'match' in array_match:
                supported, projected = self._project_match(array_match['match'], f'{path}[{index}].match')
                if not supported:
                    return False, cast(object, raw)
                array_match['match'] = projected
            projected_steps.append(array_match)
        return True, projected_steps

    def _project_model(
        self, raw: object, provider_index: int, model_index: int, provider_context: str
    ) -> object | None:
        if not isinstance(raw, Mapping):
            return raw
        model = dict(cast(Mapping[str, Any], raw))
        path = f'providers[{provider_index}].models[{model_index}]'
        context = f'{provider_context}, {_model_context(model, model_index)}'
        if 'match' in model:
            supported, projected = self._project_match(model['match'], f'{path}.match')
            if not supported:
                self._warn('match', f'{path}.match', context)
                return None
            model['match'] = projected
        if 'prices' in model:
            projected_prices = self._project_prices(model['prices'], f'{path}.prices', context)
            if isinstance(model['prices'], list) and model['prices'] and projected_prices == []:
                return None
            model['prices'] = projected_prices
        return model

    def _project_match(self, raw: object, path: str) -> tuple[bool, object]:
        if not isinstance(raw, Mapping):
            raise ValueError(f'Invalid match at {path}: expected an object')
        match = cast(Mapping[str, object], raw)
        if not match:
            return False, cast(object, raw)
        known_discriminators = {'starts_with', 'ends_with', 'contains', 'regex', 'equals', 'or', 'and'}
        discriminators = [key for key in match if key in known_discriminators]
        if not discriminators:
            return False, cast(object, raw)
        if len(discriminators) != 1:
            raise ValueError(f'Invalid match at {path}: expected exactly one recognized discriminator')
        discriminator = discriminators[0]
        projected_match = {discriminator: match[discriminator]}
        projected_match.update((key, value) for key, value in match.items() if key != discriminator)
        if discriminator not in {'or', 'and'} or not isinstance(match[discriminator], list):
            return True, projected_match

        # Nested match entries are not independently decoded here: retaining an
        # incomplete boolean expression could broaden or narrow model matching.
        projected_children: list[object] = []
        for index, child in enumerate(cast(list[object], match[discriminator])):
            supported, projected = self._project_match(child, f'{path}.{discriminator}[{index}]')
            if not supported:
                return False, cast(object, raw)
            projected_children.append(projected)
        projected_match[discriminator] = projected_children
        return True, projected_match

    def _project_prices(self, raw: object, path: str, context: str) -> object:
        if isinstance(raw, Mapping):
            return self._project_price_map(cast(Mapping[str, object], raw), path, context)
        if not isinstance(raw, list):
            raise ValueError(f'Invalid prices at {path}: expected an object or array')

        prices: list[object] = []
        for price_index, raw_price in enumerate(cast(list[object], raw)):
            price_path = f'{path}[{price_index}]'
            if not isinstance(raw_price, Mapping):
                prices.append(raw_price)
                continue
            conditional = dict(cast(Mapping[str, Any], raw_price))
            if 'prices' not in conditional:
                self._warn('price', price_path, context)
                continue
            constraint = conditional.get('constraint')
            if isinstance(constraint, Mapping):
                constraint_mapping = cast(Mapping[str, object], constraint)
                constraint_type = constraint_mapping.get('type')
                if ('type' in constraint_mapping and constraint_type not in {'start_date', 'time_of_date'}) or not (
                    {'start_date', 'start_time', 'end_time'} & constraint_mapping.keys()
                ):
                    self._warn('constraint', f'{price_path}.constraint', context)
                    continue
            conditional['prices'] = self._project_prices(conditional['prices'], f'{price_path}.prices', context)
            prices.append(conditional)
        return prices

    def _project_price_map(self, raw: Mapping[str, object], path: str, context: str) -> dict[str, object]:
        prices: dict[str, object] = {}
        for price_key, value in raw.items():
            if isinstance(value, Mapping) and not ({'base', 'tiers'} & value.keys()):
                self._warn('price', f'{path}.{price_key}', context)
                continue
            prices[price_key] = value
        return prices

    def _warn(self, capability: str, path: str, context: str) -> None:
        self.warnings.append(
            f'Unsupported {capability} variant at {path} for {context}; upgrade genai-prices for full support'
        )


def _project_providers(raw: list[object]) -> tuple[list[object], tuple[str, ...]]:
    projector = _ProviderProjector()
    providers = [projector.project_provider(provider, index) for index, provider in enumerate(raw)]
    return providers, tuple(projector.warnings)


def _provider_context(provider: Mapping[str, object], index: int) -> str:
    provider_id = provider.get('id')
    return f'provider {provider_id!r}' if isinstance(provider_id, str) else f'provider index {index}'


def _model_context(model: Mapping[str, object], index: int) -> str:
    model_id = model.get('id')
    return f'model {model_id!r}' if isinstance(model_id, str) else f'model index {index}'
