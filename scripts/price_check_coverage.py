"""Snapshot weekly scope and record content-free fetch metadata."""

import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from scripts.price_check_sources import (
    DEFAULT_ROOT,
    load_provider_sources,
    pending_backfill_rows,
    weekly_provider_sources,
)

FETCH_LEDGER = Path('/tmp/gh-aw/agent/price-check-fetch-attempts.jsonl')


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
