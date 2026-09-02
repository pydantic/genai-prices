from __future__ import annotations

import concurrent.futures
import json
import threading
import warnings
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
    wait_prices_updated_async,
    wait_prices_updated_sync,
)
from genai_prices.data_units import unit_data
from genai_prices.types import ModelPrice, UsageExtractor, UsageExtractorMapping, _providers_from_raw
from genai_prices.units import UnitRegistry, _get_registry

pytestmark = pytest.mark.anyio


def _provider_array(*, providers_json: str | None = None) -> bytes:
    providers_json = providers_json or (
        '[{"id":"openai","name":"OpenAI","api_pattern":"https://api\\\\.openai\\\\.com",'
        '"models":[{"id":"gpt-4o","match":{"equals":"gpt-4o"},'
        '"prices":{"input_mtok":2.5,"output_mtok":10}}]}]'
    )
    return providers_json.encode()


def _remote_provider() -> dict[str, object]:
    return {
        'id': 'remote',
        'name': 'Remote',
        'api_pattern': 'remote',
        'extractors': [
            {
                'root': 'usage',
                'mappings': [{'path': 'count', 'dest': 'remote_events'}],
            }
        ],
        'models': [
            {
                'id': 'remote-model',
                'match': {'equals': 'remote-model'},
                'prices': {'remote_event_price': 2},
            }
        ],
    }


def _wrapped_provider_data(*, providers: list[object] | None = None) -> bytes:
    units = deepcopy(unit_data)
    units['remote_events'] = {
        'per': 1,
        'price_key': 'remote_event_price',
        'dimensions': {'family': 'remote_events'},
    }
    return json.dumps({'units': units, 'providers': providers or [_remote_provider()]}).encode()


class NullUpdatePrices(UpdatePrices):
    def fetch(self) -> data_snapshot.DataSnapshot | None:
        return None


class CountingNullUpdatePrices(UpdatePrices):
    count = 0

    def fetch(self) -> data_snapshot.DataSnapshot | None:
        self.count += 1
        return None


def _mock_update_prices_get(monkeypatch: pytest.MonkeyPatch, content: bytes = _provider_array()) -> None:
    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url in {
            'https://example.test/prices.json',
            'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/new_data/v3/data.json',
        }
        assert timeout is not None
        return Response(content)

    monkeypatch.setattr(httpx2, 'get', fake_get)


def test_update_prices_fetch_preserves_registry_when_provider_parsing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, _provider_array(providers_json='[{"id":"missing-required-fields"}]'))

    with pytest.raises(Exception):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


@pytest.mark.parametrize('content', [b'{"providers":[]}', b'null', b'"providers"', b'1'])
def test_update_prices_fetch_rejects_invalid_payload_without_registry_change(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    previous = _get_registry()
    _mock_update_prices_get(monkeypatch, content)

    with pytest.raises(ValueError, match='Invalid provider data'):
        UpdatePrices(url='https://example.test/prices.json').fetch()

    assert _get_registry() is previous


def test_update_prices_fetch_parses_provider_array_without_registry_change(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _provider_array())

    snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert snapshot is not None
    assert snapshot.from_auto_update is True
    provider, model = snapshot.find_provider_model('gpt-4o', None, 'openai', None)
    assert provider.id == 'openai'
    assert model.id == 'gpt-4o'
    assert _get_registry() is bundled


def test_update_prices_fetch_prepares_wrapped_snapshot_without_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled_registry = _get_registry()
    bundled_snapshot = data_snapshot.get_snapshot()
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data())

    fetched = UpdatePrices(url='https://example.test/prices.json').fetch()

    assert fetched is not None
    assert fetched._activation_registry is not None
    assert 'remote_events' in fetched._activation_registry.units
    assert _get_registry() is bundled_registry
    assert data_snapshot.get_snapshot() is bundled_snapshot
    with pytest.warns(UserWarning, match='Unsupported usage key.*remote_events'):
        pending_usage = Usage(remote_events=3)
    with pytest.warns(UserWarning, match='Unsupported price key.*remote_event_price'):
        assert fetched.calc(pending_usage, 'remote-model', 'remote', None, None).total_price == 0

    try:
        data_snapshot.set_custom_snapshot(fetched)
        assert _get_registry() is fetched._activation_registry
        assert fetched.calc(Usage(remote_events=3), 'remote-model', 'remote', None, None).total_price == Decimal(6)
        extracted = fetched.extract_usage(
            {'model': 'remote-model', 'usage': {'count': 4}},
            provider_id='remote',
        )
        assert extracted.usage == Usage(remote_events=4)
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_background_activates_wrapped_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled_registry = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data())
    update_prices = UpdatePrices(url='https://example.test/prices.json', update_interval=3600)

    try:
        update_prices.start(wait=True)
        active_snapshot = data_snapshot.get_snapshot()

        assert active_snapshot.from_auto_update is True
        assert _get_registry() is not bundled_registry
        assert active_snapshot.calc(
            Usage(remote_events=2), 'remote-model', 'remote', None, None
        ).total_price == Decimal(4)
    finally:
        update_prices.stop()
        data_snapshot.set_custom_snapshot(None)

    assert _get_registry() is bundled_registry


