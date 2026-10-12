from __future__ import annotations

import argparse
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any


def is_v2_schema_compatible(baseline: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Allow optional price variants while preserving every existing schema member."""
    normalized = deepcopy(candidate)
    baseline_properties = baseline['$defs']['ModelInfo']['properties']
    model = normalized['$defs']['ModelInfo']
    if 'price_variants' not in baseline_properties and 'price_variants' in model['properties']:
        if 'price_variants' in model.get('required', []):
            return False
        del model['properties']['price_variants']
        normalized['$defs'].pop('PriceVariant', None)
    return normalized == baseline


def main() -> None:
    parser = argparse.ArgumentParser(description='Check the published v2 schema against its legacy contract')
    parser.add_argument('--base', required=True)
    parser.add_argument('schemas', nargs='+')
    args = parser.parse_args()
    for schema in args.schemas:
        baseline = json.loads(subprocess.check_output(['git', 'show', f'{args.base}:{schema}']))
        candidate = json.loads(Path(schema).read_text())
        if not is_v2_schema_compatible(baseline, candidate):
            parser.error(f'{schema}: the existing v2 schema changed; unit and contract changes require v3')


if __name__ == '__main__':
    main()
