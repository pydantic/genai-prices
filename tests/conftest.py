import pytest

import genai_prices.sources


@pytest.fixture(autouse=True)
def reset_cache():
    genai_prices.sources._cached_auto_update_snapshot = None


@pytest.fixture
def anyio_backend():
    return 'asyncio'
