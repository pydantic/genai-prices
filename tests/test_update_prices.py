from decimal import Decimal

import httpx
import pytest
from inline_snapshot import snapshot

from genai_prices import (
    UpdatePrices,
    Usage,
    calc_price,
    data_snapshot,
    wait_prices_updated_async,
    wait_prices_updated_sync,
)
from genai_prices.units import _get_registry, _set_registry

pytestmark = pytest.mark.anyio


def _wrapped_payload(*, providers_json: str | None = None, unit_families_json: str | None = None) -> bytes:
    providers_json = providers_json or (
        '[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        '"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
        '"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
    )
    unit_families_json = unit_families_json or (
        '{"tokens":{"per":1000000,"units":{'
        '"input_tokens":{"price_key":"input_mtok","dimensions":{"direction":"input"}},'
        '"output_tokens":{"price_key":"output_mtok","dimensions":{"direction":"output"}}'
        '}}}'
    )
    return f'{{"unit_families":{unit_families_json},"providers":{providers_json}}}'.encode()


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx.Timeout) -> Response:
        assert url in {
            'https://example.test/prices.json',
            'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json',
        }
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx, 'get', fake_get)


def test_update_prices_fetch_parses_wrapped_payload_and_installs_registry(monkeypatch: pytest.MonkeyPatch):
    _set_registry(None)
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_payload())

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    try:
        assert snapshot is not None
        assert snapshot.from_auto_update is True
        provider, model = snapshot.find_provider_model('gpt-4o', None, 'openai', None)
        assert provider.id == 'openai'
        assert model.id == 'gpt-4o'
        assert _get_registry() is not bundled
        assert set(_get_registry().units) == {'input_tokens', 'output_tokens'}
    finally:
        _set_registry(None)


def test_update_prices_fetch_restores_registry_when_provider_parsing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_registry(None)
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_payload(providers_json='[{"id":"missing-required-fields"}]'))

    with pytest.raises(Exception):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_rejects_malformed_wrapped_payload_without_registry_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_registry(None)
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, b'{"providers":[]}')

    with pytest.raises(ValueError, match='Expected fetched prices payload'):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_stop_restores_bundled_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_registry(None)
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    update_prices = UpdatePrices(url='https://example.test/prices.json')
    snapshot = update_prices.fetch()

    try:
        data_snapshot.set_custom_snapshot(snapshot)
        assert _get_registry() is not bundled
        assert data_snapshot._custom_snapshot is snapshot

        update_prices.stop()

        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is None
    finally:
        _set_registry(None)
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_wait_on_start(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices() as update_prices:
        update_prices.wait()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        wait_prices_updated_sync()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices():
        await wait_prices_updated_async()
        assert data_snapshot._custom_snapshot is not None
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404') as update_prices:
        with pytest.raises(httpx.HTTPStatusError):
            update_prices.wait()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx.HTTPStatusError):
        update_prices.stop()
    assert data_snapshot._custom_snapshot is None


def test_update_prices_multiple(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            with UpdatePrices():
                pass
