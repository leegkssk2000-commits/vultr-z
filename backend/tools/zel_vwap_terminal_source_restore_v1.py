from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_SHA = "52d2a4454311a604edcb9d74596dc65d092c84267e5fc439b794becd5432e338"
DRIFT_SHA = "7f48c77c82d266165eb5c790557c9b6497d3ddd3d8ccb84c719a39be5d84ac67"
VERSION = "ZEL_VWAP_TERMINAL_SOURCE_RESTORE_V1"
SCHEMA = "zel.vwap_terminal_source_restore.receipt.v1"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("zel_vwap_restore_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ENGINE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".restore.", dir=str(destination.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(source, temp)
        os.chmod(temp, destination.stat().st_mode & 0o777)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def run(active: Path, expected: Path, backup_root: Path, engine_path: Path, source_root: Path, data_root: Path) -> dict[str, Any]:
    before_sha = sha256_path(active)
    expected_sha = sha256_path(expected)
    if before_sha != DRIFT_SHA:
        raise RuntimeError(f"ACTIVE_PRECONDITION_SHA_MISMATCH:{before_sha}")
    if expected_sha != EXPECTED_SHA:
        raise RuntimeError(f"EXPECTED_SOURCE_SHA_MISMATCH:{expected_sha}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    rollback_path = backup_dir / active.name
    shutil.copy2(active, rollback_path)
    receipt_path = backup_dir / "restore_receipt.json"
    rolled_back = False
    try:
        atomic_copy(expected, active)
        after_sha = sha256_path(active)
        if after_sha != EXPECTED_SHA:
            raise RuntimeError(f"POST_RESTORE_SHA_MISMATCH:{after_sha}")
        engine = load_engine(engine_path)
        engine.init_worker(str(source_root), str(data_root), "1m")
        registry = engine._WORKER_REGISTRY
        if not isinstance(registry, dict) or len(registry) != 25:
            raise RuntimeError("REGISTRY_COUNT_NOT_25")
        owner = registry.get("vwap_revert")
        owner_sha = str(getattr(owner, "owner_sha256", ""))
        if owner_sha != EXPECTED_SHA:
            raise RuntimeError(f"REGISTRY_VWAP_OWNER_SHA_MISMATCH:{owner_sha}")
        receipt = {
            "schema_version": SCHEMA,
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": "PASS_VWAP_TERMINAL_SOURCE_RESTORED",
            "strategy_id": "vwap_revert",
            "active_path": str(active),
            "expected_source_path": str(expected),
            "rollback_path": str(rollback_path),
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "expected_sha256": EXPECTED_SHA,
            "registry_count": len(registry),
            "registry_owner_sha256": owner_sha,
            "rollback_ready": True,
            "rolled_back": False,
            "source_change_type": "ROLLBACK_TO_TERMINAL_AND_MANIFEST_PIN",
            "new_strategy_epoch_created": False,
            "formal_ledger_mutated": False,
            "runtime_registry_mutated": False,
            "shadow_started": False,
            "paper_started": False,
            "live_started": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
            "next": "RUN_EXACT25_SOURCE_OWNER_AUDIT_AND_SELECTED_INDICATOR_SCREEN",
        }
    except Exception:
        atomic_copy(rollback_path, active)
        rolled_back = True
        if sha256_path(active) != before_sha:
            raise RuntimeError("ROLLBACK_SHA_MISMATCH")
        raise
    finally:
        if rolled_back:
            failure = {
                "schema_version": SCHEMA,
                "version": VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "state": "ROLLBACK_VWAP_RESTORE_FAILED",
                "strategy_id": "vwap_revert",
                "before_sha256": before_sha,
                "restored_sha256": sha256_path(active),
                "rollback_path": str(rollback_path),
                "rolled_back": True,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "action": "rollback",
            }
            failure["receipt_sha256"] = stable_sha(failure)
            receipt_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt_sha256"] = stable_sha(receipt)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    receipt = run(args.active.resolve(), args.expected.resolve(), args.backup_root.resolve(), args.engine.resolve(), args.source_root.resolve(), args.data_root.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
