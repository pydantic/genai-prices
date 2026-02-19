from __future__ import annotations

import pytest
from dirty_equals import IsStr
from inline_snapshot import snapshot

from genai_prices._cli import cli_logic


def test_version(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--version']) == 0
    out, err = capsys.readouterr()
    assert out == IsStr(regex=r'genai-prices .*\n')
    assert err == ''


def test_calc(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: gpt 4o
  Model Prices: $2.5/input MTok, $1.25/cache read MTok, $10/output MTok, $25 / K web searches, $2.5 / K file searches
Context Window: 128,000
   Input Price: $0.0025
  Output Price: $0.001
   Total Price: $0.0035

""")
    assert err == ''


def test_calc_with_provider(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', '--output-tokens', '100', 'azure:gpt-3.5-turbo-16k-0613']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: Microsoft Azure
         Model: GPT-3.5 Turbo 16k
  Model Prices: $3/input MTok, $4/output MTok
Context Window: 16,385
   Input Price: $0.003
  Output Price: $0.0004
   Total Price: $0.0034

""")
    assert err == ''


def test_calc_timestamp(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '10000', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: o3
  Model Prices: $2/input MTok, $0.5/cache read MTok, $8/output MTok
   Input Price: $0.02
  Output Price: $0
   Total Price: $0.02

""")
    assert err == ''

    assert cli_logic(['calc', '--input-tokens', '10000', '--timestamp', '2025-06-01', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: o3
  Model Prices: $10/input MTok, $0.5/cache read MTok, $40/output MTok
   Input Price: $0.1
  Output Price: $0
   Total Price: $0.1

""")
    assert err == ''


def test_list(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list']) == 0
    out, err = capsys.readouterr()
    assert out.count('\n') > 100
    assert err == ''


def test_list_provider(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list', 'deepseek']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
Deepseek: (2 models)
  deepseek:deepseek-chat: DeepSeek Chat
  deepseek:deepseek-reasoner: Deepseek R1
""")
    assert err == ''


def test_list_provider_wrong(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list', 'foobar']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert err == IsStr(regex="^Error: provider 'foobar' not found in .*\n")
