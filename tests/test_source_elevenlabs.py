from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_elevenlabs
from prices.prices_types import ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PAGE = """\
<html><script>var Realtime = 1;</script><body>
<h2>Eleven Realtime v1 Mini</h2>
<div>Minutes included</div><div>Connected audio (per additional minute)</div>
<div>Input tokens (per 1M)</div><div>Output tokens (per 1M)</div>
<div>~14 min</div><div>$0.080</div><div>$0.20</div><div>$6.00</div>
<div>~71 min</div><div>$0.080</div><div>$0.20</div><div>$6.00</div>
<h2>Eleven Realtime v1 Max</h2>
<div>Minutes included</div><div>Connected audio (per additional minute)</div>
<div>Input tokens (per 1M)</div><div>Output tokens (per 1M)</div>
<div>~12 min</div><div>$0.080</div><div>$1.80</div><div>$9.00</div>
<div>Both models</div>
</body></html>
"""


def test_elevenlabs_parses_realtime_rates_per_model() -> None:
    models = source_elevenlabs.parse_pricing_page(PAGE)

    assert [(model.id, model.name, model.prices) for model in models] == [
        (
            'eleven_realtime_v1_mini',
            'Eleven Realtime v1 Mini',
            ModelPrice.model_validate(
                {'audio_hours': Decimal('4.8'), 'input_mtok': Decimal('0.2'), 'output_mtok': Decimal('6')}
            ),
        ),
        (
            'eleven_realtime_v1_max',
            'Eleven Realtime v1 Max',
            ModelPrice.model_validate(
                {'audio_hours': Decimal('4.8'), 'input_mtok': Decimal('1.8'), 'output_mtok': Decimal('9')}
            ),
        ),
    ]
    assert all(model.prices_checked == date.today() for model in models)


@pytest.mark.parametrize(
    'page, error',
    [
        (PAGE.replace('Eleven Realtime v1 Max', 'Eleven Realtime v2'), 'no Eleven Realtime v1 Max rate table'),
        (PAGE.replace('Input tokens (per 1M)', 'Input (per 1M)', 1), 'no Eleven Realtime v1 Mini rate table'),
        (PAGE.replace('$6.00', '$7.00', 1), 'has 2 distinct rate rows'),
        (PAGE.replace('$9.00', 'Contact sales'), 'Invalid ElevenLabs price: Contact sales'),
    ],
)
def test_elevenlabs_rejects_unexpected_page_shapes(page: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_elevenlabs.parse_pricing_page(page)


@pytest.mark.vcr()
def test_elevenlabs_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'elevenlabs.yml'
    copyfile(package_dir / 'providers/elevenlabs.yml', provider_path)

    source_elevenlabs.main(provider_path)

    assert capsys.readouterr().out == 'ElevenLabs prices updated: 0 added, 2 updated\n'
    provider = ProviderYaml(provider_path).provider
    max_model = provider.find_model('eleven_realtime_v1_max')
    assert max_model is not None
    assert max_model.prices == ModelPrice.model_validate(
        {
            'audio_hours': Decimal('4.8'),
            'input_mtok': Decimal('1.8'),
            'cache_read_mtok': Decimal('0.18'),
            'output_mtok': Decimal('9'),
        }
    )
