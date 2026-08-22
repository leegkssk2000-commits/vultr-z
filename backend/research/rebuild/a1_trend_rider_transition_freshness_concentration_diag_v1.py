#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as ab
from backend.research.rebuild import a1_trend_rider_momentum_ab_v1 as helper
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.policy_kernel_v1 import atr

SCHEMA = "zel.a1_trend_rider_transition_freshness_concentration_diag.v1"
MIN_MATURE = 25
POLICY_PATH = Path("backend/research/zel_economic_hardening_policy_v1.json")


def _session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


def _window(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _group_rows(trades: list[dict], fn, total_profit_bps: float) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for x in trades:
        groups.setdefault(str(fn(x)), []).append(x)
    out = []
    for key, xs in sorted(groups.items()):
        net_bps = sum(float(x["net_bps"]) for x in xs)
        pos_bps = sum(max(0.0, float(x["net_bps"])) for x in xs)
        out.append({
            "group": key,
            "trade_count": len(xs),
            "net_R": net_bps / 100.0,
            "profit_share": pos_bps / total_profit_bps if total_profit_bps > 0 else 0.0,
        })
    return out


def run(out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="trend_transition_concentration_") as td:
        child_path = Path(td) / "child.json"
        child = ab._run_exact(child_path, child=True)

    if child.get("strategy_id") != "trend_rider":
        raise RuntimeError("STRATEGY_ID_MISMATCH")
    if child.get("execution_authority") != "NONE" or child.get("order_authority") != "BLOCKED" or child.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("AUTHORITY_BOUNDARY_VIOLATION")
    if list(child.get("integrity_defects") or []):
        raise RuntimeError("CHILD_INTEGRITY_DEFECT")
    if int(child.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("CHILD_LOOKAHEAD_DEFECT")

    trades = list(child.get("trades") or [])
    completed = int(child.get("completed_trades") or 0)
    if len(trades) != completed or completed <= 0:
        raise RuntimeError("TRADE_COUNT_MISMATCH")

    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {sym: ev.fetch_bars(sym, "1h", 1000) for sym in symbols}
    maps = {sym: {int(b["ts_ms"]): i for i, b in enumerate(bs)} for sym, bs in bars_by.items()}

    def regime(x: dict) -> str:
        sym = str(x["symbol"])
        i = maps[sym][int(x["signal_ts"])]
        bs = bars_by[sym]
        return "VOL_HIGH" if atr(bs[: i + 1], 14) >= atr(bs[: i + 1], 50) else "VOL_LOW"

    total_profit_bps = sum(max(0.0, float(x["net_bps"])) for x in trades)
    total_net_R = sum(float(x["net_bps"]) for x in trades) / 100.0
    groupers = {
        "symbol": lambda x: x["symbol"],
        "regime": regime,
        "side": lambda x: x["side"],
        "session": lambda x: _session(int(x["signal_ts"])),
        "window": lambda x: _window(int(x["entry_ts"])),
    }
    dimensions = {name: _group_rows(trades, fn, total_profit_bps) for name, fn in groupers.items()}

    loo = []
    for dim, rows in dimensions.items():
        for row in rows:
            loo.append({
                "dimension": dim,
                "group": row["group"],
                "net_R": total_net_R - float(row["net_R"]),
            })

    top10 = (
        sum(sorted((max(0.0, float(x["net_bps"])) for x in trades), reverse=True)[:10]) / total_profit_bps
        if total_profit_bps > 0 else 0.0
    )
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    h5p = policy["h5_concentration_fragility"]
    max_symbol = max((float(x["profit_share"]) for x in dimensions["symbol"]), default=0.0)
    max_regime = max((float(x["profit_share"]) for x in dimensions["regime"]), default=0.0)
    min_loo = min((float(x["net_R"]) for x in loo), default=0.0)

    blockers = []
    if max_symbol > float(h5p["maximum_single_symbol_profit_share"]):
        blockers.append("SINGLE_SYMBOL_CONCENTRATION")
    if max_regime > float(h5p["maximum_single_regime_profit_share"]):
        blockers.append("SINGLE_REGIME_CONCENTRATION")
    if top10 > float(h5p["maximum_top10_trade_profit_share"]):
        blockers.append("TOP10_TRADE_CONCENTRATION")
    if min_loo < float(h5p["minimum_leave_one_group_out_net_R"]):
        blockers.append("LEAVE_ONE_GROUP_OUT_NON_POSITIVE")

    row = {
        "schema_version": SCHEMA,
        "state": "DIAG_FRESH_TRANSITION_CONCENTRATION_ONLY",
        "strategy_id": "trend_rider",
        "changed_axis": "TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY",
        "completed_trades": completed,
        "minimum_mature_hardening_trades": MIN_MATURE,
        "mature_budget_ready": completed >= MIN_MATURE,
        "diagnostic_only": True,
        "survivor_improvement_claim_allowed": False,
        "child_current_receipt_sha256": child.get("receipt_sha256"),
        "child_current_metrics": child.get("metrics"),
        "dimensions": dimensions,
        "top10_trade_profit_share": top10,
        "leave_one_group_out": loo,
        "diagnostic_blockers_if_thresholds_were_applied": blockers,
        "thresholds": {
            "maximum_single_symbol_profit_share": h5p["maximum_single_symbol_profit_share"],
            "maximum_single_regime_profit_share": h5p["maximum_single_regime_profit_share"],
            "maximum_top10_trade_profit_share": h5p["maximum_top10_trade_profit_share"],
            "minimum_leave_one_group_out_net_R": h5p["minimum_leave_one_group_out_net_R"],
        },
        "source_quality_state": (child.get("source_quality_gate") or {}).get("state") if isinstance(child.get("source_quality_gate"), dict) else None,
        "integrity_defects": list(child.get("integrity_defects") or []),
        "leakage_lookahead": int(child.get("leakage_lookahead") or 0),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "WAIT_FOR_25_THEN_USE_CANONICAL_H4_H5;_IF_FAIL_ROUTE_TO_DISTINCT_CONCENTRATION_CAUSAL_AXIS",
    }
    row["receipt_sha256"] = helper._sha(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return row


def self_test() -> int:
    assert MIN_MATURE == 25
    assert SCHEMA.endswith("concentration_diag.v1")
    print("PASS_A1_TREND_RIDER_TRANSITION_FRESHNESS_CONCENTRATION_DIAG_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_transition_freshness_concentration_diag_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    row = run(args.out)
    print("A1_TRANSITION_FRESHNESS_CONCENTRATION_DIAG=" + json.dumps({
        "state": row["state"],
        "trades": row["completed_trades"],
        "mature_budget_ready": row["mature_budget_ready"],
        "top10": row["top10_trade_profit_share"],
        "blockers": row["diagnostic_blockers_if_thresholds_were_applied"],
        "symbol": row["dimensions"]["symbol"],
        "regime": row["dimensions"]["regime"],
        "side": row["dimensions"]["side"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
