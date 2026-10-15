"""Run with the same harness and provider extras as the gh-aw engine."""

import importlib
import json
import os
import unittest
from collections.abc import AsyncIterator
from unittest.mock import patch

from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from scripts import price_check_agent


class PriceCheckAgentTests(unittest.TestCase):
    def test_tools(self) -> None:
        async def inspect_tools(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
            del messages
            self.assertEqual(
                {tool.name for tool in info.function_tools},
                {'read_file', 'write_file', 'edit_file', 'list_files', 'grep', 'shell', 'web_fetch'},
            )
            yield 'checked'

        result = price_check_agent.agent.run_sync('Check tools.', model=FunctionModel(stream_function=inspect_tools))
        self.assertEqual(result.output, 'checked')

    def test_shell_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                'HTTPS_PROXY': 'http://proxy.example:3128',
                'GIT_AUTHOR_NAME': 'Price Check',
                'ANTHROPIC_API_KEY': 'private-provider-key',
                'OPENAI_API_KEY': 'private-provider-key',
                'GH_AW_SESSION_FRAME_KEY': 'private-session-key',
            },
        ):
            agent = importlib.reload(price_check_agent).agent

        async def check_environment(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            del info
            returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
            if not returns:
                yield {
                    0: DeltaToolCall(
                        name='shell',
                        json_args=json.dumps(
                            {
                                'command': "printf '%s|%s|%s|%s|%s' "
                                '"${HTTPS_PROXY-}" "${GIT_AUTHOR_NAME-}" '
                                '"${ANTHROPIC_API_KEY-}" "${OPENAI_API_KEY-}" '
                                '"${GH_AW_SESSION_FRAME_KEY-}"'
                            }
                        ),
                    )
                }
            else:
                self.assertIn('http://proxy.example:3128|Price Check|||', str(returns[-1].content))
                self.assertNotIn('private-', str(returns[-1].content))
                yield 'checked'

        result = agent.run_sync('Check shell environment.', model=FunctionModel(stream_function=check_environment))
        self.assertEqual(result.output, 'checked')


if __name__ == '__main__':
    unittest.main()
