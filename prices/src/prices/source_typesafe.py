from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from prices.prices_types import ClauseEquals, ClauseOr, MatchLogic, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

MODELS_URL = 'https://docs.typesafe.ai/models.md'
MIN_MODEL_COUNT = 1


def parse_models_markdown(markdown: str) -> list[ModelInfo]:
    current = {row[0]: row[1:] for row in _table(markdown, 'Current models')}
    aliases = {row[0].strip('`'): row[1].strip('`') for row in _table(markdown, 'Aliases')}
    if 'Model ID' not in current or 'Price (per Btok / per Mtok)' not in current:
        raise RuntimeError('TypeSafe current models table is missing the Model ID or Price row')
    model_ids = [cell.strip('`') for cell in current['Model ID']]
    unknown = set(aliases.values()) - set(model_ids)
    if unknown:
        raise RuntimeError(f'TypeSafe aliases point at models missing from the current models table: {unknown}')
    contexts = current.get('Context length', [''] * len(model_ids))
    models: list[ModelInfo] = []
    for model_id, price, context in zip(model_ids, current['Price (per Btok / per Mtok)'], contexts, strict=True):
        rate = re.fullmatch(r'\\?\$[0-9.]+ / \\?\$([0-9]+(?:\.[0-9]+)?)', price)
        if not model_id.startswith('jev-') or rate is None:
            raise RuntimeError(f'Unexpected TypeSafe model column: {model_id} {price}')
        clauses: list[MatchLogic] = [ClauseEquals(equals=model_id)]
        clauses += [ClauseEquals(equals=alias) for alias, target in aliases.items() if target == model_id]
        per_question = re.search(r'(\d+)k per-question', context)
        models.append(
            ModelInfo(
                id=model_id,
                name=model_id.replace('jev-', 'Jev '),
                match=ClauseOr.model_validate({'or': clauses}) if len(clauses) > 1 else clauses[0],
                context_window=int(per_question.group(1)) * 1000 if per_question else None,
                prices=ModelPrice(input_mtok=Decimal(rate.group(1))),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_models_markdown(get_markdown(MODELS_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/typesafe.yml')
    targets = {
        clause.equals: model.id
        for model in models
        if isinstance(model.match, ClauseOr)
        for clause in model.match.or_
        if isinstance(clause, ClauseEquals)
    }
    for yaml_model in provider_yaml.data['models']:
        model_id = cast(str, yaml_model['id'])
        clauses = cast(list[dict[str, Any]], cast(dict[str, Any], yaml_model['match']).get('or', []))
        if clauses:
            kept = [c for c in clauses if targets.get(c.get('equals', ''), model_id) == model_id]
            yaml_model['match'] = kept[0] if len(kept) == 1 else {'or': kept}
    added, updated = provider_yaml.upsert_models(models, source='TypeSafe', min_count=MIN_MODEL_COUNT)
    print(f'TypeSafe prices updated: {added} added, {updated} updated')


def get_typesafe_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update TypeSafe prices."""
    main()


def _table(markdown: str, title: str) -> list[list[str]]:
    section = re.search(rf'^## {title}\s*$\n(.*?)(?=^## |\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
    lines = [line for line in section.group(1).splitlines() if line.startswith('|')] if section else []
    if len(lines) < 3:
        raise RuntimeError(f'TypeSafe models page has no "{title}" table')
    return [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in lines[2:]]
