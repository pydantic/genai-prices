from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from pydantic import AliasChoices, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliPositionalArg,
    CliSettingsSource,
    CliSubCommand,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    get_subcommand,
)
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

from . import Usage, __version__, calc_price, update_prices
from .types import ModelPrice, PriceCalculation, Provider, TieredPrices

PROGRAM_NAME = 'genai-prices'
_PROVIDER_COLORS = (
    'steel_blue1',
    'sea_green2',
    'gold3',
    'orchid2',
    'turquoise2',
    'light_sky_blue3',
    'medium_purple4',
    'chartreuse3',
    'deep_pink3',
    'sandy_brown',
    'deep_sky_blue1',
    'dodger_blue2',
    'cyan3',
    'spring_green2',
    'green_yellow',
    'yellow2',
    'orange3',
    'dark_orange3',
    'red3',
    'magenta3',
    'purple3',
    'violet',
    'hot_pink3',
    'salmon1',
    'light_salmon3',
    'khaki1',
    'olive_drab3',
    'aquamarine3',
    'medium_turquoise',
    'light_coral',
)
_PRICE_STYLES: dict[str, str] = {
    'input_mtok': 'deep_sky_blue2',
    'cache_write_mtok': 'dark_goldenrod',
    'cache_read_mtok': 'khaki3',
    'output_mtok': 'orange_red1',
    'input_audio_mtok': 'medium_purple3',
    'cache_audio_read_mtok': 'plum3',
    'output_audio_mtok': 'hot_pink2',
    'requests_kcount': 'dark_turquoise',
}


def _build_root_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description=f'{PROGRAM_NAME} CLI v{__version__}\n\nCalculate prices for calling LLM inference APIs.\n',
        formatter_class=RichHelpFormatter,
    )


class _CLIBase(
    BaseSettings,
    cli_enforce_required=True,
    cli_hide_none_type=True,
    cli_exit_on_error=True,
    case_sensitive=True,
):
    model_config = SettingsConfigDict(
        extra='forbid',
        cli_parse_args=False,
        cli_implicit_flags=True,
    )


class _ToggleCliSettingsSource(CliSettingsSource[Any]):
    # Workaround for toggle-only boolean flags; upstream support merged in
    # https://github.com/pydantic/pydantic-settings/pull/717 but not in a tagged release yet.
    def _convert_bool_flag(self, kwargs: dict[str, Any], field_info: FieldInfo, model_default: Any) -> None:
        if kwargs.get('metavar') == 'bool' and self.cli_implicit_flags:
            del kwargs['metavar']
            if kwargs.get('required'):
                kwargs['action'] = argparse.BooleanOptionalAction
            else:
                kwargs['action'] = 'store_false' if model_default is True else 'store_true'


class CalcCLI(_CLIBase):
    """calculate prices"""

    model: CliPositionalArg[list[str]] = Field(
        ...,
        description='Model and optionally provider used: either just the model ID, e.g. "gpt-4o" or in format "<provider>:<model>" e.g. "openai:gpt-4o".',
    )
    update_prices: bool = Field(
        False,
        validation_alias=AliasChoices('u', 'update-prices'),
        description='Whether to update the model prices from GitHub.',
    )
    timestamp: datetime | None = Field(
        None,
        validation_alias=AliasChoices('t', 'timestamp'),
        description='Timestamp of the request, in RFC 3339 format, if not provided, the current time will be used.',
    )
    table: bool = Field(
        False,
        validation_alias=AliasChoices('T', 'table'),
        description='Whether to use wide table output with one row per model.',
    )
    no_color: bool = Field(
        False,
        validation_alias=AliasChoices('n', 'no-color'),
        description='Whether to disable colors in calc output.',
    )
    keep_going: bool = Field(
        False,
        validation_alias=AliasChoices('k', 'keep-going'),
        description='Whether to continue if a model is not found.',
    )
    input_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('i', 'input-tokens'),
        description='Usage: Number of text input/prompt tokens.',
    )
    cache_write_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('w', 'cache-write-tokens'),
        description='Usage: Number of tokens written to the cache.',
    )
    cache_read_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('r', 'cache-read-tokens'),
        description='Usage: Number of tokens read from the cache.',
    )
    output_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('o', 'output-tokens'),
        description='Usage: Number of text output/completion tokens.',
    )
    input_audio_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('a', 'input-audio-tokens'),
        description='Usage: Number of audio input tokens.',
    )
    cache_audio_read_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('A', 'cache-audio-read-tokens'),
        description='Usage: Number of audio tokens read from the cache.',
    )
    output_audio_tokens: int | None = Field(
        None,
        validation_alias=AliasChoices('O', 'output-audio-tokens'),
        description='Usage: Number of output audio tokens.',
    )


