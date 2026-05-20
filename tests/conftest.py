from datetime import datetime
from typing import Any

import dirty_equals
import pytest


def IsNow(**kwargs: Any) -> datetime:  # pragma: no cover
    kwargs.setdefault('delta', 10)
    return dirty_equals.IsNow(**kwargs)  # pyright: ignore[reportReturnType]


@pytest.fixture
def anyio_backend():
    return 'asyncio'
