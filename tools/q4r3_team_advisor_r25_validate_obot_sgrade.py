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
    parser.add_argument("--r24", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    r24 = load(args.r24)
    contract = load(args.contract)
    blockers: list[str] = []

    if r24.get("state") != "PASS" or r24.get("official_stage") != "R2.4":
        blockers.append("R24_MBOT_FOUNDATION_NOT_PASS")
    if contract.get("schema") != "q4r3_obot_sgrade_contract_v1":
        blockers.append("OBOT_CONTRACT_SCHEMA_INVALID")
    authority = contract.get("authority") or {}
    if authority.get("runtime_binding") is not False or authority.get("execution_authority") != "none":
        blockers.append("OBOT_AUTHORITY_INVALID")
    decision = contract.get("decision_policy") or {}
    if decision.get("numeric_thresholds_in_code") is not False:
        blockers.append("EMBEDDED_THRESHOLD_POLICY_INVALID")
    if decision.get("ssot_rule_required") is not True:
        blockers.append("SSOT_RULE_POLICY_INVALID")
    if decision.get("watch_only") is not True or decision.get("veto_allowed") is not False:
        blockers.append("OBOT_ROLE_AUTHORITY_INVALID")

    audit_module = import_r21(args.worktree / "tools/q4r3_team_advisor_r21_bot_sgrade_revalidation.py")
    readiness = audit_module.inspect_bot(args.worktree, "OBot")
    if readiness.get("s_grade_ready") is not True:
        blockers.append("OBOT_STATIC_SGRADE_NOT_READY")

    source = (args.worktree / "canonical/bots/obot.py").read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "CAPABILITY_TAGS", "SNAPSHOT_FIELDS", "breakout_quality_score", "fakeout_risk_score",
        "momentum_score", "anomaly_score", "exhaustion_score", "mfe_mae_spread",
        "OBOT_SSOT_RULES_MISSING", "OBOT_RULE_INVALID", "OBOT_UNRESOLVED_BREAKOUT_STATE",
        "OBOT_UNRESOLVED_FAKEOUT_FLAGS", "OBOT_UNRESOLVED_ANOMALY_FLAGS",
        "OBOT_UNRESOLVED_EXHAUSTION_FLAGS", "route_change",
    )
    missing_tokens = [token for token in required_tokens if token not in source]
    if missing_tokens:
        blockers.append("OBOT_REQUIRED_LOGIC_MISSING:" + ",".join(missing_tokens))
    forbidden = [
        token for token in ("create_order(", "place_order(", "cancel_order(", "os.environ", "api_key")
        if token in source
    ]
    if forbidden:
        blockers.append("OBOT_FORBIDDEN_SURFACE:" + ",".join(forbidden))

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r25_obot_sgrade_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.5",
        "state": state,
        "verdict": "R25_OBOT_SGRADE_LOCK_PASS" if state == "PASS" else "R25_OBOT_SGRADE_BLOCKED",
        "blockers": blockers,
        "report": {
            "obot_sgrade_ready": readiness.get("s_grade_ready"),
            "capability_hits": readiness.get("capability_hits"),
            "capability_hit_count": readiness.get("capability_hit_count"),
            "required_capability_count": readiness.get("required_capability_count"),
            "required_snapshot_count": len(contract.get("required_snapshot") or []),
            "derived_metric_count": len(contract.get("derived_metrics") or []),
            "source_prefixes": (contract.get("source_policy") or {}).get("allowed_prefixes"),
            "embedded_numeric_trading_thresholds": False,
            "watch_only": True,
            "veto_allowed": False,
            "runtime_binding": False,
            "execution_authority": "none",
            "next_route": "R2.6_REVALIDATE_ALL_FOUR_SGRADE_BOTS",
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
        "obot_sgrade_ready": readiness.get("s_grade_ready"),
        "capability_hit_count": readiness.get("capability_hit_count"),
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
