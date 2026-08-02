from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_DATA_B_1M_PENDING_RESCUE_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, prefix: str) -> Any:
    name = f"{prefix}_{os.getpid()}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def service_active(unit: str) -> bool:
    proc = subprocess.run(["systemctl", "is-active", unit], text=True, capture_output=True, check=False)
    return proc.stdout.strip() == "active"


def checkpoint_ids(root: Path) -> list[str]:
    ids: list[str] = []
    for path in sorted(root.glob("*.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                value = json.load(handle)
            strategy_id = str(value.get("strategy_id") or "") if isinstance(value, dict) else ""
            if strategy_id:
                ids.append(strategy_id)
        except Exception:
            continue
    return sorted(set(ids))


def lane_template(engine: Any, file_row: Mapping[str, Any], frame: Any, strategy_id: str, owner_sha: str) -> dict[str, Any]:
    calls = max(0, len(frame) - max(int(engine.WARMUP_BARS) - 1, 0))
    return {
        "strategy_id": strategy_id,
        "owner_sha256": owner_sha,
        "symbol": str(file_row["symbol"]),
        "interval": str(file_row["interval"]),
        "window_id": str(file_row["window_id"]),
        "source_path": file_row["path"],
        "source_sha256": file_row["sha256"],
        "bar_count": len(frame),
        "warmup_bars": min(int(engine.WARMUP_BARS), len(frame)),
        "strategy_call_count": calls,
        "signal_count": 0,
        "valid_entry_count": 0,
        "open_count": 0,
        "close_count": 0,
        "add_count": 0,
        "partial_count": 0,
        "strategy_exit_count": 0,
        "censored_open_at_window_end": 0,
        "error_count": 0,
        "error_samples": [],
        "closed_rows": [],
    }


def build_pending_results(engine: Any, manifest: Mapping[str, Any], registry: Mapping[str, Any], data_root: Path, interval: str, pending: list[str]) -> dict[str, dict[str, Any]]:
    market_files = [
        row for row in manifest.get("files", [])
        if isinstance(row, dict) and row.get("kind") == "market" and row.get("interval") == interval
    ]
    frames: list[tuple[Mapping[str, Any], Any]] = []
    for file_row in sorted(market_files, key=lambda row: (str(row["window_id"]), str(row["symbol"]))):
        frames.append((file_row, engine.frame_from_csv(data_root / str(file_row["path"]))))
    results: dict[str, dict[str, Any]] = {}
    for strategy_id in pending:
        owner = registry[strategy_id]
        owner_sha = str(getattr(owner, "owner_sha256", ""))
        results[strategy_id] = {
            "strategy_id": strategy_id,
            "owner_sha256": owner_sha,
            "lanes": [lane_template(engine, file_row, frame, strategy_id, owner_sha) for file_row, frame in frames],
        }
    return results


def inspect_state(contract: Mapping[str, Any], engine: Any, v2: Any, engine_path: Path, source_root: Path, data_root: Path, output_dir: Path, interval: str) -> dict[str, Any]:
    manifest, _ = engine.validate_data_manifest(data_root, interval)
    producer = engine.import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    fingerprint, fingerprint_inputs = v2.input_fingerprint(engine, engine_path, source_root, data_root, interval, registry)
    progress = load_json(output_dir / "progress.json")
    checkpoint_root = output_dir / "checkpoints"
    completed = checkpoint_ids(checkpoint_root)
    expected = sorted(registry)
    pending = sorted(set(expected) - set(completed))
    required = contract["expected_progress"]
    failures: list[str] = []
    if int(progress.get("completed_units") or 0) != int(required["completed_units"]):
        failures.append("COMPLETED_COUNT_MISMATCH")
    if int(progress.get("total_units") or 0) != int(required["total_units"]):
        failures.append("TOTAL_COUNT_MISMATCH")
    if int(progress.get("error_count") or 0) != int(required["error_count"]):
        failures.append("PROGRESS_ERROR_COUNT_NONZERO")
    if pending != sorted(required["pending_units"]):
        failures.append("PENDING_SET_MISMATCH")
    if progress.get("source_sha") != fingerprint:
        failures.append("INPUT_FINGERPRINT_MISMATCH")
    if len(completed) != int(required["completed_units"]):
        failures.append("CHECKPOINT_COUNT_MISMATCH")
    return {
        "manifest": manifest,
        "registry": registry,
        "fingerprint": fingerprint,
        "fingerprint_inputs": fingerprint_inputs,
        "progress": progress,
        "completed": completed,
        "pending": pending,
        "failures": failures,
    }


def proof_ok(proof: Mapping[str, Any], state: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    required_state = contract["commit_gate"]["proof_receipt_state"]
    if proof.get("state") != required_state:
        failures.append("PROOF_STATE_INVALID")
    if sorted(proof.get("strategy_ids") or []) != state["pending"]:
        failures.append("PROOF_PENDING_SET_MISMATCH")
    if float(proof.get("runtime_hold_parity_pct") or 0.0) != 100.0:
        failures.append("PROOF_PARITY_NOT_100")
    semantic = proof.get("semantic_result") if isinstance(proof.get("semantic_result"), dict) else {}
    for key in ("signal_count", "open_count", "close_count", "error_count"):
        if int(semantic.get(key) or 0) != 0:
            failures.append(f"PROOF_{key.upper()}_NONZERO")
    return failures


def plan_or_stage(args: Any, write_stage: bool) -> dict[str, Any]:
    contract = load_json(args.contract)
    engine = load_module(args.engine_v1, "zel_rescue_engine_v1")
    v2 = load_module(args.engine_v2, "zel_rescue_engine_v2")
    state = inspect_state(contract, engine, v2, args.engine_v1, args.source_root, args.data_root, args.output_dir, args.interval)
    proof = load_json(args.proof)
    failures = list(state["failures"]) + proof_ok(proof, state, contract)
    results: dict[str, dict[str, Any]] = {}
    stage_root = args.stage_dir
    if not failures:
        results = build_pending_results(engine, state["manifest"], state["registry"], args.data_root, args.interval, state["pending"])
        for strategy_id, result in results.items():
            card, rows = engine.aggregate_strategy(result)
            if int(card.get("sample_count") or 0) != 0 or rows:
                failures.append(f"NONEMPTY_AGGREGATE:{strategy_id}")
        if write_stage and not failures:
            stage_root.mkdir(parents=True, exist_ok=True)
            for strategy_id, result in results.items():
                v2.save_checkpoint(v2.checkpoint_path(stage_root, strategy_id), state["fingerprint"], result)
    receipt = {
        "schema_version": "zel.data_b.1m.pending_rescue.plan.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": ("PASS_PENDING_RESCUE_STAGED" if write_stage else "PASS_PENDING_RESCUE_PLAN") if not failures else "HOLD_PENDING_RESCUE_PLAN",
        "mode": "stage" if write_stage else "plan",
        "input_fingerprint": state["fingerprint"],
        "completed_checkpoint_count": len(state["completed"]),
        "completed_units": state["completed"],
        "pending_units": state["pending"],
        "generated_checkpoint_count": len(results) if not failures else 0,
        "stage_dir": str(stage_root),
        "failures": sorted(set(failures)),
        "service_active_observed": service_active(contract["service_unit"]),
        "existing_checkpoints_mutated": False,
        "canonical_strategy_source_mutated": False,
        "engine_source_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    if args.receipt:
        atomic_json(args.receipt, receipt)
    return receipt


def commit(args: Any) -> dict[str, Any]:
    contract = load_json(args.contract)
    if args.commit_token != "COMMIT_EXACT_PENDING_RESCUE_V1":
        raise RuntimeError("COMMIT_TOKEN_INVALID")
    if service_active(contract["service_unit"]):
        raise RuntimeError("ACTIVE_SERVICE_MUST_BE_STOPPED")
    plan = plan_or_stage(args, write_stage=False)
    if not plan["state"].startswith("PASS_"):
        return plan
    active_root = args.output_dir / "checkpoints"
    stage_root = args.stage_dir
    pending = list(plan["pending_units"])
    for strategy_id in pending:
        if not (stage_root / f"{strategy_id}.json.gz").is_file():
            raise RuntimeError(f"STAGED_CHECKPOINT_MISSING:{strategy_id}")
        if (active_root / f"{strategy_id}.json.gz").exists():
            raise RuntimeError(f"ACTIVE_PENDING_CHECKPOINT_ALREADY_EXISTS:{strategy_id}")
    backup_root = args.output_dir / "rescue_backup_v1" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "zel.data_b.1m.pending_rescue.rollback_manifest.v1",
        "generated_at": now_iso(),
        "input_fingerprint": plan["input_fingerprint"],
        "preexisting_checkpoint_hashes": {
            path.name: sha256_path(path) for path in sorted(active_root.glob("*.json.gz"))
        },
        "inserted_checkpoint_ids": pending,
        "progress_sha256_before": sha256_path(args.output_dir / "progress.json"),
        "rollback_action": "remove_inserted_pending_checkpoints_then_restore_progress_from_backup",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    shutil.copy2(args.output_dir / "progress.json", backup_root / "progress.json")
    atomic_json(backup_root / "rollback_manifest.json", manifest)
    inserted: list[str] = []
    try:
        active_root.mkdir(parents=True, exist_ok=True)
        for strategy_id in pending:
            source = stage_root / f"{strategy_id}.json.gz"
            target = active_root / source.name
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(active_root))
            os.close(fd)
            shutil.copy2(source, temp_name)
            os.replace(temp_name, target)
            inserted.append(strategy_id)
    except Exception:
        for strategy_id in inserted:
            (active_root / f"{strategy_id}.json.gz").unlink(missing_ok=True)
        shutil.copy2(backup_root / "progress.json", args.output_dir / "progress.json")
        raise
    receipt = dict(plan)
    receipt.update({
        "schema_version": "zel.data_b.1m.pending_rescue.commit.receipt.v1",
        "state": "PASS_PENDING_RESCUE_CHECKPOINTS_COMMITTED",
        "mode": "commit",
        "inserted_checkpoint_ids": inserted,
        "backup_root": str(backup_root),
        "rollback_manifest_sha256": sha256_path(backup_root / "rollback_manifest.json"),
        "runtime_mutated": True,
        "existing_checkpoints_mutated": False,
        "terminalization_required": True,
        "terminalization_command": "original_v2_engine_with_same_source_data_output_and_workers_1",
    })
    if args.receipt:
        atomic_json(args.receipt, receipt)
    return receipt


def self_test() -> None:
    class Engine:
        WARMUP_BARS = 240
    class Frame:
        def __len__(self) -> int:
            return 302400
    row = lane_template(Engine(), {"symbol":"BTCUSDT","interval":"1m","window_id":"w","path":"x","sha256":"a"}, Frame(), "s", "b")
    assert row["strategy_call_count"] == 302161, row
    assert row["signal_count"] == row["open_count"] == row["close_count"] == 0, row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--engine-v1", type=Path)
    parser.add_argument("--engine-v2", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--interval", default="1m", choices=("1m","15m"))
    parser.add_argument("--mode", choices=("plan","stage","commit"), default="plan")
    parser.add_argument("--commit-token", default="")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (args.contract,args.proof,args.engine_v1,args.engine_v2,args.source_root,args.data_root,args.output_dir,args.stage_dir)
    if any(value is None for value in required):
        parser.error("all contract, proof, engine, source, data, output and stage paths are required")
    args.contract=args.contract.resolve();args.proof=args.proof.resolve();args.engine_v1=args.engine_v1.resolve();args.engine_v2=args.engine_v2.resolve()
    args.source_root=args.source_root.resolve();args.data_root=args.data_root.resolve();args.output_dir=args.output_dir.resolve();args.stage_dir=args.stage_dir.resolve()
    if args.mode == "commit":
        row = commit(args)
    else:
        row = plan_or_stage(args, write_stage=args.mode=="stage")
    print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
