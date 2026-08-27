#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "zel.a1.top5.additive_entry_union.v1"
TRADE_KEY_FIELDS = ("symbol", "signal_ts", "entry_ts", "side")
IMMUTABLE_OVERLAP_FIELDS = (
    "symbol", "signal_ts", "entry_ts", "exit_ts", "side",
    "entry", "exit", "gross_bps", "net_bps", "reason",
)


def stable(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def trade_key(trade: Mapping[str, Any]) -> tuple[Any, ...]:
    missing = [field for field in TRADE_KEY_FIELDS if field not in trade]
    if missing:
        raise RuntimeError("TRADE_KEY_FIELDS_MISSING:" + ",".join(missing))
    return tuple(trade[field] for field in TRADE_KEY_FIELDS)


def _trade_map(trades: Sequence[Mapping[str, Any]], label: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in trades:
        trade = dict(raw)
        key = trade_key(trade)
        if key in out:
            raise RuntimeError(f"DUPLICATE_TRADE_KEY:{label}:{key}")
        out[key] = trade
    return out


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(x) for x in trades]
    if not rows:
        return {
            "trades": 0,
            "gross_pnl_bps": 0.0,
            "gross_expectancy_bps": None,
            "net_pnl_bps": 0.0,
            "net_expectancy_bps": None,
            "profit_factor": None,
            "profit_factor_unbounded": False,
            "win_rate": None,
            "drawdown_bps": 0.0,
        }
    net = [float(x["net_bps"]) for x in rows]
    gross = [float(x.get("gross_bps", x["net_bps"])) for x in rows]
    wins = [x for x in net if x > 0.0]
    losses = [-x for x in net if x < 0.0]
    gp = sum(wins)
    gl = sum(losses)
    return {
        "trades": len(rows),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross),
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net),
        "profit_factor": (gp / gl) if gl > 0.0 else None,
        "profit_factor_unbounded": bool(gp > 0.0 and gl == 0.0),
        "win_rate": len(wins) / len(net),
        "drawdown_bps": max_drawdown(net),
    }


