from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from prices import update
from prices.prices_types import ModelPrice
from prices.update import UnreadableRowError, report_manual_update, skipping_unreadable_row


def test_report_manual_update_appends_each_note_to_the_notes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = tmp_path / 'importer.notes'
    monkeypatch.setenv(update.MANUAL_UPDATE_NOTES_ENV, str(notes))

    report_manual_update('Source: kept a unchanged; update it by hand')
    report_manual_update('Source: kept b unchanged; update it by hand')

    expected = 'Source: kept a unchanged; update it by hand\nSource: kept b unchanged; update it by hand\n'
    assert notes.read_text() == expected
    assert capsys.readouterr().out == expected


def test_report_manual_update_only_prints_outside_the_price_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(update.MANUAL_UPDATE_NOTES_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    report_manual_update('Source: kept a unchanged; update it by hand')

    assert capsys.readouterr().out == 'Source: kept a unchanged; update it by hand\n'
    assert list(tmp_path.iterdir()) == []


def test_skipping_unreadable_row_reports_the_row_and_reads_the_rest(capsys: pytest.CaptureFixture[str]) -> None:
    read: list[str] = []
    for row in ['a', 'b', 'c']:
        with skipping_unreadable_row('Source'):
            if row == 'b':
                raise UnreadableRowError(f'unexpected row {row!r}')
            read.append(row)

    assert read == ['a', 'c']
    assert capsys.readouterr().out == "Source: skipped a row it cannot read; update it by hand. unexpected row 'b'\n"


def test_report_manual_update_writes_a_multiline_note_on_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = tmp_path / 'importer.notes'
    monkeypatch.setenv(update.MANUAL_UPDATE_NOTES_ENV, str(notes))

    report_manual_update(
        'Source: skipped a row it cannot read; update it by hand. Unexpected row: <tr>\n  <td>x</td>\n</tr>\n'
    )

    expected = 'Source: skipped a row it cannot read; update it by hand. Unexpected row: <tr> <td>x</td> </tr>\n'
    assert notes.read_text() == expected
    assert capsys.readouterr().out == expected


def test_skipping_unreadable_row_skips_a_row_whose_values_do_not_parse(capsys: pytest.CaptureFixture[str]) -> None:
    with skipping_unreadable_row('Source'):
        Decimal('TBD')
    with skipping_unreadable_row('Source'):
        ModelPrice.model_validate({'input_mtok': 'TBD'})

    first, second = capsys.readouterr().out.splitlines()
    assert first.startswith('Source: skipped a row it cannot read; update it by hand. ')
    assert second.startswith('Source: skipped a row it cannot read; update it by hand. ')
    assert 'validation error' in second


def test_skipping_unreadable_row_holds_the_models_of_a_skipped_row(capsys: pytest.CaptureFixture[str]) -> None:
    unreadable: set[str] = set()
    for model_id, price in [('model-a', '$1'), ('model-b', 'TBD'), ('model-a', 'TBD')]:
        with skipping_unreadable_row('Source', unreadable) as row:
            row.model_ids.add(model_id)
            if not price.startswith('$'):
                raise UnreadableRowError(f'unexpected price {price!r}')

    assert unreadable == {'model-a', 'model-b'}
    assert capsys.readouterr().out == (
        "Source: skipped a row it cannot read for model-b; update it by hand. unexpected price 'TBD'\n"
        "Source: skipped a row it cannot read for model-a; update it by hand. unexpected price 'TBD'\n"
    )


def test_skipping_unreadable_row_lets_page_level_errors_fail_the_importer() -> None:
    with pytest.raises(RuntimeError, match='no pricing table'), skipping_unreadable_row('Source'):
        raise RuntimeError('Source pricing page has no pricing table')


def printed_note_lines(source: str) -> list[int]:
    """Lines that `print` a note asking a person to update something by hand."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'print'
        and any(
            isinstance(part, ast.Constant) and isinstance(part.value, str) and 'by hand' in part.value
            for arg in node.args
            for part in ast.walk(arg)
        )
    ]


def test_importer_notes_go_through_report_manual_update() -> None:
    # The price update collects notes from `report_manual_update` only, so a printed note never reaches anyone.
    printed_notes = [
        f'{path.name}:{line}'
        for path in sorted(Path(update.__file__).parent.glob('*.py'))
        for line in printed_note_lines(path.read_text())
    ]
    assert not printed_notes, f'Report these with report_manual_update instead of print: {", ".join(printed_notes)}'


def test_printed_note_lines_finds_a_printed_manual_update_note() -> None:
    source = "print('Source: done')\nprint(f'Source: kept {model} unchanged; update it by hand')\n"

    assert printed_note_lines(source) == [2]
