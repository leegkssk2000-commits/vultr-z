from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / 'tools' / 'q4r3_strategy_runtime_owner_contract_probe.py'
    spec = importlib.util.spec_from_file_location('q4r3_runtime_owner_contract_probe_test_module', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def record(tmp_path: Path, relative: str, text: str):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    imports, strings, functions, classes = MODULE.parse_python(path, text)
    return MODULE.CodeRecord(
        path=path,
        relative=relative,
        module='.'.join(Path(relative).with_suffix('').parts),
        text=text,
        lower=text.lower(),
        imports=frozenset(imports),
        strings=frozenset(strings),
        functions=frozenset(functions),
        classes=frozenset(classes),
    )


def test_parse_python_collects_import_strings_and_callables(tmp_path: Path) -> None:
    rec = record(tmp_path, 'backend/engine/a.py', "import backend.strategies.range_fade\nTARGET='backend.strategies.range_fade'\ndef generate_signal(): pass\nclass X: pass\n")
    assert 'backend.strategies.range_fade' in rec.imports
    assert 'backend.strategies.range_fade' in rec.strings
    assert 'generate_signal' in rec.functions
    assert 'X' in rec.classes


def test_build_graph_includes_dynamic_string_module_reference(tmp_path: Path, monkeypatch) -> None:
    first = record(tmp_path, 'backend/strategies/range_fade.py', 'def generate_signal(): pass\n')
    second = record(tmp_path, 'backend/engine/loader.py', "MODULE='backend.strategies.range_fade'\n")
    by_module, forward, reverse = MODULE.build_graph([first, second])
    assert 'backend.strategies.range_fade' in forward['backend.engine.loader']
    assert 'backend.engine.loader' in reverse['backend.strategies.range_fade']


def test_owner_probe_prefers_runtime_reachable_owner(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    canonical = record(tmp_path, 'backend/strategies/range_fade.py', 'def generate_signal(): pass\n')
    legendary = record(tmp_path, 'backend/legendary_rebuild/strategies/range_fade_legendary.py', 'def generate_signal(): pass\n')
    loader = record(tmp_path, 'backend/engine/loader.py', "MODULE='backend.strategies.range_fade'\n")
    records = [canonical, legendary, loader]
    by_module, forward, reverse = MODULE.build_graph(records)
    result = MODULE.owner_probe('range_fade', records, by_module, reverse, 'backend.engine.loader backend.strategies.range_fade')
    assert result['owner_module'] == 'backend.strategies.range_fade'
    assert result['verdict'] == 'RUNTIME_OR_REGISTRY_OWNER_CONFIRMED'


def test_writer_probe_finds_common_indirect_writer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    strategy = record(tmp_path, 'backend/strategies/grid_rebalance.py', 'def generate_signal(): pass\n')
    engine = record(tmp_path, 'backend/engine/runner.py', "import backend.strategies.grid_rebalance\ninitial_risk_usdt=1\nrealized_r=1\njson.dumps({'ledger': 1})\n")
    records = [strategy, engine]
    by_module, forward, reverse = MODULE.build_graph(records)
    result = MODULE.writer_probe('grid_rebalance', ['backend.strategies.grid_rebalance'], by_module, reverse, '')
    assert result['verdict'] == 'STATIC_COMMON_WRITER_CANDIDATES_FOUND'
    assert result['candidates'][0]['module'] == 'backend.engine.runner'


def test_contract_surface_reports_multi_owner_and_missing_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    canonical = record(tmp_path, 'backend/strategies/range_fade.py', 'def generate_signal(): pass\n')
    legendary = record(tmp_path, 'backend/legendary_rebuild/strategies/range_fade_legendary.py', 'def generate_signal(): pass\n')
    records = [canonical, legendary]
    by_module, forward, reverse = MODULE.build_graph(records)
    result = MODULE.contract_surface(['range_fade'], records, by_module)
    assert result['summary']['multi_module_count'] == 1
    assert result['summary']['missing_contract_surface_count'] == 1


def test_existing_test_surface_detects_registry_harness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    strategies = [f'strategy_{index:02d}' for index in range(25)]
    text = "import pytest\n@pytest.mark.parametrize('strategy', REGISTRY)\ndef test_contract(strategy):\n    assert strategy\n"
    rec = record(tmp_path, 'tests/test_all_strategies.py', text)
    result = MODULE.existing_test_surface(strategies, [rec])
    assert len(result['shared_harness_candidates']) == 1
    assert result['shared_harness_candidates'][0]['registry_driven'] is True


def test_load_expected_reads_exact_universe(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / 'complete.json'
    path.write_text(json.dumps({'expected_universe': {'selected': {'names': ['A', 'B']}}}), encoding='utf-8')
    monkeypatch.setattr(MODULE, 'COMPLETENESS', path)
    assert MODULE.load_expected() == ['a', 'b']
