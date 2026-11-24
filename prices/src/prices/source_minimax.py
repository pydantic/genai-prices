from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml, UnreadableRowError, report_manual_update, skipping_unreadable_row
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://platform.minimax.io/docs/pricing/overview.md'
MODELS_URL = 'https://platform.minimax.io/docs/guides/text-generation.md'
MIN_MODEL_COUNT = 2
PRICE_COLUMNS = {
    'Input': 'input_mtok',
    'Output': 'output_mtok',
    'Prompt caching Read': 'cache_read_mtok',
    'Prompt caching Write': 'cache_write_mtok',
}

Rates = dict[str, Decimal]
# HTML tags and Markdown links, keeping a link's label.
MARKUP = re.compile(r'<[^>]+>|\[([^]]+)]\([^)]*\)')


def parse_pricing_markdown(markdown: str, unreadable: set[str] | None = None) -> list[ModelInfo]:
    """The Standard tier's models. A model with a row this cannot read is left out and added to `unreadable`."""
    unreadable = set[str]() if unreadable is None else unreadable
    section = re.search(r'^## LLM\s*$(.*?)(?=^## |\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
    if section is None:
        raise RuntimeError('MiniMax pricing page has no LLM section')
    standard = re.sub(
        r'^> \[tab\] Priority(?:\\\*)?$(?:\n>(?! \[tab\] )[^\n]*)*', '', section.group(1), flags=re.MULTILINE
    )
    if set(re.findall(r'^> \[tab\] ([^\n]+)', standard, flags=re.MULTILINE)) - {'Standard'}:
        raise RuntimeError('MiniMax LLM pricing has a tier other than Standard and Priority')

    flat: dict[str, Rates] = {}
    tiered: dict[str, list[tuple[str, int, Rates]]] = {}
    duplicates: set[str] = set()
    for header, rows in markdown_tables(standard):
        header = [re.sub(r'\*\*|\\\$ / M tokens', '', cell).strip() for cell in header]
        if (
            header[0] != 'Model'
            or len(set(header)) != len(header)
            or not {'Input', 'Output'} <= set(header[1:]) <= PRICE_COLUMNS.keys()
        ):
            raise RuntimeError(f'Unexpected MiniMax LLM pricing columns: {header}')
        for row in rows:
            with skipping_unreadable_row('MiniMax', unreadable) as source_row:
                if not (model := re.fullmatch(r'\*\*([A-Za-z0-9.-]+)\*\*(.*)', row[0])):
                    raise UnreadableRowError(f'Unexpected MiniMax model cell: {row[0]}')
                name, label = model.groups()
                source_row.model_ids.add(name)
                rates = {PRICE_COLUMNS[column]: _price(cell) for column, cell in zip(header[1:], row[1:])}
                if band := re.match(r' ([≤>]) ([0-9]+)k input tokens', label):
                    tiered.setdefault(name, []).append((band.group(1), int(band.group(2)) * 1000, rates))
                elif re.sub(r'Permanent [0-9]+% off', '', label).strip():
                    raise UnreadableRowError(f'Unexpected MiniMax pricing row: {row[0]}')
                elif name in flat:
                    duplicates.add(name)
                else:
                    flat[name] = rates

    # A model with both a flat row and context bands is listed more than once.
    duplicates |= flat.keys() & tiered.keys()
    for name in sorted(duplicates):
        report_manual_update(
            f'MiniMax: kept {name} unchanged, the pricing page lists it more than once; update it by hand'
        )
    # A model with an unreadable row keeps its prices, rather than taking them from its other rows alone.
    unchanged = duplicates | unreadable
    models = [_model(name, ModelPrice(**rates)) for name, rates in flat.items() if name not in unchanged]
    for name, bands in tiered.items():
        if name in unchanged:
            continue
        with skipping_unreadable_row('MiniMax'):
            if [(sign, start) for sign, start, _ in bands] != [('≤', bands[0][1]), ('>', bands[0][1])]:
                raise UnreadableRowError(f'Unexpected MiniMax context bands for {name}')
            (_, start, base), (_, _, above) = bands
            if base.keys() != above.keys():
                raise UnreadableRowError(f'MiniMax context bands for {name} price different units')
            prices = {key: TieredPrices(base=base[key], tiers=[Tier(start=start, price=above[key])]) for key in base}
            models.append(_model(name, ModelPrice(**prices)))  # pyright: ignore[reportArgumentType]
    return models


def parse_models_markdown(markdown: str) -> dict[str, tuple[int | None, str]]:
    """Each model's context window and description from the text generation guide's model tables."""
    details: dict[str, tuple[int | None, str]] = {}
    for header, rows in markdown_tables(markdown):
        if header != ['Model Name', 'Context Window', 'Description']:
            continue
        for name, context, description in rows:
            name = MARKUP.sub(r'\1', name).replace('**', '').strip()
            context = context.replace(',', '').replace(' ', '')
            window = int(context[:-1]) * 1000 if context.endswith('K') else int(context) if context.isdigit() else None
            details[name] = (window, MARKUP.sub(r'\1', description).replace('**', '').strip())
    return details


def main(provider_path: Path | None = None) -> None:
    details = parse_models_markdown(get_markdown(MODELS_URL))
    unreadable: set[str] = set()
    models = [
        model.model_copy(update={'context_window': details[model.id][0], 'description': details[model.id][1]})
        if model.id in details
        else model
        for model in parse_pricing_markdown(get_markdown(PRICING_URL), unreadable)
    ]
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/minimax.yml')
    # Several legacy page rows share one YAML model; they must agree or the shared entry would be mispriced.
    shared: dict[str, ModelInfo] = {}
    tracked: dict[str, str] = {}
    conflicting: set[str] = set()
    for index, model in enumerate(models):
        if (existing := provider_yaml.provider.find_model(model.id)) is not None:
            if existing.id in shared and shared[existing.id].prices != model.prices:
                conflicting.add(existing.id)
            shared[existing.id] = model
            tracked[model.id] = existing.id
            # A tracked model keeps its curated match rather than gaining the page's case aliases.
            models[index] = model.model_copy(update={'match': ClauseEquals(equals=model.id)})
    for model_id in sorted(conflicting):
        report_manual_update(
            f'MiniMax: kept {model_id} unchanged, the pricing page lists it at conflicting rates; update it by hand'
        )
    # A shared entry also keeps its prices when one of its page rows is unreadable.
    unreadable_entries = {
        existing.id for name in unreadable if (existing := provider_yaml.provider.find_model(name)) is not None
    }
    models = [model for model in models if tracked.get(model.id) not in conflicting | unreadable_entries]
    added, updated = provider_yaml.upsert_models(models, source='MiniMax', min_count=MIN_MODEL_COUNT)
    print(f'MiniMax prices updated: {added} added, {updated} updated')


def get_minimax_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update MiniMax prices."""
    main()


def _model(name: str, prices: ModelPrice) -> ModelInfo:
    return ModelInfo(
        id=name,
        name=name,
        match=ClauseOr.model_validate({'or': [ClauseEquals(equals=name), ClauseEquals(equals=name.lower())]}),
        prices=prices,
        prices_checked=date.today(),
    )


def _price(cell: str) -> Decimal:
    if not (match := re.fullmatch(r'(?:~~\\\$[0-9.]+~~ )?\\\$([0-9]+(?:\.[0-9]+)?)', cell)):
        raise UnreadableRowError(f'Unexpected MiniMax price cell: {cell}')
    return Decimal(match.group(1))
