import json
from typing import Any

import yaml
from utils import raw_bodies_path, this_dir

bodies: list[Any] = []
for f in (this_dir / '../../../pydantic-ai/tests').rglob('*.yaml'):
    text = f.read_text()
    if len(text) > 3_000_000:
        continue
    parsed = yaml.safe_load(text)
    interactions = parsed.get('interactions', [])
    for interaction in interactions:
        parsed_body = interaction.get('response', {}).get('parsed_body', {})
        if parsed_body:
            bodies.append(parsed_body)

raw_bodies_path.write_text(json.dumps(bodies))
