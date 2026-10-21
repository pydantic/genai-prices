import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices import proposed_start_dates
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, StartDateConstraint
from prices.proposed_start_dates import keep_proposed_start_dates
from prices.update import ProviderYaml

MAIN = """\
id: acme
name: Acme
api_pattern: acme
models:
  - id: batched
    match:
      equals: batched
    prices_checked: 2026-10-01
    prices:
      input_mtok: 2
    price_variants:
      - when: { processing: batch }
        prices:
          input_mtok: 1

  - id: flat
    match:
      equals: flat
    prices_checked: 2026-10-01
    prices:
      input_mtok: 1
"""
FIRST_SEEN = date(2026, 10, 18)
NEXT_DAY = date(2026, 10, 19)


def hourly_import(path: Path, day: date, rates: dict[str, str]) -> str:
    """Rerun an importer against unchanged main, as the hourly import job does, and return the file it writes."""
    path.write_text(MAIN)
    models = [
        ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=ModelPrice(input_mtok=Decimal(rate)),
            prices_checked=day,
        )
        for model_id, rate in rates.items()
    ]
    ProviderYaml(path).upsert_models(models, source='Acme', min_count=1)
    return path.read_text()


def test_a_rate_change_keeps_the_date_it_was_first_proposed(tmp_path: Path) -> None:
    path = tmp_path / 'acme.yml'
    proposal = hourly_import(path, FIRST_SEEN, {'batched': '1', 'flat': '0.5'})
    rerun = hourly_import(path, NEXT_DAY, {'batched': '1', 'flat': '0.5'})
    assert 'start_date: 2026-10-19' in rerun

    assert keep_proposed_start_dates(path, MAIN, proposal) == 3

    assert path.read_text() == proposal.replace('prices_checked: 2026-10-18', 'prices_checked: 2026-10-19')
    batched = ProviderYaml(path).provider.models[0]
    assert isinstance(batched.prices, list)
    assert batched.prices[-1].constraint == StartDateConstraint(start_date=FIRST_SEEN)
    assert batched.price_variants is not None
    assert batched.price_variants[0].constraint == StartDateConstraint(start_date=FIRST_SEEN)
    assert batched.prices_checked == NEXT_DAY


def test_a_rate_that_changed_again_is_dated_to_the_run_that_saw_it(tmp_path: Path) -> None:
    path = tmp_path / 'acme.yml'
    proposal = hourly_import(path, FIRST_SEEN, {'batched': '1', 'flat': '0.5'})
    hourly_import(path, NEXT_DAY, {'batched': '1', 'flat': '0.4', 'new': '3'})

    assert keep_proposed_start_dates(path, MAIN, proposal) == 2

    batched, flat = ProviderYaml(path).provider.models[:2]
    assert isinstance(batched.prices, list) and isinstance(flat.prices, list)
    assert batched.prices[-1].constraint == StartDateConstraint(start_date=FIRST_SEEN)
    assert flat.prices[-1].constraint == StartDateConstraint(start_date=NEXT_DAY)


def test_nothing_changes_without_an_earlier_proposal_of_the_same_change(tmp_path: Path) -> None:
    path = tmp_path / 'acme.yml'
    proposal = hourly_import(path, FIRST_SEEN, {'flat': '0.5'})
    hourly_import(path, NEXT_DAY, {'batched': '1', 'flat': '0.5'})
    assert keep_proposed_start_dates(path, MAIN, MAIN) == 0
    assert keep_proposed_start_dates(path, MAIN, proposal.replace('2026-10-18', '2026-10-20')) == 0

    # The proposal makes the flat change but not the batched one.
    assert keep_proposed_start_dates(path, MAIN, proposal) == 1

    batched, flat = ProviderYaml(path).provider.models
    assert isinstance(batched.prices, list) and isinstance(flat.prices, list)
    assert batched.prices[-1].constraint == StartDateConstraint(start_date=NEXT_DAY)
    assert flat.prices[-1].constraint == StartDateConstraint(start_date=FIRST_SEEN)


def test_a_dated_entry_already_on_main_keeps_its_date(tmp_path: Path) -> None:
    path = tmp_path / 'acme.yml'
    proposal = hourly_import(path, FIRST_SEEN, {'flat': '0.5'})
    corrected_on_main = proposal.replace('start_date: 2026-10-18', 'start_date: 2026-10-19')
    path.write_text(corrected_on_main)

    assert keep_proposed_start_dates(path, corrected_on_main, proposal) == 0
    assert path.read_text() == corrected_on_main


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args],
        check=True,
        capture_output=True,
    )


def test_cli_reads_main_and_the_proposal_from_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    providers = tmp_path / 'prices/providers'
    providers.mkdir(parents=True)
    acme = providers / 'acme.yml'
    unchanged = providers / 'unchanged.yml'
    git(tmp_path, 'init', '--quiet')
    proposal = hourly_import(acme, FIRST_SEEN, {'flat': '0.5'})
    unchanged.write_text(MAIN)
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '--quiet', '--no-gpg-sign', '-m', 'proposal')
    git(tmp_path, 'branch', 'proposal')
    acme.write_text(MAIN)
    git(tmp_path, 'commit', '--quiet', '--no-gpg-sign', '-am', 'main')
    hourly_import(acme, NEXT_DAY, {'flat': '0.5'})
    (providers / 'new.yml').write_text(MAIN)
    monkeypatch.setattr(proposed_start_dates, 'root_dir', tmp_path)
    monkeypatch.setattr(proposed_start_dates, 'package_dir', tmp_path / 'prices')
    monkeypatch.setattr(sys, 'argv', ['proposed_start_dates', 'proposal'])

    proposed_start_dates.main()

    assert capsys.readouterr().out == 'acme.yml: kept 1 start dates from the open price update\n'
    assert acme.read_text() == proposal.replace('prices_checked: 2026-10-18', 'prices_checked: 2026-10-19')

    hourly_import(acme, NEXT_DAY, {'flat': '0.4'})
    proposed_start_dates.main()
    assert capsys.readouterr().out == ''
