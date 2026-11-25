from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from prices import source_openai_decisions
from prices.prices_types import ConditionalPrice, ModelPrice, StartDateConstraint, Tier, TieredPrices
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

MODEL_MARKDOWN = """\
### Text tokens

| Metric | Price | Unit |
| --- | ---: | --- |
| Input | $0.1 | 1M tokens |
| Output | $0.5 | 1M tokens |

- Prompts with more than 272K input tokens are priced at 2x input and cache rates and 1.5x output for the full request.
"""


def test_openai_decisions_parses_input_rate_and_long_context_tier() -> None:
    model = source_openai_decisions.parse_model_markdown('gpt-6-luna', MODEL_MARKDOWN)

    assert model.prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('0.1'), tiers=[Tier(start=272000, price=Decimal('0.2'))])
    )
    assert model.prices_checked == date.today()


@pytest.mark.parametrize('replace', [('| Input | $0.1 |', '| Input | Free |'), ('more than 272K', 'over 272K')])
def test_openai_decisions_reports_an_unreadable_model_page_and_reads_the_others(
    replace: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    provider_snapshot: ProviderSnapshot,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_path = provider_snapshot('openai_decisions.yml')
    provider_path.write_text(
        provider_path.read_text()
        + '  - id: gpt-6-sol\n    match:\n      equals: gpt-6-sol\n    prices:\n      input_mtok: 1\n'
    )
    pages = {'gpt-6-luna': MODEL_MARKDOWN, 'gpt-6-sol': MODEL_MARKDOWN.replace(*replace)}
    monkeypatch.setattr(
        source_openai_decisions,
        'get_markdown',
        {source_openai_decisions.MODEL_URL.format(model_id=model_id): page for model_id, page in pages.items()}.get,
    )

    source_openai_decisions.main(provider_path)

    assert capsys.readouterr().out == (
        'OpenAI Decisions: skipped a row it cannot read; update it by hand. '
        'OpenAI gpt-6-sol page has no input rate or long-context pricing in the expected shape\n'
        'OpenAI Decisions prices updated: 0 added, 1 updated\n'
    )


@pytest.mark.vcr()
def test_openai_decisions_main_fetches_recorded_model_pages(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('openai_decisions.yml')
    current = provider_path.read_text()
    stale = re.sub(r'prices_checked: \S+', 'prices_checked: 2026-01-01', current).replace('price: 0.2', 'price: 0.3')
    assert stale.count('2026-01-01') == stale.count('price: 0.3') == 1
    provider_path.write_text(stale)

    source_openai_decisions.main(provider_path)

    assert capsys.readouterr().out == 'OpenAI Decisions prices updated: 0 added, 1 updated\n'
    model = ProviderYaml(provider_path).provider.find_model('gpt-6-luna')
    assert model is not None
    assert model.prices_checked == date.today()
    assert model.prices == [
        ConditionalPrice(
            prices=ModelPrice(
                input_mtok=TieredPrices(base=Decimal('0.1'), tiers=[Tier(start=272000, price=Decimal('0.3'))])
            )
        ),
        ConditionalPrice(
            constraint=StartDateConstraint(start_date=date.today()),
            prices=ModelPrice(
                input_mtok=TieredPrices(base=Decimal('0.1'), tiers=[Tier(start=272000, price=Decimal('0.2'))])
            ),
        ),
    ]
