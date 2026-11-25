from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from prices import source_minimax
from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

M3_HEADER = (
    '| **Model** | **Input** \\$ / M tokens | **Output** \\$ / M tokens | **Prompt caching Read** \\$ / M tokens |\n'
    '| :- | :-: | :-: | :-: |\n'
)
M3_ROWS = (
    '| **MiniMax-M3** ≤ 512k input tokens Permanent 50% off | ~~\\$0.60~~ \\$0.30 | ~~\\$2.40~~ \\$1.20'
    ' | ~~\\$0.12~~ \\$0.06 |\n'
    '| **MiniMax-M3** > 512k input tokens\\* Permanent 50% off | ~~\\$1.20~~ \\$0.60 | ~~\\$4.80~~ \\$2.40'
    ' | ~~\\$0.24~~ \\$0.12 |\n'
)
FLAT_HEADER = '| Model | Input | Output | Prompt caching Read | Prompt caching Write |\n| :- | :- | :- | :- | :- |\n'
M27_ROW = '| **MiniMax-M2.7** | \\$0.3 | \\$1.2 | \\$0.06 | \\$0.375 |\n'
PRIORITY_ROWS = M3_ROWS.replace('\\$0.30 |', '\\$0.45 |')


def page(llm: str) -> str:
    return f"""\
## LLM

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

{llm}
## Audio

| **API** | **Endpoint** | **Description** | **Price** |
| :- | :- | :- | :- |
| Speech Recognition | Speech-to-Text | Audio-to-text transcription. | \\$0.38 / hour |
"""


def tab(name: str, table: str) -> str:
    return f'> [tab] {name}\n>\n' + ''.join(f'> {line}\n' for line in table.splitlines()) + '\n'


