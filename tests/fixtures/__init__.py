"""Trimmed recordings of the upstream payloads the `prices.source_*` importers read.

Each `.json` here is a real response with all but a handful of entries removed, so the importer tests
decode the shape upstream actually sends without carrying a full payload (364 OpenRouter models, 2986
LiteLLM entries) in the repo. Every importer test that would otherwise reach the network reads one of
these instead — no test in this suite makes a live call.

Refresh a fixture by re-downloading the source URL named in the matching `prices/src/prices/source_*.py`
and keeping the same entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
from pydantic import TypeAdapter

from prices import source_prices

fixtures_dir = Path(__file__).parent

_mapping_schema = TypeAdapter(dict[str, object])
_entries_schema = TypeAdapter(list[dict[str, object]])


def load_payload(name: str) -> bytes:
    """Raw fixture bytes, for feeding straight into `model_validate_json`."""
    return (fixtures_dir / name).read_bytes()


def load_mapping(name: str) -> dict[str, object]:
    """The fixture decoded as a plain JSON object, bypassing any importer schema."""
    return _mapping_schema.validate_json(load_payload(name))


def load_entries(name: str, key: str) -> list[dict[str, object]]:
    """The raw entry list under `key`, for counting entries *before* an importer schema sees them."""
    return _entries_schema.validate_python(load_mapping(name)[key])


@dataclass
class FakeResponse:
    """Stands in for an `httpx2.Response` across the `.content` / `.raise_for_status()` surface the
    importers actually use."""

    content: bytes

    def raise_for_status(self) -> None:
        pass


def mock_httpx_get(monkeypatch: pytest.MonkeyPatch, *, expected_url: str, content: bytes) -> None:
    """Serve `content` for the importer's one GET, and fail loudly if it asks for a different URL."""

    def fake_get(url: str) -> FakeResponse:
        assert url == expected_url, f'unexpected URL {url!r}'
        return FakeResponse(content=content)

    monkeypatch.setattr(httpx2, 'get', fake_get)


def capture_source_prices(monkeypatch: pytest.MonkeyPatch) -> dict[str, source_prices.SourcePricesType]:
    """Let an importer run end-to-end while capturing what it would write to `source_prices/*.json`.

    The importers are only reachable through functions that write generated files, so intercepting the
    write is what makes the real mapping code testable without touching the repo's generated data.
    """
    written: dict[str, source_prices.SourcePricesType] = {}

    def fake_write(source: str, prices: source_prices.SourcePricesType) -> None:
        written[source] = prices

    monkeypatch.setattr(source_prices, 'write_source_prices', fake_write)
    return written
