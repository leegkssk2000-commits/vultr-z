#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "protected_mutations": 0,
}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def assert_safety(value: dict[str, Any], label: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"{label}_SAFETY_MISMATCH:{key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ai-receipt", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        receipt = read_object(args.receipt)
        plan = read_object(args.plan)
        ai = read_object(args.ai_receipt)
        manifest = read_object(args.inputs / "materialized_manifest.json")
        cost = read_object(args.inputs / "cost_binding.json")
        assert_safety(receipt, "REPLAY")

        expected_receipt_sha = receipt.pop("receipt_sha256", None)
        if expected_receipt_sha != canonical_sha256(receipt):
            raise ValueError("REPLAY_RECEIPT_SHA_MISMATCH")
        receipt["receipt_sha256"] = expected_receipt_sha

        if plan.get("state") != "PASS_SESSION_EVENT_CONTINUATION_PLAN_SEALED_RESEARCH_ONLY":
            raise ValueError("PLAN_NOT_SEALED")
        plan_copy = dict(plan)
        plan_receipt = plan_copy.pop("receipt_sha256", None)
        if plan_receipt != canonical_sha256(plan_copy):
            raise ValueError("PLAN_RECEIPT_SHA_MISMATCH")
        if ai.get("state") != "PASS_SESSION_EVENT_AI_CHAIN_BOUND":
            raise ValueError("AI_CHAIN_NOT_PASS")
        if receipt.get("selected_axis") != ai.get("selected_axis"):
            raise ValueError("AI_AXIS_REPLAY_AXIS_MISMATCH")
        if manifest.get("state") != "PASS_MATERIALIZED_REPLAY_INPUTS":
            raise ValueError("MATERIALIZED_INPUTS_NOT_PASS")
        if cost.get("stress_lineage_complete") is not True:
            raise ValueError("COST_LINEAGE_INCOMPLETE")

        lineage = receipt.get("lineage", {})
        expected_lineage = {
            "plan_sha256": sha256_file(args.plan),
            "ai_receipt_sha256": sha256_file(args.ai_receipt),
            "materialized_manifest_sha256": sha256_file(args.inputs / "materialized_manifest.json"),
            "cost_binding_sha256": sha256_file(args.inputs / "cost_binding.json"),
        }
        for key, expected in expected_lineage.items():
            if lineage.get(key) != expected:
                raise ValueError(f"LINEAGE_MISMATCH:{key}")
        if receipt.get("integrity", {}).get("event_ledger_sha256") != sha256_file(args.ledger):
            raise ValueError("EVENT_LEDGER_SHA_MISMATCH")
        if receipt.get("integrity", {}).get("future_information") != 0:
            raise ValueError("FUTURE_INFORMATION_PRESENT")
        if receipt.get("integrity", {}).get("duplicate_events") != 0:
            raise ValueError("DUPLICATE_EVENTS_PRESENT")
        if receipt.get("integrity", {}).get("closed_bar_only") is not True:
            raise ValueError("CLOSED_BAR_ONLY_NOT_PROVEN")

        gates = receipt.get("gate_results", {})
        required_gates = {
            "events_gte",
            "mean_net_return_gt_pct",
            "bootstrap_ci95_low_gt_pct",
            "controls_coverage_gte_pct",
            "controls_separated",
        }
        if set(gates) != required_gates:
            raise ValueError("GATE_SET_MISMATCH")
        failed = sorted(key for key in required_gates if gates.get(key) is not True)
        if failed:
            raise ValueError("REPLAY_EDGE_GATE_FAILED:" + ",".join(failed))
        if receipt.get("window") == "research":
            expected_state = "PASS_SESSION_EVENT_RESEARCH_EDGE"
            expected_next = "W1_HOLDOUT_REPLAY"
        elif receipt.get("window") == "W1":
            expected_state = "PASS_SESSION_EVENT_W1_EDGE"
            expected_next = "NONE_UNTIL_EDGE_PASS"
        else:
            raise ValueError("VALIDATOR_WINDOW_NOT_ALLOWED")
        if receipt.get("state") != expected_state:
            raise ValueError("REPLAY_STATE_NOT_PASS")
        if receipt.get("next_gate") != expected_next:
            raise ValueError("NEXT_GATE_MISMATCH")

        validation = {
            "schema_version": "zel.session_event.replay_validation.v1",
            "state": "PASS_SESSION_EVENT_DETERMINISTIC_REPLAY_VALIDATED",
            "selected_axis": receipt["selected_axis"],
            "window": receipt["window"],
            "event_count": receipt["event_count"],
            "replay_receipt_sha256": receipt["receipt_sha256"],
            "replay_file_sha256": sha256_file(args.receipt),
            "event_ledger_sha256": sha256_file(args.ledger),
            "plan_sha256": sha256_file(args.plan),
            "ai_receipt_sha256": sha256_file(args.ai_receipt),
            "next_gate": receipt["next_gate"],
            **SAFETY,
            "action": "route_change",
        }
        validation["receipt_sha256"] = canonical_sha256(validation)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "state": validation["state"],
            "selected_axis": validation["selected_axis"],
            "event_count": validation["event_count"],
            "next_gate": validation["next_gate"],
        }, sort_keys=True))
        return 0
    except Exception as exc:
        hold = {
            "schema_version": "zel.session_event.replay_validation.v1",
            "state": "HOLD_SESSION_EVENT_DETERMINISTIC_REPLAY",
            "blocker_codes": [str(exc)[:1200]],
            "next_gate": "NONE",
            **SAFETY,
            "action": "hold",
        }
        hold["receipt_sha256"] = canonical_sha256(hold)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(hold, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"state": hold["state"], "blocker_codes": hold["blocker_codes"]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
