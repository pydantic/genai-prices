from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

from .utils import root_dir

V2_ARTIFACT_SHA256: Final[Mapping[str, str]] = {
    'prices/new_data/v2/data.json': 'a774b91f8b60e3c93f6001470451eab04d6c23dbaa145f517b9e0857d56c4bbd',
    'prices/new_data/v2/data.schema.json': '74cd799c1fa1f06f0e8a043196569ecd28f90acb775b31cc44b84add77a953c7',
    'prices/new_data/v2/data_slim.json': '15d0b12f2bb3a6a949d2ac7902d5bcc8bbc8db40b964283f4243e1c1e68c8baf',
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
