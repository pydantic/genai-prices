from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_minimax
from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

BADGE = '<span className="rounded-full">Permanent 50% off</span>'
M3_HEADER = '        | Model | Input | Output | Prompt caching Read |\n        | :- | :- | :- | :- |\n'
M3_ROWS = (
    f'        | **MiniMax-M3**<br />≤ 512k input tokens {BADGE} | ~~\\$0.60~~ \\$0.30 / M tokens'
    ' | ~~\\$2.40~~ \\$1.20 / M tokens | ~~\\$0.12~~ \\$0.06 / M tokens |\n'
    f'        | **MiniMax-M3**<br />> 512k input tokens\\* {BADGE} | ~~\\$1.20~~ \\$0.60 / M tokens'
    ' | ~~\\$4.80~~ \\$2.40 / M tokens | ~~\\$0.24~~ \\$0.12 / M tokens |\n'
)
FLAT_HEADER = (
    '    | Model | Input | Output | Prompt caching Read | Prompt caching Write |\n    | :- | :- | :- | :- | :- |\n'
)
M27_ROW = (
    '    | **MiniMax-M2.7** | \\$0.3 / M tokens | \\$1.2 / M tokens | \\$0.06 / M tokens | \\$0.375 / M tokens |\n'
)


def page(llm: str) -> str:
    return f"""\
  <section id="models/text" className="pricing-section" data-pricing-title="LLM">
    ## LLM

{llm}
  </section>

  <section id="models/speech" className="pricing-section" data-pricing-title="Audio">
    ## Audio

    | **API** | **Endpoint** | **Description** | **Price** |
    | :- | :- | :- | :- |
    | Speech Recognition | Speech-to-Text | Audio-to-text transcription. | \\$0.38 / hour |
  </section>
"""


PRICING_MARKDOWN = page(
    f"""\
    <Tabs>
      <Tab title="Standard">
{M3_HEADER}{M3_ROWS}\
      </Tab>

      <Tab title="Priority*">
{M3_HEADER}{M3_ROWS.replace('0.30 /', '0.45 /')}\
      </Tab>
    </Tabs>

{FLAT_HEADER}{M27_ROW}"""
)


def test_minimax_parses_standard_tab_bands_and_flat_models() -> None:
    models = source_minimax.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [model.id for model in models] == ['MiniMax-M2.7', 'MiniMax-M3']
    assert models[0].match == ClauseOr.model_validate(
        {'or': [ClauseEquals(equals='MiniMax-M2.7'), ClauseEquals(equals='minimax-m2.7')]}
    )
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.3'),
        cache_read_mtok=Decimal('0.06'),
        cache_write_mtok=Decimal('0.375'),
        output_mtok=Decimal('1.2'),
    )
    assert models[1].prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('0.30'), tiers=[Tier(start=512000, price=Decimal('0.60'))]),
        cache_read_mtok=TieredPrices(base=Decimal('0.06'), tiers=[Tier(start=512000, price=Decimal('0.12'))]),
        output_mtok=TieredPrices(base=Decimal('1.20'), tiers=[Tier(start=512000, price=Decimal('2.40'))]),
    )
    assert models[1].prices_checked == date.today()


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('## Audio\n', 'has no LLM section'),
        (page('<Tab title="Batch">\n</Tab>'), 'tab other than Standard and Priority'),
        (page('| Model | Price |\n| :- | :- |\n| **MiniMax-M2** | \\$1 |\n'), 'Unexpected MiniMax LLM pricing columns'),
        (page('| Model | Input |\n| :- | :- |\n'), 'Unexpected MiniMax LLM pricing columns'),
        (page('| Model | Input | Output | Input |\n| :- | :- | :- | :- |\n'), 'Unexpected MiniMax LLM pricing columns'),
        (page(FLAT_HEADER + M27_ROW.replace('**MiniMax-M2.7**', 'MiniMax-M2.7')), 'Unexpected MiniMax model cell'),
        (page(FLAT_HEADER + M27_ROW.replace('**MiniMax-M2.7**', '**MiniMax-M2.7** (beta)')), 'pricing row'),
        (page(FLAT_HEADER + M27_ROW * 2), r'Unexpected MiniMax pricing row: \*\*MiniMax-M2.7\*\*'),
        (page(M3_HEADER + M3_ROWS.split('\n')[0] + '\n'), 'Unexpected MiniMax context bands for MiniMax-M3'),
        (
            page(M3_HEADER + M3_ROWS + '\n' + FLAT_HEADER + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M3')),
            'Unexpected MiniMax context bands for MiniMax-M3',
        ),
        (
            page(
                M3_HEADER
                + M3_ROWS.split('\n')[0]
                + '\n\n'
                + FLAT_HEADER
                + '| **MiniMax-M3**<br />> 512k input tokens | \\$1 / M tokens | \\$1 / M tokens | \\$1 / M tokens'
                ' | \\$1 / M tokens |\n'
            ),
            'context bands for MiniMax-M3 price different units',
        ),
        (page(FLAT_HEADER + M27_ROW.replace('\\$0.3 / M tokens', '\\$0.3 / hour')), 'Unexpected MiniMax price cell'),
    ],
)
def test_minimax_rejects_unexpected_pricing_layout(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_minimax.parse_pricing_markdown(markdown)


def test_minimax_refuses_conflicting_rates_for_one_shared_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider_path = tmp_path / 'minimax.yml'
    copyfile(package_dir / 'providers/minimax.yml', provider_path)
    legacy = (
        M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M9')
        + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.5')
        + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.1').replace('\\$0.3 /', '\\$0.4 /')
    )
    monkeypatch.setattr(
        source_minimax,
        'get_markdown',
        {source_minimax.PRICING_URL: page(FLAT_HEADER + legacy), source_minimax.MODELS_URL: ''}.get,
    )

    with pytest.raises(RuntimeError, match='MiniMax prices MiniMax-M2.5 and MiniMax-M2.1 differently'):
        source_minimax.main(provider_path)


def test_minimax_reads_context_windows_and_descriptions_from_the_model_tables() -> None:
    markdown = """\
| Model Name | Context Window | Description |
| :- | :- | :- |
| <span style={{whiteSpace:"nowrap"}}>MiniMax-M3.1-Flash</span> | 1,000,000 | **Frontier coding model**. Open-weight. |
| **[M2-her](/docs/guides/text-chat)** | 64 K | **Designed for [dialogue](/docs/guides/text-chat)** |
| MiniMax-Next | Coming soon | **Preview** |

| Field | Value |
| :- | :- |
| `model` | See above |
"""

    assert source_minimax.parse_models_markdown(markdown) == {
        'MiniMax-M3.1-Flash': (1_000_000, 'Frontier coding model. Open-weight.'),
        'M2-her': (64_000, 'Designed for dialogue'),
        'MiniMax-Next': (None, 'Preview'),
    }


@pytest.mark.vcr()
def test_minimax_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'minimax.yml'
    copyfile(package_dir / 'providers/minimax.yml', provider_path)

    source_minimax.main(provider_path)

    assert capsys.readouterr().out == 'MiniMax prices updated: 0 added, 2 updated\n'
    flash = ProviderYaml(provider_path).provider.find_model('MiniMax-M3.1-Flash')
    assert flash is not None
    assert flash.context_window == 1_000_000
    assert flash.description is not None and flash.description.startswith('Frontier multimodal coding model')
