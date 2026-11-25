import threading
from collections.abc import Iterator
from pathlib import Path
from shutil import copyfile

import pytest
import time_machine

from genai_prices.data_snapshot import set_custom_snapshot

from .fixtures import IMPORT_TIME, ProviderSnapshot, provider_snapshots_dir


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


@pytest.fixture
def provider_snapshot(tmp_path: Path) -> Iterator[ProviderSnapshot]:
    """Copy a provider YAML snapshot into `tmp_path`, with the clock frozen at `IMPORT_TIME`."""
    with time_machine.travel(IMPORT_TIME, tick=False):
        yield lambda name: copyfile(provider_snapshots_dir / name, tmp_path / name)
