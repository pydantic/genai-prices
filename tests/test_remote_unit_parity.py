from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

from genai_prices import UpdatePrices, Usage, data_snapshot
from genai_prices.types import ModelPrice, UsageExtractorMapping
from genai_prices.units import _get_registry


def test_python_remote_unit_parity_fixture_fetch_customization_and_atomicity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = Path('tests/fixtures/remote-unit-v3.json').read_bytes()
    response_content = payload

    class Response:
        content: bytes

        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

    def fake_get(_url: str, *, timeout: httpx2.Timeout) -> Response:
        assert timeout is not None
        return Response(response_content)

    monkeypatch.setattr(httpx2, 'get', fake_get)
    bundled_registry = _get_registry()
    bundled_snapshot = data_snapshot.get_snapshot()
    fetched = UpdatePrices(url='https://example.test/remote-unit-v3.json').fetch()
    assert fetched is not None
    assert fetched._activation_registry is not None
    assert _get_registry() is bundled_registry
    assert data_snapshot.get_snapshot() is bundled_snapshot

    provider = fetched.providers[0]
    model_prices = provider.models[0].prices
    assert isinstance(model_prices, ModelPrice)
    model_prices.remote_events_kcount = Decimal(2)  # pyright: ignore[reportAttributeAccessIssue]
    assert provider.extractors is not None
    provider.extractors[0].mappings.append(UsageExtractorMapping(path='ignored', dest='input_tokens', required=False))

    try:
        data_snapshot.set_custom_snapshot(fetched)
        assert _get_registry() is fetched._activation_registry

        extracted = fetched.extract_usage(
            {'model': 'remote-model', 'usage': {'events': 500}},
            provider_id='remote-alias',
        )
        assert extracted.usage == Usage(remote_events=500)
        assert extracted.provider.id == 'remote-fixture'
        assert extracted.model is not None and extracted.model.id == 'remote-model'

        calculation = fetched.calc(
            Usage(remote_events=500),
            'remote-model',
            'remote-alias',
            None,
            None,
        )
        assert calculation.provider.id == 'remote-fixture'
        assert calculation.model.id == 'remote-model'
        assert calculation.input_price == Decimal(1)
        assert calculation.output_price == Decimal(0)
        assert calculation.total_price == Decimal(1)

        invalid = json.loads(payload)
        del invalid['units']['input_tokens']
        response_content = json.dumps(invalid).encode()
        with pytest.raises(ValueError, match='Removed published unit: input_tokens'):
            UpdatePrices(url='https://example.test/invalid-remote-unit-v3.json').fetch()

        assert data_snapshot.get_snapshot() is fetched
        assert _get_registry() is fetched._activation_registry
        assert fetched.calc(Usage(remote_events=500), 'remote-model', 'remote-alias', None, None).total_price == 1
    finally:
        data_snapshot.set_custom_snapshot(None)

    assert _get_registry() is bundled_registry
