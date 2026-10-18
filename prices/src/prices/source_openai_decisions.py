from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

MODEL_URL = 'https://developers.openai.com/api/docs/models/{model_id}.md'
MIN_MODEL_COUNT = 1


def parse_model_markdown(model_id: str, markdown: str) -> ModelInfo:
    """Decisions bill input only, at the model's standard input rate and long-context multiplier."""
    rate = re.search(r'^\| Input \| \$([0-9]+(?:\.[0-9]+)?) \| 1M tokens \|$', markdown, flags=re.MULTILINE)
    tier = re.search(r'more than ([0-9]+)K input tokens are priced at ([0-9]+(?:\.[0-9]+)?)x input', markdown)
    if rate is None or tier is None:
        raise RuntimeError(f'OpenAI {model_id} page has no input rate or long-context pricing in the expected shape')
    base = Decimal(rate.group(1))
    return ModelInfo(
        id=model_id,
        match=ClauseEquals(equals=model_id),
        prices=ModelPrice(
            input_mtok=TieredPrices(
                base=base, tiers=[Tier(start=int(tier.group(1)) * 1000, price=base * Decimal(tier.group(2)))]
            )
        ),
        prices_checked=date.today(),
    )


def main(provider_path: Path | None = None) -> None:
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/openai_decisions.yml')
    models = [
        parse_model_markdown(model.id, get_markdown(MODEL_URL.format(model_id=model.id)))
        for model in provider_yaml.provider.models
    ]
    added, updated = provider_yaml.upsert_models(models, source='OpenAI Decisions', min_count=MIN_MODEL_COUNT)
    print(f'OpenAI Decisions prices updated: {added} added, {updated} updated')


def get_openai_decisions_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update OpenAI Decisions prices."""
    main()
