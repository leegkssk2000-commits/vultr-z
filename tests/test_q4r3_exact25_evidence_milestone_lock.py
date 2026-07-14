from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("evidence_lock", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lock = load_module(ROOT / "tools/q4r3_exact25_evidence_milestone_lock.py")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def make_args(tmp_path: Path, rows: list[dict]) -> argparse.Namespace:
    root = tmp_path / "root"
    strategy_root = root / "backend/strategies"
    strategy_root.mkdir(parents=True)
    (strategy_root / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    ledger = root / "runtime/formal.jsonl"
    manifest = root / "backend/config/manifest.json"
    producer = root / "runtime/producer.json"
    writer = root / "runtime/writer.json"
    ssot = root / "backend/config/lock_ssot.json"
    write_jsonl(ledger, rows)
    write_json(manifest, {"strategies": [{"strategy_id": "alpha"}, {"strategy_id": "beta"}]})
    write_json(producer, {"state": "RUNNING", "paper_enabled": False, "live_enabled": False, "order_enabled": False})
    write_json(writer, {"state": "RUNNING", "paper_enabled": False, "live_enabled": False, "order_enabled": False})
    write_json(ssot, {
        "expected_epoch": "EXACT25_EDGE_V1",
        "expected_strategy_count": 2,
        "milestones": [20, 100, 200, 300],
        "per_strategy_preview_min": 30,
        "per_strategy_final_min": 50,
        "daily_snapshot_enabled": True,
        "protected_strategy_roots": ["backend/strategies"],
        "required_safe_flags": {"paper_enabled": False, "live_enabled": False, "order_enabled": False},
    })
    out = root / "runtime/out"
    return argparse.Namespace(
        root=root,
        ledger=ledger,
        manifest=manifest,
        producer_status=producer,
        writer_status=writer,
        ssot=ssot,
        baseline=out / "protected_surface_baseline.json",
        snapshot_dir=out / "snapshots",
        evidence_latest=out / "evidence_latest.json",
        gate_latest=out / "gate_latest.json",
        status=out / "status_latest.json",
    )


def rows(count: int) -> list[dict]:
    return [
        {
            "event_id": f"event-{index}",
            "strategy_id": "alpha" if index % 2 == 0 else "beta",
            "epoch_id": "EXACT25_EDGE_V1",
        }
        for index in range(count)
    ]


def test_creates_immutable_20c_snapshot_and_keeps_mutation_locked(tmp_path: Path) -> None:
    args = make_args(tmp_path, rows(20))
    assert lock.run(args) == 0
    gate = json.loads(args.gate_latest.read_text(encoding="utf-8"))
    status = json.loads(args.status.read_text(encoding="utf-8"))
    assert gate["integrity_checkpoint_20_due"] is True
    assert gate["strategy_mutation_allowed"] is False
    assert gate["repair_fork_creation_allowed"] is False
    assert status["state"] == "CLEAR"
    pointers = list(args.snapshot_dir.glob("milestone_0020_latest.json"))
    assert len(pointers) == 1


def test_strategy_surface_drift_is_c_violation(tmp_path: Path) -> None:
    args = make_args(tmp_path, rows(5))
    assert lock.run(args) == 0
    strategy = args.root / "backend/strategies/alpha.py"
    strategy.write_text("VALUE = 2\n", encoding="utf-8")
    assert lock.run(args) == 0
    status = json.loads(args.status.read_text(encoding="utf-8"))
    codes = {item["code"] for item in status["issues"]}
    assert "PROTECTED_SURFACE_DRIFT" in codes
    assert status["violation_severity"] == "C"


def test_300c_still_requires_per_strategy_samples(tmp_path: Path) -> None:
    all_rows = [{"event_id": f"e-{index}", "strategy_id": "alpha"} for index in range(300)]
    args = make_args(tmp_path, all_rows)
    assert lock.run(args) == 0
    gate = json.loads(args.gate_latest.read_text(encoding="utf-8"))
    assert gate["freeze_checkpoint_300_due"] is True
    assert gate["preview_sample_ready"] is False
    assert gate["repair_fork_creation_allowed"] is False
    assert "beta" in gate["insufficient_preview_strategies"]
