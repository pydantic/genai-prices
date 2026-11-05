from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any, cast

import pytest

from prices import source_openai
from prices.prices_types import ClauseEquals, ModelPrice, PriceVariant, StartDateConstraint, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

CONTEXT_TIER_HEADER = (
    '| Model | Short context input | Short context output | Short context cached input | Short context 30m write '
    '| Short context 12h write | Long context input | Long context output | Long context cached input '
    '| Long context 30m write | Long context 12h write |'
)
PRICING_MARKDOWN = f"""\
Standard

### Standard pricing data

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7 (<272K context length) | $2.00 | $10.00 | $0.20 | $2.50 | $5.00 | $4.00 | $15.00 | $0.40 | $5.00 | $10.00 |
| gpt-7-pro | $30.00 | $180.00 | - | - | - | - | - | - | - | - |

Batch

### Batch pricing data

#### Batch

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-pro | $15.00 | $90.00 | - | - | - | - | - | - | - | - |

#### Flex

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-pro | $14.00 | $84.00 | - | - | - | - | - | - | - | - |
| gpt-7-free | Free | - | - | - | - | - | - | - | - | - |
| gpt-7 | - | - | - | - | - | - | - | - | - | - |

Fast

### Fast pricing data

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-pro | $60.00 | $360.00 | - | - | - | - | - | - | - | - |

Ultrafast

### Ultrafast pricing data

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-pro | $180.00 | $1080.00 | - | - | - | - | - | - | - | - |

Prices per 1M tokens.

### Grouped Pricing Table data

| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-7-pro | $30.00 | $180.00 | - |
| gpt-bio | $5.00 | $25.00 | $0.50 |

### Grouped Pricing Table data

| Model | Modality | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| gpt-image-9 | Image | $8.00 | $2.00 | $30.00 |

Standard

### Grouped Pricing Table data

| Category | Model | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| Embedding | text-embedding-9 | $0.02 | - | - |
| Moderation | omni-moderation-latest | Free | - | - |
"""


def tiered(base: str, price: str) -> TieredPrices:
    return TieredPrices(base=Decimal(base), tiers=[Tier(start=272_000, price=Decimal(price))])


def tiers(markdown: str) -> dict[str, list[PriceVariant]]:
    return {
        model.id: model.price_variants
        for model in source_openai.parse_pricing_markdown(markdown)
        if model.price_variants
    }


def test_openai_parses_standard_text_rates_and_skips_other_tabs_and_units() -> None:
    models = source_openai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(m.id, m.match, m.prices_checked) for m in models] == [
        (model_id, ClauseEquals(equals=model_id), date.today())
        for model_id in ('gpt-7', 'gpt-7-pro', 'gpt-bio', 'text-embedding-9')
    ]
    assert [m.prices for m in models] == [
        ModelPrice(
            input_mtok=tiered('2', '4'),
            cache_read_mtok=tiered('0.2', '0.4'),
            cache_write_mtok=tiered('2.5', '5'),
            output_mtok=tiered('10', '15'),
        ),
        ModelPrice(input_mtok=Decimal(30), output_mtok=Decimal(180)),
        ModelPrice(input_mtok=Decimal(5), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal(25)),
        ModelPrice(input_mtok=Decimal('0.02')),
    ]


def test_openai_parses_each_tab_into_its_request_context() -> None:
    variants = tiers(PRICING_MARKDOWN)

    assert [(variant.when, variant.prices.input_mtok) for variant in variants['gpt-7-pro']] == [
        ({'processing': 'batch'}, Decimal(15)),
        ({'service_tier': 'flex'}, Decimal(14)),
        ({'service_tier': 'fast'}, Decimal(60)),
        ({'service_tier': 'priority'}, Decimal(60)),
        ({'service_tier': 'ultrafast'}, Decimal(180)),
    ]
    assert list(variants) == ['gpt-7-pro']


def test_openai_parses_the_former_priority_tab_name() -> None:
    assert PRICING_MARKDOWN.count('\nFast\n') == 1
    variants = tiers(PRICING_MARKDOWN.replace('\nFast\n', '\nPriority\n'))

    assert [(variant.when, variant.prices.input_mtok) for variant in variants['gpt-7-pro']][2:4] == [
        ({'service_tier': 'priority'}, Decimal(60)),
        ({'service_tier': 'ultrafast'}, Decimal(180)),
    ]


def test_openai_keeps_the_first_rates_a_page_lists_for_a_tier(capsys: pytest.CaptureFixture[str]) -> None:
    assert PRICING_MARKDOWN.count('\nUltrafast\n') == 1
    variants = tiers(PRICING_MARKDOWN.replace('\nUltrafast\n', '\nPriority\n'))

    assert [(variant.when, variant.prices.input_mtok) for variant in variants['gpt-7-pro']][2:] == [
        ({'service_tier': 'fast'}, Decimal(60)),
        ({'service_tier': 'priority'}, Decimal(60)),
    ]
    assert (
        "kept the first {'service_tier': 'priority'} rates of gpt-7-pro, Priority lists others; update them by hand"
        in capsys.readouterr().out
    )


