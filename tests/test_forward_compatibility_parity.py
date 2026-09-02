from __future__ import annotations

import json
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest

from genai_prices import UpdatePrices, Usage, data_snapshot
from genai_prices.units import _get_registry

EXPECTED_WARNINGS = (
    "Unsupported match variant at providers[0].model_match for provider 'future-fixture'; upgrade genai-prices for full support",
    "Unsupported extractor variant at providers[0].extractors[1] for provider 'future-fixture'; upgrade genai-prices for full support",
    "Unsupported price variant at providers[0].models[0].prices[0].prices.cache_read_mtok for provider 'future-fixture', model 'future-model'; upgrade genai-prices for full support",
    "Unsupported constraint variant at providers[0].models[0].prices[1].constraint for provider 'future-fixture', model 'future-model'; upgrade genai-prices for full support",
    "Unsupported match variant at providers[0].models[1].match for provider 'future-fixture', model 'unsupported-model'; upgrade genai-prices for full support",
)


def test_python_forward_compatible_projection_and_malformed_atomicity(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _read_json('forward-compatible-v3.json')
    malformed = _read_json('malformed-recognized-v3.json')
    response_content = json.dumps(fixture).encode()

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

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        fetched = UpdatePrices(url='https://example.test/forward-compatible-v3.json').fetch()

    assert fetched is not None
    assert tuple(str(item.message) for item in caught) == EXPECTED_WARNINGS
    assert _get_registry() is bundled_registry
    assert data_snapshot.get_snapshot() is bundled_snapshot
    assert len(fetched.providers) == 1
    provider = fetched.providers[0]
    assert provider.id == 'future-fixture'
    assert len(provider.models) == 1 and provider.models[0].id == 'future-model'
    assert provider.extractors is not None and len(provider.extractors) == 1
    assert len(provider.extractors[0].mappings) == 2

    try:
        data_snapshot.set_custom_snapshot(fetched)
        assert fetched.find_provider(None, 'future-alias', None) is provider
        extracted = fetched.extract_usage(
            {'model': 'future-model', 'usage': {'input': 1_000_000, 'output': 1_000_000}},
            provider_id='future-alias',
        )
        assert extracted.usage == Usage(input_tokens=1_000_000, output_tokens=1_000_000)

        before_change = fetched.calc(
            extracted.usage,
            'future-model',
            'future-alias',
            None,
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert before_change.input_price == Decimal(1)
        assert before_change.output_price == Decimal(2)
        assert before_change.total_price == Decimal(3)
        after_change = fetched.calc(
            extracted.usage,
            'future-model',
            'future-alias',
            None,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert after_change.input_price == Decimal(3)
        assert after_change.output_price == Decimal(4)
        assert after_change.total_price == Decimal(7)

        invalid_constraint = deepcopy(fixture)
        invalid_constraint['providers'][0]['models'][0]['prices'][2]['constraint'] = malformed['constraint']
        response_content = json.dumps(invalid_constraint).encode()
        with warnings.catch_warnings(record=True) as invalid_warnings:
            warnings.simplefilter('always')
            with pytest.raises(ValueError, match='Invalid provider data at providers'):
                UpdatePrices(url='https://example.test/malformed-constraint-v3.json').fetch()
        assert invalid_warnings == []

        invalid_extractor = deepcopy(fixture)
        invalid_extractor['providers'][0]['extractors'][0] = malformed['extractor']
        response_content = json.dumps(invalid_extractor).encode()
        with warnings.catch_warnings(record=True) as invalid_warnings:
            warnings.simplefilter('always')
            with pytest.raises(ValueError, match='Invalid provider data at providers'):
                UpdatePrices(url='https://example.test/malformed-extractor-v3.json').fetch()
        assert invalid_warnings == []

        assert data_snapshot.get_snapshot() is fetched
        assert _get_registry() is fetched._activation_registry
        assert (
            fetched.calc(
                Usage(input_tokens=1_000_000, output_tokens=1_000_000),
                'future-model',
                'future-alias',
                None,
                datetime(2025, 1, 1, tzinfo=timezone.utc),
            ).total_price
            == 3
        )
    finally:
        data_snapshot.set_custom_snapshot(None)

    assert _get_registry() is bundled_registry


def _read_json(name: str) -> dict[str, Any]:
    return json.loads(Path('tests/fixtures', name).read_bytes())
