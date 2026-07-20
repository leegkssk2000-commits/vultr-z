from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "backend/strategy25/shared_strategy_adapter.py"
spec = importlib.util.spec_from_file_location("shared_strategy_adapter", MODULE_PATH)
assert spec and spec.loader
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)

A3_STATUS = Path("/home/z/z/runtime/r7a3_strategy25_s_grade_audit/status_latest.json")


def test_receipt_contract_keys_and_replay_guard():
    guard = adapter.ReplayGuard(True, True, True, True)
    receipt = adapter.StrategyReceipt(
        strategy_id="s",
        source_sha="a" * 64,
        event_id="e",
        feature_ts="2026-01-01T00:00:00Z",
        signal="hold",
        invalidation={"type": "test"},
        replay_guard=guard,
    ).to_dict()
    assert set(adapter.REQUIRED_RECEIPT_KEYS).issubset(receipt)


def test_replay_guard_fails_closed():
    with pytest.raises(ValueError, match="REPLAY_GUARD_NOT_SATISFIED"):
        adapter.ReplayGuard(True, False, True, True).validate()


def test_source_sha_drift_is_blocked(tmp_path: Path):
    strategy = tmp_path / "strategy.py"
    strategy.write_text("def evaluate(context):\n    return {'signal':'hold','invalidation':1}\n")
    binding = adapter.build_binding("s", str(strategy))
    strategy.write_text("def evaluate(context):\n    return {'signal':'hold','invalidation':2}\n")
    with pytest.raises(ValueError, match="SOURCE_SHA_DRIFT"):
        adapter.invoke(
            binding,
            event_id="e",
            feature_ts="2026-01-01T00:00:00Z",
            context={},
            replay_guard=adapter.ReplayGuard(True, True, True, True),
        )


def test_class_method_is_statically_bound_but_runtime_factory_is_required(tmp_path: Path):
    strategy = tmp_path / "class_strategy.py"
    strategy.write_text("class Strategy:\n    def evaluate(self, context):\n        return {'signal':'hold'}\n")
    binding = adapter.build_binding("s", str(strategy))
    assert binding.entrypoint == "Strategy.evaluate"
    assert binding.entrypoint_kind == "class_method"
    with pytest.raises(RuntimeError, match="ENTRYPOINT_REQUIRES_RUNTIME_FACTORY_BINDING"):
        adapter.invoke(
            binding,
            event_id="e",
            feature_ts="2026-01-01T00:00:00Z",
            context={},
            replay_guard=adapter.ReplayGuard(True, True, True, True),
        )


@pytest.mark.skipif(not A3_STATUS.is_file(), reason="server A3 receipt not available")
def test_all_25_real_strategy_entrypoints_resolve():
    diagnosis = adapter.diagnose_bindings_from_a3_status(A3_STATUS)
    assert diagnosis["ok"], json.dumps(diagnosis["failures"], ensure_ascii=False, indent=2)
    assert diagnosis["binding_count"] == 25
    assert len({row["strategy_id"] for row in diagnosis["bindings"]}) == 25
    assert all(Path(row["implementation_path"]).is_file() for row in diagnosis["bindings"])
    assert all(row["source_sha"] and row["entrypoint"] and row["entrypoint_kind"] for row in diagnosis["bindings"])


@pytest.mark.skipif(not A3_STATUS.is_file(), reason="server A3 receipt not available")
def test_a3_manifest_has_exact_25_unique_strategies():
    data = json.loads(A3_STATUS.read_text())
    ids = [row["strategy_id"] for row in data["strategies"]]
    assert len(ids) == 25
    assert len(set(ids)) == 25
