"""Temporary AWF diagnostic: exercise WebFetch before any model request."""

import asyncio
import json
import os
import ssl
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import httpx2

from pydantic_ai.common_tools.web_fetch import web_fetch_tool


async def check() -> None:
    names = ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS')
    paths = dict.fromkeys([os.environ[name] for name in names if os.environ.get(name)])
    paths['/etc/ssl/certs/ca-certificates.crt'] = None
    paths['/run/awf-lib/awf-ca.crt'] = None
    for path in Path('/usr/local/share/ca-certificates').glob('*.crt'):
        paths[str(path)] = None
    versions = {}
    for name in ['pydantic-ai-slim', 'httpx', 'httpcore', 'httpx2', 'httpcore2']:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            continue
    print(
        json.dumps(
            {
                'versions': versions,
                'trust_environment': {name: os.environ.get(name) for name in names},
                'default_verify_paths': ssl.get_default_verify_paths()._asdict(),
                'available_bundles': {path: Path(path).is_file() for path in paths},
            }
        ),
        file=sys.stderr,
        flush=True,
    )
    try:
        async with httpx2.AsyncClient() as client:
            response = await client.get('https://developers.openai.com/api/docs/pricing.md')
            stream = response.extensions.get('network_stream')
            tls = stream.get_extra_info('ssl_object') if stream else None
            peer = tls.getpeercert() if tls else None
            print(
                json.dumps({'direct_httpx2_status': response.status_code, 'peer_certificate': peer}),
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:
        print(json.dumps({'direct_httpx2_error': str(exc)}), file=sys.stderr, flush=True)
    fetch = web_fetch_tool().function
    for bundle in [None, *paths]:
        if bundle is not None:
            if not Path(bundle).is_file():
                continue
            os.environ['SSL_CERT_FILE'] = bundle
        try:
            result = await fetch(url='https://developers.openai.com/api/docs/pricing.md')
            print(
                json.dumps({'bundle': bundle, 'status': 'success', 'content_chars': len(result['content'])}),
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            print(json.dumps({'bundle': bundle, 'status': 'failed', 'error': str(exc)}), file=sys.stderr, flush=True)


asyncio.run(check())
raise SystemExit(0)
