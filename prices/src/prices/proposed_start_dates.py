"""Keep the start date of a rate change the open hourly price update already proposes.

The hourly update rebuilds its branch from main, so each run would otherwise date a pending rate change to the
day of that run, and requests from the first detection until the merge would keep the old rate.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path
from typing import TypeVar

from .prices_types import ConditionalPrice, ModelInfo, ModelPrice, PriceVariant, Provider, StartDateConstraint
from .update import ProviderYaml, yaml
from .utils import package_dir, root_dir

Entry = TypeVar('Entry', ConditionalPrice, PriceVariant)


def keep_proposed_start_dates(path: Path, main_yaml: str, proposal_yaml: str) -> int:
    """Give each dated entry the run added the proposal's earlier date, where the proposal adds the same entry."""
    current = ProviderYaml(path)
    main = models_by_id(main_yaml)
    proposal = models_by_id(proposal_yaml)
    kept = 0
    for yaml_model in current.data['models']:
        record = ModelInfo.model_validate(yaml_model)
        if (base := main.get(record.id)) is None or (proposed := proposal.get(record.id)) is None:
            continue
        start_dates = proposed_start_dates(record, base, proposed)
        for field, index, start in start_dates:
            yaml_model[field][index]['constraint']['start_date'] = start
        kept += len(start_dates)
    if kept:
        current.save()
    return kept


def proposed_start_dates(record: ModelInfo, base: ModelInfo, proposed: ModelInfo) -> list[tuple[str, int, date]]:
    """The proposal's date for each entry not on main, or none unless the proposal makes every change identically."""
    prices = earlier_start_dates(as_list(record.prices), as_list(proposed.prices), as_list(base.prices))
    variants = earlier_start_dates(
        record.price_variants or [], proposed.price_variants or [], base.price_variants or []
    )
    if prices is None or variants is None:
        return []
    return [('prices', *change) for change in prices] + [('price_variants', *change) for change in variants]


def earlier_start_dates(ours: list[Entry], theirs: list[Entry], on_main: list[Entry]) -> list[tuple[int, date]] | None:
    """Index and earlier date of each entry that differs from the proposal only by it; `None` for any other change."""
    if len(ours) != len(theirs):
        return None
    start_dates: list[tuple[int, date]] = []
    for index, (entry, proposed) in enumerate(zip(ours, theirs)):
        if entry == proposed:
            continue
        if not (
            entry not in on_main
            and isinstance(entry.constraint, StartDateConstraint)
            and isinstance(proposed.constraint, StartDateConstraint)
            and proposed.constraint.start_date < entry.constraint.start_date
            and entry.model_copy(update={'constraint': proposed.constraint}) == proposed
        ):
            return None
        start_dates.append((index, proposed.constraint.start_date))
    return start_dates


def models_by_id(provider_yaml: str) -> dict[str, ModelInfo]:
    provider = Provider.model_validate(yaml.load(provider_yaml))  # pyright: ignore[reportUnknownMemberType]
    return {model.id: model for model in provider.models}


def as_list(prices: ModelPrice | list[ConditionalPrice]) -> list[ConditionalPrice]:
    return prices if isinstance(prices, list) else []


def git_show(ref: str, path: str) -> str | None:
    result = subprocess.run(['git', 'show', f'{ref}:{path}'], cwd=root_dir, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description='Keep the start dates of rate changes an open price update proposes')
    parser.add_argument('proposal', help='the git ref of the open price update')
    args = parser.parse_args()
    for path in sorted((package_dir / 'providers').glob('*.yml')):
        relative = path.relative_to(root_dir).as_posix()
        main_yaml = git_show('HEAD', relative)
        proposal_yaml = git_show(args.proposal, relative)
        if main_yaml is None or proposal_yaml is None or main_yaml == path.read_text():
            continue
        if kept := keep_proposed_start_dates(path, main_yaml, proposal_yaml):
            print(f'{path.name}: kept {kept} start dates from the open price update')


if __name__ == '__main__':
    main()
