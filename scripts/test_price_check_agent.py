"""Run with the same harness and provider extras as the gh-aw engine."""

import importlib
import json
import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai_harness import Coder
from pydantic_clai2.runtime.speculation import SpeculationCounters
from pydantic_clai2.runtime.speculative_mode import speculative_capabilities

from scripts import price_check_agent, price_check_coverage


class PriceCheckAgentTests(unittest.TestCase):
    def test_tools(self) -> None:
        async def inspect_tools(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
            del messages
            self.assertEqual(
                {tool.name for tool in info.function_tools},
                {
                    'read_file',
                    'write_file',
                    'edit_file',
                    'list_files',
                    'grep',
                    'shell',
                    'web_fetch',
                    'get_coverage_plan',
                    'record_provider_result',
                },
            )
            yield 'checked'

        result = price_check_agent.agent.run_sync('Check tools.', model=FunctionModel(stream_function=inspect_tools))
        self.assertEqual(result.output, 'checked')

    def test_host_reporting_through_actual_clai_code_mode(self) -> None:
        """Exercise the CLI's eager CodeMode composition without a provider or LLM request."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_file = root / 'gh-aw/price-check-coverage/plan.json'
            plan_file.parent.mkdir(parents=True)
            plan = {
                'schema_version': 1,
                'providers': [
                    {
                        'provider_id': 'openai',
                        'file': 'prices/providers/openai.yml',
                        'sources': ['https://openai.com/api/pricing/'],
                        'weekly': True,
                        'backfill': [
                            {'request_id': 'selected-request', 'target_model': 'gpt-test', 'provider_id': 'openai'}
                        ],
                    }
                ],
            }
            plan_file.write_text(json.dumps(plan))
            catalog_file = root / 'gh-aw/price-check/provider-sources.json'
            catalog_file.parent.mkdir(parents=True)
            catalog_file.write_text('{"proof":"trusted-host-provider-catalog"}')
            result_file = root / 'host/provider-results.json'
            code = """import json
import os
from pathlib import Path
plan = json.loads(await get_coverage_plan())
print('host-plan', plan['providers'][0]['backfill'][0]['target_model'])
print('vfs', os.environ.get('RUNNER_TEMP'), Path(PLAN_PATH).exists())
print(await shell(command='cat "$RUNNER_TEMP/gh-aw/price-check/provider-sources.json"'))
result = {
    'provider_id': 'openai', 'status': 'partial',
    'sources': [{'url': plan['providers'][0]['sources'][0], 'status': 'readable'}],
    'backfill': [{'request_id': 'selected-request', 'status': 'unresolved'}],
    'price_changes': 0, 'new_models': 0, 'potential_removals': 0, 'unchecked_fields': 1, 'deferred_changes': 0,
}
print(await record_provider_result(result=result))
result['provider_id'] = 'outside-plan'
try:
    await record_provider_result(result=result)
except Exception:
    print('out-of-plan rejected')
""".replace('PLAN_PATH', repr(str(plan_file)))

            async def call_code(
                messages: list[ModelMessage],
                info: AgentInfo,
            ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
                returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
                if not returns:
                    self.assertEqual(
                        {tool.name for tool in info.function_tools}, {'write_file', 'edit_file', 'run_code'}
                    )
                    self.assertIn('get_coverage_plan', info.function_tools[-1].description)
                    yield {0: DeltaToolCall(name='run_code', json_args=json.dumps({'code': code}))}
                else:
                    output = str(returns[-1].content)
                    self.assertIn('host-plan gpt-test', output)
                    self.assertIn('vfs None False', output)
                    self.assertIn('Saved provider result: openai', output)
                    self.assertIn('out-of-plan rejected', output)
                    self.assertIn('{"proof":"trusted-host-provider-catalog"}', output)
                    yield 'checked'

            with (
                patch.dict(os.environ, {'RUNNER_TEMP': str(root)}),
                patch.object(price_check_coverage, 'PROVIDER_RESULTS', result_file),
            ):
                host_agent = importlib.reload(price_check_agent).agent
                result = host_agent.run_sync(
                    'Exercise host reporting.',
                    model=FunctionModel(stream_function=call_code),
                    capabilities=speculative_capabilities(
                        SpeculationCounters(),
                        [LocalWorkspace('.'), Coder(sub_agents=False)],
                        speculate=False,
                    ),
                )
            self.assertEqual(result.output, 'checked')
            persisted = json.loads(result_file.read_text())
            self.assertEqual([row['provider_id'] for row in persisted['providers']], ['openai'])
            self.assertEqual(
                persisted['providers'][0]['sources'],
                [
                    {'url': 'https://openai.com/api/pricing/', 'status': 'readable'},
                ],
            )

    def test_shell_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                'HTTPS_PROXY': 'http://proxy.example:3128',
                'GIT_AUTHOR_NAME': 'Price Check',
                'PRICE_CHECK_SCOPE_COMMAND': 'node /tmp/price-check-scope',
                'SSL_CERT_FILE': '/tmp/ca-bundle.pem',
                'ANTHROPIC_API_KEY': 'private-provider-key',
                'OPENAI_API_KEY': 'private-provider-key',
                'GH_AW_SESSION_FRAME_KEY': 'private-session-key',
                'GITHUB_TOKEN': 'private-github-token',
                'GH_AW_GITHUB_TOKEN': 'private-gh-aw-token',
                'SLACK_WEBHOOK_URL': 'private-slack-webhook',
                'LOGFIRE_OTLP_AUTHORIZATION': 'private-logfire-token',
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
                                'command': "printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s' "
                                '"${HTTPS_PROXY-}" "${GIT_AUTHOR_NAME-}" '
                                '"${PRICE_CHECK_SCOPE_COMMAND-}" "${SSL_CERT_FILE-}" '
                                '"${ANTHROPIC_API_KEY-}" "${OPENAI_API_KEY-}" '
                                '"${GH_AW_SESSION_FRAME_KEY-}" "${GITHUB_TOKEN-}" '
                                '"${GH_AW_GITHUB_TOKEN-}" "${SLACK_WEBHOOK_URL-}" '
                                '"${LOGFIRE_OTLP_AUTHORIZATION-}"'
                            }
                        ),
                    )
                }
            else:
                self.assertIn(
                    'http://proxy.example:3128|Price Check|node /tmp/price-check-scope|/tmp/ca-bundle.pem|||||||',
                    str(returns[-1].content),
                )
                self.assertNotIn('private-', str(returns[-1].content))
                yield 'checked'

        result = agent.run_sync('Check shell environment.', model=FunctionModel(stream_function=check_environment))
        self.assertEqual(result.output, 'checked')


if __name__ == '__main__':
    unittest.main()
