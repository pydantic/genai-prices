from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

from .utils import root_dir

V2_ARTIFACT_SHA256: Final[Mapping[str, str]] = {
    'prices/new_data/v2/data.json': '06f100aaacf6ebaa76a536587fa5356e4ef21a0ba088dca2d5f5d78f15a9e88e',
    'prices/new_data/v2/data.schema.json': '74cd799c1fa1f06f0e8a043196569ecd28f90acb775b31cc44b84add77a953c7',
    'prices/new_data/v2/data_slim.json': '59a2baa1a14a1c63bceec347c8cf7647f1df5c06a5809e24e0623246f3322de5',
    'prices/new_data/v2/data_slim.schema.json': 'aa36a263543092a2eb76cd07342fe32bd6b8143112f37d1d33d7be6dce63d89d',
}


def validate_frozen_v2_artifacts() -> None:
    """Verify that every v2 cutover artifact retains its exact published bytes."""
    for relative_path, expected_digest in V2_ARTIFACT_SHA256.items():
        path = root_dir / relative_path
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(f'Missing frozen v2 artifact: {relative_path}') from exc

        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(
                f'Frozen v2 artifact changed: {relative_path} (expected {expected_digest}, got {actual_digest})'
            )
