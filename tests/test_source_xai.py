from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_xai
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_MARKDOWN = f"""\
### Text API Pricing

{source_xai.TABLE_HEADER}
| --- | --- | --- | --- | --- |
| grok-4.7 (< 200k prompt tokens) | 500k | $2.00 | $0.50 | $6.00 |
| grok-4.7 (≥ 200k prompt tokens) | 500k | $4.00 | $1.00 | $12.00 |
| grok-mini | 1.5M | $0.20 | $0.05 | $0.50 |

*Prices shown per million tokens.*
"""


def tiered(base: str, price: str) -> TieredPrices:
    return TieredPrices(base=Decimal(base), tiers=[Tier(start=199_999, price=Decimal(price))])


def test_xai_long_context_rows_become_tiers_billed_from_the_threshold() -> None:
    long_context, flat = source_xai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert (long_context.id, long_context.context_window, long_context.prices_checked) == (
        'grok-4.7',
        500_000,
        date.today(),
    )
    assert long_context.prices == ModelPrice(
        input_mtok=tiered('2', '4'), cache_read_mtok=tiered('0.5', '1'), output_mtok=tiered('6', '12')
    )
    assert (flat.id, flat.context_window) == ('grok-mini', 1_500_000)
    assert flat.prices == ModelPrice(
        input_mtok=Decimal('0.2'), cache_read_mtok=Decimal('0.05'), output_mtok=Decimal('0.5')
    )


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('# Pricing\n', 'xAI pricing page has no text pricing table'),
        (PRICING_MARKDOWN.replace('| grok-mini | 1.5M |', '| grok mini | 1.5M |'), 'Unexpected xAI pricing row'),
        (PRICING_MARKDOWN.replace('| $0.05 | $0.50 |', '| $0.05 |'), 'Unexpected xAI pricing row'),
        (PRICING_MARKDOWN.replace('$0.20', 'N/A'), "Unexpected xAI price 'N/A'"),
        (PRICING_MARKDOWN.replace('1.5M', '1.5B'), "Unexpected xAI context window '1.5B'"),
        (PRICING_MARKDOWN.replace('grok-mini', 'grok-4.7'), 'Duplicate xAI pricing row'),
        (PRICING_MARKDOWN.replace('(≥ 200k', '(≥ 100k'), 'do not pair a base and a long-context rate'),
        (
            PRICING_MARKDOWN.replace('grok-4.7 (< 200k prompt tokens)', 'grok-4.6 (< 200k prompt tokens)'),
            'do not pair a base and a long-context rate',
        ),
        (
            f'{source_xai.TABLE_HEADER}\n| --- |\n| grok-x (≥ 200k prompt tokens) | 500k | $4.00 | $1.00 | $12.00 |\n',
            'xAI long-context rows without a base row: grok-x',
        ),
    ],
)
def test_xai_rejects_an_unexpected_pricing_table(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_xai.parse_pricing_markdown(markdown)


def test_upsert_prefers_the_record_id_and_keeps_its_rates_over_a_differing_alias(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = tmp_path / 'x_ai.yml'
    provider_path.write_text(
        """\
id: x-ai
name: X AI
api_pattern: x
models:
  - id: grok-4.20
    match: {or: [{equals: grok-4.20}, {equals: grok-4.20-0309-reasoning}, {equals: grok-4.20-0309-non-reasoning}]}
    prices: {input_mtok: 1.25, output_mtok: 2.5}
"""
    )

    def model(model_id: str, input_mtok: str) -> ModelInfo:
        prices = ModelPrice(input_mtok=Decimal(input_mtok), output_mtok=Decimal('2.5'))
        return ModelInfo(id=model_id, match=ClauseEquals(equals=model_id), prices=prices, prices_checked=date.today())

    models = [
        model('grok-4.20-0309-reasoning', '9'),
        model('grok-4.20-0309-non-reasoning', '9'),
        model('grok-4.20', '1.25'),
    ]
    assert ProviderYaml(provider_path).upsert_models(models, source='xAI', min_count=1) == (0, 1)

    record = ProviderYaml(provider_path).provider.find_model('grok-4.20')
    assert record is not None
    assert record.prices == ModelPrice(input_mtok=Decimal('1.25'), output_mtok=Decimal('2.5'))
    assert capsys.readouterr().out == (
        'xAI: kept grok-4.20 at its own rates, alias grok-4.20-0309-reasoning reports others\n'
        'xAI: kept grok-4.20 at its own rates, alias grok-4.20-0309-non-reasoning reports others\n'
    )


@pytest.mark.vcr()
def test_xai_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'x_ai.yml'
    copyfile(package_dir / 'providers/x_ai.yml', provider_path)

    source_xai.main(provider_path)

    assert capsys.readouterr().out == 'xAI prices updated: 0 added, 7 updated\n'
