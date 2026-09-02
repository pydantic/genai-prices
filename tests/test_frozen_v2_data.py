import hashlib
from pathlib import Path

import pytest

from prices import frozen_v2


def test_frozen_v2_artifacts_unchanged() -> None:
    frozen_v2.validate_frozen_v2_artifacts()


def test_frozen_v2_verifier_rejects_changed_and_missing_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    relative_path = 'prices/new_data/v2/artifact.json'
    expected_data = b'published bytes'
    monkeypatch.setattr(frozen_v2, 'root_dir', tmp_path)
    monkeypatch.setattr(
        frozen_v2,
        'V2_ARTIFACT_SHA256',
        {relative_path: hashlib.sha256(expected_data).hexdigest()},
    )

    with pytest.raises(ValueError, match=f'Missing frozen v2 artifact: {relative_path}'):
        frozen_v2.validate_frozen_v2_artifacts()

    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match=f'Frozen v2 artifact changed: {relative_path}'):
        frozen_v2.validate_frozen_v2_artifacts()
