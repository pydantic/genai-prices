from __future__ import annotations

import ast
import re
from pathlib import Path

LIVE_PROVIDER_DATA = re.compile(r'\bpackage_dir\b|prices/providers')


def reads_live_provider_data(source: str) -> bool:
    if LIVE_PROVIDER_DATA.search(source):
        return True
    # An importer entry point called without a path, such as `source_groq.main()`, defaults to the live file.
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id.startswith('source_')
        and not node.args
        and not node.keywords
        for node in ast.walk(ast.parse(source))
    )


def test_importer_tests_never_read_live_provider_yaml() -> None:
    # The hourly price update rewrites `prices/providers/*.yml` before it runs these tests, so a test that
    # reads them breaks as soon as its provider adds a model or changes a rate.
    offenders = [
        path.name
        for path in sorted(Path(__file__).parent.glob('test_source_*.py'))
        if reads_live_provider_data(path.read_text())
    ]
    assert not offenders, (
        f'{", ".join(offenders)} read live provider data. Start each importer test from '
        "`provider_snapshot('<provider>.yml')`, adding the snapshot to tests/fixtures/providers/ if it is missing, "
        'and pass its path to the importer.'
    )


def test_a_path_less_importer_call_reads_live_provider_data() -> None:
    assert reads_live_provider_data("copyfile(package_dir / 'providers/groq.yml', path)")
    assert reads_live_provider_data('source_groq.main()')
    assert not reads_live_provider_data("source_groq.main(provider_snapshot('groq.yml'))")
    assert not reads_live_provider_data('source_groq.parse_models_markdown(MARKDOWN)')
