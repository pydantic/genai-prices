from typing import Any, cast

import pytest
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema, from_json

from genai_prices.data import providers_schema
from prices import build as build_module
from prices.utils import package_dir as prices_package_dir, simplify_json_schema


class CustomGenerateJsonSchema(GenerateJsonSchema):
    def decimal_schema(self, schema: core_schema.DecimalSchema) -> JsonSchemaValue:
        return self.float_schema(core_schema.float_schema())


def remove_ignored_fields(json_schema: Any):
    if isinstance(json_schema, dict):
        json_schema = cast(dict[str, Any], json_schema)

        for f in 'description', 'maxLength', 'minLength', 'pattern', 'additionalProperties':
            json_schema.pop(f, None)

        for value in json_schema.values():
            remove_ignored_fields(value)
    elif isinstance(json_schema, list):
        for item in cast(list[Any], json_schema):
            remove_ignored_fields(item)


def test_provider_yaml_schema_suggests_registry_price_keys_from_units() -> None:
    schema = build_module._provider_yaml_schema(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
        }
    )

    model_price_schema = schema['$defs']['ModelPrice']
    properties = model_price_schema['properties']
    assert properties['input_mtok']['description'] == 'price in USD per million uncached text input/prompt token'
    assert properties['sausage_mtok'] == model_price_schema['additionalProperties']
    assert isinstance(model_price_schema['additionalProperties'], dict)


def test_provider_yaml_schema_includes_current_dynamic_registry_price_keys() -> None:
    schema = build_module._provider_yaml_schema(build_module.load_units())

    properties = schema['$defs']['ModelPrice']['properties']
    assert 'cache_image_read_mtok' in properties


@pytest.mark.requires_latest_pydantic
def test_package_schema():
    package_schema = simplify_json_schema(providers_schema.json_schema(schema_generator=CustomGenerateJsonSchema))
    remove_ignored_fields(package_schema)

    # prices is not required in the model info package schema for simplicity
    package_schema['$defs']['ModelInfo']['required'].append('prices')

    # models is not required in the provider package schema for simplicity
    package_schema['$defs']['Provider']['required'].append('models')
    package_schema['$defs']['Provider']['properties']['pricing_urls']['items']['format'] = 'uri'

    # work around for hack on ConditionalPrice
    package_schema['$defs']['ConditionalPrice']['required'] = ['prices']

    package_schema['$defs']['ClauseRegex']['properties']['regex']['format'] = 'regex'

    prices_schema_path = prices_package_dir / 'data.schema.json'
    wrapped_prices_schema = from_json(prices_schema_path.read_bytes())
    assert wrapped_prices_schema['required'] == ['units', 'providers']
    assert set(wrapped_prices_schema['properties']) == {'units', 'providers'}

    prices_schema = wrapped_prices_schema['properties']['providers']
    prices_schema['$defs'] = wrapped_prices_schema['$defs']
    remove_ignored_fields(prices_schema)

    assert prices_schema == package_schema
