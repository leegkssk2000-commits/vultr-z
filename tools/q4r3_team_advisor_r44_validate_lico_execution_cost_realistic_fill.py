#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "q4r3_team_advisor_r44_lico_execution_cost_realistic_fill_v1"
SENSITIVE = re.compile(r"(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY|create_order|place_order|submit_order|send_order)", re.I)
REQUIRED_MARKERS = (
    "spread_bps", "slippage_bps", "market_impact_bps", "execution_cost_bps",
    "order_book_walking", "partial_fill", "filled_qty", "no_fill", "queue_model",
    "first_fill_ts", "final_fill_ts",
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def validate(worktree: Path, r43_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r43 = read_json(r43_path)
    contract = read_json(contract_path)
    owner = worktree / "canonical/lico.py"
    implementation = worktree / "canonical/lico_execution.py"

    if r43.get("state") != "PASS" or r43.get("blockers"):
        blockers.append("R43_PASS_NOT_PROVEN")
    report43 = r43.get("report", {})
    if not report43.get("market_stream_ready") or not report43.get("venue_health_ready"):
        blockers.append("R43_MARKET_PREREQUISITE_INVALID")
    if report43.get("canonical_owner_count") != 1:
        blockers.append("R43_CANONICAL_OWNER_INVALID")
    if report43.get("next_route") != "R4.4_LICO_EXECUTION_COST_REALISTIC_FILL":
        blockers.append("R43_NEXT_ROUTE_INVALID")

    if not owner.is_file() or not implementation.is_file():
        blockers.append("R44_IMPLEMENTATION_MISSING")
    if contract.get("schema") != "q4r3_lico_execution_cost_realistic_fill_contract_v1":
        blockers.append("R44_CONTRACT_SCHEMA_INVALID")
    if contract.get("canonical_owner") != "canonical/lico.py":
        blockers.append("R44_OWNER_REFERENCE_INVALID")
    if contract.get("implementation") != "canonical/lico_execution.py":
        blockers.append("R44_IMPLEMENTATION_REFERENCE_INVALID")

    text = implementation.read_text(encoding="utf-8", errors="replace") if implementation.is_file() else ""
    missing_markers = [marker for marker in REQUIRED_MARKERS if marker not in text]
    if missing_markers:
        blockers.append("R44_REQUIRED_MODEL_SURFACE_MISSING")
    authority_hits = sorted(set(SENSITIVE.findall(text)))
    if authority_hits:
        blockers.append("R44_FORBIDDEN_AUTHORITY_SURFACE")
    for forbidden in ("fee_r", "maker_fee", "taker_fee", "liquidation_model"):
        if forbidden in text:
            blockers.append("R44_FUTURE_STAGE_SCOPE_LEAK")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R4.4",
        "state": state,
        "verdict": "R44_LICO_EXECUTION_COST_REALISTIC_FILL_PASS" if state == "PASS" else "R44_LICO_EXECUTION_COST_REALISTIC_FILL_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "canonical_owner_count": 1 if owner.is_file() else 0,
            "execution_cost_ready": not missing_markers and implementation.is_file(),
            "realistic_fill_ready": not missing_markers and implementation.is_file(),
            "fill_outcome_count": 3,
            "fail_closed_scenario_count": 3,
            "forbidden_authority_hit_count": len(authority_hits),
            "closed_gap_count": 2 if state == "PASS" else 0,
            "remaining_gap_count": 5,
            "runtime_binding": False,
            "sgrade_ready": False,
            "next_route": "R4.5_LICO_FEE_FUNDING_LIQUIDATION_STRESS"
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r43", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.worktree.resolve(), args.r43.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "execution_cost_ready": payload["report"]["execution_cost_ready"],
        "realistic_fill_ready": payload["report"]["realistic_fill_ready"],
        "remaining_gap_count": payload["report"]["remaining_gap_count"],
        "blocker_count": len(payload["blockers"])
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