PRIORITY_TAB = tab('Priority\\*', M3_HEADER + PRIORITY_ROWS)
PRICING_MARKDOWN = page(
    f"""\
{FLAT_HEADER}{M27_ROW}
{tab('Standard', M3_HEADER + M3_ROWS)}{PRIORITY_TAB}\
> [!NOTE]
>
> Note:
"""
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
    assert source_minimax.parse_pricing_markdown(PRICING_MARKDOWN.split('## Audio')[0]) == models


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('## Audio\n', 'has no LLM section'),
        (page('> [tab] Batch\n'), 'tier other than Standard and Priority'),
        (page('> [tab] Batch API\n'), 'tier other than Standard and Priority'),
        (page('> [tab] Priority Plus\n'), 'tier other than Standard and Priority'),
        (page('> [tab] Priority\n> [tab] Batch\n'), 'tier other than Standard and Priority'),
        (page('| Model | Price |\n| :- | :- |\n| **MiniMax-M2** | \\$1 |\n'), 'Unexpected MiniMax LLM pricing columns'),
        (page('| Model | Input |\n| :- | :- |\n'), 'Unexpected MiniMax LLM pricing columns'),
        (page('| Model | Input | Output | Input |\n| :- | :- | :- | :- |\n'), 'Unexpected MiniMax LLM pricing columns'),
    ],
)
def test_minimax_rejects_unexpected_pricing_layout(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_minimax.parse_pricing_markdown(markdown)


M25_ROW = M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.5')
M3_LOW_BAND = M3_ROWS.split('\n')[0] + '\n'


SKIPPED = 'MiniMax: skipped a row it cannot read; update it by hand. '
SKIPPED_M27 = 'MiniMax: skipped a row it cannot read for MiniMax-M2.7; update it by hand. '
SKIPPED_M3 = 'MiniMax: skipped a row it cannot read for MiniMax-M3; update it by hand. '


@pytest.mark.parametrize(
    ('llm', 'notes', 'model_ids'),
    [
        (
            FLAT_HEADER + M27_ROW.replace('**MiniMax-M2.7**', 'MiniMax-M2.7') + M25_ROW,
            [f'{SKIPPED}Unexpected MiniMax model cell: MiniMax-M2.7'],
            ['MiniMax-M2.5'],
        ),
        (
            FLAT_HEADER + M27_ROW.replace('**MiniMax-M2.7**', '**MiniMax-M2.7** (beta)') + M25_ROW,
            [f'{SKIPPED_M27}Unexpected MiniMax pricing row: **MiniMax-M2.7** (beta)'],
            ['MiniMax-M2.5'],
        ),
        (
            FLAT_HEADER + M27_ROW.replace('\\$0.3 |', '\\$0.3 / hour |') + M25_ROW,
            [f'{SKIPPED_M27}Unexpected MiniMax price cell: \\$0.3 / hour'],
            ['MiniMax-M2.5'],
        ),
        (
            # A readable row after an unreadable one for the same model still leaves the model unchanged.
            FLAT_HEADER + M27_ROW.replace('\\$0.3 |', 'TBD |') + M27_ROW + M25_ROW,
            [f'{SKIPPED_M27}Unexpected MiniMax price cell: TBD'],
            ['MiniMax-M2.5'],
        ),
        (
            M3_HEADER + M3_LOW_BAND + '\n' + FLAT_HEADER + M27_ROW,
            [f'{SKIPPED_M3}Unexpected MiniMax context bands for MiniMax-M3'],
            ['MiniMax-M2.7'],
        ),
        (
            # A skipped band row leaves the model unchanged rather than priced at its other band alone.
            M3_HEADER + M3_ROWS.replace('~~\\$1.20~~ \\$0.60', 'TBD') + '\n' + FLAT_HEADER + M27_ROW,
            [f'{SKIPPED_M3}Unexpected MiniMax price cell: TBD'],
            ['MiniMax-M2.7'],
        ),
        (
            M3_HEADER
            + M3_LOW_BAND
            + '\n'
            + FLAT_HEADER
            + '| **MiniMax-M3** > 512k input tokens | \\$1 | \\$1 | \\$1 | \\$1 |\n'
            + M27_ROW,
            [f'{SKIPPED_M3}MiniMax context bands for MiniMax-M3 price different units'],
            ['MiniMax-M2.7'],
        ),
    ],
)
def test_minimax_reports_an_unreadable_row_and_reads_the_others(
    llm: str, notes: list[str], model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_minimax.parse_pricing_markdown(page(llm))

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == ''.join(f'{note}\n' for note in notes)


@pytest.mark.parametrize(
    ('llm', 'model_id', 'model_ids'),
    [
        (FLAT_HEADER + M27_ROW * 2 + M25_ROW, 'MiniMax-M2.7', ['MiniMax-M2.5']),
        (
            M3_HEADER + M3_ROWS + '\n' + FLAT_HEADER + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M3') + M27_ROW,
            'MiniMax-M3',
            ['MiniMax-M2.7'],
        ),
    ],
)
def test_minimax_keeps_a_model_listed_more_than_once_unchanged(
    llm: str, model_id: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_minimax.parse_pricing_markdown(page(llm))

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == (
        f'MiniMax: kept {model_id} unchanged, the pricing page lists it more than once; update it by hand\n'
    )


@pytest.mark.parametrize(
    ('legacy', 'notes'),
    [
        (
            M25_ROW + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.1').replace('\\$0.3 |', '\\$0.4 |'),
            'MiniMax: kept MiniMax-M2 unchanged, the pricing page lists it at conflicting rates; update it by hand\n',
        ),
        (
            # MiniMax-M8 has no YAML entry, so its unreadable row holds no other model.
            M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M8').replace('\\$0.3 |', 'TBD |')
            + M25_ROW.replace('\\$0.3 |', 'TBD |')
            + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.1'),
            'MiniMax: skipped a row it cannot read for MiniMax-M8; update it by hand. '
            'Unexpected MiniMax price cell: TBD\n'
            'MiniMax: skipped a row it cannot read for MiniMax-M2.5; update it by hand. '
            'Unexpected MiniMax price cell: TBD\n',
        ),
        (
            # A duplicated sibling holds the shared entry, so its other sibling cannot rewrite it.
            M25_ROW * 2 + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.1'),
            'MiniMax: kept MiniMax-M2.5 unchanged, the pricing page lists it more than once; update it by hand\n',
        ),
        (
            # So does a sibling whose context bands cannot be paired.
            M25_ROW.replace('**MiniMax-M2.5**', '**MiniMax-M2.5** ≤ 512k input tokens')
            + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M2.1'),
            'MiniMax: skipped a row it cannot read for MiniMax-M2.5; update it by hand. '
            'Unexpected MiniMax context bands for MiniMax-M2.5\n',
        ),
    ],
)
def test_minimax_keeps_a_shared_model_unchanged_when_a_sibling_row_conflicts_or_is_left_out(
    legacy: str,
    notes: str,
    monkeypatch: pytest.MonkeyPatch,
    provider_snapshot: ProviderSnapshot,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_path = provider_snapshot('minimax.yml')
    shared = ProviderYaml(provider_path).provider.find_model('MiniMax-M2')
    pricing = page(FLAT_HEADER + M27_ROW.replace('MiniMax-M2.7', 'MiniMax-M9') + legacy + M27_ROW)
    monkeypatch.setattr(
        source_minimax, 'get_markdown', {source_minimax.PRICING_URL: pricing, source_minimax.MODELS_URL: ''}.get
    )

    source_minimax.main(provider_path)

    assert capsys.readouterr().out == f'{notes}MiniMax prices updated: 1 added, 1 updated\n'
    assert ProviderYaml(provider_path).provider.find_model('MiniMax-M2') == shared


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
def test_minimax_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('minimax.yml')

    source_minimax.main(provider_path)

    assert capsys.readouterr().out == 'MiniMax prices updated: 0 added, 2 updated\n'
    flash = ProviderYaml(provider_path).provider.find_model('MiniMax-M3.1-Flash')
    assert flash is not None
    assert flash.context_window == 1_000_000
    assert flash.description is not None and flash.description.startswith('Frontier multimodal coding model')
