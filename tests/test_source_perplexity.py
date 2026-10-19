from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest

from prices import source_perplexity
from prices.prices_types import ModelPrice
from prices.utils import package_dir

PRICING: dict[str, Any] = {
    '_meta': {'units': {**source_perplexity.EXPECTED_UNITS, 'tools': '$ per invocation'}},
    'sonar': {
        'models': [
            {'id': 'sonar', 'label': 'Sonar', 'input': 1, 'output': 1, 'request': {'low': 5, 'medium': 8, 'high': 12}},
            {
                'id': 'sonar-deep-research',
                'label': 'Sonar Deep Research',
                'input': 2,
                'output': 8,
                'citation': 2,
                'reasoning': 3,
                'searchQueries': 5,
            },
        ]
    },
}


def page(pricing: dict[str, Any]) -> str:
    return f'# Pricing\n\nexport const PRICING = {json.dumps(pricing)};\n\nexport const Calculator = () => {{}}\n'


def test_perplexity_parses_sonar_rates_with_the_highest_request_fee() -> None:
    sonar, deep_research = source_perplexity.parse_pricing_markdown(page(PRICING))

    assert (sonar.id, sonar.name, sonar.prices_checked) == ('sonar', 'Sonar', date.today())
    assert sonar.prices == ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('1'), requests_kcount=Decimal('12'))
    assert deep_research.prices == ModelPrice.model_validate(
        {
            'input_mtok': '2',
            'output_mtok': '8',
            'output_reasoning_mtok': '3',
            'output_citation_mtok': '2',
            'web_searches_kcount': '5',
        }
    )


def test_perplexity_rejects_a_page_without_pricing_data() -> None:
    with pytest.raises(RuntimeError, match='Perplexity pricing page has no PRICING data'):
        source_perplexity.parse_pricing_markdown('# Pricing\n')


def test_perplexity_rejects_a_changed_unit() -> None:
    units = {**source_perplexity.EXPECTED_UNITS, 'sonar.searchQueries': '$ per 1,000,000 searches'}

    with pytest.raises(RuntimeError, match="Perplexity changed the unit of sonar.searchQueries to '\\$ per 1,000,000"):
        source_perplexity.parse_pricing_markdown(page({**PRICING, '_meta': {'units': units}}))


@pytest.mark.vcr()
def test_perplexity_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'perplexity.yml'
    copyfile(package_dir / 'providers/perplexity.yml', provider_path)

    source_perplexity.main(provider_path)

    assert capsys.readouterr().out == 'Perplexity prices updated: 0 added, 4 updated\n'