class ListCLI(_CLIBase):
    """list providers and models"""

    provider: CliPositionalArg[str | None] = Field(
        None,
        description='Only list models for the provider.',
    )


class CLIRoot(_CLIBase):
    calc: CliSubCommand[CalcCLI] = Field(
        description='Calculate prices.',
    )
    list: CliSubCommand[ListCLI] = Field(
        description='List providers and models.',
    )
    version: bool = Field(
        False,
        validation_alias=AliasChoices('v', 'version'),
        description='Show version and exit',
    )
    plain: bool = Field(
        False,
        validation_alias=AliasChoices('p', 'plain'),
        description='Use plain output without rich formatting.',
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            cast(
                PydanticBaseSettingsSource,
                _ToggleCliSettingsSource(
                    CLIRoot,
                    root_parser=_build_root_parser(),
                    formatter_class=RichHelpFormatter,
                    cli_parse_args=True,
                ),
            ),
        )


def cli() -> int:  # pragma: no cover
    """Run the CLI."""
    sys.exit(cli_logic())


def cli_logic(args_list: Sequence[str] | None = None) -> int:
    try:
        cli = _parse_cli(args_list)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    if cli.version:
        if cli.plain:
            print(f'{PROGRAM_NAME} {__version__}')
        else:
            Console(soft_wrap=True).print(f'{PROGRAM_NAME} {__version__}', highlight=False)
        return 0

    sub = get_subcommand(cli, is_required=False)
    if sub is None:
        _build_root_parser().print_help()
        return 1

    if isinstance(sub, CalcCLI):
        return calc_prices(sub, plain=cli.plain)
    if isinstance(sub, ListCLI):
        return list_models(sub, plain=cli.plain)

    _build_root_parser().print_help()
    return 1


def _parse_cli(args_list: Sequence[str] | None) -> CLIRoot:
    if args_list is None:
        return CliApp.run(CLIRoot)

    original_argv = sys.argv
    try:
        sys.argv = [PROGRAM_NAME, *args_list]
        return CliApp.run(CLIRoot)
    finally:
        sys.argv = original_argv


def calc_prices(args: CalcCLI, *, plain: bool) -> int:
    from .data import providers

    usage = Usage(
        input_tokens=args.input_tokens,
        cache_write_tokens=args.cache_write_tokens,
        cache_read_tokens=args.cache_read_tokens,
        output_tokens=args.output_tokens,
        input_audio_tokens=args.input_audio_tokens,
        cache_audio_read_tokens=args.cache_audio_read_tokens,
        output_audio_tokens=args.output_audio_tokens,
    )
    console = Console(soft_wrap=True)
    err_console = Console(stderr=True, soft_wrap=True)
    use_color = not args.no_color
    tables: list[Table] = []
    summary_results: list[PriceCalculation] = []
    seen_models: set[tuple[str, str]] = set()
    had_error = False
    if args.update_prices:
        price_update = update_prices.UpdatePrices()
        price_update.start(wait=True)
    for model in args.model:
        provider_id = None
        if ':' in model:
            provider_id, model = model.split(':', 1)

        try:
            price_calc = calc_price(
                usage,
                model_ref=model,
                provider_id=provider_id,
                genai_request_timestamp=args.timestamp,
            )
        except LookupError as exc:
            had_error = True
            _render_calc_error(
                err_console,
                message=str(exc),
                model_ref=model,
                provider_id=provider_id,
                providers=providers,
                plain=plain,
                use_color=use_color,
            )
            if not args.keep_going:
                if not plain:
                    if args.table:
                        _render_calc_summary_results(console, summary_results, use_color=use_color)
                    else:
                        _render_calc_tables(console, tables)
                return 1
            continue

        resolved_key = (price_calc.provider.id, price_calc.model.id)
        if resolved_key in seen_models:
            continue
        seen_models.add(resolved_key)
        w = price_calc.model.context_window
        output: list[tuple[str, str | None]] = [
            ('Provider', price_calc.provider.name),
            ('Model', price_calc.model.name or price_calc.model.id),
            ('Model Prices', str(price_calc.model_price)),
            ('Context Window', f'{w:,d}' if w is not None else None),
            ('Input Price', f'${price_calc.input_price}'),
            ('Output Price', f'${price_calc.output_price}'),
            ('Total Price', f'${price_calc.total_price}'),
        ]
        if plain:
            for key, value in output:
                if value is not None:
                    print(f'{key:>14}: {value}')
            print('')
        elif args.table:
            summary_results.append(price_calc)
        else:
            tables.append(_build_calc_table(price_calc, output, split_prices=True, use_color=use_color))

    if not plain:
        if args.table:
            _render_calc_summary_results(console, summary_results, use_color=use_color)
        else:
            _render_calc_tables(console, tables)
    return 1 if had_error else 0