def test_openai_reads_a_tier_listed_twice_at_the_same_rates_once(capsys: pytest.CaptureFixture[str]) -> None:
    row = '| gpt-7-pro | $180.00 | $1080.00 | - | - | - | - | - | - | - | - |\n'
    assert PRICING_MARKDOWN.count(row) == 1

    assert tiers(PRICING_MARKDOWN.replace(row, row * 2)) == tiers(PRICING_MARKDOWN)
    assert 'update them by hand' not in capsys.readouterr().out


def test_openai_skips_the_tiers_of_a_model_without_standard_rates(capsys: pytest.CaptureFixture[str]) -> None:
    row = '| gpt-7-pro | $180.00 | $1080.00 | - | - | - | - | - | - | - | - |\n'
    assert PRICING_MARKDOWN.count(row) == 1
    markdown = PRICING_MARKDOWN.replace(row, row + row.replace('gpt-7-pro', 'gpt-7-tier-only'))

    assert 'gpt-7-tier-only' not in tiers(markdown)
    assert (
        'skipped the tiers of gpt-7-tier-only, which has no standard rates; update them by hand'
        in capsys.readouterr().out
    )


def test_openai_skips_an_unknown_table_under_a_tier_tab_with_a_manual_note(capsys: pytest.CaptureFixture[str]) -> None:
    markdown = PRICING_MARKDOWN.replace('#### Flex', '#### Regional')

    assert [variant.when for variant in tiers(markdown)['gpt-7-pro']] == [
        {'processing': 'batch'},
        {'service_tier': 'fast'},
        {'service_tier': 'priority'},
        {'service_tier': 'ultrafast'},
    ]
    out = capsys.readouterr().out
    assert 'skipped the Regional tables under Batch; update them by hand' in out
    # Its tables aren't read as Batch rates either.
    assert 'lists others' not in out
    assert [m.id for m in source_openai.parse_pricing_markdown(markdown)][:2] == ['gpt-7', 'gpt-7-pro']


def test_openai_unknown_subheading_under_the_standard_tab_keeps_standard_rates() -> None:
    markdown = PRICING_MARKDOWN.replace(
        '### Standard pricing data\n', '### Standard pricing data\n\n#### Text tokens\n', 1
    )

    assert source_openai.parse_pricing_markdown(markdown) == source_openai.parse_pricing_markdown(PRICING_MARKDOWN)


def test_openai_reports_a_tier_table_with_unknown_columns(capsys: pytest.CaptureFixture[str]) -> None:
    markdown = PRICING_MARKDOWN.replace(
        '### Ultrafast pricing data\n\n| Model | Short context input',
        '### Ultrafast pricing data\n\n| Model | Short context audio input',
    )

    variants = tiers(markdown)

    assert {'service_tier': 'ultrafast'} not in [variant.when for variant in variants['gpt-7-pro']]
    assert 'skipped a Ultrafast table with unknown columns; update them by hand' in capsys.readouterr().out


def test_openai_skips_an_unreadable_variant_row_with_a_manual_note(capsys: pytest.CaptureFixture[str]) -> None:
    markdown = PRICING_MARKDOWN.replace('| $180.00 | $1080.00 |', '| $180.00 / 1M | $1080.00 |')

    variants = tiers(markdown)

    assert {'service_tier': 'ultrafast'} not in [variant.when for variant in variants['gpt-7-pro']]
    assert 'skipped an unreadable Ultrafast row; update them by hand' in capsys.readouterr().out
    assert [m.id for m in source_openai.parse_pricing_markdown(markdown)][:2] == ['gpt-7', 'gpt-7-pro']


def test_openai_skips_a_malformed_tier_table_but_not_a_malformed_standard_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown = PRICING_MARKDOWN.replace('| $180.00 | $1080.00 | - |', '| $180.00 | $1080.00 | - | - |')

    assert len(source_openai.parse_pricing_markdown(markdown)) == 4
    assert {'service_tier': 'ultrafast'} not in [v.when for v in tiers(markdown)['gpt-7-pro']]
    assert 'skipped an unreadable Ultrafast table; update them by hand' in capsys.readouterr().out
    with pytest.raises(ValueError, match='Table row has 5 cells'):
        source_openai.parse_pricing_markdown(PRICING_MARKDOWN.replace('| $5.00 | $25.00 |', '| $5.00 | $25.00 | - |'))


