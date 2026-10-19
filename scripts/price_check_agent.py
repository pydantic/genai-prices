"""Price Check tools composed for the public CLAI 2 gh-aw engine."""

import os

from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace, WebFetch
from pydantic_ai_harness import Coder

from scripts.price_check_web_fetch import web_fetch

SHELL_ENV_NAMES = frozenset(
    {
        'ALL_PROXY',
        'CI',
        'GIT_AUTHOR_EMAIL',
        'GIT_AUTHOR_NAME',
        'GIT_COMMITTER_EMAIL',
        'GIT_COMMITTER_NAME',
        'GITHUB_ACTIONS',
        'GITHUB_REPOSITORY',
        'GITHUB_WORKSPACE',
        'GOMODCACHE',
        'GOPATH',
        'GOROOT',
        'GOTOOLCHAIN',
        'HTTP_PROXY',
        'HTTPS_PROXY',
        'NODE_EXTRA_CA_CERTS',
        'NODE_PATH',
        'NO_PROXY',
        'PRICE_CHECK_SCOPE_COMMAND',
        'REQUESTS_CA_BUNDLE',
        'RUNNER_TEMP',
        'SSL_CERT_FILE',
        'UV_CACHE_DIR',
        'UV_FROZEN',
        'UV_PYTHON',
        'all_proxy',
        'http_proxy',
        'https_proxy',
        'no_proxy',
    }
)

agent = Agent(
    name='price-check',
    capabilities=[
        LocalWorkspace(
            '.',
            env={name: value for name, value in os.environ.items() if name in SHELL_ENV_NAMES},
        ),
        Coder(sub_agents=False),
        WebFetch(native=False, local=web_fetch),
    ],
)
