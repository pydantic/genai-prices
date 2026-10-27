from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://docs.z.ai/guides/overview/pricing.md'
MIN_MODEL_COUNT = 10
TOKEN_TABLE_HEADER = ['Model', 'Input', 'Cached Input', 'Cached Input Storage', 'Output']
UNPRICED_CELLS = {'Free', '-', '\\\\'}


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    models: list[ModelInfo] = []
    seen: set[str] = set()
    # Older models are listed in a blockquote under "Other Pricing".
    for header, rows in markdown_tables(re.sub(r'^> ?', '', markdown, flags=re.MULTILINE)):
        if header[:2] != ['Model', 'Input']:
            continue
        if header != TOKEN_TABLE_HEADER:
            raise RuntimeError(f'Unexpected Z.ai token pricing columns: {header}')
        for name, input_cell, cache_read_cell, _storage, output_cell in rows:
            if name in seen:
                raise RuntimeError(f'Duplicate Z.ai model in pricing data: {name}')
            seen.add(name)
            prices = ModelPrice(
                input_mtok=_price(input_cell), cache_read_mtok=_price(cache_read_cell), output_mtok=_price(output_cell)
            )
            if prices.input_mtok is None and prices.output_mtok is None:
                continue
            models.append(
                ModelInfo(
                    id=name,
                    name=name,
                    match=ClauseOr.model_validate(
                        {'or': [ClauseEquals(equals=name), ClauseEquals(equals=name.lower())]}
                    ),
                    prices=prices,
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/zai.yml')
    added, updated = provider_yaml.upsert_models(models, source='Z.ai', min_count=MIN_MODEL_COUNT)
    print(f'Z.ai prices updated: {added} added, {updated} updated')


def get_zai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Z.ai prices."""
    main()


def _price(cell: str) -> Decimal | None:
    if cell in UNPRICED_CELLS:
        return None
    if not re.fullmatch(r'\\\$[0-9]+(?:\.[0-9]+)?', cell):
        raise RuntimeError(f'Unexpected Z.ai price cell: {cell}')
    return Decimal(cell[2:])
