"""Temporary AWF diagnostic: exercise the registered fetcher before model use."""

import asyncio
import json
import sys

from scripts.price_check_web_fetch import web_fetch


async def check() -> None:
    page = await web_fetch('https://developers.openai.com/api/docs/pricing.md')
    print(
        json.dumps({key: page[key] for key in ['url', 'status', 'total_length', 'truncated']}),
        file=sys.stderr,
        flush=True,
    )
    if page['status'] != 200 or not page['content']:
        raise RuntimeError('Official pricing source was not fetched successfully')
    while page['truncated']:
        tail = await web_fetch(page['url'], start_index=page['end_index'])
        if not tail['content'] or tail['end_index'] <= page['end_index']:
            raise RuntimeError('Official pricing source pagination was incomplete')
        page = tail
    print(json.dumps({'pagination': 'complete', 'total_chars': page['end_index']}), file=sys.stderr, flush=True)


asyncio.run(check())
raise SystemExit(0)
