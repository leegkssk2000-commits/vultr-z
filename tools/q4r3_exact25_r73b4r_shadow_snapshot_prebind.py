#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def canonical_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def build(contract: dict[str, Any], parent: dict[str, Any], validation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    blockers: list[str] = []
    if parent.get("state") != "PASS" or parent.get("cleanup_applied") is not True:
        blockers.append("R73B3_STATUS_INVALID")
    if validation.get("state") != "PASS" or validation.get("receipt_verified") is not True:
        blockers.append("R73B3_VALIDATION_INVALID")
    owner = contract.get("future_owner", {})
    epoch = contract.get("epoch", {})
    if owner.get("writer_count") != 1 or owner.get("enabled_now") is not False:
        blockers.append("OWNER_CONTRACT_INVALID")
    if epoch.get("sample_count") != 0 or epoch.get("closed_count") != 0:
        blockers.append("INITIAL_EPOCH_NOT_ZERO")
    snapshot_core = {
        "schema": "q4r3_exact25_shadow_aggregate_snapshot_v1",
        "owner_id": owner.get("owner_id"),
        "planned_unit": owner.get("planned_unit"),
        "writer_count": 1,
        "epoch_id": epoch.get("epoch_id"),
        "state": "PREBIND",
        "sample_count": 0,
        "active_count": 0,
        "closed_count": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "winrate_pct": None,
        "gross_r": 0.0,
        "net_r": 0.0,
        "latest_trace_id": None,
        "runtime_active": False,
        "formal_ledger_bound": False,
        "legacy_metric_import_count": 0,
        "order_authority": "blocked",
        "execution_authority": "none"
    }
    snapshot = dict(snapshot_core, snapshot_sha256=canonical_hash(snapshot_core))
    status = {
        "schema": "q4r3_exact25_r73b4r_shadow_snapshot_prebind_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "owner_count": 1,
        "snapshot_count": 1 if not blockers else 0,
        "sample_count": 0,
        "runtime_active": False,
        "formal_ledger_bound": False,
        "legacy_metric_import_count": 0,
        "mutation_count": 1 if not blockers else 0,
        "next_stage": contract.get("next_stage")
    }
    return snapshot, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--parent-status", type=Path, required=True)
    parser.add_argument("--parent-validation", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    parent = json.loads(args.parent_status.read_text(encoding="utf-8"))
    validation = json.loads(args.parent_validation.read_text(encoding="utf-8"))
    snapshot, status = build(contract, parent, validation)
    if status["state"] == "PASS":
        if args.snapshot.resolve() == Path(contract["forbidden_source"]).resolve():
            status["state"] = "HOLD"
            status["blockers"] = ["FORBIDDEN_FORMAL_LEDGER_TARGET"]
            status["blocker_count"] = 1
            status["snapshot_count"] = 0
            status["mutation_count"] = 0
        else:
            atomic_json(args.snapshot, snapshot)
    atomic_json(args.status, status)
    print(json.dumps(status, sort_keys=True))
    return 0 if status["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
