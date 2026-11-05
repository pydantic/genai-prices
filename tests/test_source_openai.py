from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

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
| gpt-7-unpriced | - | - | - | - | - | - | - | - | - | - |

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
    variants = source_openai.parse_price_variants(PRICING_MARKDOWN)

    assert [(variant.when, variant.prices.input_mtok) for variant in variants['gpt-7-pro']] == [
        ({'processing': 'batch'}, Decimal(15)),
        ({'service_tier': 'flex'}, Decimal(14)),
        ({'service_tier': 'fast'}, Decimal(60)),
        ({'service_tier': 'priority'}, Decimal(60)),
        ({'service_tier': 'ultrafast'}, Decimal(180)),
    ]
    assert list(variants) == ['gpt-7-pro']


def test_openai_unknown_subheading_stays_in_its_tab() -> None:
    markdown = PRICING_MARKDOWN.replace('#### Flex', '#### Regional')

    assert source_openai.parse_price_variants(markdown)['gpt-7-pro'][1].when == {'processing': 'batch'}
    assert [m.id for m in source_openai.parse_pricing_markdown(markdown)][:2] == ['gpt-7', 'gpt-7-pro']


def test_openai_skips_an_unreadable_variant_row_with_a_manual_note(capsys: pytest.CaptureFixture[str]) -> None:
    markdown = PRICING_MARKDOWN.replace('| $180.00 | $1080.00 |', '| $180.00 / 1M | $1080.00 |')

    variants = source_openai.parse_price_variants(markdown)

    assert {'service_tier': 'ultrafast'} not in [variant.when for variant in variants['gpt-7-pro']]
    assert 'skipped an unreadable Ultrafast row; update them by hand' in capsys.readouterr().out
    assert [m.id for m in source_openai.parse_pricing_markdown(markdown)][:2] == ['gpt-7', 'gpt-7-pro']


def test_openai_skips_a_malformed_tier_table_but_not_a_malformed_standard_table(
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown = PRICING_MARKDOWN.replace('| $180.00 | $1080.00 | - |', '| $180.00 | $1080.00 | - | - |')

    assert len(source_openai.parse_pricing_markdown(markdown)) == 4
    assert {'service_tier': 'ultrafast'} not in [
        v.when for v in source_openai.parse_price_variants(markdown)['gpt-7-pro']
    ]
    assert 'skipped an unreadable Ultrafast table; update them by hand' in capsys.readouterr().out
    with pytest.raises(ValueError, match='Table row has 5 cells'):
        source_openai.parse_pricing_markdown(PRICING_MARKDOWN.replace('| $5.00 | $25.00 |', '| $5.00 | $25.00 | - |'))


def test_openai_adds_only_the_price_variants_a_model_does_not_record(tmp_path: Path) -> None:
    path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', path)
    new_tier = ModelPrice(input_mtok=tiered('12', '24'), output_mtok=tiered('60', '90'))
    start = date(2020, 1, 2)
    before = ProviderYaml(path).provider.find_model('gpt-6.1-sol')
    assert before is not None and before.price_variants is not None

    ProviderYaml(path).add_missing_price_variants(
        {
            'gpt-6.1-sol': [
                PriceVariant(when={'service_tier': 'flex'}, prices=new_tier),
                PriceVariant(when={'service_tier': 'new-tier'}, prices=new_tier),
            ],
            'not-a-recorded-model': [PriceVariant(when={'service_tier': 'new-tier'}, prices=new_tier)],
            'gpt-6.1-sol-2026-09-29': [PriceVariant(when={'service_tier': 'new-tier'}, prices=ModelPrice())],
        },
        start=start,
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
    assert 'start_date: 2020-01-02' in path.read_text()


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
        assert ultrafast.constraint == StartDateConstraint(start_date=date.today())
        assert ultrafast.prices.input_mtok == tiered(str(rate), str(rate * 2))


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
