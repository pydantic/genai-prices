from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_fireworks
from prices.prices_types import ConditionalPrice, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_MARKDOWN = f"""\
## Text and vision models

{source_fireworks.TABLE_HEADER}
| - | - | - |
| [Kimi K3](https://app.fireworks.ai/models/fireworks/kimi-k3) | \\$3.00 / \\$0.30 / \\$15.00 | \\$3.75 / \\$0.375 / \\$18.75 |
| [Kimi K3 Fast](https://app.fireworks.ai/models/fireworks/kimi-k3) | \\$4.50 / \\$0.45 / \\$22.50 | — |
| [GLM 5.3 Flash (US)](https://app.fireworks.ai/models/fireworks/glm-5p3-flash) | \\$0.225 / \\$0.045 / \\$0.75 | — |

**—** in the Priority column means Priority is not available for that model.
"""


def test_fireworks_fast_and_us_rows_are_router_models() -> None:
    models = source_fireworks.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(model.id, model.name) for model in models] == [
        ('accounts/fireworks/models/kimi-k3', 'Kimi K3'),
        ('accounts/fireworks/routers/kimi-k3-fast', 'Kimi K3 Fast'),
        ('accounts/fireworks/routers/glm-5p3-flash-us', 'GLM 5.3 Flash US'),
    ]
    assert models[2].prices == ModelPrice(
        input_mtok=Decimal('0.225'), cache_read_mtok=Decimal('0.045'), output_mtok=Decimal('0.75')
    )


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('# Pricing\n', 'Fireworks pricing page has no text and vision models table'),
        (
            PRICING_MARKDOWN.replace('https://app.fireworks.ai', 'https://example.com'),
            'Unexpected Fireworks pricing row',
        ),
        (PRICING_MARKDOWN.replace('\\$4.50 / ', ''), 'Unexpected Fireworks pricing row'),
        (PRICING_MARKDOWN.replace(' | — |\n| [GLM', ' |\n| [GLM'), 'Unexpected Fireworks pricing row'),
        (PRICING_MARKDOWN.replace('Kimi K3 Fast', 'Kimi K3'), 'Duplicate Fireworks pricing row'),
    ],
)
def test_fireworks_rejects_an_unexpected_pricing_table(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_fireworks.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_fireworks_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'fireworks.yml'
    provider_path.write_text(
        """\
id: fireworks
name: Fireworks
api_pattern: 'https://api\\.fireworks\\.ai'
models:
  - id: kimi-k3-fast
    match:
      equals: accounts/fireworks/routers/kimi-k3-fast
    prices: {input_mtok: 4, cache_read_mtok: 0.4, output_mtok: 20}
"""
    )

    source_fireworks.main(provider_path)

    assert capsys.readouterr().out == 'Fireworks prices updated: 16 added, 1 updated\n'
    provider = ProviderYaml(provider_path).provider
    fast = provider.find_model('accounts/fireworks/routers/kimi-k3-fast')
    assert fast is not None and isinstance(fast.prices, list)
    assert fast.prices[-1] == ConditionalPrice.model_validate(
        {
            'constraint': {'start_date': fast.prices_checked},
            'prices': {'input_mtok': '4.5', 'cache_read_mtok': '0.45', 'output_mtok': '22.5'},
        }
    )
    added = provider.find_model('accounts/fireworks/models/kimi-k3')
    assert added is not None and added.id == 'kimi-k3'


@pytest.mark.vcr()
def test_fireworks_main_keeps_the_tracked_models_in_sync(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'fireworks.yml'
    copyfile(package_dir / 'providers/fireworks.yml', provider_path)

    source_fireworks.main(provider_path)

    assert capsys.readouterr().out == 'Fireworks prices updated: 0 added, 17 updated\n'
