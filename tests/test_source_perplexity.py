from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from prices import source_perplexity
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot

EMBEDDINGS = """\
## Embeddings API Pricing

| Model | Dimensions | Price (\\$/1M tokens) |
| - | :-: | :-: |
| `pplx-embed-v1-0.6b` | 1024 | \\$0.004 |
| `pplx-embed-v1-4b` | 2560 | \\$0.03 |
"""
DECISIONS = """\
## Decisions API Pricing

| Model | Price (\\$/1M input tokens) | Output tokens | Per-request fee |
| - | :-: | :-: | :-: |
| `pplx-decider-v1.2` | \\$0.02 | Free | None |
"""
AGENT_MODELS = """\
| Model | Input (\\$/1M) | Output (\\$/1M) | Cache read (\\$/1M) | Service tiers | Docs |
| - | - | - | - | - | - |
| `openai/gpt-5.5` | 5.00 (≤272k)<br />10.00 (>272k) | 30.00 | 0.50 | `flex`, `priority` | [GPT-5.5](https://x) |
| `perplexity/sonar` | 0.25 | 2.50 | 0.0625 | — | — |
"""


def test_perplexity_parses_embeddings_and_decisions_input_rates() -> None:
    models = source_perplexity.parse_pricing_markdown(f'# Pricing\n\n{EMBEDDINGS}\n{DECISIONS}')

    assert [(model.id, model.prices, model.prices_checked) for model in models] == [
        ('pplx-embed-v1-0.6b', ModelPrice(input_mtok=Decimal('0.004')), date.today()),
        ('pplx-embed-v1-4b', ModelPrice(input_mtok=Decimal('0.03')), date.today()),
        ('pplx-decider-v1.2', ModelPrice(input_mtok=Decimal('0.02')), date.today()),
    ]


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        (EMBEDDINGS, 'no longer has its Embeddings and Decisions price tables'),
        (EMBEDDINGS.replace('1M tokens', '1K tokens') + DECISIONS, 'no longer has its Embeddings and Decisions'),
    ],
)
def test_perplexity_rejects_an_unexpected_pricing_page(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_perplexity.parse_pricing_markdown(markdown)


@pytest.mark.parametrize(
    ('markdown', 'error', 'model_ids'),
    [
        (
            EMBEDDINGS + DECISIONS.replace('Free', '\\$0.10'),
            'Perplexity now bills Decisions output tokens or requests',
            ['pplx-embed-v1-0.6b', 'pplx-embed-v1-4b'],
        ),
        (
            EMBEDDINGS.replace('\\$0.03', 'Contact sales') + DECISIONS,
            'Unexpected Perplexity price row',
            ['pplx-embed-v1-0.6b', 'pplx-decider-v1.2'],
        ),
    ],
)
def test_perplexity_reports_an_unreadable_pricing_row_and_reads_the_others(
    markdown: str, error: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_perplexity.parse_pricing_markdown(markdown)

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out.startswith(f'Perplexity: skipped a row it cannot read; update it by hand. {error}')


def test_perplexity_parses_only_the_agent_api_models_it_hosts() -> None:
    assert [(model.id, model.prices) for model in source_perplexity.parse_agent_models_markdown(AGENT_MODELS)] == [
        (
            'perplexity/sonar',
            ModelPrice(input_mtok=Decimal('0.25'), cache_read_mtok=Decimal('0.0625'), output_mtok=Decimal('2.50')),
        )
    ]


def test_perplexity_reads_agent_models_from_a_tab_blockquote() -> None:
    quoted = '> [tab] Perplexity\n>\n' + ''.join(f'> {line}\n' for line in AGENT_MODELS.splitlines())

    assert source_perplexity.parse_agent_models_markdown(quoted) == source_perplexity.parse_agent_models_markdown(
        AGENT_MODELS
    )


def test_perplexity_rejects_an_agent_models_page_without_perplexity_hosted_models() -> None:
    with pytest.raises(RuntimeError, match='no longer lists Perplexity-hosted models'):
        source_perplexity.parse_agent_models_markdown(AGENT_MODELS.replace('perplexity/', 'other/'))


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        (AGENT_MODELS.replace('| — | — |', '| `flex` | — |'), 'Unexpected Perplexity Agent API model row'),
        (AGENT_MODELS.replace('0.0625', 'Free'), 'Unexpected Perplexity Agent API model row'),
    ],
)
def test_perplexity_reports_an_unreadable_agent_model_row_and_reads_the_others(
    markdown: str, error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_perplexity.parse_agent_models_markdown(
        f'{markdown}| `perplexity/sonar-pro` | 3 | 15 | 0.3 | — | — |\n'
    )

    assert [model.id for model in models] == ['perplexity/sonar-pro']
    assert capsys.readouterr().out.startswith(f'Perplexity: skipped a row it cannot read; update it by hand. {error}')


@pytest.mark.vcr()
def test_perplexity_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('perplexity.yml')

    source_perplexity.main(provider_path)

    assert capsys.readouterr().out == 'Perplexity prices updated: 0 added, 12 updated\n'