def list_models(args: ListCLI, *, plain: bool) -> int:
    from .data import providers

    console = Console(soft_wrap=True)
    err_console = Console(stderr=True, soft_wrap=True)

    if args.provider:
        provider_ids = {p.id for p in providers}
        if args.provider not in provider_ids:
            message = f'Error: provider {args.provider!r} not found in {sorted(provider_ids)}'
            if plain:
                print(message, file=sys.stderr)
            else:
                err_console.print(message, highlight=False)
            return 1

    for provider in providers:
        if args.provider and provider.id != args.provider:
            continue
        if plain:
            print(f'{provider.name}: ({len(provider.models)} models)')
            for model in provider.models:
                if model.name:
                    print(f'  {provider.id}:{model.id}: {model.name}')
                else:
                    print(f'  {provider.id}:{model.id}')
        else:
            _render_list_provider(console, provider)
    return 0


def _build_calc_table(
    price_calc: PriceCalculation,
    output: list[tuple[str, str | None]],
    *,
    split_prices: bool,
    use_color: bool,
) -> Table:
    table = Table(show_header=False, box=box.SIMPLE, pad_edge=False)
    table.add_column(justify='right')
    table.add_column()
    for key, value in output:
        if value is None:
            continue
        renderable = _format_calc_value(key, value, price_calc, split_prices=split_prices, use_color=use_color)
        table.add_row(_format_calc_label(key, use_color=use_color), renderable)
    return table


def _render_calc_tables(console: Console, tables: list[Table]) -> None:
    if not tables:
        return
    if len(tables) == 1:
        console.print(tables[0])
    else:
        console.print(Columns(tables, expand=True, equal=False))
    console.print('')


def _build_calc_summary_table(price_fields: Sequence[str] | None, *, use_color: bool) -> Table:
    table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
    table.add_column('Provider', header_style='bold cyan' if use_color else None)
    table.add_column('Model', header_style='bold cyan' if use_color else None)
    if price_fields:
        for field_name in price_fields:
            table.add_column(
                _price_field_label(field_name),
                header_style=_price_field_header_style(field_name) if use_color else None,
                justify='right',
            )
    else:
        table.add_column('Model Prices', header_style='bold cyan' if use_color else None)
    table.add_column('Context Window', header_style='bold cyan' if use_color else None, justify='right')
    table.add_column('Input Price', header_style='bold sea_green3' if use_color else None, justify='right')
    table.add_column('Output Price', header_style='bold dark_orange3' if use_color else None, justify='right')
    table.add_column('Total Price', header_style='bold bright_white' if use_color else None, justify='right')
    return table


def _add_calc_summary_row(
    table: Table,
    price_calc: PriceCalculation,
    price_fields: Sequence[str] | None,
    *,
    use_color: bool,
) -> None:
    context_window = price_calc.model.context_window
    price_cells: list[Text] = []
    if price_fields:
        price_cells = [
            _format_model_price_value(price_calc.model_price, field_name, use_color=use_color)
            for field_name in price_fields
        ]
    else:
        price_cells = [_format_model_prices(price_calc.model_price, split_lines=True, use_color=use_color)]
    table.add_row(
        Text(price_calc.provider.name, style=_provider_style(price_calc.provider.id))
        if use_color
        else Text(price_calc.provider.name),
        Text(price_calc.model.name or price_calc.model.id),
        *price_cells,
        Text(f'{context_window:,d}' if context_window is not None else ''),
        _format_calc_value(
            'Input Price', f'${price_calc.input_price}', price_calc, split_prices=True, use_color=use_color
        ),
        _format_calc_value(
            'Output Price', f'${price_calc.output_price}', price_calc, split_prices=True, use_color=use_color
        ),
        _format_calc_value(
            'Total Price', f'${price_calc.total_price}', price_calc, split_prices=True, use_color=use_color
        ),
    )


