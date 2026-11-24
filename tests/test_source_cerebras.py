from __future__ import annotations

from decimal import Decimal

import pytest

from prices import source_cerebras
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot


def test_cerebras_converts_per_token_prices_and_skips_unpriced_models() -> None:
    models = source_cerebras.parse_models(
        [
            {
                'id': 'gpt-oss-120b',
                'name': 'OpenAI GPT OSS',
                'pricing': {'prompt': '0.00000035', 'completion': '0.00000075'},
                'limits': {'max_context_length': 131072},
            },
            {'id': 'free-model', 'pricing': {'prompt': '0', 'completion': '0'}},
            {'id': 'no-pricing'},
        ]
    )

    assert [(model.id, model.name, model.context_window) for model in models] == [
        ('gpt-oss-120b', 'OpenAI GPT OSS', 131072)
    ]
    assert models[0].prices == ModelPrice(input_mtok=Decimal('0.35'), output_mtok=Decimal('0.75'))


@pytest.mark.vcr()
def test_cerebras_main_fetches_recorded_models(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('cerebras.yml')

    source_cerebras.main(provider_path)

    assert capsys.readouterr().out == 'Cerebras prices updated: 0 added, 2 updated\n'
