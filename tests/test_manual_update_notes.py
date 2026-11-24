from __future__ import annotations

import ast
from pathlib import Path

import pytest

from prices import update
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


def test_skipping_unreadable_row_lets_page_level_errors_fail_the_importer() -> None:
    with pytest.raises(RuntimeError, match='no pricing table'), skipping_unreadable_row('Source'):
        raise RuntimeError('Source pricing page has no pricing table')


def test_importer_notes_go_through_report_manual_update() -> None:
    # The price update collects notes from `report_manual_update` only, so a printed note never reaches anyone.
    printed_notes: list[str] = []
    for path in sorted(Path(update.__file__).parent.glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                text = ''.join(
                    part.value
                    for arg in node.args
                    for part in ast.walk(arg)
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
                if 'by hand' in text:
                    printed_notes.append(f'{path.name}:{node.lineno}')
    assert not printed_notes, f'Report these with report_manual_update instead of print: {", ".join(printed_notes)}'