def test_update_prices_fetch_emits_compatibility_warnings_only_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _remote_provider()
    provider['provider_match'] = {'future_match': 'remote'}
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data(providers=[provider]))

    with pytest.warns(UserWarning, match=r'providers\[0\]\.provider_match.*upgrade genai-prices'):
        snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()
    assert snapshot is not None

    provider.pop('name')
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data(providers=[provider]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with pytest.raises(ValueError, match='name'):
            UpdatePrices(url='https://example.test/prices.json').fetch()
    assert caught == []


def test_update_prices_fetch_preserves_transport_http_and_json_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_error = httpx2.ConnectError('transport failed')

    def transport_failure(_url: str, *, timeout: httpx2.Timeout) -> None:
        assert timeout is not None
        raise transport_error

    monkeypatch.setattr(httpx2, 'get', transport_failure)
    with pytest.raises(httpx2.ConnectError) as transport_info:
        UpdatePrices(url='https://example.test/prices.json').fetch()
    assert transport_info.value is transport_error

    request = httpx2.Request('GET', 'https://example.test/prices.json')
    http_error = httpx2.HTTPStatusError(
        'status failed', request=request, response=httpx2.Response(500, request=request)
    )

    class HttpFailureResponse:
        content = b'[]'

        def raise_for_status(self) -> None:
            raise http_error

    def http_failure(_url: str, *, timeout: httpx2.Timeout) -> HttpFailureResponse:
        assert timeout is not None
        return HttpFailureResponse()

    monkeypatch.setattr(httpx2, 'get', http_failure)
    with pytest.raises(httpx2.HTTPStatusError) as http_info:
        UpdatePrices(url='https://example.test/prices.json').fetch()
    assert http_info.value is http_error

    json_error = json.JSONDecodeError('invalid', '!', 0)

    def json_failure(_value: object) -> object:
        raise json_error

    class JsonFailureResponse:
        content = b'!'

        def raise_for_status(self) -> None:
            pass

    def json_response(_url: str, *, timeout: httpx2.Timeout) -> JsonFailureResponse:
        assert timeout is not None
        return JsonFailureResponse()

    monkeypatch.setattr(httpx2, 'get', json_response)
    monkeypatch.setattr(json, 'loads', json_failure)
    with pytest.raises(json.JSONDecodeError) as json_info:
        UpdatePrices(url='https://example.test/prices.json').fetch()
    assert json_info.value is json_error


def test_update_prices_invalid_candidate_preserves_active_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    previous_registry = _get_registry()
    previous_snapshot = data_snapshot.DataSnapshot([], from_auto_update=False)
    data_snapshot.set_custom_snapshot(previous_snapshot)
    invalid = json.loads(_wrapped_provider_data())
    assert isinstance(invalid, dict)
    invalid['units'] = {}
    _mock_update_prices_get(monkeypatch, json.dumps(invalid).encode())

    try:
        with pytest.raises(ValueError, match='Removed published unit'):
            UpdatePrices(url='https://example.test/prices.json').fetch()
        assert _get_registry() is previous_registry
        assert data_snapshot.get_snapshot() is previous_snapshot
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_activation_rechecks_append_only_evolution(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled_registry = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data())
    fetched = UpdatePrices(url='https://example.test/prices.json').fetch()
    assert fetched is not None

    intervening_registry = UnitRegistry._from_untrusted(
        {
            **unit_data,
            'intervening_events': {
                'per': 1,
                'price_key': 'intervening_event_price',
                'dimensions': {'family': 'intervening_events'},
            },
        }
    )
    intervening_snapshot = data_snapshot.DataSnapshot._from_wrapped(
        _providers_from_raw([_remote_provider()]), True, intervening_registry
    )

    try:
        data_snapshot.set_custom_snapshot(intervening_snapshot)
        with pytest.raises(ValueError, match='Removed published unit: intervening_events'):
            data_snapshot.set_custom_snapshot(fetched)
        assert _get_registry() is intervening_registry
        assert data_snapshot.get_snapshot() is intervening_snapshot
    finally:
        data_snapshot.set_custom_snapshot(None)

    assert _get_registry() is bundled_registry


def test_update_prices_fetch_override_reapplies_lazy_customizations_on_each_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled_registry = _get_registry()
    _mock_update_prices_get(monkeypatch, _wrapped_provider_data())

    class CustomUpdatePrices(UpdatePrices):
        fetched_snapshots: list[data_snapshot.DataSnapshot]

        def __init__(self) -> None:
            super().__init__(url='https://example.test/prices.json')
            self.fetched_snapshots = []

        def fetch(self) -> data_snapshot.DataSnapshot | None:
            fetched = super().fetch()
            assert fetched is not None
            provider = fetched.providers[0]
            model_prices = provider.models[0].prices
            assert isinstance(model_prices, ModelPrice)
            model_prices.remote_event_price = 'invalid custom price'  # pyright: ignore[reportAttributeAccessIssue]
            provider.extractors = [
                UsageExtractor(
                    root='usage',
                    mappings=[
                        UsageExtractorMapping(path='count', dest='remote_events'),
                        UsageExtractorMapping(path='custom_count', dest='custom_events', required=False),
                    ],
                )
            ]
            self.fetched_snapshots.append(fetched)
            return fetched

    updater = CustomUpdatePrices()
    try:
        for refresh_index in range(2):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                fetched = updater.fetch()
            assert caught == []
            assert fetched is not None
            assert fetched is updater.fetched_snapshots[refresh_index]

            data_snapshot.set_custom_snapshot(fetched)
            active_snapshot = data_snapshot.get_snapshot()
            assert active_snapshot is fetched
            assert active_snapshot._activation_registry is _get_registry()
            assert active_snapshot._activation_registry is not None
            assert 'remote_events' in active_snapshot._activation_registry.units
            assert Usage(remote_events=1).remote_events == 1

            with pytest.raises(ValueError, match='Invalid price value for remote_event_price'):
                active_snapshot.calc(Usage(remote_events=1), 'remote-model', 'remote', None, None)
            with pytest.warns(UserWarning, match='Unsupported extractor destination.*custom_events'):
                extracted = active_snapshot.extract_usage(
                    {'model': 'remote-model', 'usage': {'count': 4, 'custom_count': 5}},
                    provider_id='remote',
                )
            assert extracted.usage == Usage(remote_events=4)

        assert updater.fetched_snapshots[0] is not updater.fetched_snapshots[1]
    finally:
        data_snapshot.set_custom_snapshot(None)

    assert _get_registry() is bundled_registry


def test_update_prices_fetch_provider_array_defers_invalid_extractor_without_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        snapshot = UpdatePrices(url='https://example.test/prices.json').fetch()

        assert snapshot is not None
        provider = snapshot.find_provider(None, 'broken', None)
        with pytest.warns(
            UserWarning,
            match='Unsupported extractor destination for standard extraction: imaginary_tokens',
        ):
            provider.extract_usage({'usage': {'tokens': 1}})

        assert provider.id == 'broken'
        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is previous_snapshot
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_fetch_provider_array_does_not_eagerly_validate_unused_model_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    _mock_update_prices_get(monkeypatch, _provider_array())
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
    _mock_update_prices_get(monkeypatch, _provider_array())
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
    _mock_update_prices_get(monkeypatch, _provider_array())
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


def test_update_prices_stop_preserves_bundled_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    _mock_update_prices_get(monkeypatch, _provider_array())
    update_prices = UpdatePrices(url='https://example.test/prices.json')
    snapshot = update_prices.fetch()

    try:
        data_snapshot.set_custom_snapshot(snapshot)
        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is snapshot

        update_prices.stop()

        assert _get_registry() is bundled
        assert data_snapshot._custom_snapshot is None
    finally:
        data_snapshot.set_custom_snapshot(None)


def test_update_prices_stop_restores_registry_after_in_flight_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    bundled = _get_registry()
    fetch_started = threading.Event()
    allow_fetch_return = threading.Event()

    class Response:
        content = _provider_array()

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
    bundled = _get_registry()
    assert data_snapshot._custom_snapshot is None
    update_prices = UpdatePrices(url='https://demo-endpoints.pydantic.workers.dev/bin?status=404')
    update_prices.start()
    with pytest.raises(httpx2.HTTPStatusError):
        update_prices.stop()
    assert _get_registry() is bundled
    assert data_snapshot._custom_snapshot is None


def test_update_prices_multiple(monkeypatch: pytest.MonkeyPatch):
    _mock_update_prices_get(monkeypatch, _provider_array())
    with UpdatePrices():
        with pytest.raises(
            RuntimeError,
            match='UpdatePrices global task already started, only one UpdatePrices can be active at a time',
        ):
            UpdatePrices().start()