def _render_calc_summary_results(console: Console, results: Sequence[PriceCalculation], *, use_color: bool) -> None:
    if not results:
        return
    price_fields = _collect_model_price_fields(results)
    split_prices = _should_split_model_price_columns(console, price_fields)
    fields = price_fields if split_prices else None
    table = _build_calc_summary_table(fields, use_color=use_color)
    for price_calc in results:
        _add_calc_summary_row(table, price_calc, fields, use_color=use_color)
    console.print(table)
    console.print('')


def _render_list_provider(console: Console, provider: Provider) -> None:
    style = _provider_style(provider.id)
    console.print(f'[{style}]{provider.name}[/]: ({len(provider.models)} models)', highlight=False)
    for model in provider.models:
        prefix = f'  [{style}]{provider.id}[/]:{model.id}'
        if model.name:
            console.print(f'{prefix}: {model.name}', highlight=False)
        else:
            console.print(prefix, highlight=False)


def _provider_style(provider_id: str) -> str:
    digest = hashlib.md5(provider_id.encode()).digest()
    return _PROVIDER_COLORS[digest[0] % len(_PROVIDER_COLORS)]


def _format_calc_value(
    key: str,
    value: str,
    price_calc: PriceCalculation,
    *,
    split_prices: bool,
    use_color: bool,
) -> Text:
    if key == 'Model Prices':
        return _format_model_prices(price_calc.model_price, split_lines=split_prices, use_color=use_color)
    if key == 'Provider':
        return Text(value, style=_provider_style(price_calc.provider.id)) if use_color else Text(value)
    if key == 'Input Price':
        return Text(value, style='sea_green3') if use_color else Text(value)
    if key == 'Output Price':
        return Text(value, style='dark_orange3') if use_color else Text(value)
    if key == 'Total Price':
        return Text(value, style='bold bright_white') if use_color else Text(value)
    return Text(value)


def _format_calc_label(key: str, *, use_color: bool) -> Text:
    if not use_color:
        return Text(key)
    if key == 'Input Price':
        return Text(key, style='bold sea_green3')
    if key == 'Output Price':
        return Text(key, style='bold dark_orange3')
    if key == 'Total Price':
        return Text(key, style='bold bright_white')
    return Text(key, style='bold cyan')


def _collect_model_price_fields(results: Sequence[PriceCalculation]) -> list[str]:
    ordered_fields = [field.name for field in dataclasses.fields(ModelPrice)]
    present_fields: list[str] = []
    for field_name in ordered_fields:
        if any(getattr(result.model_price, field_name) is not None for result in results):
            present_fields.append(field_name)
    return present_fields


def _should_split_model_price_columns(console: Console, fields: Sequence[str]) -> bool:
    if not fields:
        return False
    base_headers = [
        'Provider',
        'Model',
        'Context Window',
        'Input Price',
        'Output Price',
        'Total Price',
    ]
    base_width = sum(len(header) for header in base_headers) + len(base_headers) * 3
    price_width = sum(max(len(_price_field_label(field)), 10) + 3 for field in fields)
    required = base_width + price_width
    return console.width >= required


def _price_field_label(field_name: str) -> str:
    labels = {
        'input_mtok': 'Input/MTok',
        'cache_write_mtok': 'Cache Write/MTok',
        'cache_read_mtok': 'Cache Read/MTok',
        'output_mtok': 'Output/MTok',
        'input_audio_mtok': 'Input Audio/MTok',
        'cache_audio_read_mtok': 'Cache Audio Read/MTok',
        'output_audio_mtok': 'Output Audio/MTok',
        'requests_kcount': 'Requests/K',
    }
    return labels.get(field_name, field_name.replace('_mtok', '').replace('_', ' ').title())


def _price_field_header_style(field_name: str) -> str:
    style = _PRICE_STYLES.get(field_name)
    return f'bold {style}' if style else 'bold cyan'


