from __future__ import annotations

import concurrent.futures
import json
import threading
from collections.abc import Iterator
from copy import deepcopy
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
    data_units,
    runtime_state,
    wait_prices_updated_async,
    wait_prices_updated_sync,
)
from genai_prices.units import _get_registry
from genai_prices.update_prices import DEFAULT_UPDATE_URL

pytestmark = pytest.mark.anyio


def _active_snapshot() -> data_snapshot.DataSnapshot:
    return data_snapshot.get_snapshot()


def _bundled_snapshot() -> data_snapshot.DataSnapshot:
    return runtime_state._bundled_runtime_data().snapshot


def _wrapped_v2(
    *,
    providers_json: str | None = None,
    units: dict[str, dict[str, object]] | None = None,
) -> bytes:
    providers_json = providers_json or (
        '[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        '"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
        '"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
    )
    return json.dumps(
        {
            'units': deepcopy(data_units.unit_data) if units is None else units,
            'providers': json.loads(providers_json),
        }
    ).encode()


@pytest.fixture(autouse=True)
def _restore_bundled_runtime_data() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    generation = runtime_state.begin_update()
    assert runtime_state.activate_runtime_data(generation, runtime_state._bundled_runtime_data())


class NullUpdatePrices(UpdatePrices):
    def fetch(self) -> data_snapshot.DataSnapshot | None:
        return None


class CountingNullUpdatePrices(UpdatePrices):
    count = 0

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        self.count += 1
        return None


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes = _wrapped_v2()) -> None:
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


def test_default_update_url_points_to_wrapped_v2_data() -> None:
    assert DEFAULT_UPDATE_URL == (
        'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data_v2.json'
    )


def test_update_prices_fetch_preserves_registry_when_provider_parsing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_v2(providers_json='[{"id":"missing-required-fields"}]'))

    with pytest.raises(Exception):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


