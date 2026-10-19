"""Bind gh-aw's proxy-aware fetcher to the manifest's official HTTPS origins."""

import asyncio
import json
from pathlib import Path

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelRetry
from typing_extensions import TypedDict

from scripts.price_check_sources import DEFAULT_ROOT, official_source_hosts


class WebFetchResult(TypedDict):
    url: str
    status: int
    content_type: str
    start_index: int
    end_index: int
    total_length: int
    truncated: bool
    content: str


page_adapter = TypeAdapter(WebFetchResult)
allowed_hosts = official_source_hosts(DEFAULT_ROOT)


async def web_fetch(url: str, start_index: int = 0, max_length: int = 20_000) -> WebFetchResult:
    """Fetch an official HTTPS source through AWF. Use start_index to continue truncated pages; max_length is at most 20000."""
    process = await asyncio.create_subprocess_exec(
        'node',
        str(Path(__file__).with_suffix('.cjs')),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(
        json.dumps(
            {'url': url, 'start_index': start_index, 'max_length': max_length, 'allowedHosts': allowed_hosts}
        ).encode()
    )
    if process.returncode:
        raise ModelRetry(stderr.decode().strip())
    return page_adapter.validate_json(stdout)