def _format_model_price_value(model_price: ModelPrice, field_name: str, *, use_color: bool) -> Text:
    value = getattr(model_price, field_name)
    style = _PRICE_STYLES.get(field_name) if use_color else None
    if value is None:
        return Text('')
    if field_name == 'requests_kcount':
        return Text(f'${value}', style=style) if style else Text(f'${value}')
    if isinstance(value, TieredPrices):
        return Text(f'${value.base} (+tiers)', style=style) if style else Text(f'${value.base} (+tiers)')
    return Text(f'${value}', style=style) if style else Text(f'${value}')


def _format_model_prices(model_price: ModelPrice, *, split_lines: bool, use_color: bool) -> Text:
    parts = Text()
    for field in dataclasses.fields(model_price):
        value = getattr(model_price, field.name)
        if value is None:
            continue
        if parts:
            parts.append('\n' if split_lines else ', ')

        style = _PRICE_STYLES.get(field.name) if use_color else None
        if field.name == 'requests_kcount':
            if style:
                parts.append(f'${value} / K requests', style=style)
            else:
                parts.append(f'${value} / K requests')
            continue

        name = field.name.replace('_mtok', '').replace('_', ' ')
        if isinstance(value, TieredPrices):
            text = f'${value.base}/{name} MTok (+tiers)'
        else:
            text = f'${value}/{name} MTok'
        if style:
            parts.append(text, style=style)
        else:
            parts.append(text)
    return parts


def _render_calc_error(
    console: Console,
    *,
    message: str,
    model_ref: str,
    provider_id: str | None,
    providers: list[Provider],
    plain: bool,
    use_color: bool,
) -> None:
    if plain:
        print(f'Error: {message}', file=sys.stderr)
    else:
        if use_color:
            console.print(f'[red]Error:[/] {message}', highlight=False)
        else:
            console.print(f'Error: {message}', highlight=False)

    provider_ids = {provider.id for provider in providers}
    if provider_id and provider_id not in provider_ids:
        provider_suggestions = _suggest_values(provider_id, sorted(provider_ids))
        if provider_suggestions:
            if plain:
                line = f'Did you mean provider: {", ".join(provider_suggestions)}'
                print(line, file=sys.stderr)
            else:
                if use_color:
                    line = Text('Did you mean provider: ')
                    line.append_text(_format_provider_suggestions(provider_suggestions))
                    console.print(line, highlight=False)
                else:
                    console.print(f'Did you mean provider: {", ".join(provider_suggestions)}', highlight=False)
        return

    model_suggestions = _suggest_models(model_ref, provider_id, providers)
    if model_suggestions:
        if plain:
            line = f'Did you mean: {", ".join(model_suggestions)}'
            print(line, file=sys.stderr)
        else:
            if use_color:
                line = Text('Did you mean: ')
                line.append_text(_format_model_suggestions(model_suggestions))
                console.print(line, highlight=False)
            else:
                console.print(f'Did you mean: {", ".join(model_suggestions)}', highlight=False)


def _suggest_models(model_ref: str, provider_id: str | None, providers: list[Provider]) -> list[str]:
    model_ref = model_ref.lower()
    if provider_id:
        provider = next((p for p in providers if p.id == provider_id), None)
        if provider is None:
            return []
        candidates = [model.id for model in provider.models]
        matches = _suggest_values(model_ref, candidates)
        return [f'{provider.id}:{model_id}' for model_id in matches]

    candidates = [f'{provider.id}:{model.id}' for provider in providers for model in provider.models]
    return _suggest_values(model_ref, candidates)


def _suggest_values(value: str, candidates: list[str]) -> list[str]:
    return difflib.get_close_matches(value, candidates, n=5, cutoff=0.6)


def _format_provider_suggestions(suggestions: list[str]) -> Text:
    parts = Text()
    for index, suggestion in enumerate(suggestions):
        if index:
            parts.append(', ')
        parts.append(suggestion, style=_provider_style(suggestion))
    return parts


def _format_model_suggestions(suggestions: list[str]) -> Text:
    parts = Text()
    for index, suggestion in enumerate(suggestions):
        if index:
            parts.append(', ')
        parts.append_text(_format_model_suggestion(suggestion))
    return parts


def _format_model_suggestion(suggestion: str) -> Text:
    if ':' in suggestion:
        provider_id, model_id = suggestion.split(':', 1)
        text = Text(provider_id, style=_provider_style(provider_id))
        text.append(f':{model_id}')
        return text
    return Text(suggestion)
