"""Tests for `prices.source_simonw_prices`.

Drop-count and legacy-shape tests: OnErrorOmit used to swallow a payload-shape change into an empty write.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from inline_snapshot import snapshot
from pydantic import ValidationError

from prices.source_simonw_prices import (
    SimonWModel,
    get_provider,
    get_simonw_prices,
    lookup_vendor,
    simonw_response_schema,
)
from prices.update import get_providers_yaml

from .fixtures import capture_source_prices, load_entries, load_payload, mock_httpx_get

SIMONW_URL = 'https://www.llm-prices.com/current-v1.json'

# `vendor` values present upstream that `lookup_vendor` deliberately omits: open-weight families served
# by many providers, with no single provider entry to attribute an upstream price to.
UNMAPPED_VENDORS = ['meta-ai', 'qwen']


def simonw_model(vendor: str, *, input_cached: Decimal | None = None) -> SimonWModel:
    return SimonWModel(
        id=f'{vendor}-test-model',
        vendor=vendor,
        name=f'Test {vendor}',
        input=Decimal('1'),
        output=Decimal('2'),
        input_cached=input_cached,
    )


def test_simonw_response_parses_current_payload():
    response = simonw_response_schema.validate_json(load_payload('simonw_current_v1.json'))

    assert response.updated_at == snapshot('2026-07-30')
    assert [model.id for model in response.prices] == snapshot(
        [
            'amazon-nova-micro',
            'claude-3.7-sonnet',
            'deepseek-v4-flash',
            'gemini-2.5-pro-preview-03-25',
            'muse-spark-1.1',
            'minimax-m2',
            'pixtral-12b',
            'kimi-k2-0905-preview',
            'text-davinci-003',
            'qwen3.6-plus',
            'grok-3',
        ]
    )


def test_simonw_payload_drops_no_models():
    """The assertion that would have caught the silent breakage: every raw entry must survive decoding."""
    raw_entries = load_entries('simonw_current_v1.json', 'prices')
    response = simonw_response_schema.validate_json(load_payload('simonw_current_v1.json'))

    assert len(response.prices) == len(raw_entries)
    assert [model.id for model in response.prices] == [entry['id'] for entry in raw_entries]


def test_simonw_rejects_legacy_payload_shape():
    """The pre-change shape must now fail loudly rather than decode to zero models."""
    legacy = b'{"gpt-4o": {"id": "gpt-4o", "vendor": "openai", "name": "GPT-4o", "input": 2.5, "output": 10}}'

    with pytest.raises(ValidationError) as exc_info:
        simonw_response_schema.validate_json(legacy)

    assert [error['type'] for error in exc_info.value.errors()] == snapshot(['missing', 'missing'])


def test_simonw_rejects_payload_with_unparseable_entry():
    """A single malformed model must fail the whole decode — the opposite of the `OnErrorOmit` behaviour."""
    payload = b'{"updated_at": "2026-07-30", "prices": [{"id": "x", "vendor": "openai", "name": "X"}]}'

    with pytest.raises(ValidationError):
        simonw_response_schema.validate_json(payload)


@pytest.mark.parametrize(('vendor', 'provider_id'), sorted(lookup_vendor.items()))
def test_get_provider_maps_vendor_to_provider_id(vendor: str, provider_id: str):
    assert get_provider(simonw_model(vendor)) == provider_id


@pytest.mark.parametrize('provider_id', sorted(set(lookup_vendor.values())))
def test_mapped_providers_all_exist(provider_id: str):
    """`get_simonw_prices` asserts the mapped id is a real provider, so a typo here would only surface
    during a live pull."""
    assert provider_id in get_providers_yaml()


@pytest.mark.parametrize('vendor', UNMAPPED_VENDORS)
def test_get_provider_returns_none_for_deliberately_unmapped_vendor(vendor: str):
    assert get_provider(simonw_model(vendor)) is None


def test_unmapped_vendors_are_still_present_upstream():
    """Guards the test above: if upstream dropped these vendors, it would pass vacuously."""
    response = simonw_response_schema.validate_json(load_payload('simonw_current_v1.json'))

    vendors = {model.vendor for model in response.prices}
    assert set(UNMAPPED_VENDORS) <= vendors
    assert vendors - set(lookup_vendor) == set(UNMAPPED_VENDORS)


def test_simonw_prices_map_vendors_and_cached_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Runs the importer end-to-end on the recorded payload, capturing the write instead of performing it."""
    mock_httpx_get(monkeypatch, expected_url=SIMONW_URL, content=load_payload('simonw_current_v1.json'))
    written = capture_source_prices(monkeypatch)

    get_simonw_prices()

    assert {
        provider: {name: price.model_dump(exclude_none=True) for name, price in models.items()}
        for provider, models in written['simonw'].items()
    } == snapshot(
        {
            'aws': {'amazon-nova-micro': {'input_mtok': Decimal('0.035'), 'output_mtok': Decimal('0.14')}},
            'anthropic': {'claude-3.7-sonnet': {'input_mtok': Decimal('3'), 'output_mtok': Decimal('15')}},
            'deepseek': {
                'deepseek-v4-flash': {
                    'input_mtok': Decimal('0.14'),
                    'cache_read_mtok': Decimal('0.028'),
                    'output_mtok': Decimal('0.28'),
                }
            },
            'google': {'gemini-2.5-pro-preview-03-25': {'input_mtok': Decimal('1.25'), 'output_mtok': Decimal('10')}},
            'minimax': {'minimax-m2': {'input_mtok': Decimal('0.30'), 'output_mtok': Decimal('1.20')}},
            'mistral': {'pixtral-12b': {'input_mtok': Decimal('0.15'), 'output_mtok': Decimal('0.15')}},
            'moonshotai': {
                'kimi-k2-0905-preview': {
                    'input_mtok': Decimal('0.60'),
                    'cache_read_mtok': Decimal('0.15'),
                    'output_mtok': Decimal('2.50'),
                }
            },
            'openai': {'text-davinci-003': {'input_mtok': Decimal('20'), 'output_mtok': Decimal('20')}},
            'x-ai': {
                'grok-3': {
                    'input_mtok': Decimal('3'),
                    'cache_read_mtok': Decimal('0.75'),
                    'output_mtok': Decimal('15'),
                }
            },
        }
    )

    out = capsys.readouterr().out
    for vendor in UNMAPPED_VENDORS:
        assert f'(vendor {vendor!r})' in out


def test_simonw_input_cached_maps_to_cache_read_mtok(monkeypatch: pytest.MonkeyPatch):
    """`input_cached` is the only field whose name differs from its `ModelPrice` target."""
    payload = (
        b'{"updated_at": "2026-07-30", "prices": ['
        b'{"id": "m-cached", "vendor": "openai", "name": "Cached", "input": 1, "output": 2, "input_cached": 0.5},'
        b'{"id": "m-plain", "vendor": "openai", "name": "Plain", "input": 1, "output": 2, "input_cached": null}'
        b']}'
    )
    mock_httpx_get(monkeypatch, expected_url=SIMONW_URL, content=payload)
    written = capture_source_prices(monkeypatch)

    get_simonw_prices()

    assert written['simonw']['openai']['m-cached'].cache_read_mtok == Decimal('0.5')
    assert written['simonw']['openai']['m-plain'].cache_read_mtok is None
