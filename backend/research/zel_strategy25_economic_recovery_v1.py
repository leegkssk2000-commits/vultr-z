#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.strategy25.economic_recovery.v1"
POLICY_SCHEMA = "zel.production_performance_bootstrap_policy.v1"
INVENTORY_SCHEMA = "zel.legacy_strategy25.inventory.v1"
EXACT_SCHEMA = "zel.historical_oos_exact25_replay.result.v2"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"JSON_NOT_OBJECT:{path}")
    return row


def metric(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    row = scorecard.get("closed_metrics_including_funding_estimate") or scorecard.get("closed_metrics_ex_funding") or {}
    if not isinstance(row, Mapping):
        row = {}
    return {
        "sample_count": int(row.get("sample_count") or 0),
        "net_R": float(row.get("net_R") or 0.0),
        "expectancy_R": float(row.get("expectancy_R") or 0.0),
        "profit_factor": float(row.get("profit_factor") or 0.0),
        "win_rate_pct": float(row.get("win_rate_pct") or 0.0),
        "max_drawdown_R": float(row.get("max_drawdown_R") or 0.0),
    }


def classify(scorecard: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[str, str]:
    fingerprint = str(scorecard.get("failure_fingerprint") or "")
    rules = policy["admission_rules"]
    if fingerprint == rules["positive_unpromoted_fingerprint"]:
        return "ADMISSION_EXTENSION_REQUIRED", "POSITIVE_LOW_SAMPLE_NOT_SURVIVOR"
    if fingerprint == rules["zero_trade_fingerprint"]:
        return "ZERO_SIGNAL_REPAIR_REQUIRED", "ZERO_TRADES_NO_ECONOMIC_EVIDENCE"
    if fingerprint == rules["negative_fingerprint"]:
        return "TERMINAL_REJECT_CURRENT_EVIDENCE", "NEGATIVE_OR_UNSTABLE_OOS_EDGE"
    return "HOLD_UNCLASSIFIED_EVIDENCE", f"UNRECOGNIZED_FINGERPRINT:{fingerprint or 'EMPTY'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exact25", type=Path, required=True)
    ap.add_argument("--inventory", type=Path, required=True)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    exact = load(args.exact25)
    inventory = load(args.inventory)
    policy = load(args.policy)
    if exact.get("schema_version") != EXACT_SCHEMA:
        raise RuntimeError("EXACT25_SCHEMA_INVALID")
    if exact.get("execution_authority") != "NONE" or exact.get("order_authority") != "BLOCKED" or exact.get("research_only") is not True:
        raise RuntimeError("EXACT25_AUTHORITY_INVALID")
    replay = exact.get("replay") or {}
    if replay.get("strategy_count_completed") != 25 or replay.get("strategy_count_expected") != 25:
        raise RuntimeError("EXACT25_CARDINALITY_INVALID")
    if int(replay.get("error_count") or 0) != 0 or int(replay.get("censored_open_at_window_end") or 0) != 0:
        raise RuntimeError("EXACT25_INTEGRITY_FAIL")
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise RuntimeError("INVENTORY_SCHEMA_INVALID")
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("BOOTSTRAP_POLICY_SCHEMA_INVALID")
    names = list(inventory.get("historical_implementation_inventory_25") or [])
    if len(names) != 25 or len(set(names)) != 25:
        raise RuntimeError("INVENTORY_CARDINALITY_INVALID")
    cards = exact.get("scorecards") or []
    by_id = {str(row.get("strategy_id")): row for row in cards if isinstance(row, Mapping) and row.get("strategy_id")}
    if set(by_id) != set(names):
        missing = sorted(set(names) - set(by_id))
        extra = sorted(set(by_id) - set(names))
        raise RuntimeError(f"SCORECARD_IDENTITY_MISMATCH:missing={missing}:extra={extra}")

    rows = []
    admission = []
    state_counts: dict[str, int] = {}
    for index, strategy_id in enumerate(names):
        card = by_id[strategy_id]
        state, reason = classify(card, policy)
        state_counts[state] = state_counts.get(state, 0) + 1
        row = {
            "inventory_index": index,
            "strategy_id": strategy_id,
            "claim_tier": card.get("claim_tier"),
            "failure_fingerprint": card.get("failure_fingerprint"),
            "classification": state,
            "reason": reason,
            "metrics": metric(card),
            "owner_sha256": card.get("owner_sha256"),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
        }
        rows.append(row)
        if state == "ADMISSION_EXTENSION_REQUIRED":
            admission.append({
                "queue_index": len(admission),
                "strategy_id": strategy_id,
                "route": "LOW_SAMPLE_EXTENSION_SAME_RULE",
                "baseline_metrics": row["metrics"],
                "source_owner_sha256": row["owner_sha256"],
                "state": "PENDING_ADMISSION_EVIDENCE",
            })

    budget = int(policy.get("candidate_budget") or 0)
    queue = admission[:budget]
    survivor_count = 0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "HOLD_ZERO_SURVIVOR_ADMISSION_QUEUE_READY" if queue else "HOLD_ZERO_SURVIVOR_NO_ADMISSION_CANDIDATE",
        "exact25_source": {
            "schema_version": exact.get("schema_version"),
            "generated_at": exact.get("generated_at"),
            "input_fingerprint": (exact.get("checkpoint") or {}).get("input_fingerprint"),
            "data_manifest_sha256": ((exact.get("checkpoint") or {}).get("input_fingerprint_fields") or {}).get("data_manifest_sha256"),
            "strategy_tree_sha256": ((exact.get("checkpoint") or {}).get("input_fingerprint_fields") or {}).get("strategy_tree_sha256"),
        },
        "strategy_count": len(rows),
        "economic_survivor_count": survivor_count,
        "state_counts": dict(sorted(state_counts.items())),
        "rows": rows,
        "admission_candidate_count_total": len(admission),
        "candidate_budget": budget,
        "admission_queue": queue,
        "next": "RUN_SINGLE_LOW_SAMPLE_ADMISSION_EXTENSION" if queue else "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY",
        "replay_performed_by_recovery": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "state_counts": receipt["state_counts"],
        "admission_queue": receipt["admission_queue"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
