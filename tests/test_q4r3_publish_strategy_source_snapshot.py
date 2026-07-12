from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / 'tools' / 'q4r3_publish_strategy_source_snapshot.py'
    spec = importlib.util.spec_from_file_location('q4r3_strategy_source_snapshot_test_module', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_extract_strategy_map() -> None:
    probe = {
        'contract_surface': {
            'strategies': [
                {'strategy': 'range_fade', 'modules': [{'path': 'backend/strategies/range_fade.py'}]},
                {'strategy': 'trend_rider', 'modules': [{'path': 'backend/strategies/trend_rider.py'}]},
            ]
        }
    }
    assert MODULE.extract_strategy_map(probe) == {
        'range_fade': ['backend/strategies/range_fade.py'],
        'trend_rider': ['backend/strategies/trend_rider.py'],
    }


def test_env_reference_is_not_literal_secret(tmp_path: Path) -> None:
    path = tmp_path / 'safe.py'
    text = "import os\nAPI_KEY = os.getenv('API_KEY')\n"
    assert MODULE.python_sensitive_findings(path, text) == []


def test_literal_secret_is_blocked(tmp_path: Path) -> None:
    path = tmp_path / 'unsafe.py'
    text = "API_KEY = 'abcdefghijk12345'\n"
    assert 'literal_secret_assignment' in MODULE.python_sensitive_findings(path, text)


def test_json_secret_is_blocked() -> None:
    findings = MODULE.json_sensitive_findings({'api_key': 'abcdefghijk12345'})
    assert findings == ['literal_secret_json:api_key']


def test_local_relative_import_resolution(tmp_path: Path) -> None:
    root = tmp_path
    strategy = root / 'backend' / 'strategies' / 'a.py'
    base = root / 'backend' / 'strategies' / 'base.py'
    strategy.parent.mkdir(parents=True)
    strategy.write_text('from .base import X\n', encoding='utf-8')
    base.write_text('class X: pass\n', encoding='utf-8')
    assert base in MODULE.local_imports(strategy, root)


def test_publish_complete_snapshot(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / 'root'
    strategy_dir = root / 'backend' / 'strategies'
    strategy_dir.mkdir(parents=True)
    strategies = []
    for index in range(25):
        name = f'strategy_{index:02d}'
        path = strategy_dir / f'{name}.py'
        path.write_text(f"def strategy(payload):\n    return {{'strategy_id': '{name}'}}\n", encoding='utf-8')
        strategies.append({'strategy': name, 'modules': [{'path': f'backend/strategies/{name}.py'}]})
    probe = root / 'probe.json'
    probe.write_text(json.dumps({'contract_surface': {'strategies': strategies}}), encoding='utf-8')
    output = tmp_path / 'out'
    monkeypatch.setattr(MODULE, 'SUPPORT_PATHS', ())
    result = MODULE.publish(root, probe, output)
    assert result['verdict'] == 'STRATEGY_SOURCE_SNAPSHOT_READY'
    assert result['expected_strategy_count'] == 25
    assert result['published_file_count'] == 25
    assert (output / 'source' / 'backend' / 'strategies' / 'strategy_00.py').is_file()
