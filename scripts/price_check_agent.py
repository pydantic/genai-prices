"""Price Check tools composed for the public CLAI 2 gh-aw engine."""

import os
from fnmatch import fnmatchcase

from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace, WebFetch
from pydantic_ai_harness import Coder
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

from scripts.price_check_web_fetch import web_fetch

agent = Agent(
    name='price-check',
    capabilities=[
        LocalWorkspace(
            '.',
            env={
                name: value
                for name, value in os.environ.items()
                if name != 'GH_AW_SESSION_FRAME_KEY'
                and not any(fnmatchcase(name, pattern) for pattern in LLM_API_KEY_ENV_PATTERNS)
            },
        ),
        Coder(sub_agents=False),
        WebFetch(native=False, local=web_fetch),
    ],
)
