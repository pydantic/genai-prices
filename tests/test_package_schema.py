from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic_core import from_json

from genai_prices import Usage
from genai_prices.types import _providers_from_raw
from prices import build as build_module
from prices.utils import package_dir as prices_package_dir


def test_legacy_provider_payload_remains_runtime_compatible() -> None:
    """The frozen v1 payload must still *price* a request for pre-0.1.0 clients, not merely still parse."""
    raw_providers = from_json((prices_package_dir / 'data.json').read_bytes())
    providers = _providers_from_raw(raw_providers)

    assert providers

    openai = next(provider for provider in providers if provider.id == 'openai')
    model = openai.find_model('gpt-4o', all_providers=providers)
    assert model is not None

    price = model.calc_price(
        Usage(input_tokens=1_000_000, output_tokens=500_000, cache_read_tokens=200_000),
        openai,
        # v1 gpt-4o prices are unconditional, but pin the timestamp so conditional pricing could never make this flaky
        genai_request_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    # 0.8 MTok uncached input @ $2.50 + 0.2 MTok cache read @ $1.25; 0.5 MTok output @ $10
    assert price.input_price == Decimal('2.25')
    assert price.output_price == Decimal('5')
    assert price.total_price == Decimal('7.25')


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
    assert properties['audio_hours']['description'] == 'price in USD per audio hour'
    assert properties['input_audio_hours']['description'] == 'price in USD per input audio hour'
    assert properties['output_audio_hours']['description'] == 'price in USD per output audio hour'
    assert properties['input_text_messages_kcount']['description'] == 'price in USD per thousand input text messages'
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
