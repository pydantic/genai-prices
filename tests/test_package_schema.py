from typing import Any, cast

import pytest
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema, from_json

from genai_prices.data import providers_schema
from prices.utils import package_dir as prices_package_dir, simplify_json_schema


class CustomGenerateJsonSchema(GenerateJsonSchema):
    def decimal_schema(self, schema: core_schema.DecimalSchema) -> JsonSchemaValue:
        return self.float_schema(core_schema.float_schema())


def remove_ignored_fields(json_schema: Any):
    if isinstance(json_schema, dict):
        json_schema = cast(dict[str, Any], json_schema)

        for f in 'description', 'maxLength', 'minLength', 'pattern', 'additionalProperties', 'propertyNames':
            json_schema.pop(f, None)

        for value in json_schema.values():
            remove_ignored_fields(value)
    elif isinstance(json_schema, list):
        for item in cast(list[Any], json_schema):
            remove_ignored_fields(item)


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
    prices_schema = from_json(prices_schema_path.read_bytes())

    remove_ignored_fields(prices_schema)

    assert prices_schema == package_schema
