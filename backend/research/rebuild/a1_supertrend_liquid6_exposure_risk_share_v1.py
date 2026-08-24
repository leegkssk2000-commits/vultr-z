#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

STRATEGY_ID = "supertrend_pullback"
EXPECTED_RECEIPT_SHA256 = "5be1986bba47492333e6df1daaf735538ee73694d99da68332344d7215344eec"
EXPECTED_COMPLETED_TRADES = 47
EXPECTED_SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def ordered_trades(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    return sorted(
        rows,
        key=lambda x: (
            int(x.get("entry_ts") or 0),
            int(x.get("exit_ts") or 0),
            str(x.get("symbol") or ""),
            str(x.get("intent_sha") or ""),
        ),
    )


def validate_receipt(receipt: Mapping[str, Any]) -> list[str]:
    defects: list[str] = []
    if str(receipt.get("strategy_id") or "") != STRATEGY_ID:
        defects.append("STRATEGY_ID_MISMATCH")
    if str(receipt.get("receipt_sha256") or "") != EXPECTED_RECEIPT_SHA256:
        defects.append("FROZEN_RECEIPT_SHA_MISMATCH")
    rows = ordered_trades(receipt)
    completed = int(receipt.get("completed_trades") or len(rows))
    if completed != EXPECTED_COMPLETED_TRADES or len(rows) != EXPECTED_COMPLETED_TRADES:
        defects.append("FROZEN_TRADE_COUNT_MISMATCH")
    if (receipt.get("source_quality_gate") or {}).get("state") != "PASS":
        defects.append("SOURCE_QUALITY_NOT_PASS")
    if list(receipt.get("integrity_defects") or []):
        defects.append("UPSTREAM_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        defects.append("UPSTREAM_LOOKAHEAD_NONZERO")
    got_symbols = sorted({str(x.get("symbol") or "") for x in rows})
    if got_symbols != sorted(EXPECTED_SYMBOLS):
        defects.append("LIQUID6_SYMBOL_SET_MISMATCH")
    ids = [str(x.get("intent_sha") or "") for x in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        defects.append("TRADE_ID_MISSING_OR_DUPLICATE")
    for row in rows:
        entry_ts = int(row.get("entry_ts") or 0)
        exit_ts = int(row.get("exit_ts") or 0)
        net = float(row.get("net_bps") or 0.0)
        # Same-bar exits are valid in the canonical evaluator: entry and exit
        # can share the bar timestamp when SL/TP is realized inside the entry bar.
        # Only a strictly earlier exit is an interval defect.
        if entry_ts <= 0 or exit_ts < entry_ts:
            defects.append("INVALID_TRADE_INTERVAL")
            break
        if not math.isfinite(net):
            defects.append("NONFINITE_NET_BPS")
            break
    return sorted(set(defects))


def max_drawdown_exit_buckets(rows: list[dict[str, Any]], pnl_key: str) -> float:
    buckets: dict[int, float] = defaultdict(float)
    for row in rows:
        buckets[int(row["exit_ts"])] += float(row[pnl_key])
    equity = peak = dd = 0.0
    for _, pnl in sorted(buckets.items()):
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def metrics(rows: list[dict[str, Any]], pnl_key: str) -> dict[str, Any]:
    vals = [float(x[pnl_key]) for x in rows]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    pnl = sum(vals)
    dd = max_drawdown_exit_buckets(rows, pnl_key)
    gp = sum(wins)
    gl = sum(losses)
    return {
        "completed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else None,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": pnl / len(rows) if rows else None,
        "profit_factor": (gp / gl) if gl > 0 else None,
        "realized_exit_bucket_max_drawdown_bps": dd,
        "pnl_to_drawdown": (pnl / dd) if dd > 0 else None,
        "largest_loss_bps": min(vals) if vals else None,
    }


def active_same_symbol_count(trade: Mapping[str, Any], rows: list[dict[str, Any]]) -> int:
    symbol = str(trade["symbol"])
    entry_ts = int(trade["entry_ts"])
    # Includes the trade itself. Same-bar exits count as active at their entry
    # instant; equal-entry overlaps receive the same count, avoiding ordering bias.
    return sum(
        1
        for other in rows
        if str(other["symbol"]) == symbol
        and int(other["entry_ts"]) <= entry_ts <= int(other["exit_ts"])
    )


def apply_equal_same_symbol_risk_share(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        concurrency = active_same_symbol_count(row, rows)
        if concurrency < 1:
            raise RuntimeError("CONCURRENCY_COUNT_INVALID")
        weight = 1.0 / float(concurrency)
        item = dict(row)
        item["same_symbol_active_at_entry"] = concurrency
        item["risk_share_weight"] = weight
        item["risk_shared_net_bps"] = float(row["net_bps"]) * weight
        out.append(item)
    return out


def run(receipt: Mapping[str, Any]) -> dict[str, Any]:
    defects = validate_receipt(receipt)
    rows = ordered_trades(receipt)
    if defects:
        result = {
            "schema_version": "zel.a1.supertrend.liquid6.exposure_risk_share.v1",
            "state": "HOLD_FROZEN_EVIDENCE_INTEGRITY",
            "strategy_id": STRATEGY_ID,
            "integrity_defects": defects,
            "research_only": True,
            **AUTH,
        }
        result["receipt_sha256"] = stable_sha(result)
        return result

    for row in rows:
        row["baseline_net_bps"] = float(row["net_bps"])
    shared = apply_equal_same_symbol_risk_share(rows)
    parent = metrics(rows, "baseline_net_bps")
    child = metrics(shared, "risk_shared_net_bps")
    max_concurrency = max(int(x["same_symbol_active_at_entry"]) for x in shared)
    concurrency_counts = dict(sorted(Counter(int(x["same_symbol_active_at_entry"]) for x in shared).items()))

    dd_improved = float(child["realized_exit_bucket_max_drawdown_bps"]) < float(parent["realized_exit_bucket_max_drawdown_bps"])
    ratio_improved = bool(
        child["pnl_to_drawdown"] is not None
        and parent["pnl_to_drawdown"] is not None
        and float(child["pnl_to_drawdown"]) > float(parent["pnl_to_drawdown"])
    )
    pnl_positive = float(child["net_pnl_bps"]) > 0.0
    if dd_improved and ratio_improved and pnl_positive:
        state = "PASS_EXPOSURE_RISK_SHARE_RISK_ADJUSTED_COUNTERFACTUAL"
    elif dd_improved and pnl_positive:
        state = "HOLD_EXPOSURE_RISK_SHARE_DD_IMPROVES_WITH_EFFICIENCY_TRADEOFF"
    else:
        state = "HOLD_EXPOSURE_RISK_SHARE_NO_RISK_ADJUSTED_UPGRADE"

    result = {
        "schema_version": "zel.a1.supertrend.liquid6.exposure_risk_share.v1",
        "state": state,
        "strategy_id": STRATEGY_ID,
        "scope": "FROZEN_PR990_RETROSPECTIVE_COUNTERFACTUAL_ONLY",
        "frozen_source_receipt_sha256": EXPECTED_RECEIPT_SHA256,
        "candidate_id": "supertrend_equal_same_symbol_risk_share_at_entry_v1",
        "changed_axis": "POSITION_RISK_ALLOCATION_ONLY",
        "contract": {
            "entry_signals_changed": False,
            "entry_trade_count_changed": False,
            "exit_geometry_changed": False,
            "stop_changed": False,
            "timeout_changed": False,
            "numeric_threshold_sweep": False,
            "post_outcome_threshold_fitting": False,
            "weight_rule": "1 / concurrent_same_symbol_positions_at_entry_including_self",
            "weight_rule_uses_preentry_position_state_only": True,
            "risk_share_static_for_trade_after_entry": True,
        },
        "parent": parent,
        "risk_shared": child,
        "delta": {
            "net_pnl_bps": float(child["net_pnl_bps"]) - float(parent["net_pnl_bps"]),
            "net_expectancy_bps": float(child["net_expectancy_bps"]) - float(parent["net_expectancy_bps"]),
            "realized_exit_bucket_max_drawdown_bps": float(child["realized_exit_bucket_max_drawdown_bps"]) - float(parent["realized_exit_bucket_max_drawdown_bps"]),
            "pnl_to_drawdown": None if child["pnl_to_drawdown"] is None or parent["pnl_to_drawdown"] is None else float(child["pnl_to_drawdown"]) - float(parent["pnl_to_drawdown"]),
        },
        "pnl_retention": float(child["net_pnl_bps"]) / float(parent["net_pnl_bps"]) if float(parent["net_pnl_bps"]) != 0 else None,
        "dd_improved": dd_improved,
        "pnl_to_drawdown_improved": ratio_improved,
        "all_47_entries_preserved": len(shared) == EXPECTED_COMPLETED_TRADES,
        "win_loss_signs_preserved": [float(x["baseline_net_bps"]) > 0 for x in rows] == [float(x["risk_shared_net_bps"]) > 0 for x in shared],
        "max_same_symbol_concurrency_at_entry": max_concurrency,
        "same_symbol_concurrency_distribution": concurrency_counts,
        "trade_weights": [
            {
                "intent_sha": x["intent_sha"],
                "symbol": x["symbol"],
                "entry_ts": x["entry_ts"],
                "exit_ts": x["exit_ts"],
                "same_symbol_active_at_entry": x["same_symbol_active_at_entry"],
                "risk_share_weight": x["risk_share_weight"],
                "baseline_net_bps": x["baseline_net_bps"],
                "risk_shared_net_bps": x["risk_shared_net_bps"],
            }
            for x in shared
        ],
        "fresh_oos_required_before_any_runtime_use": True,
        "promotion_claim": False,
        "integrity_defects": [],
        "research_only": True,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> int:
    rows = [
        {"intent_sha": "a", "symbol": "BTC-USDT", "entry_ts": 10, "exit_ts": 30, "net_bps": 100.0},
        {"intent_sha": "b", "symbol": "BTC-USDT", "entry_ts": 20, "exit_ts": 40, "net_bps": -50.0},
        {"intent_sha": "c", "symbol": "ETH-USDT", "entry_ts": 20, "exit_ts": 40, "net_bps": 20.0},
    ]
    shared = apply_equal_same_symbol_risk_share(rows)
    by_id = {x["intent_sha"]: x for x in shared}
    assert by_id["a"]["same_symbol_active_at_entry"] == 1 and by_id["a"]["risk_share_weight"] == 1.0
    assert by_id["b"]["same_symbol_active_at_entry"] == 2 and by_id["b"]["risk_share_weight"] == 0.5
    assert by_id["c"]["same_symbol_active_at_entry"] == 1 and by_id["c"]["risk_share_weight"] == 1.0
    assert by_id["b"]["risk_shared_net_bps"] == -25.0
    same_entry = [
        {"intent_sha": "x", "symbol": "BTC-USDT", "entry_ts": 10, "exit_ts": 20, "net_bps": 10.0},
        {"intent_sha": "y", "symbol": "BTC-USDT", "entry_ts": 10, "exit_ts": 30, "net_bps": 20.0},
    ]
    same_shared = apply_equal_same_symbol_risk_share(same_entry)
    assert all(x["same_symbol_active_at_entry"] == 2 and x["risk_share_weight"] == 0.5 for x in same_shared)
    same_bar = [{"intent_sha": "z", "symbol": "SOL-USDT", "entry_ts": 50, "exit_ts": 50, "net_bps": -10.0}]
    same_bar_shared = apply_equal_same_symbol_risk_share(same_bar)
    assert same_bar_shared[0]["same_symbol_active_at_entry"] == 1
    print("PASS_A1_SUPERTREND_LIQUID6_EXPOSURE_RISK_SHARE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt")
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.receipt or not args.out:
        raise SystemExit("--receipt and --out required")
    result = run(read(Path(args.receipt)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "parent": result.get("parent"),
        "risk_shared": result.get("risk_shared"),
        "delta": result.get("delta"),
        "max_same_symbol_concurrency_at_entry": result.get("max_same_symbol_concurrency_at_entry"),
        "integrity_defects": result.get("integrity_defects"),
    }, sort_keys=True))
    return 2 if result.get("integrity_defects") else 0


if __name__ == "__main__":
    raise SystemExit(main())
