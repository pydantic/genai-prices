from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypeAlias

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://ai.google.dev/gemini-api/docs/pricing.md.txt'
MIN_MODEL_COUNT = 15
MODEL_IDS = re.compile(r'\[`([\w.-]+)`\]')
RATE = re.compile(
    r'\$(?P<price>\d+(?:\.\d+)?)'
    r'(?:,? prompts (?P<op><=|>) (?P<threshold>\d+)k(?: tokens)?)?'
    r'(?: or \$[\d.]+/min)?'
    r'(?: \((?P<modalities>[a-z /,]+)\))?'
    r'(?: (?P<when>through|starting) (?P<date>\w+ \d+, \d{4})\.)?'
)
SEARCH_RATE = re.compile(r'then \$(\d+(?:\.\d+)?) (?:per|/) 1,000 (?:requests|grounded prompts)')
NOISE = [
    re.compile(r'\^[\\*]+\^|\\\*'),
    re.compile(r',? equivalent to .*$', re.IGNORECASE),
    re.compile(r' ?\(\$[\d.]+ per \w+\)'),
    re.compile(r' ?\$[\d.]+ / 1,000,000 tokens per hour \(storage price\)(?: (?:through|starting) \w+ \d+, \d{4}\.)?'),
    re.compile(r' ?Implicit caching only \(explicit caching is not supported\)\.'),
]
ROWS = {
    'Input price': 'input',
    'Text input price': 'input',
    'Image input price': 'input_image',
    'Audio input price': 'input_audio',
    'Video input price': 'input_video',
    'Output price': 'output',
    'Context caching price': 'cache_read',
}
MODALITY_KEYS = {
    'input': {'audio': 'input_audio_mtok', 'image': 'input_image_mtok', 'video': 'input_video_mtok'},
    'output': {'audio': 'output_audio_mtok', 'image': 'output_image_mtok', 'video': 'output_video_mtok'},
    'cache_read': {'audio': 'cache_audio_read_mtok'},
}

Rate: TypeAlias = 'Decimal | TieredPrices'


class UnreadablePriceError(ValueError):
    """A pricing cell the parser cannot turn into rates without guessing."""


def parse_pricing_markdown(markdown: str, today: date | None = None) -> list[ModelInfo]:
    today = today or date.today()
    models: list[ModelInfo] = []
    for section in re.split(r'^## ', markdown, flags=re.MULTILINE)[1:]:
        heading, _, body = section.partition('\n')
        model_ids = MODEL_IDS.findall(next((line for line in body.splitlines() if line.startswith('*[`')), ''))
        tables = markdown_tables(body.split('### Standard', 1)[-1])
        if not model_ids or not tables:
            continue
        header, rows = tables[0]
        if len(header) != 3 or 'per 1M tokens' not in header[2]:
            print(f'Google: skipped {heading}, its prices are not per 1M tokens')
            continue
        try:
            prices = _prices({label: paid for label, _, paid in rows}, today)
        except UnreadablePriceError as e:
            print(f'Google: skipped {heading}, {e}')
            continue
        if prices.input_mtok is None:
            print(f'Google: skipped {heading}, it has no paid input price')
            continue
        models.extend(
            ModelInfo(id=model_id, match=ClauseEquals(equals=model_id), prices=prices, prices_checked=today)
            for model_id in model_ids
        )
    return models


def main(provider_path: Path | None = None) -> None:
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/google.yml')
    models: list[ModelInfo] = []
    for model in parse_pricing_markdown(get_markdown(PRICING_URL)):
        if provider_yaml.provider.find_model(model.id) is None:
            print(f'Google: skipped {model.id}, it is not in google.yml yet')
        else:
            models.append(model)
    added, updated = provider_yaml.upsert_models(models, source='Google', min_count=MIN_MODEL_COUNT)
    print(f'Google prices updated: {added} added, {updated} updated')


def get_google_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Gemini API prices."""
    main()


def _prices(cells: dict[str, str], today: date) -> ModelPrice:
    keys: dict[str, Rate] = {}
    for label, cell in cells.items():
        if label.startswith('Grounding with Google') and 'Search' in label:
            if search := SEARCH_RATE.search(cell):
                keys['web_searches_kcount'] = Decimal(search[1])
            continue
        row = next((row for prefix, row in ROWS.items() if label.startswith(prefix)), None)
        if row is None or cell.strip() in ('Not available', ''):
            continue
        for key, rate in _cell_rates(row, cell, today).items():
            if key in keys:
                raise UnreadablePriceError(f'{key} is priced twice')
            keys[key] = rate
    return ModelPrice.model_validate(keys)


def _cell_rates(row: str, cell: str, today: date) -> dict[str, Rate]:
    text = cell.replace('\\<', '<').replace('\\>', '>')
    for noise in NOISE:
        text = noise.sub('', text)
    text = ' '.join(text.split())
    matches = list(RATE.finditer(text))
    if not matches or ' '.join(m[0] for m in matches) != text:
        raise UnreadablePriceError(f'unreadable price {cell!r}')

    # A "through <date>." or "starting <date>." clause dates every rate since the previous clause.
    current: list[re.Match[str]] = []
    pending: list[re.Match[str]] = []
    for match in matches:
        pending.append(match)
        if match['when'] is None:
            continue
        if match['when'] == 'starting':
            if (start := datetime.strptime(match['date'], '%B %d, %Y').date()) > today:
                raise UnreadablePriceError(f'a rate starts on {start}, which a dated entry must record')
            current += pending
        pending = []
    current += pending

    rates: dict[str, Rate] = {}
    tiers = [m for m in current if m['op']]
    if tiers:
        if [m['op'] for m in current] != ['<=', '>'] or tiers[0]['threshold'] != tiers[1]['threshold']:
            raise UnreadablePriceError(f'unpaired prompt-size tiers in {cell!r}')
        tier = Tier(start=int(tiers[0]['threshold']) * 1000, price=Decimal(tiers[1]['price']))
        return {f'{row}_mtok': TieredPrices(base=Decimal(tiers[0]['price']), tiers=[tier])}

    for match in current:
        modalities = set(re.split(r'\s*(?:/|,|\band\b)\s*', match['modalities'] or 'text'))
        modalities = {modality.removesuffix('s') for modality in modalities} - {'thinking'}
        if 'text' in modalities or row not in MODALITY_KEYS or len(current) == 1:
            keys = {f'{row}_mtok'}
        else:
            keys = {MODALITY_KEYS[row].get(modality, '') for modality in modalities}
        if '' in keys or keys & rates.keys():
            raise UnreadablePriceError(f'unexpected modalities in {cell!r}')
        rates |= dict.fromkeys(keys, Decimal(match['price']))
    return rates
