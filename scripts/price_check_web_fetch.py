"""Bind gh-aw's proxy-aware fetcher to the manifest's official HTTPS origins."""

import asyncio
import json
import re
import time
from pathlib import Path

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelRetry
from typing_extensions import TypedDict

from scripts.price_check_coverage import record_fetch, start_fetch
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
    if (
        type(start_index) is not int
        or type(max_length) is not int
        or not 0 <= start_index <= 9_007_199_254_740_991
        or not 1 <= max_length <= 20_000
    ):
        raise ModelRetry('start_index must be a nonnegative safe integer; max_length must be between 1 and 20000')
    attempt_id = start_fetch(url, start_index, max_length)
    completion: dict[str, object] = {'type': 'finish', 'attempt_id': attempt_id, 'outcome': 'error'}
    process: asyncio.subprocess.Process | None = None
    try:
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
            completion['error_kind'] = 'invalid_response_or_execution'
            if match := re.match(rb'web_fetch received HTTP ([0-9]{3}) ', stderr):
                completion['error_kind'] = 'transport'
                completion['http_status'] = int(match[1])
            raise ModelRetry(stderr.decode().strip())
        page = page_adapter.validate_json(stdout)
        if (
            not 100 <= page['status'] <= 599
            or page['start_index'] != start_index
            or not 0 <= page['start_index'] <= page['end_index'] <= page['total_length'] <= 9_007_199_254_740_991
            or page['truncated'] != (page['end_index'] < page['total_length'])
        ):
            raise ModelRetry('web_fetch returned invalid pagination metadata')
        completion.update({key: value for key, value in page.items() if key not in {'url', 'content', 'content_type'}})
        completion['outcome'] = 'response'
        return page
    except asyncio.CancelledError:
        completion['error_kind'] = 'cancelled'
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        raise
    except Exception:
        completion.setdefault('error_kind', 'invalid_response_or_execution')
        raise
    finally:
        completion['time_ms'] = int(time.time() * 1000)
        record_fetch(completion)
