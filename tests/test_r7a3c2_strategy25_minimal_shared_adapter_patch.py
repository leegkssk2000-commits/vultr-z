from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_adapter_rejects_failed_replay_guard():
    adapter = load_module(
        Path(__file__).parents[1] / "backend/strategy25/canonical_shared_adapter.py",
        "adapter_mod",
    )
    bindings = {}
    entrypoints = {}
    for i in range(25):
        sid = f"s{i:02d}"
        bindings[sid] = adapter.StrategyBinding(sid, "a" * 40, f"backend/s{i}.py:evaluate")
        entrypoints[sid] = lambda payload: {"signal": "hold", "invalidation": "none"}
    shared = adapter.CanonicalStrategy25Adapter(bindings, entrypoints)
    replay = adapter.ReplayContext(
        event_ts="2026-01-01T00:00:00Z",
        point_in_time=True,
        lookahead_zero=False,
        cost_model_bound=True,
        cost_model_id="cost-v1",
    )
    with pytest.raises(adapter.StrategyAdapterError, match="lookahead_zero"):
        shared.dispatch(
            "s00",
            event_id="e1",
            feature_ts="2026-01-01T00:00:00Z",
            payload={},
            replay=replay,
        )


def test_adapter_emits_deterministic_receipt():
    adapter = load_module(
        Path(__file__).parents[1] / "backend/strategy25/canonical_shared_adapter.py",
        "adapter_mod2",
    )
    bindings = {}
    entrypoints = {}
    for i in range(25):
        sid = f"s{i:02d}"
        bindings[sid] = adapter.StrategyBinding(sid, "b" * 40, f"backend/s{i}.py:evaluate")
        entrypoints[sid] = lambda payload: {"signal": "hold", "invalidation": {"reason": "none"}}
    shared = adapter.CanonicalStrategy25Adapter(bindings, entrypoints)
    replay = adapter.ReplayContext(
        event_ts="2026-01-01T00:00:00Z",
        point_in_time=True,
        lookahead_zero=True,
        cost_model_bound=True,
        cost_model_id="cost-v1",
    )
    kwargs = dict(
        strategy_id="s00",
        event_id="e1",
        feature_ts="2026-01-01T00:00:00Z",
        payload={"x": 1},
        replay=replay,
    )
    one = shared.dispatch(**kwargs)
    two = shared.dispatch(**kwargs)
    assert one.receipt_hash == two.receipt_hash
    assert one.to_dict()["strategy_id"] == "s00"
    assert shared.order_authority == "none"
    assert shared.ledger_write_authority == "none"


def test_real_entrypoint_registry_builder_uses_actual_git_tree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    strategies = []
    for i in range(25):
        sid = f"strategy_{i:02d}"
        path = repo / "backend" / "strategies" / f"s{i:02d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"def evaluate_{i:02d}(payload):\n"
            "    return {'signal': 'hold', 'invalidation': 'none'}\n",
            encoding="utf-8",
        )
        strategies.append(
            {
                "strategy_id": sid,
                "implementation_refs": [str(path.relative_to(repo))],
                "source_shas": {},
                "test_refs": [],
            }
        )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    runner = load_module(
        Path(__file__).parents[1] / "tools/r7a3c2_strategy25_minimal_shared_adapter_patch.py",
        "runner_mod",
    )
    registry, blockers = runner.build_binding_registry(
        repo, sha, {"strategies": strategies}, expected_count=25
    )
    assert blockers == []
    assert registry["binding_count"] == 25
    assert len({row["strategy_id"] for row in registry["bindings"]}) == 25
    assert all(":" in row["entrypoint_ref"] for row in registry["bindings"])
    assert all(len(row["source_sha"]) == 40 for row in registry["bindings"])