def test_openai_adds_only_the_price_variants_a_model_does_not_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', path)
    new_tier = ModelPrice(input_mtok=tiered('12', '24'), output_mtok=tiered('60', '90'))
    start = date(2020, 1, 2)
    before = ProviderYaml(path).provider.find_model('gpt-6.1-sol')
    assert before is not None and before.price_variants is not None

    ProviderYaml(path).add_missing_price_variants(
        {
            # The alias comes first so the model's own rates must win on rank, not on page order.
            'gpt-6.1-sol-2026-09-29': [PriceVariant(when={'service_tier': 'new-tier'}, prices=ModelPrice())],
            'gpt-6.1-sol': [
                PriceVariant(when={'service_tier': 'flex'}, prices=new_tier),
                PriceVariant(when={'service_tier': 'new-tier'}, prices=new_tier),
            ],
            'not-a-recorded-model': [PriceVariant(when={'service_tier': 'new-tier'}, prices=new_tier)],
        },
        start=start,
        source='OpenAI',
    )

    reloaded = ProviderYaml(path).provider
    model = reloaded.find_model('gpt-6.1-sol')
    assert model is not None and model.price_variants is not None
    assert model.price_variants == [
        *before.price_variants,
        PriceVariant(
            when={'service_tier': 'new-tier'}, prices=new_tier, constraint=StartDateConstraint(start_date=start)
        ),
    ]
    assert reloaded.find_model('not-a-recorded-model') is None
    text = path.read_text()
    assert 'start_date: 2020-01-02' in text
    # The new entry joins the model's other variants without a blank line between them.
    assert '7.5\n      - when: { service_tier: new-tier }\n' in text
    assert (
        "kept gpt-6.1-sol {'service_tier': 'new-tier'} at its own rates, alias gpt-6.1-sol-2026-09-29 reports others"
        in capsys.readouterr().out
    )


@pytest.mark.default_cassette('test_openai_main_fetches_recorded_pricing_page.yaml')
@pytest.mark.vcr()
def test_openai_main_adds_new_models_with_their_tiers_once(tmp_path: Path) -> None:
    path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', path)
    provider_yaml = ProviderYaml(path)
    for model_id in ('gpt-6-astra', 'gpt-6.1-sol'):
        provider_yaml.remove_model(model_id)
    provider_yaml.save()

    source_openai.main(path)

    reloaded = ProviderYaml(path).provider
    for model_id, rate in (('gpt-6-astra', 60), ('gpt-6.1-sol', 12)):
        assert [m.id for m in reloaded.models].count(model_id) == 1
        model = reloaded.find_model(model_id)
        assert model is not None and model.price_variants is not None
        [ultrafast] = [v for v in model.price_variants if v.when == {'service_tier': 'ultrafast'}]
        # Like its standard rates, a new model's tiers apply from the start.
        assert ultrafast.constraint is None
        assert ultrafast.prices.input_mtok == tiered(str(rate), str(rate * 2))
    assert '      - when: { service_tier: ultrafast }\n' in path.read_text()


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('# Pricing\n', 'OpenAI pricing page has no standard text pricing table'),
        (PRICING_MARKDOWN.replace('| gpt-bio |', '| GPT Bio |'), 'Unexpected OpenAI pricing row'),
        (PRICING_MARKDOWN.replace('$25.00', 'TBD'), "Unexpected OpenAI price 'TBD'"),
        (PRICING_MARKDOWN.replace('| $0.20 | $2.50 |', '| $0.20 | - |'), 'without its pair'),
        (PRICING_MARKDOWN.replace('| $0.40 | $5.00 |', '| $0.40 | - |'), 'without its pair'),
        (
            PRICING_MARKDOWN.replace(
                '| gpt-7-pro | $30.00 | $180.00 | - |\n', '| gpt-7-pro | $31.00 | $180.00 | - |\n'
            ),
            'lists gpt-7-pro at conflicting standard rates',
        ),
    ],
)
def test_openai_rejects_an_unexpected_pricing_page(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_openai.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_openai_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', provider_path)

    source_openai.main(provider_path)

    assert capsys.readouterr().out == 'OpenAI prices updated: 0 added, 46 updated\n'


@pytest.mark.default_cassette('test_openai_main_fetches_recorded_pricing_page.yaml')
@pytest.mark.vcr()
def test_openai_main_adds_a_missing_tier_to_a_recorded_model(tmp_path: Path) -> None:
    path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', path)
    provider_yaml = ProviderYaml(path)
    [sol] = [model for model in provider_yaml.data['models'] if model['id'] == 'gpt-6.1-sol']
    variants = cast(list[dict[str, Any]], sol['price_variants'])
    sol['price_variants'] = [v for v in variants if v['when'] != {'service_tier': 'ultrafast'}]
    provider_yaml.save()

    source_openai.main(path)

    model = ProviderYaml(path).provider.find_model('gpt-6.1-sol')
    assert model is not None and model.price_variants is not None
    [ultrafast] = [v for v in model.price_variants if v.when == {'service_tier': 'ultrafast'}]
    assert ultrafast.constraint == StartDateConstraint(start_date=date.today())
    assert ultrafast.prices.input_mtok == tiered('12', '24')
