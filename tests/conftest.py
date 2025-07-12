from datetime import datetime
from typing import Any

import dirty_equals
import pytest

import genai_prices.sources


def IsNow(**kwargs: Any) -> datetime:
    kwargs.setdefault('delta', 10)
    return dirty_equals.IsNow(**kwargs)  # pyright: ignore[reportReturnType]


@pytest.fixture(autouse=True)
def reset_cache():
    genai_prices.sources._cached_auto_update_snapshot = None


@pytest.fixture
def anyio_backend():
    return 'asyncio'