@pytest.mark.parametrize(
    'content',
    [
        b'{"providers":[]}',
        b'{"units":{},"providers":[],"extra":true}',
        b'null',
        b'"providers"',
        b'1',
        b'[]',
    ],
)
def test_update_prices_fetch_rejects_invalid_wrapper_without_registry_change(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, content)

    with pytest.raises(ValueError):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_activates_wrapped_registry_and_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_v2())

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    assert _active_snapshot() is snapshot
    provider, model = snapshot.find_provider_model('gpt-4o', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o'
    assert _get_registry() is not bundled
    assert _get_registry().units == bundled.units


def test_update_prices_fetch_warns_and_omits_invalid_extractor_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers_json = (
        '[{"id":"broken","name":"Broken","api_pattern":"https://broken\\\\.example",'
        '"extractors":[{"root":"usage","mappings":['
        '{"path":"tokens","dest":"imaginary_tokens","required":false}]}],"models":[]}]'
    )
    _mock_update_prices_get(monkeypatch, _wrapped_v2(providers_json=providers_json))

    with pytest.warns(
        UserWarning,
        match='Unsupported extractor destination for standard extraction: imaginary_tokens',
    ):
        snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    provider = snapshot.find_provider(None, 'broken', None)
    assert provider.id == 'broken'
    assert provider.extractors is not None
    assert provider.extractors[0].mappings == []
    assert _active_snapshot() is snapshot


def test_update_prices_fetch_rejects_incomplete_recognized_price_coverage_without_state_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = runtime_state.get_runtime_data()
    providers_json = (
        '[{"id":"testing","name":"Testing","api_pattern":"https://testing\\\\.example",'
        '"models":[{"id":"unused-invalid-price","match":{"equals":"unused-invalid-price"},'
        '"prices":{"cache_image_write_mtok":1}}]}]'
    )
    _mock_update_prices_get(monkeypatch, _wrapped_v2(providers_json=providers_json))

    with pytest.raises(
        ValueError,
        match='Invalid price coverage for testing/unused-invalid-price: Missing ancestor price',
    ):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert runtime_state.get_runtime_data() is previous


def test_update_prices_fetch_warns_and_omits_unsupported_price_key(monkeypatch: pytest.MonkeyPatch) -> None:
    providers_json = (
        '[{"id":"testing","name":"Testing","api_pattern":"https://testing\\\\.example",'
        '"models":[{"id":"future","match":{"equals":"future"},'
        '"prices":{"future_mtok":1}}]}]'
    )
    _mock_update_prices_get(monkeypatch, _wrapped_v2(providers_json=providers_json))

    with pytest.warns(UserWarning, match='Unsupported price key for standard pricing: future_mtok'):
        snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    _, model = snapshot.find_provider_model('future', None, 'testing', None)
    assert not isinstance(model.prices, list)
    assert model.prices.__dict__ == {}


def test_update_prices_fetch_activates_new_unit_with_matching_provider_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = deepcopy(data_units.unit_data)
    units['widgets'] = {
        'per': 1_000,
        'price_key': 'widget_kcount',
        'dimensions': {'family': 'widgets'},
    }
    providers_json = (
        '[{"id":"testing","name":"Testing","api_pattern":"https://testing\\\\.example",'
        '"models":[{"id":"widget-model","match":{"equals":"widget-model"},'
        '"prices":{"widget_kcount":2}}]}]'
    )
    _mock_update_prices_get(monkeypatch, _wrapped_v2(providers_json=providers_json, units=units))

    fetched_snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert fetched_snapshot is _active_snapshot()
    assert 'widgets' in _get_registry().units
    price = calc_price(Usage(widgets=2_000), model_ref='widget-model', provider_id='testing')
    assert price.input_price == Decimal('0')
    assert price.output_price == Decimal('0')
    assert price.total_price == Decimal('4')


def test_update_prices_fetch_rejects_invalid_units_without_state_change(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = runtime_state.get_runtime_data()
    units = deepcopy(data_units.unit_data)
    units['broken'] = {
        'per': 1_000,
        'price_key': '_private',
        'dimensions': {'family': 'broken'},
    }
    _mock_update_prices_get(monkeypatch, _wrapped_v2(units=units))

    with pytest.raises(ValueError, match='must not start'):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert runtime_state.get_runtime_data() is previous


def test_update_prices_wait_on_start(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_v2())
    assert _active_snapshot() is _bundled_snapshot()
    with UpdatePrices() as update_prices:
        update_prices.wait()
        assert _active_snapshot() is not _bundled_snapshot()
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


def test_wait_prices_updated_sync(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_v2())
    assert _active_snapshot() is _bundled_snapshot()
    with UpdatePrices():
        wait_prices_updated_sync()
        assert _active_snapshot() is not _bundled_snapshot()
        price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')
        assert price.input_price == snapshot(Decimal('0.0025'))
        assert price.output_price == snapshot(Decimal('0.001'))
        assert price.total_price == snapshot(Decimal('0.0035'))
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is not None


async def test_wait_prices_updated_async(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_v2())
    assert _active_snapshot() is _bundled_snapshot()
    with UpdatePrices():
        await wait_prices_updated_async()
        assert _active_snapshot() is not _bundled_snapshot()
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
        assert _active_snapshot() is _bundled_snapshot()
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


def test_update_prices_concurrent_fetches_are_last_invocation_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    first_started = threading.Event()
    allow_first_return = threading.Event()
    first_content = _wrapped_v2(
        providers_json=(
            '[{"id":"first","name":"First","api_pattern":"first",'
            '"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1}}]}]'
        )
    )
    second_content = _wrapped_v2(
        providers_json=(
            '[{"id":"second","name":"Second","api_pattern":"second",'
            '"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":2}}]}]'
        )
    )

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert timeout is not None
        if url.endswith('/first'):
            first_started.set()
            assert allow_first_return.wait(timeout=5)
            return Response(first_content)
        assert url.endswith('/second')
        return Response(second_content)

    monkeypatch.setattr(httpx2, 'get', fake_get)
    first_update = UpdatePrices(url='https://example.test/first')
    second_update = UpdatePrices(url='https://example.test/second')

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(first_update.fetch)
        assert first_started.wait(timeout=5)
        second_snapshot = second_update.fetch()
        allow_first_return.set()
        first_result = first_future.result(timeout=5)

    assert second_snapshot is not None
    assert first_result is second_snapshot
    assert _active_snapshot() is second_snapshot
    assert second_snapshot.find_provider(None, 'second', None).id == 'second'


def test_update_prices_later_failed_fetch_supersedes_pending_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = runtime_state.get_runtime_data()
    first_started = threading.Event()
    allow_first_return = threading.Event()

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert timeout is not None
        if url.endswith('/first'):
            first_started.set()
            assert allow_first_return.wait(timeout=5)
            return Response(_wrapped_v2())
        assert url.endswith('/invalid')
        return Response(b'null')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    first_update = UpdatePrices(url='https://example.test/first')
    failed_update = UpdatePrices(url='https://example.test/invalid')

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(first_update.fetch)
        assert first_started.wait(timeout=5)
        with pytest.raises(ValueError):
            failed_update.fetch()
        allow_first_return.set()
        first_result = first_future.result(timeout=5)

    assert first_result is previous.snapshot
    assert runtime_state.get_runtime_data() is previous


def test_update_prices_stop_restores_bundled_providers_and_preserves_fetched_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_v2())
    update_prices = UpdatePrices(url='https://example.test/prices.json')
    snapshot = update_prices.fetch()
    fetched_registry = _get_registry()

    assert fetched_registry is not bundled
    assert _active_snapshot() is snapshot

    update_prices.stop()

    assert _get_registry() is fetched_registry
    assert _active_snapshot() is _bundled_snapshot()


def test_update_prices_stop_restores_registry_after_in_flight_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class Response:
        content = _wrapped_v2()

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
            with pytest.raises(RuntimeError, match='UpdatePrices is stopping'):
                update_prices.fetch()
            allow_fetch_return.set()
            stop_future.result(timeout=5)

        assert _get_registry() is bundled
        assert _active_snapshot() is _bundled_snapshot()
    finally:
        allow_fetch_return.set()
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_custom_snapshot_after_stop_begins_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class Response:
        content = _wrapped_v2()

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
    custom_snapshot = data_snapshot.DataSnapshot([], from_auto_update=False)
    update_prices.start()
    try:
        assert fetch_started.wait(timeout=5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            stop_future = executor.submit(update_prices.stop)
            assert update_prices._stop_event.wait(timeout=5)
            data_snapshot.set_custom_snapshot(custom_snapshot)
            allow_fetch_return.set()
            stop_future.result(timeout=5)

        assert _active_snapshot() is custom_snapshot
    finally:
        allow_fetch_return.set()
        update_prices.stop()


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed():
    assert _active_snapshot() is _bundled_snapshot()
    with UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404') as update_prices:
        with pytest.raises(httpx2.HTTPStatusError):
            update_prices.wait()
    assert _active_snapshot() is _bundled_snapshot()


@pytest.mark.default_cassette('fail.yaml')
@pytest.mark.vcr()
def test_update_prices_failed_stop():
    bundled = _get_registry()
    assert _active_snapshot() is _bundled_snapshot()
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx2.HTTPStatusError):
        update_prices.stop()
    assert _get_registry() is bundled
    assert _active_snapshot() is _bundled_snapshot()


def test_update_prices_multiple(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _wrapped_v2())
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            UpdatePrices().start()
