from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_google
from prices.prices_types import ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

TODAY = date(2026, 11, 3)
HEADER = '| Feature | Free Tier | Paid Tier, per 1M tokens in USD |'


def table(rows: str, header: str = HEADER) -> str:
    """Render `|`-delimited rows as the pricing page's Markdoc table."""
    cells = [[cell.strip() for cell in line.strip()[1:-1].split('|')] for line in [header, *rows.splitlines()]]
    body = '\n\n  ---\n\n'.join('\n'.join(f'  * {cell}' for cell in row) for row in cells)
    return f'{{% table %}}\n{body}\n{{% /table %}}'


def section(heading: str, ids: str, rows: str, table_header: str = HEADER) -> str:
    return (
        f'## {heading}  {{% id="x" %}}\n\n  *{ids}*\n\n{{% tabs %}}\n  {{% tab title="Standard" %}}\n'
        f'{table(rows, table_header)}\n  {{% /tab %}}\n\n  {{% tab title="Batch" %}}\n'
        f'{table("| Input price | x | $9 |")}\n  {{% /tab %}}\n{{% /tabs %}}\n'
    )


PRICING_MARKDOWN = '\n'.join(
    [
        'Intro text.\n',
        section(
            'Pro',
            '[`gemini-pro-x`](https://x) and\n    [`gemini-pro-x-customtools`](https://x)',
            '| Input price | Not available | $2.00, prompts <= 200k tokens $4.00, prompts > 200k tokens |\n'
            '| Output price (including thinking tokens) | Not available | $12.00, prompts <= 200k tokens '
            '$18.00, prompts > 200k |\n'
            '| Context caching price | Not available | $0.20, prompts <= 200k tokens $0.40, prompts > 200k '
            '$4.50 / 1,000,000 tokens per hour (storage price) |\n'
            '| Grounding with Google Search{% sup %}*{% /sup %} | Not available | 5,000 free search requests per month, '
            'then $14 per 1,000 requests. |\n'
            '| Grounding with Google Maps | Not available | then $25 / 1,000 grounded prompts |\n'
            '| Used to improve our products | N/A | No |',
        ),
        section(
            'Flash',
            '[`gemini-flash-x`](https://x)',
            '| Input price | Free | $0.30 (text / image / video) $1.00 (audio) through September 30, 2026. '
            '$0.40 (text / image / video) $1.20 (audio) starting October 1, 2026. |\n'
            '| Output price (including thinking tokens) | Free | $2.50 |\n'
            '| Context caching price | Not available | $0.03 (text / image / video) $0.1 (audio) '
            '$1.00 / 1,000,000 tokens per hour (storage price) |\n'
            '| Grounding with Google Search | Free | 1,500 RPD (free), then $35 / 1,000 grounded prompts |',
        ),
        section(
            'Live',
            '[`gemini-live-x`](https://x)',
            '| Input price | Free | $0.75 (text) $3.00 or $0.005/min (audio) $1.00 or $0.002/min (image/video) |\n'
            '| Output price (including thinking tokens) | Free | $4.50 (text) $12.00 or $0.018/min (audio) |\n'
            '| Grounding with Google Search | Not Supported |   |',
        ),
        section(
            'Image 🍌',
            '[`gemini-image-x`](https://x)',
            '| Input price | Not available | $2.00 (text/image), equivalent to $0.0011 per image{% sup %}*{% /sup %} |\n'
            '| Output price | Not available | $12.00 (text and thinking) $120.00 (images) Equivalent to $0.134 '
            'per 1K/2K image{% sup %}**{% /sup %} |\n'
            '| Grounding with Google Web and Image Search{% sup %}**{% /sup %} | Not available | then $14 per 1,000 requests '
            'for text and image-based grounding. |',
        ),
        section(
            'TTS',
            '[`gemini-tts-x`](https://x)',
            '| Input price | Free | $1.00 (text) |\n| Output price | Free | $20.00 (audio) |\n| Context caching price | Free | Not available |',
        ),
        section(
            'Embedding',
            '[`gemini-embedding-x`](https://x)',
            '| Text input price | Free | $0.20 |\n'
            '| Image input price | Free | $0.45 ($0.00012 per image) |\n'
            '| Audio input price | Free | $6.50 ($0.00016 per second) |',
        ),
        '## Argon\n\n*[`gemini-argon-x`](https://x)*\n\n{% table %}\n'
        '  * Feature\n  * Free Tier\n  * Paid Tier, per 1M tokens in USD\n\n  ---\n\n'
        '  * Input price\n  * Not available\n  * $2.00 through November 30, 2026. \\\\\n  $4.00 starting December 1, 2026.\n'
        '\n  ---\n\n'
        '  * Context caching price\n  * Not available\n  * $0.10 through November 30, 2026.   \n'
        '  $0.20 starting December 1, 2026.   \n  Implicit caching only (explicit caching is not supported).\n'
        '{% /table %}\n',
        section(
            'Old image',
            '[`gemini-old-image-x`](https://x)',
            '| Output price | Not available | $0.039 per image{% sup %}*{% /sup %} |',
        ),
        section('Output only', '[`gemini-output-x`](https://x)', '| Output price | Free | $1.00 |'),
        section(
            'Veo',
            '[`veo-x`](https://x)',
            '| Standard video | Not available | $0.40 (720p) |',
            '| Feature | Free Tier | Paid Tier, per second in USD |',
        ),
        '## [Gemma 4](https://x)\n\nOpen model.\n\n' + table('| Input price | Free | Not available |') + '\n',
        '## Pricing for tools\n\nTools are priced at their own rates.\n',
    ]
)