def _pf_at_least(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    if bool(candidate.get("profit_factor_unbounded")):
        return True
    baseline_unbounded = bool(baseline.get("profit_factor_unbounded"))
    if baseline_unbounded:
        return bool(candidate.get("profit_factor_unbounded"))
    c = candidate.get("profit_factor")
    b = baseline.get("profit_factor")
    if b is None:
        return True
    return c is not None and float(c) >= float(b)


def _same_overlap_trade(parent: Mapping[str, Any], lane: Mapping[str, Any]) -> bool:
    for field in IMMUTABLE_OVERLAP_FIELDS:
        if field in parent or field in lane:
            if parent.get(field) != lane.get(field):
                return False
    return True


def evaluate(parent_receipt: Mapping[str, Any], lane_receipt: Mapping[str, Any]) -> dict[str, Any]:
    parent_trades = [dict(x) for x in (parent_receipt.get("trades") or [])]
    lane_trades = [dict(x) for x in (lane_receipt.get("trades") or [])]
    if not parent_trades:
        raise RuntimeError("FROZEN_PARENT_TRADES_REQUIRED")

    parent_by = _trade_map(parent_trades, "parent")
    lane_by = _trade_map(lane_trades, "lane")

    overlap_keys = sorted(set(parent_by) & set(lane_by), key=str)
    overlap_mutations = [
        key for key in overlap_keys
        if not _same_overlap_trade(parent_by[key], lane_by[key])
    ]
    added_keys = sorted(set(lane_by) - set(parent_by), key=str)
    added_trades = [lane_by[key] for key in added_keys]

    # The frozen parent is copied verbatim first. The lane can only append unseen trades.
    combined_trades = [dict(x) for x in parent_trades] + [dict(x) for x in added_trades]
    combined_by = _trade_map(combined_trades, "combined")

    parent_preserved_keys = all(key in combined_by for key in parent_by)
    parent_payload_preserved = all(
        combined_by[key] == parent_by[key]
        for key in parent_by
    )
    parent_match_pct = 100.0 * sum(
        1 for key in parent_by if key in combined_by and combined_by[key] == parent_by[key]
    ) / len(parent_by)

    parent_metric = metrics(parent_trades)
    added_metric = metrics(added_trades)
    combined_metric = metrics(combined_trades)

    checks = {
        "parent_match_100pct": parent_preserved_keys and parent_payload_preserved and parent_match_pct == 100.0,
        "overlap_payload_mutations_zero": len(overlap_mutations) == 0,
        "trade_count_increased": len(added_trades) > 0,
        "combined_win_rate_non_decrease": float(combined_metric["win_rate"] or 0.0) >= float(parent_metric["win_rate"] or 0.0),
        "combined_net_pnl_non_decrease": float(combined_metric["net_pnl_bps"] or 0.0) >= float(parent_metric["net_pnl_bps"] or 0.0),
        "combined_expectancy_non_decrease": float(combined_metric["net_expectancy_bps"] or 0.0) >= float(parent_metric["net_expectancy_bps"] or 0.0),
        "combined_pf_non_decrease": _pf_at_least(combined_metric, parent_metric),
        "combined_dd_non_increase": float(combined_metric["drawdown_bps"] or 0.0) <= float(parent_metric["drawdown_bps"] or 0.0),
        "added_win_rate_at_least_parent": bool(added_trades) and float(added_metric["win_rate"] or 0.0) >= float(parent_metric["win_rate"] or 0.0),
        "added_expectancy_at_least_parent": bool(added_trades) and float(added_metric["net_expectancy_bps"] or 0.0) >= float(parent_metric["net_expectancy_bps"] or 0.0),
        "added_pf_at_least_parent": bool(added_trades) and _pf_at_least(added_metric, parent_metric),
        "added_net_pnl_positive": bool(added_trades) and float(added_metric["net_pnl_bps"] or 0.0) > 0.0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    passed = not failed

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_ADD_ONLY_ENTRY_LANE" if passed else "HOLD_ADD_ONLY_ENTRY_LANE",
        "strategy_id": parent_receipt.get("strategy_id") or parent_receipt.get("parent_strategy_id"),
        "mode": "FROZEN_PARENT_PLUS_APPEND_ONLY_NEW_TRADES",
        "parent_trade_count": len(parent_trades),
        "lane_trade_count": len(lane_trades),
        "overlap_trade_count": len(overlap_keys),
        "added_only_trade_count": len(added_trades),
        "combined_trade_count": len(combined_trades),
        "parent_match_pct": parent_match_pct,
        "parent_trade_identity_sha256": stable([trade_key(x) for x in parent_trades]),
        "added_trade_identity_sha256": stable([trade_key(x) for x in added_trades]),
        "combined_trade_identity_sha256": stable([trade_key(x) for x in combined_trades]),
        "overlap_payload_mutation_count": len(overlap_mutations),
        "overlap_payload_mutation_keys": [list(x) for x in overlap_mutations],
        "parent_metrics": parent_metric,
        "added_only_metrics": added_metric,
        "combined_metrics": combined_metric,
        "checks": checks,
        "failed_checks": failed,
        "policy": {
            "frozen_parent_required": True,
            "parent_trade_deletion_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "replacement_child_for_trade_count_expansion_forbidden": True,
            "append_only_new_entry_lane": True,
            "promotion_requires_parent_match_100pct": True,
            "promotion_requires_trade_count_increase": True,
            "promotion_requires_wr_pnl_expectancy_pf_non_decrease": True,
            "promotion_requires_dd_non_increase": True,
            "promotion_requires_added_cohort_quality_at_least_parent": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    p1 = {"symbol": "BTC-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "entry": 100.0, "exit": 102.0, "gross_bps": 120.0, "net_bps": 100.0, "reason": "TP"}
    p2 = {"symbol": "ETH-USDT", "signal_ts": 4, "entry_ts": 5, "exit_ts": 6, "side": "long", "entry": 100.0, "exit": 99.0, "gross_bps": -10.0, "net_bps": -20.0, "reason": "SL"}
    n1 = {"symbol": "SOL-USDT", "signal_ts": 7, "entry_ts": 8, "exit_ts": 9, "side": "long", "entry": 100.0, "exit": 103.0, "gross_bps": 150.0, "net_bps": 120.0, "reason": "TP"}
    n2 = {"symbol": "XRP-USDT", "signal_ts": 10, "entry_ts": 11, "exit_ts": 12, "side": "long", "entry": 100.0, "exit": 102.5, "gross_bps": 130.0, "net_bps": 100.0, "reason": "TP"}
    parent = {"strategy_id": "demo", "trades": [p1, p2]}
    lane = {"strategy_id": "demo", "trades": [p1, p2, n1, n2]}
    good = evaluate(parent, lane)
    assert good["parent_match_pct"] == 100.0
    assert good["added_only_trade_count"] == 2
    assert good["combined_trade_count"] == 4
    assert good["state"] == "PASS_ADD_ONLY_ENTRY_LANE"

    mutated = dict(p1)
    mutated["net_bps"] = 999.0
    bad_overlap = evaluate(parent, {"trades": [mutated, n1, n2]})
    assert bad_overlap["state"] == "HOLD_ADD_ONLY_ENTRY_LANE"
    assert bad_overlap["checks"]["overlap_payload_mutations_zero"] is False

    low = {"symbol": "DOGE-USDT", "signal_ts": 13, "entry_ts": 14, "exit_ts": 15, "side": "long", "entry": 100.0, "exit": 99.0, "gross_bps": -50.0, "net_bps": -60.0, "reason": "SL"}
    bad_quality = evaluate(parent, {"trades": [low]})
    assert bad_quality["parent_match_pct"] == 100.0
    assert bad_quality["state"] == "HOLD_ADD_ONLY_ENTRY_LANE"
    assert bad_quality["checks"]["combined_win_rate_non_decrease"] is False
    print("PASS_A1_TOP5_ADDITIVE_ENTRY_UNION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--lane", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_additive_entry_union_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None or args.lane is None:
        raise RuntimeError("--parent and --lane required")
    result = evaluate(read(args.parent), read(args.lane))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("A1_TOP5_ADDITIVE_ENTRY_UNION=" + json.dumps({
        "state": result["state"],
        "parent_trade_count": result["parent_trade_count"],
        "added_only_trade_count": result["added_only_trade_count"],
        "combined_trade_count": result["combined_trade_count"],
        "parent_match_pct": result["parent_match_pct"],
        "failed_checks": result["failed_checks"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
