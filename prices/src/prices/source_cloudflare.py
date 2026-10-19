from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_URL = 'https://developers.cloudflare.com/workers-ai/platform/pricing/index.md'
MIN_MODEL_COUNT = 40


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    sections = re.findall(
        r'^## (?:LLM|Embeddings|Other) model pricing\s*$\n(.*?)(?=^## |\Z)', markdown, flags=re.MULTILINE | re.DOTALL
    )
    models: list[ModelInfo] = []
    model_ids: set[str] = set()
    for section in sections:
        for line in section.splitlines():
            if not line.startswith('| @cf/'):
                continue
            cells = line.split('|')
            model_id = cells[1].strip()
            rates = {
                unit: Decimal(value)
                for value, unit in re.findall(
                    r'\$([0-9]+(?:\.[0-9]+)?) per M (cached input|input|output) tokens', cells[2]
                )
            }
            if not rates:
                continue
            if model_id in model_ids:
                raise RuntimeError(f'Duplicate Cloudflare model in pricing data: {model_id}')
            model_ids.add(model_id)
            models.append(
                ModelInfo(
                    id=model_id,
                    name=model_id.rsplit('/', 1)[-1],
                    match=ClauseEquals(equals=model_id),
                    prices=ModelPrice(
                        input_mtok=rates.get('input'),
                        cache_read_mtok=rates.get('cached input'),
                        output_mtok=rates.get('output'),
                    ),
                    prices_checked=date.today(),
                )
            )
    return models


def update_cloudflare_provider(provider_yaml: ProviderYaml, models: list[ModelInfo]) -> tuple[int, int]:
    if len(models) < MIN_MODEL_COUNT:
        raise RuntimeError(
            f'Cloudflare pricing returned only {len(models)} token-priced models; expected at least {MIN_MODEL_COUNT}'
        )

    models_added = 0
    models_updated = 0
    for model in models:
        matching_model = provider_yaml.provider.find_model(model.id)
        if matching_model is None:
            models_added += provider_yaml.add_model(model)
        else:
            provider_yaml.update_model(matching_model.id, model, set_prices=True)
            models_updated += 1
    provider_yaml.save()
    return models_added, models_updated


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_pricing_markdown(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/cloudflare.yml')
    models_added, models_updated = update_cloudflare_provider(provider_yaml, models)
    print(f'Cloudflare prices updated: {models_added} added, {models_updated} updated')


def get_cloudflare_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Cloudflare Workers AI prices."""
    main()


if __name__ == '__main__':
    main()
