from pathlib import Path
from typing import Any, cast

import ruamel.yaml


def load_units() -> dict[str, Any]:
    yaml = ruamel.yaml.YAML(typ='safe')
    with (Path(__file__).parent.parent / 'prices/units.yml').open() as f:
        return cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]
