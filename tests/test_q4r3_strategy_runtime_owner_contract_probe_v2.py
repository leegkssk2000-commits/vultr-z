from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / 'tools' / 'q4r3_strategy_runtime_owner_contract_probe_v2.py'
    spec = importlib.util.spec_from_file_location('q4r3_runtime_owner_contract_probe_v2_test_module', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_sanitize_removes_full_process_fields() -> None:
    payload = {
        'pid': 123,
        'cmdline': '/usr/bin/python /home/z/z/backend/worker.py --api-key SECRET',
        'cwd': '/home/z/z',
        'cgroup': '/system.slice/z-worker.service',
        'stack': 'secret stack',
    }
    result = MODULE.sanitize(payload)
    assert 'cmdline' not in result
    assert 'cwd' not in result
    assert 'cgroup' not in result
    assert 'stack' not in result
    assert '/home/z/z/backend/worker.py' in result['repo_paths']
    assert 'z-worker.service' in result['service_units']


def test_sanitize_preserves_safe_decision_fields() -> None:
    payload = {'verdict': 'PASS', 'owner': {'module': 'backend.strategies.range_fade'}}
    assert MODULE.sanitize(payload) == payload
