#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    status = json.loads(args.status.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if contract.get("official_stage") != "R7.3B4":
        blockers.append("CONTRACT_STAGE_INVALID")
    if status.get("state") != "PASS" or status.get("blocker_count") != 0:
        blockers.append("SMOKE_NOT_PASS")
    expected = {
        "read_only": True,
        "mutation_count": 0,
        "required_unit_count": 5,
        "active_required_unit_count": 5,
        "view_parity_ready": True,
        "telegram_parity_ready": True,
        "forbidden_marker_count": 0,
        "user_visible_confirmation_required": True,
    }
    for key, value in expected.items():
        if status.get(key) != value:
            blockers.append(f"{key.upper()}_INVALID")
    canonical = status.get("canonical_metrics", {})
    if canonical.get("closed_count", 0) <= 0 or not canonical.get("latest_trace_id"):
        blockers.append("CANONICAL_METRICS_INCOMPLETE")
    result = {
        "schema": "q4r3_exact25_r73b4_readonly_display_parity_validation_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "read_only": True,
        "mutation_count": 0,
        "closed_count": canonical.get("closed_count", 0),
        "winrate_pct": canonical.get("winrate_pct"),
        "total_r": canonical.get("total_r"),
        "view_parity_ready": status.get("view_parity_ready", False),
        "telegram_parity_ready": status.get("telegram_parity_ready", False),
        "next_stage": contract.get("next_stage"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
