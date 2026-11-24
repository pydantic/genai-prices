from __future__ import annotations

import re
from pathlib import Path

LIVE_PROVIDER_DATA = re.compile(r'\bpackage_dir\b|prices/providers')


def test_importer_tests_never_read_live_provider_yaml() -> None:
    # The hourly price update rewrites `prices/providers/*.yml` before it runs these tests, so a test that
    # reads them breaks as soon as its provider adds a model or changes a rate.
    offenders = [
        path.name
        for path in sorted(Path(__file__).parent.glob('test_source_*.py'))
        if LIVE_PROVIDER_DATA.search(path.read_text())
    ]
    assert not offenders, (
        f'{", ".join(offenders)} read live provider data. Start each importer test from '
        "`provider_snapshot('<provider>.yml')`, adding the snapshot to tests/fixtures/providers/ if it is missing."
    )
