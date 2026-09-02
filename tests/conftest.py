import threading

import pytest

from genai_prices.data_snapshot import set_custom_snapshot


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture(autouse=True)
def reset_price_updates():
    # UpdatePrices.stop() never joins its thread and leaves fetched prices in place; join any
    # thread still finishing a fetch and restore the bundled prices so tests stay independent.
    yield
    for thread in threading.enumerate():
        if thread.name == 'genai_prices:update':  # pragma: no cover - only hit when a fetch is still in flight
            thread.join(timeout=5)
    set_custom_snapshot(None)
