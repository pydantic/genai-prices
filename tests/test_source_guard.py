from __future__ import annotations

from pathlib import Path

import pytest

from prices.source_guard import (
    OVERRIDE_ENV_VAR,
    ImplausibleImportError,
    check_no_sharp_drop,
    check_non_empty,
)


def test_check_non_empty_accepts_a_real_import() -> None:
    check_non_empty('somewhere', 42)


def test_check_non_empty_rejects_an_empty_import() -> None:
    with pytest.raises(ImplausibleImportError, match='somewhere: upstream returned no usable models'):
        check_non_empty('somewhere', 0)


def test_check_no_sharp_drop_accepts_growth_and_small_losses() -> None:
    check_no_sharp_drop('somewhere', 'a_provider', 120, 100)
    check_no_sharp_drop('somewhere', 'a_provider', 100, 100)
    check_no_sharp_drop('somewhere', 'a_provider', 60, 100)


def test_check_no_sharp_drop_rejects_losing_most_of_the_catalogue() -> None:
    with pytest.raises(ImplausibleImportError, match='returned 10 models but 100 are already recorded'):
        check_no_sharp_drop('somewhere', 'a_provider', 10, 100)


def test_check_no_sharp_drop_accepts_a_brand_new_provider() -> None:
    """Nothing recorded yet means there is nothing to lose, so any non-empty response is plausible."""
    check_no_sharp_drop('somewhere', 'a_provider', 3, 0)


def test_check_no_sharp_drop_still_rejects_an_empty_new_provider() -> None:
    with pytest.raises(ImplausibleImportError, match='no usable models'):
        check_no_sharp_drop('somewhere', 'a_provider', 0, 0)


def test_override_downgrades_the_error_to_a_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(OVERRIDE_ENV_VAR, '1')

    check_no_sharp_drop('somewhere', 'a_provider', 1, 100)

    assert f'allowed by {OVERRIDE_ENV_VAR}' in capsys.readouterr().out


def test_override_only_applies_when_set_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OVERRIDE_ENV_VAR, 'yes')

    with pytest.raises(ImplausibleImportError):
        check_non_empty('somewhere', 0)


def test_write_source_prices_refuses_an_empty_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The chokepoint guard: one check covering every importer that writes a JSON source file."""
    from prices import source_prices

    monkeypatch.setattr(source_prices, 'source_prices_dir', tmp_path)

    with pytest.raises(ImplausibleImportError, match='no usable models'):
        source_prices.write_source_prices('somewhere', {})

    with pytest.raises(ImplausibleImportError, match='no usable models'):
        source_prices.write_source_prices('somewhere', {'a_provider': {}})
