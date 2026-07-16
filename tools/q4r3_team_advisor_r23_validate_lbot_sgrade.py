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


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"IMPORT_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r21", type=Path, required=True)
    parser.add_argument("--r22", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r21 = load(args.r21)
    r22 = load(args.r22)
    contract = load(args.contract)
    blockers: list[str] = []

    if r21.get("state") != "HOLD" or r21.get("verdict") != "R21_BOT_SGRADE_UPDATE_REQUIRED":
        blockers.append("R21_EXPECTED_HOLD_MISSING")
    if r22.get("state") != "PASS" or r22.get("verdict") != "R22_SBOT_SGRADE_LOCK_PASS":
        blockers.append("R22_SBOT_FOUNDATION_NOT_PASS")
    if contract.get("schema") != "q4r3_lbot_sgrade_contract_v1":
        blockers.append("LBOT_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority") or {}
    if authority.get("runtime_binding") is not False or authority.get("execution_authority") != "none":
        blockers.append("LBOT_AUTHORITY_INVALID")
    decision = contract.get("decision_policy") or {}
    if decision.get("support_numeric_thresholds_in_code") is not False:
        blockers.append("LBOT_EMBEDDED_THRESHOLD_POLICY_INVALID")
    if decision.get("ssot_rule_required") is not True:
        blockers.append("LBOT_SSOT_RULE_POLICY_INVALID")
    if decision.get("strength_or_continuation_transition_requires_hysteresis") is not True:
        blockers.append("LBOT_HYSTERESIS_POLICY_INVALID")
    if decision.get("veto_allowed") is not False:
        blockers.append("LBOT_VETO_POLICY_INVALID")

    audit = import_module(
        args.worktree / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py",
        "r21_audit",
    )
    readiness = audit.inspect_bot(args.worktree, "LBot")
    if readiness.get("s_grade_ready") is not True:
        blockers.append("LBOT_STATIC_SGRADE_NOT_READY")

    source = (args.worktree / "canonical/bots/lbot.py").read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "CAPABILITY_TAGS", "trend_strength_score", "continuation_score",
        "invalidation_score", "conflict_score", "regime_stability_score",
        "LBOT_HYSTERESIS_TRANSITION_UNAUTHORIZED", "LBOT_UNRESOLVED_INVALIDATION_FLAGS",
        "LBOT_UNRESOLVED_CONFLICT_FLAGS", "metric_sources", "integrity", "rules",
    )
    missing_tokens = [token for token in required_tokens if token not in source]
    if missing_tokens:
        blockers.append("LBOT_REQUIRED_LOGIC_MISSING:" + ",".join(missing_tokens))
    forbidden = [
        token for token in ("create_order(", "place_order(", "cancel_order(", "os.environ", "api_key")
        if token in source
    ]
    if forbidden:
        blockers.append("LBOT_FORBIDDEN_SURFACE:" + ",".join(forbidden))

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r23_lbot_sgrade_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.3",
        "state": state,
        "verdict": "R23_LBOT_SGRADE_LOCK_PASS" if state == "PASS" else "R23_LBOT_SGRADE_BLOCKED",
        "blockers": blockers,
        "report": {
            "lbot_sgrade_ready": readiness.get("s_grade_ready"),
            "capability_hits": readiness.get("capability_hits"),
            "capability_hit_count": readiness.get("capability_hit_count"),
            "required_capability_count": readiness.get("required_capability_count"),
            "required_snapshot_count": len(contract.get("required_snapshot") or []),
            "derived_metric_count": len(contract.get("derived_metrics") or []),
            "source_prefixes": (contract.get("source_policy") or {}).get("allowed_prefixes"),
            "embedded_numeric_trading_thresholds": False,
            "hysteresis_required": True,
            "veto_allowed": False,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R2.4_BUILD_SGRADE_MBOT",
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
        "lbot_sgrade_ready": readiness.get("s_grade_ready"),
        "capability_hit_count": readiness.get("capability_hit_count"),
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
