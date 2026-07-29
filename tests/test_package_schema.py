from pydantic_core import from_json

from genai_prices.types import _providers_from_raw
from prices import build as build_module
from prices.utils import package_dir as prices_package_dir


def test_legacy_provider_payload_remains_runtime_compatible() -> None:
    raw_providers = from_json((prices_package_dir / 'data.json').read_bytes())
    providers = _providers_from_raw(raw_providers)

    assert providers
    assert all(provider.id for provider in providers)


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
    assert properties['sausage_mtok']['title'] == 'Sausage Mtok'
    assert properties['sausage_mtok']['description'] == 'price in USD per million sausage tokens'
    assert properties['sausage_mtok']['anyOf'] == model_price_schema['additionalProperties']['anyOf']
    assert isinstance(model_price_schema['additionalProperties'], dict)


def test_provider_yaml_schema_includes_current_dynamic_registry_price_keys() -> None:
    schema = build_module._provider_yaml_schema(build_module.load_units())

    properties = schema['$defs']['ModelPrice']['properties']
    assert 'cache_image_read_mtok' in properties
    assert 'cache_write_5m_mtok' in properties
    assert (
        properties['cache_write_5m_mtok']['description']
        == 'price in USD per million tokens written to the cache with a 5-minute TTL'
    )
    assert (
        properties['cache_write_1h_mtok']['description']
        == 'price in USD per million tokens written to the cache with a 1-hour TTL'
    )


def test_provider_yaml_schema_suggests_extractor_dests_from_reported_registry_units() -> None:
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
            'requests': {
                'per': 1_000,
                'price_key': 'requests_kcount',
                'dimensions': {'family': 'requests'},
            },
        }
    )

    dest_schema = schema['$defs']['UsageExtractorMapping']['properties']['dest']
    assert dest_schema['enum'] == ['input_tokens', 'sausage_tokens']
    assert 'requests' not in dest_schema['enum']