def price(**rates: Decimal | TieredPrices) -> ModelPrice:
    return ModelPrice.model_validate(rates)


def tiered(base: str, price: str) -> TieredPrices:
    return TieredPrices(base=Decimal(base), tiers=[Tier(start=200_000, price=Decimal(price))])


def test_google_parses_standard_rates_by_modality_and_prompt_size(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_google.parse_pricing_markdown(PRICING_MARKDOWN, today=TODAY)

    assert {model.id: model.prices for model in models} == {
        'gemini-pro-x': (
            pro := price(
                input_mtok=tiered('2', '4'),
                output_mtok=tiered('12', '18'),
                cache_read_mtok=tiered('0.2', '0.4'),
                web_searches_kcount=Decimal('14'),
            )
        ),
        'gemini-pro-x-customtools': pro,
        'gemini-flash-x': price(
            input_mtok=Decimal('0.4'),
            input_audio_mtok=Decimal('1.2'),
            output_mtok=Decimal('2.5'),
            cache_read_mtok=Decimal('0.03'),
            cache_audio_read_mtok=Decimal('0.1'),
            web_searches_kcount=Decimal('35'),
        ),
        'gemini-live-x': price(
            input_mtok=Decimal('0.75'),
            input_audio_mtok=Decimal('3'),
            input_image_mtok=Decimal('1'),
            input_video_mtok=Decimal('1'),
            output_mtok=Decimal('4.5'),
            output_audio_mtok=Decimal('12'),
        ),
        'gemini-image-x': price(
            input_mtok=Decimal('2'),
            output_mtok=Decimal('12'),
            output_image_mtok=Decimal('120'),
            web_searches_kcount=Decimal('14'),
        ),
        'gemini-tts-x': price(input_mtok=Decimal('1'), output_mtok=Decimal('20')),
        'gemini-embedding-x': price(
            input_mtok=Decimal('0.2'), input_image_mtok=Decimal('0.45'), input_audio_mtok=Decimal('6.5')
        ),
    }
    assert {model.prices_checked for model in models} == {TODAY}
    assert capsys.readouterr().out == (
        'Google: skipped Argon, a rate starts on 2026-12-01, which a dated entry must record\n'
        "Google: skipped Old image, unreadable price '$0.039 per image{% sup %}*{% /sup %}'\n"
        'Google: skipped Output only, it has no paid input price\n'
        'Google: skipped Veo, its prices are not per 1M tokens\n'
    )


@pytest.mark.parametrize(
    ('rows', 'reason'),
    [
        ('| Input price | Free | $1.00 |\n| Text input price | Free | $2.00 |', 'input_mtok is priced twice'),
        (
            '| Input price | Free | $1.00, prompts <= 200k tokens $2.00, prompts > 128k tokens |',
            "unpaired prompt-size tiers in '$1.00, prompts <= 200k tokens $2.00, prompts > 128k tokens'",
        ),
        ('| Input price | Free | $1.00 (text) $2.00 (pdf) |', "unexpected modalities in '$1.00 (text) $2.00 (pdf)'"),
        (
            '| Input price | Free | $1.00 (audio) $2.00 (audio) |',
            "unexpected modalities in '$1.00 (audio) $2.00 (audio)'",
        ),
        ('| Input price | Free | $1.00 per page |', "unreadable price '$1.00 per page'"),
        ('| Input price | Free | Contact sales |', "unreadable price 'Contact sales'"),
    ],
)
def test_google_skips_a_model_whose_prices_it_cannot_read(
    rows: str, reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    markdown = section('Odd', '[`gemini-odd-x`](https://x)', rows)

    assert source_google.parse_pricing_markdown(markdown, today=TODAY) == []
    assert capsys.readouterr().out == f'Google: skipped Odd, {reason}\n'


def test_google_rejects_a_table_row_with_missing_cells() -> None:
    markdown = section('Odd', '[`gemini-odd-x`](https://x)', '| Input price | Free | $1.00 |').replace('  * Free\n', '')

    with pytest.raises(ValueError, match=r"Table row has 2 cells, header has 3: \['Input price', '\$1.00'\]"):
        source_google.parse_pricing_markdown(markdown, today=TODAY)


@pytest.mark.vcr()
def test_google_main_fetches_recorded_pricing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class RecordedDay(date):
        @classmethod
        def today(cls) -> date:
            return TODAY

    monkeypatch.setattr(source_google, 'date', RecordedDay)
    provider_path = tmp_path / 'google.yml'
    copyfile(package_dir / 'providers/google.yml', provider_path)

    source_google.main(provider_path)

    out = capsys.readouterr().out.splitlines()
    assert 'Google: skipped gemini-3.5-transcribe, it is not in google.yml yet' in out
    assert out[-1] == 'Google prices updated: 0 added, 20 updated'
    record = ProviderYaml(provider_path).provider.find_model('gemini-2.5-pro')
    assert record is not None and record.prices_checked == TODAY
