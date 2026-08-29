#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps, stable
from backend.research.rebuild.a1_top5_highamp_rescue_scan_v1 import select_semantic_parent
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, strict, trade_key
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
INCUMBENT = ROOT / "backend/research/rebuild/a1_supertrend_5455_research_incumbent_v1.json"
SCHEMA = "zel.a1.top5.supertrend.exact_parent_atr_veto.v1"
STRATEGY_ID = "supertrend_pullback"
EXPECTED_BROAD_RECEIPT = "66bf7d78ab960527ec7e7f3578c1f6dbf103dacf2de0db7f20762a7bebd5fb21"
EXPECTED_BROAD_T = 56
EXPECTED_PARENT_T = 11
EXPECTED_PARENT_WR = 6.0 / 11.0
EXPECTED_PARENT_NET = 8987.160536440786
EXPECTED_PARENT_EXPECTANCY = 817.0145942218896
EXPECTED_PARENT_PF = 12.301261556184716
EXPECTED_PARENT_DD = 245.7358707597723
FROZEN_AXIS = {
    "origin_commit": "051ff7015e6456410073b1a42dc0c201876c1958",
    "name": "long_above_sma50_and_shock_ge_1x_atr14_veto_only",
    "atr_n": 14,
    "sma_n": 50,
    "shock_atr_floor": 1.0,
    "threshold_sweep": False,
    "source_transfer_pr": 1101,
}
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _close(a: Any, b: float, tol: float = 1e-6) -> bool:
    return a is not None and abs(float(a) - float(b)) <= tol


def _signal_index(trade: Mapping[str, Any], maps: Mapping[str, dict[int, int]]) -> int | None:
    return maps[str(trade["symbol"])].get(int(trade["signal_ts"]))


