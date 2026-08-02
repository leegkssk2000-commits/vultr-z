from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_TRADE_METHOD_HISTORICAL_ADAPTER_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def behavior_index(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = receipt.get("rows") if isinstance(receipt.get("rows"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id:
            out[strategy_id] = row
    return out


def classify_behavior(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {
            "state": "HOLD_TRADE_METHOD_BEHAVIOR_MISSING",
            "counterfactual_mode": "NONE",
            "r_delta_allowed": False,
            "usdt_reweight_allowed": False,
            "blockers": ["runtime_behavior_missing"],
        }
    enabled = row.get("registry_enabled") is True
    size_multiplier = safe_float(row.get("size_multiplier"))
    target_r = safe_float(row.get("target_r"))
    authority_safe = (
        str(row.get("execution_authority") or "").upper() == "NONE"
        and str(row.get("order_authority") or "").upper() == "BLOCKED"
        and row.get("paper_execution_allowed") is False
        and row.get("live_execution_allowed") is False
    )
    blockers: list[str] = []
    if not authority_safe:
        blockers.append("authority_boundary_unsafe")
    if not enabled or size_multiplier is None or size_multiplier <= 0:
        blockers.append("registry_disabled_or_zero_size")
    if target_r is not None:
        blockers.append("target_r_requires_intratrade_price_path")
    if blockers:
        state = "HOLD_TRADE_METHOD_HISTORICAL_COUNTERFACTUAL"
        mode = "DISABLED_OR_PATH_DEPENDENT"
    elif abs(size_multiplier - 1.0) < 1e-12:
        state = "PASS_TRADE_METHOD_R_PARITY_ONLY"
        mode = "IDENTITY_SIZE"
    else:
        state = "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY"
        mode = "LINEAR_SIZE_PLAN"
    return {
        "state": state,
        "counterfactual_mode": mode,
        "registry_enabled": enabled,
        "size_multiplier": size_multiplier,
        "target_r": target_r,
        "r_delta_allowed": False,
        "usdt_reweight_allowed": state == "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY",
        "blockers": sorted(set(blockers)),
    }


def map_trade(trade: Mapping[str, Any], behavior: Mapping[str, Any] | None) -> dict[str, Any]:
    classification = classify_behavior(behavior)
    initial_risk = safe_float(trade.get("initial_risk_usdt"))
    multiplier = classification.get("size_multiplier")
    planned_risk = None
    if classification["usdt_reweight_allowed"] and initial_risk is not None and multiplier is not None:
        planned_risk = initial_risk * float(multiplier)
    blockers = list(classification["blockers"])
    if classification["usdt_reweight_allowed"] and initial_risk is None:
        blockers.append("initial_risk_usdt_missing")
    state = classification["state"]
    if blockers and state.startswith("PASS_"):
        state = "HOLD_TRADE_METHOD_USDT_REWEIGHT_INPUT_MISSING"
    return {
        "event_id": trade.get("event_id"),
        "strategy_id": trade.get("strategy_id") or trade.get("strategy"),
        "window_id": trade.get("window_id"),
        "state": state,
        "counterfactual_mode": classification["counterfactual_mode"],
        "base_realized_R": trade.get("realized_R"),
        "counterfactual_realized_R": trade.get("realized_R"),
        "r_delta": 0.0,
        "initial_risk_usdt": initial_risk,
        "planned_initial_risk_usdt": planned_risk,
        "size_multiplier": classification.get("size_multiplier"),
        "target_r": classification.get("target_r"),
        "blockers": sorted(set(blockers)),
        "linear_cost_scaling_claim_allowed": False,
        "economic_superiority_claim_allowed": False,
        "action": "hold",
    }


def build(trades_path: Path, behavior_path: Path) -> dict[str, Any]:
    behavior_receipt = load_json(behavior_path)
    behaviors = behavior_index(behavior_receipt)
    rows: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    with gzip.open(trades_path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            trade = json.loads(raw)
            if not isinstance(trade, dict):
                continue
            strategy_id = str(trade.get("strategy_id") or trade.get("strategy") or "")
            mapped = map_trade(trade, behaviors.get(strategy_id))
            rows.append(mapped)
            state_counts[mapped["state"]] += 1
            blocker_counts.update(mapped["blockers"])
    pass_count = sum(count for state, count in state_counts.items() if state.startswith("PASS_"))
    state = "PASS_TRADE_METHOD_HISTORICAL_ADAPTER" if rows and pass_count == len(rows) else "HOLD_TRADE_METHOD_HISTORICAL_ADAPTER"
    result: dict[str, Any] = {
        "schema_version": "zel.trade_method.historical_adapter.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "trade_count": len(rows),
        "pass_trade_count": pass_count,
        "blocked_trade_count": len(rows) - pass_count,
        "state_counts": dict(sorted(state_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "rows": rows,
        "r_delta_sum": 0.0,
        "linear_cost_scaling_claim_allowed": False,
        "economic_superiority_claim_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    safe = {
        "strategy_id": "s1",
        "registry_enabled": True,
        "size_multiplier": 0.5,
        "target_r": None,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_execution_allowed": False,
        "live_execution_allowed": False,
    }
    mapped = map_trade({"event_id": "e1", "strategy_id": "s1", "realized_R": 1.0, "initial_risk_usdt": 10}, safe)
    assert mapped["state"] == "PASS_TRADE_METHOD_USDT_REWEIGHT_PLAN_ONLY", mapped
    assert mapped["planned_initial_risk_usdt"] == 5.0, mapped
    assert mapped["r_delta"] == 0.0, mapped
    disabled = dict(safe, registry_enabled=False, size_multiplier=0.0)
    hold = map_trade({"event_id": "e2", "strategy_id": "s1", "realized_R": -1.0}, disabled)
    assert hold["state"] == "HOLD_TRADE_METHOD_HISTORICAL_COUNTERFACTUAL", hold
    target = dict(safe, target_r=2.5)
    target_hold = map_trade({"event_id": "e3", "strategy_id": "s1", "realized_R": 1.0}, target)
    assert "target_r_requires_intratrade_price_path" in target_hold["blockers"], target_hold
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--behavior", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.trades or not args.behavior:
        parser.error("trades and behavior are required")
    row = build(args.trades, args.behavior)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
