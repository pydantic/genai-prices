import json
from typing import Any

import yaml
from utils import raw_bodies_path, this_dir

bodies: list[Any] = []
pydantic_ai_tests = this_dir / '../../../pydantic-ai/tests'
for f in pydantic_ai_tests.rglob('*.yaml'):
    text = f.read_text()
    if len(text) > 3_000_000:
        continue
    parsed = yaml.safe_load(text)
    interactions = parsed.get('interactions', [])
    for interaction in interactions:
        parsed_body = interaction.get('response', {}).get('parsed_body', {})
        if parsed_body and isinstance(parsed_body, dict):
            assert 'file' not in parsed_body
            parsed_body['file'] = str(f.relative_to(pydantic_ai_tests))
            bodies.append(parsed_body)

raw_bodies_path.write_text(json.dumps(bodies))
