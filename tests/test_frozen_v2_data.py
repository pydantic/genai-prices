import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from prices import frozen_v2
from prices.utils import package_dir as prices_package_dir


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


def test_frozen_slim_v2_payload_is_the_documented_full_projection() -> None:
    full = cast(list[dict[str, Any]], json.loads((prices_package_dir / 'new_data/v2/data.json').read_bytes()))
    slim = cast(list[dict[str, Any]], json.loads((prices_package_dir / 'new_data/v2/data_slim.json').read_bytes()))
    expected = copy.deepcopy(full)

    for provider in expected:
        provider['models'] = [model for model in provider['models'] if not _model_is_free(model)]
        for key in ('pricing_urls', 'description', 'price_comments'):
            provider.pop(key, None)
        for model in provider['models']:
            for key in ('name', 'description', 'price_comments'):
                model.pop(key, None)

    assert slim == expected


def _model_is_free(model: dict[str, Any]) -> bool:
    prices = model['prices']
    if isinstance(prices, list):
        conditional_prices = cast(list[dict[str, object]], prices)
        return all(not conditional_price['prices'] for conditional_price in conditional_prices)
    return not prices
