#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "zel.strategy25.performance_admission.receipt.v2"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(policy: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id") or "")
    metrics = row.get("closed_metrics_including_funding_estimate") if isinstance(row.get("closed_metrics_including_funding_estimate"), dict) else {}
    windows = row.get("by_window") if isinstance(row.get("by_window"), dict) else {}
    close_count = int(row.get("close_count") or 0)
    signal_count = int(row.get("signal_count") or 0)
    valid_entry_count = int(row.get("valid_entry_count") or 0)
    error_count = int(row.get("error_count") or 0)
    duplicate_count = int(row.get("duplicate_count") or 0)
    censored = int(row.get("censored_open_at_window_end") or 0)
    claim_tier = str(row.get("claim_tier") or "")
    net_r = number(metrics.get("net_R"))
    pf = number(metrics.get("profit_factor"))
    expectancy = number(metrics.get("expectancy_R"))
    payoff = number(metrics.get("payoff_ratio"))
    retention = number(row.get("retention_pct"))
    source_owner_parity = row.get("source_owner_parity")
    cost_lineage = row.get("cost_lineage_complete")
    required_windows = list(policy["required_windows"])
    required_windows_present = all(key in windows for key in required_windows)
    all_required_windows_positive = required_windows_present and all(
        (number((windows.get(key) or {}).get("net_R")) or 0.0) > 0.0 for key in required_windows
    )

    checks = {
        "close_count": close_count,
        "signal_count": signal_count,
        "valid_entry_count": valid_entry_count,
        "error_count": error_count,
        "duplicate_count": duplicate_count,
        "censored_open_count": censored,
        "net_R": net_r,
        "profit_factor": pf,
        "expectancy_R": expectancy,
        "payoff_ratio": payoff,
        "retention_pct": retention,
        "required_windows_present": required_windows_present,
        "all_required_windows_positive": all_required_windows_positive,
        "source_owner_parity": source_owner_parity,
        "cost_lineage_complete": cost_lineage,
    }

    if close_count == 0 and signal_count == 0:
        disposition, reason = "ZERO_SIGNAL_REPAIR", "zero closed trades and zero strategy signals"
    elif close_count == 0 and valid_entry_count == 0:
        disposition, reason = "ZERO_SIGNAL_REPAIR", "signals existed but no valid entry survived"
    elif close_count == 0:
        disposition, reason = "LOW_SAMPLE_REPAIR", "valid entries existed but no terminal closed sample"
    elif claim_tier == "ZERO_TRADES_HOLD":
        disposition, reason = "ZERO_SIGNAL_REPAIR", "terminal receipt classifies zero-trade hold"
    elif claim_tier == "LOW_SAMPLE_HOLD":
        disposition, reason = "LOW_SAMPLE_REPAIR", "terminal receipt classifies low-sample hold"
    else:
        gate = policy["survivor_gate"]
        full_economic = (
            net_r is not None and net_r > float(gate["net_R_gt"])
            and pf is not None and pf >= float(gate["profit_factor_gte"])
            and expectancy is not None and expectancy > float(gate["expectancy_R_gt"])
            and payoff is not None and payoff >= float(gate["payoff_ratio_gte"])
            and retention is not None and retention >= float(gate["minimum_retention_pct"])
            and error_count <= int(gate["error_count_max"])
            and duplicate_count <= int(gate["duplicate_count_max"])
            and censored <= int(gate["censored_open_count_max"])
            and required_windows_present and all_required_windows_positive
            and source_owner_parity is True
            and cost_lineage is True
        )
        if full_economic:
            disposition, reason = "SURVIVOR_CANDIDATE", "all absolute economic, durability and lineage gates pass"
        elif net_r is not None and net_r > 0.0:
            disposition, reason = "RESERVE_CANDIDATE", "final economics positive but one or more durability/lineage gates incomplete"
        elif claim_tier in {"COMPONENT_RESEARCH_REVIEW", "INTEGRATED_RESEARCH_REVIEW"}:
            disposition, reason = "MATERIAL_ONLY", "negative final economics with bounded component learning value"
        else:
            disposition, reason = "REJECT_CURRENT_EPOCH", "non-positive final economics with no surviving gate"

    return {
        "strategy_id": strategy_id,
        "disposition": disposition,
        "reason": reason,
        "claim_tier": claim_tier,
        "checks": checks,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def route(rows: list[dict[str, Any]], budget: int) -> tuple[str, list[str]]:
    def ranked(kind: str) -> list[dict[str, Any]]:
        xs = [r for r in rows if r["disposition"] == kind]
        xs.sort(key=lambda r: (
            -(r["checks"].get("net_R") if r["checks"].get("net_R") is not None else -1e18),
            -int(r["checks"].get("close_count") or 0),
            r["strategy_id"],
        ))
        return xs
    survivors = ranked("SURVIVOR_CANDIDATE")
    if survivors:
        return "SEED_INCUMBENT_FROM_SURVIVOR", [r["strategy_id"] for r in survivors[:budget]]
    reserves = ranked("RESERVE_CANDIDATE")
    if reserves:
        return "EXPAND_DURABILITY_FOR_RESERVE", [r["strategy_id"] for r in reserves[:budget]]
    low = ranked("LOW_SAMPLE_REPAIR")
    if low:
        return "EXPAND_SAMPLE_FOR_LOW_SAMPLE", [r["strategy_id"] for r in low[:budget]]
    return "NEW_ECONOMIC_EDGE_ACQUISITION", []


def run(policy: dict[str, Any], identity: dict[str, Any], smoke: dict[str, Any], terminal: dict[str, Any]) -> dict[str, Any]:
    if identity.get("state") != "PASS_STRATEGY25_IDENTITY_25_OF_25" or identity.get("identity_gate_pass") is not True:
        raise RuntimeError("IDENTITY_GATE_REQUIRED")
    if smoke.get("state") != "PASS_STRATEGY25_BASELINE_SMOKE_25_OF_25" or int(smoke.get("compile_pass_count") or 0) != 25:
        raise RuntimeError("BASELINE_SMOKE_REQUIRED")
    replay = terminal.get("replay") if isinstance(terminal.get("replay"), dict) else {}
    scorecards = terminal.get("scorecards") if isinstance(terminal.get("scorecards"), list) else []
    if len(scorecards) != int(policy["expected_strategy_count"]):
        raise RuntimeError("STRATEGY_COUNT_MISMATCH")
    if int(replay.get("closed_trade_count") or 0) != int(policy["expected_terminal_trade_count"]):
        raise RuntimeError("TERMINAL_TRADE_COUNT_MISMATCH")
    if int(replay.get("error_count") or 0) != 0 or int(replay.get("censored_open_at_window_end") or 0) != 0:
        raise RuntimeError("TERMINAL_INTEGRITY_FAILURE")
    identity_names = {str(r.get("legacy_name") or "") for r in identity.get("rows") or []}
    score_names = {str(r.get("strategy_id") or "") for r in scorecards if isinstance(r, dict)}
    if identity_names != score_names:
        raise RuntimeError("IDENTITY_TERMINAL_NAME_PARITY_FAILURE")
    rows = [classify(policy, row) for row in scorecards if isinstance(row, dict)]
    rows.sort(key=lambda r: r["strategy_id"])
    allowed = set(policy["allowed_dispositions"])
    if any(r["disposition"] not in allowed for r in rows):
        raise RuntimeError("UNKNOWN_DISPOSITION")
    counts = dict(sorted(Counter(r["disposition"] for r in rows).items()))
    next_route, route_candidates = route(rows, int(policy["candidate_budget"]))
    survivor_count = counts.get("SURVIVOR_CANDIDATE", 0)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_STRATEGY25_FINAL_PERFORMANCE_ADMISSION",
        "identity_receipt_sha256": identity.get("receipt_sha256"),
        "baseline_smoke_receipt_sha256": smoke.get("receipt_sha256"),
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
        "strategy_count": len(rows),
        "closed_trade_count": replay.get("closed_trade_count"),
        "counts": counts,
        "strategies": rows,
        "economic_survivor_count": survivor_count,
        "next_route": next_route,
        "route_candidates": route_candidates,
        "candidate_budget": int(policy["candidate_budget"]),
        "final": True,
        "replay_performed_by_this_stage": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_mutated": False,
        "service_state_mutated": False,
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--smoke", type=Path, required=True)
    ap.add_argument("--terminal", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = run(read_json(args.policy), read_json(args.identity), read_json(args.smoke), read_json(args.terminal))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "counts": result["counts"],
        "economic_survivor_count": result["economic_survivor_count"],
        "next_route": result["next_route"],
        "route_candidates": result["route_candidates"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
