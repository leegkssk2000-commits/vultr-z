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
    parser.add_argument("--r23", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r23 = load(args.r23)
    contract = load(args.contract)
    blockers: list[str] = []

    if r23.get("state") != "PASS" or r23.get("official_stage") != "R2.3":
        blockers.append("R23_LBOT_FOUNDATION_NOT_PASS")
    if contract.get("schema") != "q4r3_mbot_sgrade_contract_v1":
        blockers.append("MBOT_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority") or {}
    if authority.get("runtime_binding") is not False or authority.get("execution_authority") != "none":
        blockers.append("MBOT_AUTHORITY_INVALID")
    decision = contract.get("decision_policy") or {}
    if decision.get("numeric_thresholds_in_code") is not False:
        blockers.append("EMBEDDED_THRESHOLD_POLICY_INVALID")
    if decision.get("ssot_rule_required") is not True:
        blockers.append("SSOT_RULE_POLICY_INVALID")
    if decision.get("helper_is_non_voting") is not True:
        blockers.append("HELPER_AUTHORITY_POLICY_INVALID")
    if decision.get("veto_allowed") is not False:
        blockers.append("MBOT_VETO_POLICY_INVALID")

    audit_module = import_r21(args.worktree / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py")
    readiness = audit_module.inspect_bot(args.worktree, "MBot")
    if readiness.get("s_grade_ready") is not True:
        blockers.append("MBOT_STATIC_SGRADE_NOT_READY")

    source = (args.worktree / "canonical/bots/mbot.py").read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "CAPABILITY_TAGS", "SNAPSHOT_FIELDS", "method_fit_score", "range_quality_score",
        "timing_quality_score", "retest_quality_score", "helper_need_score", "method_age_min",
        "MBOT_SSOT_RULES_MISSING", "MBOT_RULE_INVALID", "MBOT_UNRESOLVED_METHOD_FIT",
        "MBOT_UNRESOLVED_CONFLICT_FLAGS", "MBOT_UNRESOLVED_HELPER_FLAGS", "route_change",
    )
    missing_tokens = [token for token in required_tokens if token not in source]
    if missing_tokens:
        blockers.append("MBOT_REQUIRED_LOGIC_MISSING:" + ",".join(missing_tokens))
    forbidden = [
        token for token in ("create_order(", "place_order(", "cancel_order(", "os.environ", "api_key")
        if token in source
    ]
    if forbidden:
        blockers.append("MBOT_FORBIDDEN_SURFACE:" + ",".join(forbidden))

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r24_mbot_sgrade_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.4",
        "state": state,
        "verdict": "R24_MBOT_SGRADE_LOCK_PASS" if state == "PASS" else "R24_MBOT_SGRADE_BLOCKED",
        "blockers": blockers,
        "report": {
            "mbot_sgrade_ready": readiness.get("s_grade_ready"),
            "capability_hits": readiness.get("capability_hits"),
            "capability_hit_count": readiness.get("capability_hit_count"),
            "required_capability_count": readiness.get("required_capability_count"),
            "required_snapshot_count": len(contract.get("required_snapshot") or []),
            "derived_metric_count": len(contract.get("derived_metrics") or []),
            "source_prefixes": (contract.get("source_policy") or {}).get("allowed_prefixes"),
            "embedded_numeric_trading_thresholds": False,
            "helper_non_voting": True,
            "veto_allowed": False,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R2.5_BUILD_SGRADE_OBOT",
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
        "mbot_sgrade_ready": readiness.get("s_grade_ready"),
        "capability_hit_count": readiness.get("capability_hit_count"),
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
