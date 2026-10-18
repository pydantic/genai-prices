from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_voyageai
from prices.prices_types import ModelPrice
from prices.utils import package_dir

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


def test_voyageai_rejects_an_unparseable_price() -> None:
    with pytest.raises(RuntimeError, match='Unexpected Voyage pricing row'):
        source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN.replace('$0.06 ', 'Contact us'))


def test_voyageai_rejects_duplicate_models() -> None:
    with pytest.raises(RuntimeError, match='Duplicate Voyage model in pricing data: voyage-4'):
        source_voyageai.parse_pricing_markdown(PRICING_MARKDOWN.replace('`voyage-3.5-lite`', '`voyage-4`'))


@pytest.mark.vcr()
def test_voyageai_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'voyageai.yml'
    copyfile(package_dir / 'providers/voyageai.yml', provider_path)

    source_voyageai.main(provider_path)

    assert capsys.readouterr().out == 'Voyage AI prices updated: 0 added, 24 updated\n'


@pytest.mark.vcr()
def test_voyageai_main_rejects_an_html_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    url = 'https://example.com/'
    monkeypatch.setattr(source_voyageai, 'PRICING_URL', url)

    with pytest.raises(RuntimeError, match=f'{url} returned HTML instead of markdown'):
        source_voyageai.main(tmp_path / 'unused.yml')
