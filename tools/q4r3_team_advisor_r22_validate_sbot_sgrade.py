#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def import_r21(path: Path):
    spec = importlib.util.spec_from_file_location("r21", path)
    if not spec or not spec.loader:
        raise RuntimeError("R21_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r21", type=Path, required=True)
    parser.add_argument("--r12", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r21 = load(args.r21)
    r12 = load(args.r12)
    contract = load(args.contract)
    blockers: list[str] = []

    if r21.get("state") != "HOLD" or r21.get("verdict") != "R21_BOT_SGRADE_UPDATE_REQUIRED":
        blockers.append("R21_EXPECTED_HOLD_MISSING")
    if r12.get("state") != "PASS" or r12.get("official_stage") != "R1.2":
        blockers.append("R12_FOUNDATION_NOT_PASS")
    if contract.get("schema") != "q4r3_sbot_sgrade_contract_v1":
        blockers.append("SBOT_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority") or {}
    if authority.get("runtime_binding") is not False or authority.get("execution_authority") != "none":
        blockers.append("SBOT_AUTHORITY_INVALID")
    threshold = contract.get("threshold_policy") or {}
    if threshold.get("embedded_numeric_thresholds_allowed") is not False:
        blockers.append("EMBEDDED_THRESHOLD_POLICY_INVALID")
    if threshold.get("ssot_rule_required") is not True:
        blockers.append("SSOT_RULE_POLICY_INVALID")

    audit_module = import_r21(args.worktree / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py")
    readiness = audit_module.inspect_bot(args.worktree, "SBot")
    if readiness.get("s_grade_ready") is not True:
        blockers.append("SBOT_STATIC_SGRADE_NOT_READY")

    source = (args.worktree / "canonical/bots/sbot.py").read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "MIN_DATA", "metric_sources", "integrity", "liq_buffer_pct", "dd_day_pct",
        "dd_total_pct", "exposure_pct_x", "time_exposure_min", "sl_present",
        "SBOT_SSOT_RULES_MISSING", "SBOT_RULE_INVALID", "SBOT_HARD:SL_MISSING",
    )
    missing_tokens = [token for token in required_tokens if token not in source]
    if missing_tokens:
        blockers.append("SBOT_REQUIRED_LOGIC_MISSING:" + ",".join(missing_tokens))
    forbidden = [token for token in ("create_order(", "place_order(", "cancel_order(", "os.environ", "api_key") if token in source]
    if forbidden:
        blockers.append("SBOT_FORBIDDEN_SURFACE:" + ",".join(forbidden))

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r22_sbot_sgrade_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.2",
        "state": state,
        "verdict": "R22_SBOT_SGRADE_LOCK_PASS" if state == "PASS" else "R22_SBOT_SGRADE_BLOCKED",
        "blockers": blockers,
        "report": {
            "sbot_sgrade_ready": readiness.get("s_grade_ready"),
            "capability_hits": readiness.get("capability_hits"),
            "capability_hit_count": readiness.get("capability_hit_count"),
            "required_capability_count": readiness.get("required_capability_count"),
            "min_data_field_count": len(contract.get("required_min_data") or []),
            "derived_metric_count": len(contract.get("derived_metrics") or []),
            "source_prefixes": (contract.get("source_policy") or {}).get("allowed_prefixes"),
            "embedded_numeric_thresholds": False,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R2.3_BUILD_SGRADE_LBOT",
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "blocker_count": len(blockers),
        "sbot_sgrade_ready": readiness.get("s_grade_ready"),
        "capability_hit_count": readiness.get("capability_hit_count"),
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
