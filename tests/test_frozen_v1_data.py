import hashlib

import pytest

from prices.utils import package_dir as prices_package_dir

# The v1 payloads and schemas are a frozen compatibility surface for pre-0.1.0 clients.
# No build step writes them, so the pre-commit `build` hook — which is what catches drift
# in every other generated artifact — cannot see an edit here. They are also marked
# `linguist-generated`, so GitHub collapses their diffs and a reviewer is unlikely to look.
# These digests are the check that replaces both. Updating one is a deliberate act that
# shows up in this file's diff; new contracts belong in a new `prices/new_data/v<version>/`
# directory instead.
FROZEN_V1_DIGESTS = {
    'data.json': 'f41075aab069a7dc378f83b7586523f72682a6c9860b23a89ad0b57c073aec41',
    'data_slim.json': 'cca400c914ecd66dbb3c3f9e26fb66e5528a2986aeceed14b831361722cd4740',
    'data.schema.json': '663171ade82700f8a07075f47a3548eeda4c732fa686f2e344a4a2045d25dd59',
    'data_slim.schema.json': 'bf89de05d1b7fd9d977d6c9d7d1ffdeaca0a69fe14b6d355c31bb097bd530ce6',
}


@pytest.mark.parametrize(('filename', 'expected_digest'), sorted(FROZEN_V1_DIGESTS.items()))
def test_frozen_v1_artifact_unchanged(filename: str, expected_digest: str) -> None:
    path = prices_package_dir / filename

    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_digest, (
        f'{filename} is a frozen v1 compatibility snapshot and must not change. '
        'Publish new data under prices/new_data/ instead. If this edit really is '
        'intentional, update the digest in FROZEN_V1_DIGESTS in the same commit.'
    )
