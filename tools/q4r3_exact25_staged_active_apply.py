from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple

EXPECTED_25: Tuple[str, ...] = (
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "ema_ribbon_scalp",
    "fvg_revert",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "mfi_rsi_div",
    "obv_trend",
    "pivot_reversal",
    "range_fade",
    "rbreaker_like",
    "rsi_swing_fail",
    "scalp_snap",
    "session_bias",
    "squeeze_break",
    "sr_levels",
    "supertrend_pullback",
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "vol_spike_fade",
    "vwap_revert",
)

RECOVERED_TWO = ("ema_ribbon_scalp", "vol_spike_fade")
RESULT_REL = Path("q4r3_exact25_candidate_package_contract_latest.json")
MANIFEST_REL = Path("manifest/q4r3_canonical_strategy_owner_manifest_v1.json")
SOURCE_REL = Path("source/backend/strategies")
ACTIVE_MANIFEST_REL = Path("backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")
APPLY_TOKEN = "EXACT25_STAGED_APPLY"
ROLLBACK_TOKEN = "EXACT25_ROLLBACK"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_python(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def validate_candidate(candidate_root: Path) -> Dict[str, Any]:
    result_path = candidate_root / RESULT_REL
    manifest_path = candidate_root / MANIFEST_REL
    if not result_path.is_file():
        raise RuntimeError(f"CANDIDATE_RESULT_MISSING:{result_path}")
    if not manifest_path.is_file():
        raise RuntimeError(f"CANDIDATE_MANIFEST_MISSING:{manifest_path}")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "status": "PASS_Q4R3_EXACT25_CANDIDATE_PACKAGE_BUILD",
        "verdict": "EXACT25_CANDIDATE_PACKAGE_READY_FOR_STAGED_ACTIVE_APPLY",
        "exact_25": True,
        "all_sources_present": True,
        "recovered_two_present": True,
        "contract_pass_count": 25,
        "contract_gap_count": 0,
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise RuntimeError(f"CANDIDATE_GATE_FAILED:{key}:{result.get(key)!r}!={value!r}")

    entries = manifest.get("strategies") or []
    ids = [entry.get("strategy_id") for entry in entries]
    if manifest.get("strategy_count") != 25 or tuple(sorted(ids)) != tuple(sorted(EXPECTED_25)):
        raise RuntimeError("CANDIDATE_MANIFEST_NOT_EXACT25")
    if manifest.get("dynamic_fallback_allowed") is not False:
        raise RuntimeError("CANDIDATE_DYNAMIC_FALLBACK_NOT_DISABLED")

    recovery = result.get("recovery_decisions") or {}
    for strategy_id in RECOVERED_TWO:
        source = candidate_root / SOURCE_REL / f"{strategy_id}.py"
        if not source.is_file():
            raise RuntimeError(f"RECOVERED_SOURCE_MISSING:{strategy_id}")
        parse_python(source)
        expected_sha = ((recovery.get(strategy_id) or {}).get("candidate_sha256"))
        actual_sha = sha256_file(source)
        if expected_sha != actual_sha:
            raise RuntimeError(f"RECOVERED_SOURCE_SHA_MISMATCH:{strategy_id}:{actual_sha}:{expected_sha}")
    return {"result": result, "manifest": manifest}


def validate_active_23(active_root: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for strategy_id in EXPECTED_25:
        if strategy_id in RECOVERED_TWO:
            continue
        path = active_root / "backend" / "strategies" / f"{strategy_id}.py"
        if not path.is_file():
            raise RuntimeError(f"ACTIVE_CANONICAL_MISSING:{strategy_id}:{path}")
        parse_python(path)
        hashes[strategy_id] = sha256_file(path)
    return hashes


def build_staged_manifest(
    active_root: Path,
    candidate_root: Path,
    candidate_manifest: Mapping[str, Any],
    transaction_id: str,
    candidate_commit: str,
) -> Dict[str, Any]:
    source_entries = {entry["strategy_id"]: dict(entry) for entry in candidate_manifest.get("strategies") or []}
    entries: List[Dict[str, Any]] = []
    for strategy_id in EXPECTED_25:
        if strategy_id in RECOVERED_TWO:
            source_path = candidate_root / SOURCE_REL / f"{strategy_id}.py"
            owner_kind = "canonical_recovered_staged"
        else:
            source_path = active_root / "backend" / "strategies" / f"{strategy_id}.py"
            owner_kind = "canonical_existing_staged"
        base = source_entries.get(strategy_id) or {}
        entries.append(
            {
                "strategy_id": strategy_id,
                "owner_module": f"backend.strategies.{strategy_id}",
                "owner_path": f"backend/strategies/{strategy_id}.py",
                "owner_sha256": sha256_file(source_path),
                "owner_kind": owner_kind,
                "enabled_for_shadow": False,
                "enabled_for_paper": False,
                "enabled_for_live": False,
                "entry_contract_version": base.get("entry_contract_version", "q4r3.strategy.signal.v1"),
                "risk_writer_contract_version": base.get("risk_writer_contract_version", "q4r3.forward_r.writer.v1"),
                "source_decision_refs": base.get("source_decision_refs") or [],
                "contract_pass": True,
                "stage_status": "STAGED_NOT_BOUND",
            }
        )
    return {
        "schema": "q4r3_canonical_strategy_owner_manifest_v1",
        "created_at": utc_now(),
        "transaction_id": transaction_id,
        "candidate_commit": candidate_commit,
        "authority_rule": "ONE_OWNER_PER_STRATEGY_EXACTLY_25_NO_DYNAMIC_FALLBACK",
        "strategy_count": 25,
        "dynamic_fallback_allowed": False,
        "runtime_binding_status": "NOT_BOUND_STAGED_ACTIVE",
        "activation_allowed": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "strategies": entries,
    }


def backup_target(active_root: Path, backup_dir: Path, relative: Path) -> Dict[str, Any]:
    source = active_root / relative
    metadata: Dict[str, Any] = {
        "relative_path": str(relative),
        "existed": source.is_file(),
        "sha256": sha256_file(source) if source.is_file() else None,
        "mode": oct(source.stat().st_mode & 0o777) if source.is_file() else None,
    }
    if source.is_file():
        destination = backup_dir / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return metadata


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_handle:
            shutil.copyfileobj(input_handle, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_manifest(payload: Mapping[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_from_backup(active_root: Path, backup_dir: Path, metadata: Mapping[str, Any]) -> None:
    for item in metadata.get("targets") or []:
        relative = Path(item["relative_path"])
        destination = active_root / relative
        if item.get("existed"):
            source = backup_dir / "files" / relative
            if not source.is_file():
                raise RuntimeError(f"ROLLBACK_BACKUP_FILE_MISSING:{source}")
            atomic_copy(source, destination)
            if item.get("mode"):
                os.chmod(destination, int(str(item["mode"]), 8))
        else:
            destination.unlink(missing_ok=True)


def verify_active_apply(active_root: Path, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    entries = manifest.get("strategies") or []
    ids = [entry.get("strategy_id") for entry in entries]
    if len(entries) != 25 or tuple(sorted(ids)) != tuple(sorted(EXPECTED_25)):
        raise RuntimeError("POST_APPLY_MANIFEST_NOT_EXACT25")
    if manifest.get("runtime_binding_status") != "NOT_BOUND_STAGED_ACTIVE":
        raise RuntimeError("POST_APPLY_BINDING_STATUS_UNSAFE")
    if manifest.get("activation_allowed") is not False:
        raise RuntimeError("POST_APPLY_ACTIVATION_UNSAFE")
    for entry in entries:
        if any(entry.get(key) is not False for key in ("enabled_for_shadow", "enabled_for_paper", "enabled_for_live")):
            raise RuntimeError(f"POST_APPLY_ENABLE_FLAG_UNSAFE:{entry.get('strategy_id')}")
        path = active_root / entry["owner_path"]
        if not path.is_file():
            raise RuntimeError(f"POST_APPLY_SOURCE_MISSING:{entry.get('strategy_id')}")
        parse_python(path)
        actual_sha = sha256_file(path)
        if actual_sha != entry.get("owner_sha256"):
            raise RuntimeError(f"POST_APPLY_SHA_MISMATCH:{entry.get('strategy_id')}")
    return {"strategy_count": 25, "all_hashes_match": True, "all_execution_flags_false": True}


@contextmanager
def exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def apply_transaction(
    active_root: Path,
    candidate_root: Path,
    runtime_root: Path,
    publish_result: Path,
    candidate_commit: str,
    fail_after: int = 0,
) -> Dict[str, Any]:
    if os.environ.get("Q4R3_ALLOW_ACTIVE_APPLY") != APPLY_TOKEN:
        raise RuntimeError("ACTIVE_APPLY_TOKEN_MISSING")
    candidate = validate_candidate(candidate_root)
    active_23_hashes = validate_active_23(active_root)
    transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = runtime_root / "q4r3_exact25_apply_backups" / transaction_id
    targets = [
        Path("backend/strategies/ema_ribbon_scalp.py"),
        Path("backend/strategies/vol_spike_fade.py"),
        ACTIVE_MANIFEST_REL,
    ]
    backup_metadata = {
        "schema": "q4r3_exact25_apply_backup_v1",
        "transaction_id": transaction_id,
        "created_at": utc_now(),
        "active_root": str(active_root),
        "candidate_root": str(candidate_root),
        "candidate_commit": candidate_commit,
        "targets": [backup_target(active_root, backup_dir, relative) for relative in targets],
    }
    atomic_json(backup_dir / "backup_manifest.json", backup_metadata)
    staged_manifest = build_staged_manifest(
        active_root,
        candidate_root,
        candidate["manifest"],
        transaction_id,
        candidate_commit,
    )
    plan = {
        "schema": "q4r3_exact25_staged_apply_plan_v1",
        "transaction_id": transaction_id,
        "created_at": utc_now(),
        "targets": [str(path) for path in targets],
        "active_23_hashes": active_23_hashes,
        "candidate_two_hashes": {
            strategy_id: sha256_file(candidate_root / SOURCE_REL / f"{strategy_id}.py")
            for strategy_id in RECOVERED_TWO
        },
        "manifest_runtime_binding_status": staged_manifest["runtime_binding_status"],
        "activation_allowed": False,
        "rollback_dir": str(backup_dir),
    }
    atomic_json(runtime_root / "q4r3_exact25_staged_apply_plan_latest.json", plan)

    applied_steps = 0
    try:
        for strategy_id in RECOVERED_TWO:
            atomic_copy(
                candidate_root / SOURCE_REL / f"{strategy_id}.py",
                active_root / "backend" / "strategies" / f"{strategy_id}.py",
            )
            applied_steps += 1
            if fail_after and applied_steps >= fail_after:
                raise RuntimeError(f"INJECTED_FAILURE_AFTER_STEP:{applied_steps}")
        atomic_write_manifest(staged_manifest, active_root / ACTIVE_MANIFEST_REL)
        applied_steps += 1
        if fail_after and applied_steps >= fail_after:
            raise RuntimeError(f"INJECTED_FAILURE_AFTER_STEP:{applied_steps}")
        verification = verify_active_apply(active_root, staged_manifest)
    except Exception:
        restore_from_backup(active_root, backup_dir, backup_metadata)
        raise

    result: Dict[str, Any] = {
        "schema": "q4r3_exact25_staged_active_apply_v1",
        "status": "PASS_Q4R3_EXACT25_STAGED_ACTIVE_APPLY",
        "verdict": "TWO_CANONICALS_AND_EXACT25_MANIFEST_STAGED_NOT_BOUND",
        "action": "HOLD",
        "next_action": "RUN_ACTIVE_RUNTIME_IMPORT_SMOKE_THEN_BIND_SHADOW_ONLY",
        "created_at": utc_now(),
        "transaction_id": transaction_id,
        "candidate_commit": candidate_commit,
        "applied_targets": [str(path) for path in targets],
        "applied_file_count": len(targets),
        "backup_dir": str(backup_dir),
        "rollback_available": True,
        "rollback_command": (
            f"Q4R3_ALLOW_ROLLBACK={ROLLBACK_TOKEN} python3 tools/q4r3_exact25_staged_active_apply.py "
            f"--active-root {active_root} --runtime-root {runtime_root} --rollback-backup {backup_dir}"
        ),
        "verification": verification,
        "runtime_binding_status": "NOT_BOUND_STAGED_ACTIVE",
        "activation_allowed": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
        "production_strategy_modified": True,
        "registry_manifest_staged": True,
        "runtime_registry_bound": False,
        "persistent_forward_r_watcher_modified": False,
    }
    runtime_result = runtime_root / "q4r3_exact25_staged_active_apply_latest.json"
    atomic_json(runtime_result, result)
    atomic_json(publish_result, result)
    return result


def rollback_transaction(active_root: Path, runtime_root: Path, backup_dir: Path) -> Dict[str, Any]:
    if os.environ.get("Q4R3_ALLOW_ROLLBACK") != ROLLBACK_TOKEN:
        raise RuntimeError("ROLLBACK_TOKEN_MISSING")
    metadata_path = backup_dir / "backup_manifest.json"
    if not metadata_path.is_file():
        raise RuntimeError(f"ROLLBACK_METADATA_MISSING:{metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    restore_from_backup(active_root, backup_dir, metadata)
    result = {
        "schema": "q4r3_exact25_staged_active_rollback_v1",
        "status": "PASS_Q4R3_EXACT25_STAGED_ACTIVE_ROLLBACK",
        "verdict": "PRE_APPLY_STATE_RESTORED",
        "action": "HOLD",
        "created_at": utc_now(),
        "transaction_id": metadata.get("transaction_id"),
        "backup_dir": str(backup_dir),
        "order_authority": "blocked",
        "execution_authority": "none",
        "persistent_forward_r_watcher_modified": False,
    }
    atomic_json(runtime_root / "q4r3_exact25_staged_active_rollback_latest.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--publish-result", type=Path)
    parser.add_argument("--candidate-commit", default="unknown")
    parser.add_argument("--rollback-backup", type=Path)
    args = parser.parse_args()

    active_root = args.active_root.resolve()
    runtime_root = args.runtime_root.resolve()
    lock_path = runtime_root / "q4r3_exact25_staged_active_apply.lock"
    with exclusive_lock(lock_path):
        if args.rollback_backup:
            result = rollback_transaction(active_root, runtime_root, args.rollback_backup.resolve())
        else:
            if args.candidate_root is None or args.publish_result is None:
                parser.error("--candidate-root and --publish-result are required for apply")
            result = apply_transaction(
                active_root=active_root,
                candidate_root=args.candidate_root.resolve(),
                runtime_root=runtime_root,
                publish_result=args.publish_result.resolve(),
                candidate_commit=args.candidate_commit,
            )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
