from datetime import datetime
from typing import Any

import dirty_equals
import pytest


def IsNow(**kwargs: Any) -> datetime:
    kwargs.setdefault('delta', 10)
    return dirty_equals.IsNow(**kwargs)  # pyright: ignore[reportReturnType]


@pytest.fixture
def anyio_backend():
    return 'asyncio'
