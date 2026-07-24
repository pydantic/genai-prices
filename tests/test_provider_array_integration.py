from __future__ import annotations

import json
from decimal import Decimal

import httpx2
import pytest

from genai_prices import UpdatePrices, calc_price, data_units, runtime_state
from genai_prices.types import Usage


def test_python_wrapped_v2_dynamic_price_key_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        content = json.dumps({'units': data_units.unit_data, 'providers': _provider_array()}).encode()

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, timeout: httpx2.Timeout) -> Response:
        assert url == 'https://example.test/prices.json'
        assert timeout is not None
        return Response()

    monkeypatch.setattr(httpx2, 'get', fake_get)

    initial = runtime_state.get_runtime_data()
    try:
        UpdatePrices(url='https://example.test/prices.json').fetch()
        price = calc_price(
            Usage(
                cache_image_read_tokens=1_000_000,
                cache_read_tokens=1_000_000,
                input_image_tokens=1_000_000,
                input_tokens=1_000_000,
            ),
            model_ref='image-cache',
            provider_id='testing',
        )

        assert price.total_price == Decimal('4')
    finally:
        generation = runtime_state.begin_update()
        runtime_state.activate_runtime_data(generation, initial)


def _provider_array() -> list[object]:
    return [
        {
            'id': 'testing',
            'name': 'Testing',
            'api_pattern': 'testing',
            'models': [
                {
                    'id': 'image-cache',
                    'match': {'equals': 'image-cache'},
                    'prices': {
                        'input_mtok': 1,
                        'cache_read_mtok': 2,
                        'input_image_mtok': 3,
                        'cache_image_read_mtok': 4,
                    },
                }
            ],
        }
    ]
