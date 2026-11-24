from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices import source_typesafe
from prices.prices_types import ClauseEquals, ClauseOr, ClauseRegex, ModelPrice
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

MODELS_MARKDOWN = """\
## Current models

| | Jev 1.14 | Jev 1.13 |
| :- | :- | :- |
| Model ID | `jev-1.14.0` | `jev-1.13.0` |
| Price (per Btok / per Mtok) | \\$42 / \\$0.042 | \\$40 / \\$0.040 |
| Context length | 64k per-request / 32k per-question | 64k per-request |

## Aliases

| Alias | Points to | Meaning |
| :- | :- | :- |
| `jev-latest` | `jev-1.14.0` | The most recent stable release. |
| `jev-preview` | `jev-1.14.0` | The most recent release. |
"""


def test_typesafe_parses_transposed_table_and_aliases() -> None:
    models = source_typesafe.parse_models_markdown(MODELS_MARKDOWN)

    assert [(model.id, model.name, model.match, model.context_window, model.prices) for model in models] == [
        (
            'jev-1.14.0',
            'Jev 1.14.0',
            ClauseOr.model_validate(
                {
                    'or': [
                        ClauseEquals(equals='jev-1.14.0'),
                        ClauseEquals(equals='jev-latest'),
                        ClauseEquals(equals='jev-preview'),
                    ]
                }
            ),
            32000,
            ModelPrice(input_mtok=Decimal('0.042')),
        ),
        ('jev-1.13.0', 'Jev 1.13.0', ClauseEquals(equals='jev-1.13.0'), None, ModelPrice(input_mtok=Decimal('0.040'))),
    ]
    assert models[0].prices_checked == date.today()


