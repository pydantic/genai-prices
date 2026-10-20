from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/price_update_branch.sh'
MESSAGE = 'Update provider prices from official sources'


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(path), *args], text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / 'remote.git'
    path = tmp_path / 'checkout'
    git(tmp_path, 'init', '--bare', str(remote))
    git(tmp_path, 'init', '-b', 'main', str(path))
    git(path, 'config', 'user.name', 'genai-prices-automation[bot]')
    git(path, 'config', 'user.email', 'genai-prices-automation[bot]@users.noreply.github.com')
    (path / 'prices.txt').write_text('original\n')
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'Main')
    return path, remote


def candidate(path: Path, content: str) -> str:
    git(path, 'switch', 'main')
    (path / 'prices.txt').write_text(content)
    git(path, 'add', '.')
    git(path, 'commit', '-m', MESSAGE)
    return git(path, 'rev-parse', 'HEAD')


def publish(path: Path, remote: Path, previous: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['bash', str(SCRIPT), 'publish', str(remote), 'automation/hourly-price-update', previous],
        cwd=path,
        text=True,
        capture_output=True,
    )


def test_publication_appends_without_force_and_reuses_identical_trees(repository: tuple[Path, Path]) -> None:
    path, remote = repository
    first = candidate(path, 'first rate\n')
    result = publish(path, remote)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == first
    assert git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == first

    git(path, 'switch', '--detach', 'HEAD~1')
    git(path, 'branch', '-f', 'main', 'HEAD')
    git(path, 'switch', 'main')
    (path / 'main.txt').write_text('New main changes\n')
    git(path, 'add', '.')
    git(path, 'commit', '--author', 'Maintainer <maintainer@example.com>', '-m', 'Advance main')
    second = candidate(path, 'second rate\n')
    result = publish(path, remote, first)
    assert result.returncode == 0, result.stderr
    published = result.stdout.strip()
    assert git(path, 'rev-parse', f'{published}^1') == first
    assert git(path, 'rev-parse', f'{published}^2') == second
    assert git(remote, 'show', f'{published}:prices.txt') == 'second rate'
    assert git(remote, 'show', f'{published}:main.txt') == 'New main changes'

    result = publish(path, remote, published)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == published
    assert git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == published


def test_repairs_block_rebuilding_even_when_generated_tree_is_unchanged(repository: tuple[Path, Path]) -> None:
    path, remote = repository
    original = candidate(path, 'new rate\n')
    assert publish(path, remote).returncode == 0
    git(path, 'switch', '--detach', original)
    (path / 'review-fix.txt').write_text('Keep this repair\n')
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'Fix a review finding')
    repair = git(path, 'rev-parse', 'HEAD')
    git(path, 'push', str(remote), f'{repair}:refs/heads/automation/hourly-price-update')
    git(path, 'switch', 'main')

    check = subprocess.run(['bash', str(SCRIPT), 'check', 'HEAD', repair], cwd=path, text=True, capture_output=True)
    assert check.returncode == 1
    assert 'contains repairs' in check.stderr
    result = publish(path, remote, repair)
    assert result.returncode == 1
    assert 'contains repairs' in result.stderr
    assert git(remote, 'show', f'{repair}:review-fix.txt') == 'Keep this repair'
    assert git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == repair


def test_concurrent_push_cannot_be_overwritten(repository: tuple[Path, Path]) -> None:
    path, remote = repository
    first = candidate(path, 'first rate\n')
    assert publish(path, remote).returncode == 0
    candidate(path, 'concurrent rate\n')
    concurrent = publish(path, remote, first).stdout.strip()
    candidate(path, 'stale run\n')
    result = publish(path, remote, first)
    assert result.returncode != 0
    assert git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == concurrent


def test_publication_does_not_replace_an_untracked_remote_branch(repository: tuple[Path, Path]) -> None:
    path, remote = repository
    first = candidate(path, 'first rate\n')
    assert publish(path, remote).returncode == 0
    git(path, 'switch', '--detach', 'HEAD~1')
    git(path, 'branch', '-f', 'main', 'HEAD')
    candidate(path, 'unrelated proposal\n')
    result = publish(path, remote)
    assert result.returncode != 0
    assert git(remote, 'rev-parse', 'refs/heads/automation/hourly-price-update') == first