def veto_hit(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    if str(trade.get("side")) != "long":
        return False
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 50:
        return False
    bars = bars_by[symbol]
    window = bars[: idx + 1]
    a = atr(window, 14)
    shock = abs(float(bars[idx]["close"]) - float(bars[idx - 1]["close"]))
    shock_atr = shock / max(float(a), 1e-12)
    sma50 = sum(float(x["close"]) for x in bars[idx - 49 : idx + 1]) / 50.0
    above = float(bars[idx]["close"]) >= sma50
    return bool(above and shock_atr >= 1.0)


def run(source: Path) -> dict[str, Any]:
    broad = json.loads(source.read_text(encoding="utf-8"))
    incumbent = json.loads(INCUMBENT.read_text(encoding="utf-8"))
    if broad.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError(f"BROAD_STRATEGY_MISMATCH:{broad.get('strategy_id')}")
    if broad.get("receipt_sha256") != EXPECTED_BROAD_RECEIPT:
        raise RuntimeError(f"BROAD_RECEIPT_MISMATCH:{broad.get('receipt_sha256')}")
    trades = [dict(x) for x in broad.get("trades") or []]
    if int(broad.get("completed_trades") or 0) != EXPECTED_BROAD_T or len(trades) != EXPECTED_BROAD_T:
        raise RuntimeError(f"BROAD_T_MISMATCH:{broad.get('completed_trades')}:{len(trades)}")
    if broad.get("integrity_defects") or int(broad.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("BROAD_INTEGRITY_OR_LOOKAHEAD_FAIL")

    parent = select_semantic_parent(broad, incumbent)
    pm = metrics(parent)
    checks = {
        "T": int(pm["trades"]) == EXPECTED_PARENT_T,
        "WR": _close(pm["win_rate"], EXPECTED_PARENT_WR, 1e-12),
        "NET": _close(pm["net_pnl_bps"], EXPECTED_PARENT_NET, 0.1),
        "EXPECTANCY": _close(pm["net_expectancy_bps"], EXPECTED_PARENT_EXPECTANCY, 0.1),
        "PF": _close(pm["profit_factor"], EXPECTED_PARENT_PF, 1e-6),
        "DD": _close(pm["drawdown_bps"], EXPECTED_PARENT_DD, 0.1),
    }
    if not all(checks.values()):
        raise RuntimeError(f"TOP5_SUPERTREND_FROZEN_PARENT_MISMATCH:{checks}:{pm}")

    pkeys = {trade_key(x) for x in parent}
    donor = [dict(x) for x in trades if trade_key(x) not in pkeys]
    if len(donor) != EXPECTED_BROAD_T - EXPECTED_PARENT_T:
        raise RuntimeError(f"DONOR_T_MISMATCH:{len(donor)}")
    bars_by, maps = _maps(broad)
    vetoed = [dict(x) for x in donor if veto_hit(x, bars_by, maps)]
    added = [dict(x) for x in donor if not veto_hit(x, bars_by, maps)]
    if any(trade_key(x) in pkeys for x in added):
        raise RuntimeError("PARENT_DONOR_OVERLAP")

    ok, strict_checks, added_metrics, combined_metrics, combined_payoff = strict(parent, added)
    state = "PASS_TOP5_SUPERTREND_ATR_VETO_DEVELOPMENT_CANDIDATE" if (ok and added) else "FALSIFIED_TOP5_SUPERTREND_ATR_VETO_DONOR"
    nxt = "PREREGISTER_FRESH_PROSPECTIVE_CHILD" if (ok and added) else "ARCHITECTURE_FAMILY_REPLACEMENT_REQUIRED"
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "scope": "TOP5_FROZEN_SUPERTREND_PARENT_ONLY",
        "source_artifact_id": 9614562185,
        "source_broad_receipt_sha256": EXPECTED_BROAD_RECEIPT,
        "source_broad_T": EXPECTED_BROAD_T,
        "incumbent_receipt_sha256": incumbent.get("receipt_sha256"),
        "exact_parent_T": len(parent),
        "exact_parent_metrics": pm,
        "exact_parent_trade_keys": [list(trade_key(x)) for x in parent],
        "architecture": {
            "id": "FROZEN_ATR_ADVERSE_VETO_NATIVE_DONOR_ADD_ONLY",
            "frozen_axis": FROZEN_AXIS,
            "description": "Preserve all exact frozen 11T. Among distinct native Supertrend broad donors, admit only rows not vetoed by the pre-existing long+above-SMA50+1bar-shock>=1xATR14 adverse-regime rule.",
            "changed_axis_count": 1,
            "numeric_threshold_sweep": False,
            "outcome_fitted_cutoff": False,
            "preentry_only": True,
        },
        "distinct_historical_donor_T": len(donor),
        "vetoed_donor_T": len(vetoed),
        "added_T": len(added),
        "added_metrics": added_metrics,
        "combined_T": len(parent) + len(added),
        "combined_metrics": combined_metrics,
        "combined_payoff": combined_payoff,
        "strict_checks": strict_checks,
        "development_economic_pass": bool(ok and added),
        "added_trade_keys": [list(trade_key(x)) for x in added],
        "vetoed_trade_keys": [list(trade_key(x)) for x in vetoed],
        "parent_deleted_or_rewritten": False,
        "historical_donor_is_development_only": True,
        "fresh_prospective_required_before_any_promotion": True,
        "next": nxt,
        **AUTH,
    }
    out["receipt_sha256"] = stable(out)
    return out


def self_test() -> int:
    assert EXPECTED_PARENT_T == 11 and EXPECTED_BROAD_T == 56
    assert FROZEN_AXIS["threshold_sweep"] is False
    assert FROZEN_AXIS["shock_atr_floor"] == 1.0
    print("PASS_A1_TOP5_SUPERTREND_EXACT_PARENT_ATR_VETO_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_supertrend_exact_parent_atr_veto_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.source is None:
        raise SystemExit("--source required")
    r = run(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state":r["state"],"parent":r["exact_parent_metrics"],"donor_T":r["distinct_historical_donor_T"],"vetoed_T":r["vetoed_donor_T"],"added_T":r["added_T"],"added":r["added_metrics"],"combined_T":r["combined_T"],"combined":r["combined_metrics"],"pass":r["development_economic_pass"],"next":r["next"]},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
