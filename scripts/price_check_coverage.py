"""Snapshot weekly scope and record content-free fetch metadata."""

import json
import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from scripts.price_check_sources import (
    DEFAULT_ROOT,
    load_provider_sources,
    pending_backfill_rows,
    weekly_provider_sources,
)

FETCH_LEDGER = Path('/tmp/gh-aw/agent/price-check-fetch-attempts.jsonl')
PROVIDER_RESULTS = Path('/tmp/gh-aw/agent/provider-results.json')
_RESULT_LOCK = threading.Lock()
Count = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class SourceAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str
    status: Literal['readable', 'unreadable', 'unresolved']


class BackfillAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    status: Literal['checked', 'partial', 'unresolved']


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider_id: str
    status: Literal['checked', 'partial', 'unresolved']
    sources: list[SourceAssessment]
    backfill: list[BackfillAssessment]
    price_changes: Count
    new_models: Count
    potential_removals: Count
    unchecked_fields: Count
    deferred_changes: Count


class ProviderResults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    providers: list[ProviderResult]


def read_bounded(file: Path, limit: int) -> str:
    descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Invalid coverage file')
        content = os.read(descriptor, limit + 1)
        if len(content) != info.st_size or len(content) > limit:
            raise ValueError('Invalid coverage file')
        return content.decode()
    finally:
        os.close(descriptor)


def get_coverage_plan() -> str:
    """Read the host's weekly coverage plan, including exact sources and selected rollout requests, as JSON.

    Call this function from run_code. The sandbox's own environment and scratch filesystem do not contain this plan.
    """
    directory = coverage_directory()
    if directory is None:
        raise ValueError('Weekly coverage plan unavailable')
    return read_bounded(directory / 'plan.json', 256 * 1024)


def record_provider_result(result: ProviderResult) -> str:
    """Save one provider assessment on the host for the durable coverage artifact.

    Call after each provider. Replaces that provider's previous assessment while preserving other results.
    Use only provider IDs, source URLs and request IDs from get_coverage_plan. Never include page contents.
    """
    plan = json.loads(get_coverage_plan())
    provider = next((row for row in plan['providers'] if row['provider_id'] == result.provider_id), None)
    if provider is None:
        raise ValueError('Provider is outside the coverage plan')
    urls = [source.url for source in result.sources]
    requests = [request.request_id for request in result.backfill]
    if len(set(urls)) != len(urls) or not set(urls) <= set(provider['sources']):
        raise ValueError('Sources are outside the coverage plan or duplicated')
    if len(set(requests)) != len(requests) or not set(requests) <= {row['request_id'] for row in provider['backfill']}:
        raise ValueError('Requests are outside the coverage plan or duplicated')
    with _RESULT_LOCK:
        try:
            previous = ProviderResults.model_validate_json(read_bounded(PROVIDER_RESULTS, 128 * 1024))
        except FileNotFoundError:
            previous = ProviderResults(providers=[])
        providers = [row for row in previous.providers if row.provider_id != result.provider_id] + [result]
        content = ProviderResults(providers=providers).model_dump_json()
        if len(content.encode()) > 128 * 1024:
            raise ValueError('Provider results exceed the artifact limit')
        PROVIDER_RESULTS.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=PROVIDER_RESULTS.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(content)
            temporary.replace(PROVIDER_RESULTS)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return f'Saved provider result: {result.provider_id}'


def coverage_plan(root: Path, pending: object) -> dict[str, object]:
    """Keep weekly URLs exact and add only the receiver's selected provider scopes."""
    all_providers = {provider.id: provider for provider in load_provider_sources(root)}
    weekly = {provider.id: provider for provider in weekly_provider_sources(root)}
    rows = pending_backfill_rows(pending, set(all_providers))
    providers: list[dict[str, object]] = []
    for provider_id in sorted(set(weekly) | {row.provider_id for row in rows}):
        provider = weekly.get(provider_id) or all_providers.get(provider_id)
        providers.append(
            {
                'provider_id': provider_id,
                'file': provider.file if provider else None,
                'sources': list(provider.sources) if provider else [],
                'weekly': provider_id in weekly,
                'backfill': [row.model_dump() for row in rows if row.provider_id == provider_id],
            }
        )
    return {'schema_version': 1, 'providers': providers}


def coverage_directory() -> Path | None:
    """Enable recording only when the weekly preflight installed a coverage plan."""
    directory = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'gh-aw/price-check-coverage'
    return directory if (directory / 'plan.json').is_file() else None


def record_fetch(event: dict[str, object]) -> None:
    """Append one small event; never record response content or exception text."""
    try:
        if coverage_directory() is None:
            return
        FETCH_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with FETCH_LEDGER.open('a') as output:
            output.write(json.dumps(event, separators=(',', ':')) + '\n')
    except OSError as exc:
        print(f'Price-check coverage ledger unavailable: {type(exc).__name__}', file=sys.stderr)


def start_fetch(url: str, start_index: int, max_length: int) -> str:
    """Identify exact required URLs without persisting arbitrary tool input URLs."""
    attempt_id = uuid4().hex
    try:
        directory = coverage_directory()
        if directory is not None:
            plan = json.loads((directory / 'plan.json').read_text())
            sources = {source for provider in plan['providers'] for source in provider['sources']}
            record_fetch(
                {
                    'type': 'start',
                    'attempt_id': attempt_id,
                    'source': url if url in sources else None,
                    'start_index': start_index,
                    'max_length': max_length,
                    'time_ms': int(time.time() * 1000),
                }
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Price-check coverage plan unavailable: {type(exc).__name__}', file=sys.stderr)
    return attempt_id


if __name__ == '__main__':
    print(json.dumps(coverage_plan(DEFAULT_ROOT, json.loads(os.environ.get('PRICE_CHECK_PENDING_BACKFILL', '[]')))))
