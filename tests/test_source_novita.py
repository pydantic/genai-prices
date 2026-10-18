from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_novita
from prices.prices_types import ModelPrice, Tier, TieredPrices
from prices.utils import package_dir


def rates(prompt: str, completion: str, cache_read: str | None = None) -> dict[str, object]:
    pricing: dict[str, object] = {
        'prompt': {'price_per_m_decimal': prompt},
        'completion': {'price_per_m_decimal': completion},
    }
    if cache_read is not None:
        pricing['input_cache_read'] = {'price_per_m_decimal': cache_read}
    return pricing


def test_novita_parses_flat_prices_skips_free_models_and_drops_unknown_context() -> None:
    models = source_novita.parse_models(
        [
            {
                'id': 'zai-org/glm-5.3-flash',
                'display_name': 'GLM 5.3 Flash',
                'context_size': 1048576,
                'pricing': rates('0.15', '0.5', '0.03'),
            },
            {'id': 'free', 'pricing': rates('0', '0')},
            {'id': 'image', 'display_name': 'image\t', 'context_size': 0, 'pricing': rates('1', '1')},
        ]
    )

    assert [(model.id, model.name, model.context_window) for model in models] == [
        ('zai-org/glm-5.3-flash', 'GLM 5.3 Flash', 1048576),
        ('image', 'image', None),
    ]
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.15'), cache_read_mtok=Decimal('0.03'), output_mtok=Decimal('0.5')
    )


def test_novita_billing_bands_become_tiers_only_where_a_base_rate_exists() -> None:
    [model] = source_novita.parse_models(
        [
            {
                'id': 'minimax/minimax-m3',
                'pricing': rates('0.3', '1.2'),
                'is_tiered_billing': True,
                'tiered_billing_configs': [
                    {'min_tokens': 1, 'max_tokens': 524288, 'pricing': rates('0.3', '1.2')},
                    {'min_tokens': 524288, 'max_tokens': 1000000, 'pricing': rates('0.6', '2.4', '0.12')},
                ],
            }
        ]
    )

    assert model.prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('0.3'), tiers=[Tier(start=524288, price=Decimal('0.6'))]),
        output_mtok=TieredPrices(base=Decimal('1.2'), tiers=[Tier(start=524288, price=Decimal('2.4'))]),
    )


@pytest.mark.vcr()
def test_novita_main_fetches_recorded_models(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'novita.yml'
    copyfile(package_dir / 'providers/novita.yml', provider_path)

    source_novita.main(provider_path)

    assert capsys.readouterr().out == 'Novita prices updated: 0 added, 92 updated\n'