@pytest.mark.parametrize(
    'markdown, error',
    [
        (MODELS_MARKDOWN.replace('## Aliases', '## Names'), 'TypeSafe models page has no "Aliases" table'),
        (MODELS_MARKDOWN.replace('| Model ID |', '| ID |'), 'missing the Model ID or Price row'),
    ],
)
def test_typesafe_rejects_unexpected_page_shapes(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_typesafe.parse_models_markdown(markdown)


@pytest.mark.parametrize(
    ('markdown', 'error', 'model_ids'),
    [
        (
            MODELS_MARKDOWN.replace('`jev-preview` | `jev-1.14.0`', '`jev-preview` | `jev-2.0.0`'),
            "TypeSafe aliases point at models missing from the current models table: {'jev-2.0.0'}",
            ['jev-1.14.0', 'jev-1.13.0'],
        ),
        (
            MODELS_MARKDOWN.replace('\\$42 / \\$0.042', 'Contact us'),
            'Unexpected TypeSafe model column: jev-1.14.0 Contact us',
            ['jev-1.13.0'],
        ),
    ],
)
def test_typesafe_reports_an_unreadable_column_or_alias_and_reads_the_others(
    markdown: str, error: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_typesafe.parse_models_markdown(markdown)

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == f'TypeSafe: skipped a row it cannot read; update it by hand. {error}\n'


def test_typesafe_keeps_a_model_listed_in_two_columns_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    markdown = (
        MODELS_MARKDOWN.replace('`jev-1.13.0` |', '`jev-1.13.0` | `jev-1.14.0` |')
        .replace('\\$40 / \\$0.040 |', '\\$40 / \\$0.040 | \\$41 / \\$0.041 |')
        .replace('| 64k per-request |\n', '| 64k per-request | 64k per-request |\n')
    )

    models = source_typesafe.parse_models_markdown(markdown)

    assert [model.id for model in models] == ['jev-1.13.0']
    assert capsys.readouterr().out == (
        'TypeSafe: kept jev-1.14.0 unchanged, the models page lists it more than once; update it by hand\n'
    )


def test_typesafe_keeps_the_aliases_of_a_column_it_cannot_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = tmp_path / 'typesafe.yml'
    provider_path.write_text(
        """\
id: typesafe
name: TypeSafe
api_pattern: typesafe
models:
  - id: jev-1.13.0
    match:
      or:
        - equals: jev-1.13.0
        - equals: jev-latest
    prices: {input_mtok: 0.040}

  - id: jev-1.14.0
    match:
      or:
        - equals: jev-1.14.0
        - equals: jev-preview
    prices: {input_mtok: 0.041}
"""
    )
    markdown = MODELS_MARKDOWN.replace('\\$42 / \\$0.042', 'Contact us')
    monkeypatch.setattr(source_typesafe, 'get_markdown', {source_typesafe.MODELS_URL: markdown}.__getitem__)

    source_typesafe.main(provider_path)

    provider = ProviderYaml(provider_path).provider
    assert [(model.id, model.match, model.prices) for model in provider.models] == [
        (
            'jev-1.13.0',
            ClauseOr.model_validate({'or': [ClauseEquals(equals='jev-1.13.0'), ClauseEquals(equals='jev-latest')]}),
            ModelPrice(input_mtok=Decimal('0.040')),
        ),
        (
            'jev-1.14.0',
            ClauseOr.model_validate({'or': [ClauseEquals(equals='jev-1.14.0'), ClauseEquals(equals='jev-preview')]}),
            ModelPrice(input_mtok=Decimal('0.041')),
        ),
    ]
    assert capsys.readouterr().out.startswith(
        'TypeSafe: skipped a row it cannot read; update it by hand. Unexpected TypeSafe model column: jev-1.14.0'
    )


def test_typesafe_moves_aliases_and_drops_unlisted_ones(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'typesafe.yml'
    provider_path.write_text(
        """\
id: typesafe
name: TypeSafe
api_pattern: typesafe
models:
  - id: jev-1.11.0
    match: {equals: jev-1.11.0}
    prices: {input_mtok: 0.042}

  - id: jev-1.12.0
    match:
      or:
        - equals: jev-1.12.0
        - equals: jev-legacy
    prices: {input_mtok: 0.042}

  - id: jev-1.13.0
    match:
      or:
        - equals: jev-1.13.0
        - equals: jev-latest
    prices: {input_mtok: 0.040}

  - id: jev-1.14.0
    match:
      or:
        - equals: jev-1.14.0
        - regex: ^(typesafe/)?jev-1\\.14(-\\d{8})?$
        - equals: jev-preview
    prices: {input_mtok: 0.042}
"""
    )
    monkeypatch.setattr(source_typesafe, 'get_markdown', {source_typesafe.MODELS_URL: MODELS_MARKDOWN}.__getitem__)

    source_typesafe.main(provider_path)

    provider = ProviderYaml(provider_path).provider
    assert [model.match for model in provider.models] == [
        ClauseEquals(equals='jev-1.11.0'),
        ClauseEquals(equals='jev-1.12.0'),
        ClauseEquals(equals='jev-1.13.0'),
        ClauseOr.model_validate(
            {
                'or': [
                    ClauseEquals(equals='jev-1.14.0'),
                    ClauseRegex(regex=re.compile(r'^(typesafe/)?jev-1\.14(-\d{8})?$')),
                    ClauseEquals(equals='jev-preview'),
                    ClauseEquals(equals='jev-latest'),
                ]
            }
        ),
    ]


@pytest.mark.vcr()
def test_typesafe_main_fetches_recorded_models_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('typesafe.yml')

    source_typesafe.main(provider_path)

    assert capsys.readouterr().out == 'TypeSafe prices updated: 0 added, 2 updated\n'
    provider = ProviderYaml(provider_path).provider
    assert [(model.id, model.match, model.prices, model.prices_checked) for model in provider.models] == [
        (
            'jev-1.13.0',
            ClauseOr.model_validate(
                {
                    'or': [
                        ClauseEquals(equals='jev-1.13.0'),
                        ClauseRegex(regex=re.compile(r'^(typesafe/)?jev-1\.13(-\d{8})?$')),
                        ClauseEquals(equals='jev-latest'),
                    ]
                }
            ),
            ModelPrice(input_mtok=Decimal('0.042')),
            date.today(),
        ),
        (
            'jev-1.14.0',
            ClauseOr.model_validate(
                {
                    'or': [
                        ClauseEquals(equals='jev-1.14.0'),
                        ClauseRegex(regex=re.compile(r'^(typesafe/)?jev-1\.14(-\d{8})?$')),
                        ClauseEquals(equals='jev-preview'),
                    ]
                }
            ),
            ModelPrice(input_mtok=Decimal('0.042')),
            date.today(),
        ),
    ]
