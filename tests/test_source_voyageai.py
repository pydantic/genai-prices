from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

from prices import source_voyageai
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot

PRICING_MARKDOWN = """\
# Text Embeddings

| Model                                    | Price per thousand tokens | Price per million tokens | Number of free tokens |
| ---------------------------------------- | ------------------------- | ------------------------ | --------------------- |
| `voyage-4`                               | $0.00006                  | $0.06                    | 200 million           |
| `voyage-law-2`<br />`voyage-code-2`      | $0.00012                  | $0.12                    | 50 million            |

# Multimodal Embeddings

| Model                   | Price per million tokens | Price per billion pixels |
| ----------------------- | ------------------------ | ------------------------ |
| `voyage-multimodal-3.5` | $0.12                    | $0.60                    |

***

## Older models

| Model                                           | Price per thousand tokens | Price per million tokens |
| :---------------------------------------------- | :------------------------ | :----------------------- |
| `voyage-3.5-lite`<br />`voyage-multimodal-2`    | $0.00002                  | $0.02                    |
| `rerank-1`                                      | $0.00005                  | $0.05                    |
"""


def test_voyageai_parses_text_embedding_rows_and_skips_rerankers_and_multimodal() -> None:
    models = source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(model.id, model.name, model.prices) for model in models] == [
        ('voyage-4', 'Voyage 4', ModelPrice(input_mtok=Decimal('0.06'))),
        ('voyage-law-2', 'Voyage Law 2', ModelPrice(input_mtok=Decimal('0.12'))),
        ('voyage-code-2', 'Voyage Code 2', ModelPrice(input_mtok=Decimal('0.12'))),
        ('voyage-3.5-lite', 'Voyage 3.5 Lite', ModelPrice(input_mtok=Decimal('0.02'))),
    ]
    assert models[0].prices_checked == date.today()


def test_voyageai_rejects_a_missing_section() -> None:
    with pytest.raises(RuntimeError, match='Voyage pricing page has no "Older models" table'):
        source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN.replace('Older models', 'Legacy models'))


def test_voyageai_reports_an_unparseable_price_and_reads_the_other_rows(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN.replace('$0.06 ', 'Contact us'))

    assert [model.id for model in models] == ['voyage-law-2', 'voyage-code-2', 'voyage-3.5-lite']
    assert capsys.readouterr().out.startswith(
        'Voyage AI: skipped a row it cannot read for voyage-4; update it by hand. '
        "Unexpected Voyage pricing row: ['`voyage-4`'"
    )


def test_voyageai_reports_a_row_without_a_price_cell(capsys: pytest.CaptureFixture[str]) -> None:
    law_row = next(line for line in PRICING_MARKDOWN.splitlines() if line.startswith('| `voyage-law-2`'))
    markdown = PRICING_MARKDOWN.replace(law_row, law_row + '\n| `voyage-5` |')

    models = source_voyageai.parse_pricing_markdown(markdown)

    assert 'voyage-5' not in [model.id for model in models]
    assert capsys.readouterr().out.startswith(
        'Voyage AI: skipped a row it cannot read for voyage-5; update it by hand. '
    )


def test_voyageai_keeps_a_model_unchanged_when_a_duplicate_row_is_unreadable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown = PRICING_MARKDOWN.replace('`voyage-3.5-lite`', '`voyage-4`').replace('$0.02 ', 'Contact us')

    models = source_voyageai.parse_pricing_markdown(markdown)

    assert [model.id for model in models] == ['voyage-law-2', 'voyage-code-2']
    assert capsys.readouterr().out.startswith(
        'Voyage AI: skipped a row it cannot read for voyage-4, voyage-multimodal-2; update it by hand. '
    )


def test_voyageai_keeps_a_duplicated_model_unchanged_and_reports_it(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN.replace('`voyage-3.5-lite`', '`voyage-4`'))

    assert [model.id for model in models] == ['voyage-law-2', 'voyage-code-2']
    assert capsys.readouterr().out == (
        'Voyage AI: kept voyage-4 unchanged, the pricing page lists it more than once; update it by hand\n'
    )


@pytest.mark.vcr()
def test_voyageai_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('voyageai.yml')

    source_voyageai.main(provider_path)

    assert capsys.readouterr().out == 'Voyage AI prices updated: 0 added, 24 updated\n'


@pytest.mark.vcr()
def test_voyageai_main_rejects_an_html_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    url = 'https://example.com/'
    monkeypatch.setattr(source_voyageai, 'PRICING_URL', url)

    with pytest.raises(RuntimeError, match=f'{url} returned HTML instead of markdown'):
        source_voyageai.main(tmp_path / 'unused.yml')


def test_voyageai_main_rejects_html_whatever_the_media_type_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def get(url: str, **_: object) -> httpx2.Response:
        return httpx2.Response(
            200, headers={'Content-Type': 'Text/HTML'}, text='<p>hi</p>', request=httpx2.Request('GET', url)
        )

    monkeypatch.setattr(httpx2, 'get', get)

    with pytest.raises(RuntimeError, match='returned HTML instead of markdown'):
        source_voyageai.main(tmp_path / 'unused.yml')
