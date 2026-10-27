from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_URL = 'https://elevenlabs.io/pricing/api'
MIN_MODEL_COUNT = 2
MODEL_IDS = {
    'Eleven Realtime v1 Mini': 'eleven_realtime_v1_mini',
    'Eleven Realtime v1 Max': 'eleven_realtime_v1_max',
}
HEADER = [
    'Minutes included',
    'Connected audio (per additional minute)',
    'Input tokens (per 1M)',
    'Output tokens (per 1M)',
]


def parse_pricing_page(page: str) -> list[ModelInfo]:
    """Parse the Realtime API tables; the page lists the same rates on every plan row."""
    page = re.sub(r'<(script|style)\b.*?</\1>', '', page, flags=re.DOTALL)
    lines = [line for text in re.sub(r'<[^>]+>', '\n', page).splitlines() if (line := html.unescape(text).strip())]
    models: list[ModelInfo] = []
    for name, model_id in MODEL_IDS.items():
        start = next((i for i in range(len(lines) - 4) if lines[i] == name and lines[i + 1 : i + 5] == HEADER), None)
        if start is None:
            raise RuntimeError(f'ElevenLabs pricing page has no {name} rate table in the expected shape')
        rates: set[tuple[str, ...]] = set()
        row = start + 5
        while row + 3 < len(lines) and lines[row].startswith('~'):
            rates.add(tuple(lines[row + 1 : row + 4]))
            row += 4
        if len(rates) != 1:
            raise RuntimeError(f'ElevenLabs {name} has {len(rates)} distinct rate rows; expected 1')
        minute, input_mtok, output_mtok = (_parse_price(value) for value in rates.pop())
        models.append(
            ModelInfo(
                id=model_id,
                name=name,
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice.model_validate(
                    {'audio_hours': minute * 60, 'input_mtok': input_mtok, 'output_mtok': output_mtok}
                ),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_pricing_page(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/elevenlabs.yml')
    added, updated = provider_yaml.upsert_models(models, source='ElevenLabs', min_count=MIN_MODEL_COUNT)
    print(f'ElevenLabs prices updated: {added} added, {updated} updated')


def get_elevenlabs_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update ElevenLabs Realtime prices."""
    main()


def _parse_price(value: str) -> Decimal:
    if re.fullmatch(r'\$[0-9]+(?:\.[0-9]+)?', value) is None:
        raise RuntimeError(f'Invalid ElevenLabs price: {value}')
    return Decimal(value.removeprefix('$'))


if __name__ == '__main__':
    main()
