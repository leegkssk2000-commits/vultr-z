from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

EXPECTED_PRIMARY_WRITER = "tools/q4r3_vwap_mfe_mae_capture_sidecar.py"
EXPECTED_PRIMARY_WRITER_SHA = "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50"
EXPECTED_SECONDARY_WRITER = "tools/q4r3_sr70_accum_sidecar_and_replay_probe.py"
EXPECTED_SECONDARY_WRITER_SHA = "d654ba43edc1a49b985a65f4ac7e79c67a1b62c03602631eb0a2bd7eb6b51b35"
TARGET_RELATIVE_PATHS = (
    "backend/engine/q4r3_exact25_shadow_manifest_loader.py",
    "backend/config/q4r3_exact25_shadow_binding_v1.json",
    "tools/q4r3_exact25_edge_v1_shadow_sidecar.py",
    "runtime/exact25_edge_v1/epoch_latest.json",
    "runtime/exact25_edge_v1/dry_run_latest.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    if mode is not None:
        temporary.chmod(mode)
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_bytes(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def verify_manifest(root: Path) -> Dict[str, Any]:
    path = root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    payload = load_object(path)
    if payload.get("schema") != "q4r3_canonical_strategy_owner_manifest_v1":
        raise ValueError("MANIFEST_SCHEMA_MISMATCH")
    if payload.get("authority_rule") != "ONE_OWNER_PER_STRATEGY_EXACTLY_25_NO_DYNAMIC_FALLBACK":
        raise ValueError("MANIFEST_AUTHORITY_RULE_MISMATCH")
    if payload.get("dynamic_fallback_allowed") is not False:
        raise ValueError("MANIFEST_DYNAMIC_FALLBACK_FORBIDDEN")
    entries = payload.get("strategies")
    if not isinstance(entries, list) or len(entries) != 25:
        raise ValueError("MANIFEST_EXACT25_COUNT_MISMATCH")
    ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("MANIFEST_ENTRY_OBJECT_REQUIRED")
        strategy_id = str(entry.get("strategy_id") or "")
        ids.append(strategy_id)
        owner = root / str(entry.get("owner_path") or "")
        if not owner.is_file():
            raise FileNotFoundError(f"OWNER_MISSING:{strategy_id}:{owner}")
        if sha256(owner) != str(entry.get("owner_sha256") or ""):
            raise ValueError(f"OWNER_SHA_MISMATCH:{strategy_id}")
        if entry.get("contract_pass") is not True:
            raise ValueError(f"OWNER_CONTRACT_NOT_PASSED:{strategy_id}")
        if entry.get("enabled_for_paper") is not False or entry.get("enabled_for_live") is not False:
            raise ValueError(f"UNSAFE_MANIFEST_FLAG:{strategy_id}")
    if len(set(ids)) != 25 or any(not item for item in ids):
        raise ValueError("MANIFEST_UNIQUE25_MISMATCH")
    return payload


def verify_surface_audit(worktree: Path) -> Dict[str, Any]:
    path = worktree / "runtime_results/q4r3/exact25_shadow_binding_surface_audit/q4r3_exact25_shadow_binding_surface_audit_latest.json"
    payload = load_object(path)
    if payload.get("status") != "PASS_Q4R3_EXACT25_SHADOW_BINDING_SURFACE_AUDIT":
        raise ValueError("SURFACE_AUDIT_STATUS_NOT_PASS")
    if payload.get("verdict") != "EXACT25_SHADOW_BINDING_SURFACE_READY":
        raise ValueError("SURFACE_AUDIT_NOT_READY")
    if payload.get("manifest_gate") is not True or payload.get("gaps") not in ([], None):
        raise ValueError("SURFACE_AUDIT_GAPS_REMAIN")
    surfaces = payload.get("source_surfaces") or {}
    open_strong = [item for item in surfaces.get("open_writer", []) if item.get("strong")]
    close_strong = [item for item in surfaces.get("close_r_writer", []) if item.get("strong")]
    if [item.get("path") for item in open_strong] != [EXPECTED_PRIMARY_WRITER]:
        raise ValueError("OPEN_WRITER_AUTHORITY_CHANGED")
    close_paths = {str(item.get("path")) for item in close_strong}
    if close_paths != {EXPECTED_PRIMARY_WRITER, EXPECTED_SECONDARY_WRITER}:
        raise ValueError("CLOSE_WRITER_CANDIDATES_CHANGED")
    return payload


def verify_writer_files(root: Path) -> Dict[str, str]:
    primary = root / EXPECTED_PRIMARY_WRITER
    secondary = root / EXPECTED_SECONDARY_WRITER
    if not primary.is_file() or sha256(primary) != EXPECTED_PRIMARY_WRITER_SHA:
        raise ValueError("PRIMARY_LIFECYCLE_WRITER_SHA_MISMATCH")
    if not secondary.is_file() or sha256(secondary) != EXPECTED_SECONDARY_WRITER_SHA:
        raise ValueError("SECONDARY_CLOSE_WRITER_SHA_MISMATCH")
    return {
        "authoritative_lifecycle_writer": EXPECTED_PRIMARY_WRITER,
        "authoritative_lifecycle_writer_sha256": EXPECTED_PRIMARY_WRITER_SHA,
        "secondary_close_writer": EXPECTED_SECONDARY_WRITER,
        "secondary_close_writer_sha256": EXPECTED_SECONDARY_WRITER_SHA,
        "secondary_close_writer_mode": "OBSERVER_ONLY_NOT_BOUND",
    }


def service_state(unit: str) -> Dict[str, Any]:
    result = subprocess.run(
        ["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    values: Dict[str, Any] = {"unit": unit, "returncode": result.returncode}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = int(value) if key == "MainPID" and value.isdigit() else value
    return values


def make_backup(root: Path, backup_dir: Path, paths: Iterable[str]) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {"root": str(root), "targets": {}}
    files_dir = backup_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    for relative in paths:
        target = root / relative
        record: Dict[str, Any] = {"relative_path": relative, "existed": target.exists()}
        if target.exists():
            backup = files_dir / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            record["sha256"] = sha256(target)
            record["backup_path"] = str(backup)
        manifest["targets"][relative] = record
    atomic_json(backup_dir / "backup_manifest.json", manifest)
    return manifest


def restore_backup(root: Path, backup_dir: Path) -> None:
    manifest = load_object(backup_dir / "backup_manifest.json")
    for relative, record in (manifest.get("targets") or {}).items():
        target = root / relative
        if record.get("existed"):
            backup = Path(str(record["backup_path"]))
            atomic_bytes(target, backup.read_bytes(), backup.stat().st_mode & 0o777)
        elif target.exists():
            target.unlink()


def write_standalone_rollback(backup_dir: Path) -> None:
    script = '''from __future__ import annotations
import json
import os
import shutil
import sys
from pathlib import Path

if os.environ.get("Q4R3_ALLOW_ROLLBACK") != "EXACT25_SHADOW_BINDING_ROLLBACK":
    raise SystemExit("ROLLBACK_TOKEN_REQUIRED")
backup_dir = Path(__file__).resolve().parent
manifest = json.loads((backup_dir / "backup_manifest.json").read_text(encoding="utf-8"))
root = Path(manifest["root"])
for relative, record in manifest["targets"].items():
    target = root / relative
    if record["existed"]:
        source = Path(record["backup_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".rollback.tmp")
        shutil.copy2(source, temporary)
        temporary.replace(target)
    elif target.exists():
        target.unlink()
print("Q4R3_EXACT25_SHADOW_BINDING_ROLLBACK_DONE")
'''
    atomic_bytes(backup_dir / "rollback.py", script.encode("utf-8"), 0o700)


def build_binding(manifest: Mapping[str, Any], writer: Mapping[str, str], transaction_id: str) -> Dict[str, Any]:
    return {
        "schema": "q4r3_exact25_shadow_binding_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transaction_id": transaction_id,
        "epoch_id": "EXACT25_EDGE_V1",
        "preexisting_data_label": "PRE_EXACT25",
        "forward_rows_only": True,
        "historical_r_backfill_allowed": False,
        "dynamic_fallback_allowed": False,
        "strategy_count": 25,
        "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "shadow_enabled": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "write_enabled": False,
        "canary_enabled": False,
        "binding_state": "SHADOW_BOUND_DRYRUN_ONLY",
        **writer,
        "required_measurement_fields": [
            "strategy_id", "owner_sha256", "symbol", "side", "regime", "entry_ts", "exit_ts",
            "entry_price", "stop_price", "initial_risk_usdt", "realized_pnl_usdt", "realized_R",
            "fee", "slippage", "latency_ms", "MFE_R", "MAE_R", "time_exposure_min", "epoch_id",
        ],
    }


def apply(root: Path, worktree: Path, result_path: Path) -> Dict[str, Any]:
    root = root.resolve()
    worktree = worktree.resolve()
    manifest = verify_manifest(root)
    audit = verify_surface_audit(worktree)
    writer = verify_writer_files(root)
    watcher_before = service_state("q4r3-forward-r-persistent-write-watch.service")
    if watcher_before.get("ActiveState") != "active" or watcher_before.get("SubState") != "running":
        raise ValueError("FORWARD_R_WATCHER_NOT_ACTIVE")

    transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = root / "runtime/q4r3_exact25_shadow_binding_backups" / transaction_id
    make_backup(root, backup_dir, TARGET_RELATIVE_PATHS)
    write_standalone_rollback(backup_dir)

    try:
        artifact_root = worktree / "artifacts/q4r3_exact25_shadow_binding"
        loader_source = artifact_root / "backend/engine/q4r3_exact25_shadow_manifest_loader.py"
        sidecar_source = artifact_root / "tools/q4r3_exact25_edge_v1_shadow_sidecar.py"
        if not loader_source.is_file() or not sidecar_source.is_file():
            raise FileNotFoundError("BINDING_ARTIFACT_MISSING")

        atomic_bytes(root / "backend/engine/q4r3_exact25_shadow_manifest_loader.py", loader_source.read_bytes(), 0o644)
        atomic_bytes(root / "tools/q4r3_exact25_edge_v1_shadow_sidecar.py", sidecar_source.read_bytes(), 0o755)
        binding = build_binding(manifest, writer, transaction_id)
        atomic_json(root / "backend/config/q4r3_exact25_shadow_binding_v1.json", binding)
        epoch = {
            "schema": "q4r3_exact25_edge_epoch_v1",
            "epoch_id": "EXACT25_EDGE_V1",
            "state": "CREATED_DRYRUN_ONLY_NOT_STARTED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "preexisting_data_label": "PRE_EXACT25",
            "forward_rows_only": True,
            "historical_r_backfill_allowed": False,
            "accepted_row_count": 0,
            "rejected_row_count": 0,
            "canary_enabled": False,
            "write_enabled": False,
        }
        atomic_json(root / "runtime/exact25_edge_v1/epoch_latest.json", epoch)

        dry_run_path = root / "runtime/exact25_edge_v1/dry_run_latest.json"
        completed = subprocess.run(
            [str(root / ".venv/bin/python"), str(root / "tools/q4r3_exact25_edge_v1_shadow_sidecar.py"), "--dry-run", "--output", str(dry_run_path)],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"SIDECAR_DRY_RUN_FAILED:{completed.returncode}:{completed.stderr[-500:]}")
        dry_run = load_object(dry_run_path)
        if dry_run.get("pass_count") != 25 or dry_run.get("gap_count") != 0:
            raise ValueError("SIDECAR_DRY_RUN_NOT_25_OF_25")

        watcher_after = service_state("q4r3-forward-r-persistent-write-watch.service")
        if watcher_after.get("MainPID") != watcher_before.get("MainPID"):
            raise ValueError("FORWARD_R_WATCHER_PID_CHANGED")
        if watcher_after.get("ActiveState") != "active" or watcher_after.get("SubState") != "running":
            raise ValueError("FORWARD_R_WATCHER_STATE_CHANGED")

        result = {
            "schema": "q4r3_exact25_shadow_only_sidecar_staged_bind_v1",
            "status": "PASS_Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_STAGED_BIND",
            "verdict": "EXACT25_SHADOW_SIDECAR_BOUND_DRYRUN_PASS_CANARY_NOT_STARTED",
            "action": "HOLD",
            "next_action": "RUN_SHORT_EXACT25_EDGE_V1_SHADOW_CANARY_WITH_WRITE_DUPLICATE_AND_LINEAGE_GUARDS",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "transaction_id": transaction_id,
            "backup_dir": str(backup_dir),
            "rollback_available": True,
            "rollback_command": f"Q4R3_ALLOW_ROLLBACK=EXACT25_SHADOW_BINDING_ROLLBACK {root / '.venv/bin/python'} {backup_dir / 'rollback.py'}",
            "surface_audit_commit_input": audit.get("created_at"),
            "strategy_count": 25,
            "dry_run_pass_count": 25,
            "dry_run_gap_count": 0,
            "epoch_id": "EXACT25_EDGE_V1",
            "epoch_state": "CREATED_DRYRUN_ONLY_NOT_STARTED",
            "preexisting_data_label": "PRE_EXACT25",
            "shadow_sidecar_bound": True,
            "core_runtime_registry_bound": False,
            "shadow_enabled": True,
            "write_enabled": False,
            "canary_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
            "authoritative_writer": writer,
            "watcher_before": watcher_before,
            "watcher_after": watcher_after,
            "production_strategy_modified": False,
            "owner_manifest_modified": False,
            "persistent_forward_r_watcher_modified": False,
            "applied_targets": list(TARGET_RELATIVE_PATHS[:4]),
        }
        atomic_json(result_path, result)
        return result
    except Exception:
        restore_backup(root, backup_dir)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--apply-token", required=True)
    args = parser.parse_args()
    if args.apply_token != "Q4R3_EXACT25_SHADOW_BIND_DRYRUN_ONLY":
        raise SystemExit("APPLY_TOKEN_MISMATCH")
    result = apply(args.active_root, args.worktree, args.result)
    print(json.dumps({key: result[key] for key in ("status", "verdict", "strategy_count", "dry_run_pass_count", "epoch_state", "next_action")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
