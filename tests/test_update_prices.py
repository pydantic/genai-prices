from __future__ import annotations

import concurrent.futures
import threading
from decimal import Decimal
from time import monotonic, sleep

import httpx2
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
from genai_prices.update_prices import DEFAULT_UPDATE_URL

pytestmark = pytest.mark.anyio


def _wrapped_payload(*, providers_json: str | None = None, units_json: str | None = None) -> bytes:
    providers_json = providers_json or (
        '[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        '"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
        '"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
    )
    units_json = units_json or (
        '{"input_tokens":{"per":1000000,"price_key":"input_mtok","dimensions":{"family":"tokens","direction":"input"}},'
        '"output_tokens":{"per":1000000,"price_key":"output_mtok","dimensions":{"family":"tokens","direction":"output"}}}'
    )
    return f'{{"units":{units_json},"providers":{providers_json}}}'.encode()


def _provider_array(*, providers_json: str | None = None) -> bytes:
    providers_json = providers_json or (
        '[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        '"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
        '"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
    )
    return providers_json.encode()


class NullUpdatePrices(UpdatePrices):
    def fetch(self) -> data_snapshot.DataSnapshot | None:
        return None


class CountingNullUpdatePrices(UpdatePrices):
    count = 0

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        self.count += 1
        return None


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes = _wrapped_payload()) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url in {
            'https://example.test/prices.json',
            'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data_v2.json',
        }
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx2, 'get', fake_get)


def test_default_update_url_points_to_v2_provider_array() -> None:
    assert DEFAULT_UPDATE_URL == (
        'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data_v2.json'
    )


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


def test_update_prices_fetch_parses_provider_array_without_registry_change(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_registry(None)
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _provider_array())

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    provider, model = snapshot.find_provider_model('gpt-4o', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o'
    assert _get_registry() is bundled


def test_update_prices_fetch_provider_array_rejects_invalid_extractor_without_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_registry(None)
    bundled = _get_registry()
    previous_snapshot = data_snapshot.DataSnapshot([], from_auto_update=False)
    data_snapshot.set_custom_snapshot(previous_snapshot)
    providers_json = (
        '[{"id":"broken","name":"Broken","api_pattern":"https://broken\\\\.example",'
        '"extractors":[{"root":"usage","mappings":['
        '{"path":"tokens","dest":"imaginary_tokens","required":false}]}],"models":[]}]'
    )
    _mock_update_prices_get(monkeypatch, _provider_array(providers_json=providers_json))

    try:
        with pytest.raises(ValueError, match='Invalid extractor destination: imaginary_tokens'):
            UpdatePrices(url='https://example.test/prices.json').fetch()

        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is previous_snapshot
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_fetch_provider_array_does_not_eagerly_validate_unused_model_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_registry(None)
    bundled = _get_registry()
    providers_json = (
        '[{"id":"testing","name":"Testing","api_pattern":"https://testing\\\\.example",'
        '"models":[{"id":"unused-invalid-price","match":{"equals":"unused-invalid-price"},'
        '"prices":{"cache_image_write_mtok":1}}]}]'
    )
    _mock_update_prices_get(monkeypatch, _provider_array(providers_json=providers_json))

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    _, model = snapshot.find_provider_model('unused-invalid-price', None, 'testing', None)
    assert model.id == 'unused-invalid-price'
    assert _get_registry() is bundled


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


def test_wait_prices_updated_sync_without_active_updater():
    assert wait_prices_updated_sync(timeout=0) is False


def test_update_prices_start_waits_and_rejects_second_start():
    update_prices = NullUpdatePrices(update_interval=3600)
    update_prices.start(wait=True)
    try:
        assert data_snapshot._custom_snapshot is None
        with pytest.raises(RuntimeError, match='UpdatePrices background task already started'):
            update_prices.start()
    finally:
        update_prices.stop()


def test_update_prices_continues_after_interval_until_stopped():
    update_prices = CountingNullUpdatePrices(update_interval=0.001)
    update_prices.start(wait=True)
    try:
        deadline = monotonic() + 1
        while update_prices.count < 2 and monotonic() < deadline:
            sleep(0.01)
        assert update_prices.count >= 2
    finally:
        update_prices.stop()


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


def test_update_prices_stop_restores_registry_after_in_flight_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_registry(None)
    bundled = _get_registry()
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class Response:
        content = _wrapped_payload()

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url == 'https://example.test/prices.json'
        assert timeout is not None
        fetch_started.set()
        assert allow_fetch_return.wait(timeout=5)
        return Response()

    monkeypatch.setattr(httpx2, 'get', fake_get)
    update_prices = UpdatePrices(url='https://example.test/prices.json', update_interval=3600)
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert update_prices._stop_event.wait(timeout=5)
            allow_fetch_return.set()
            stop_future.result(timeout=5)

        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is None
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        _set_registry(None)
        data_snapshot.set_custom_snapshot(None)


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed():
    assert data_snapshot._custom_snapshot is None
    with UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404') as update_prices:
        with pytest.raises(httpx2.HTTPStatusError):
            update_prices.wait()
    assert data_snapshot._custom_snapshot is None


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx2.HTTPStatusError):
        update_prices.stop()
    assert data_snapshot._custom_snapshot is None


def test_update_prices_multiple(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_payload())
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            UpdatePrices().start()
