from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / 'tools' / 'q4r3_strategy_owner_writer_test_audit.py'
    spec = importlib.util.spec_from_file_location('q4r3_strategy_owner_writer_test_audit_test_module', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_writer_characteristics_requires_writer_and_risk() -> None:
    assert MODULE.writer_characteristics("initial_risk_usdt=1\njson.dumps({})")['writer_like'] is True
    assert MODULE.writer_characteristics("json.dumps({})")['writer_like'] is False
    assert MODULE.writer_characteristics("initial_risk_usdt=1")['writer_like'] is False


def test_reachable_modules_walks_reverse_graph() -> None:
    reverse = {
        'backend.strategies.a': {'backend.engine.one'},
        'backend.engine.one': {'backend.worker.two'},
    }
    result = MODULE.reachable_modules('backend.strategies.a', reverse, depth=3)
    assert result['backend.engine.one'] == 1
    assert result['backend.worker.two'] == 2


def test_normalized_ast_hash_ignores_formatting(tmp_path: Path) -> None:
    first = tmp_path / 'a.py'
    second = tmp_path / 'b.py'
    first.write_text('x=1\n', encoding='utf-8')
    second.write_text('x = 1\n', encoding='utf-8')
    assert MODULE.normalized_ast_hash(first) == MODULE.normalized_ast_hash(second)


def test_test_coverage_detects_shared_harness(tmp_path: Path, monkeypatch) -> None:
    expected = [f'strategy_{index:02d}' for index in range(25)]
    test_dir = tmp_path / 'tests'
    test_dir.mkdir()
    test_file = test_dir / 'test_all.py'
    test_file.write_text("STRATEGIES=" + repr(expected) + "\n", encoding='utf-8')
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    result = MODULE.test_coverage(expected, [test_file])
    assert result['direct_covered_count'] == 25
    assert result['verdict'] == 'ALL_25_DIRECTLY_COVERED'


def test_test_coverage_detects_no_harness(tmp_path: Path, monkeypatch) -> None:
    expected = ['alpha', 'beta']
    test_dir = tmp_path / 'tests'
    test_dir.mkdir()
    test_file = test_dir / 'test_misc.py'
    test_file.write_text('def test_misc(): assert True\n', encoding='utf-8')
    monkeypatch.setattr(MODULE, 'ROOT', tmp_path)
    result = MODULE.test_coverage(expected, [test_file])
    assert result['verdict'] == 'NO_25_STRATEGY_CONTRACT_HARNESS_FOUND'
    assert result['direct_missing'] == ['alpha', 'beta']


def test_load_expected_uses_completeness_universe(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / 'complete.json'
    path.write_text(json.dumps({'expected_universe': {'selected': {'names': ['a', 'b']}}}), encoding='utf-8')
    monkeypatch.setattr(MODULE, 'COMPLETENESS', path)
    names, payload = MODULE.load_expected()
    assert names == ['a', 'b']
    assert payload['expected_universe']['selected']['names'] == ['a', 'b']
