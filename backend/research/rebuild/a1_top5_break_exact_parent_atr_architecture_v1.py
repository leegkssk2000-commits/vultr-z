#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import (
    _maps,
    keep_liquidity,
    keep_volatility_regime,
    stable,
)
from backend.research.rebuild.a1_top5_highamp_rescue_scan_v1 import select_break_parent
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, strict, trade_key

SCHEMA = "zel.a1.top5.break.exact_parent_atr_architecture.v1"
STRATEGY_ID = "break_and_continue"
EXPECTED_BROAD_RECEIPT = "401cc362e0ad9a4fc0f7d076c9827b5cfdb8e1ae8713918890605bb40069ecaf"
EXPECTED_BROAD_T = 51
EXPECTED_PARENT_T = 9
EXPECTED_PARENT_WR = 5.0 / 9.0
EXPECTED_PARENT_NET = 9063.67059948244
EXPECTED_PARENT_EXPECTANCY = 1007.0745110536045
EXPECTED_PARENT_PF = 16.457706602258355
EXPECTED_PARENT_PAYOFF = 13.166165281806684
EXPECTED_PARENT_DD = 586.3528680353038
ROOT_EVIDENCE = {
    "axis": "ATR_PCT",
    "loss_streak_mean": 0.8376500872866031,
    "winner_reference_mean": 0.537195908600973,
    "relative_delta": 0.5593009437992691,
    "source_pr": 1096,
}
CANDIDATE_ORDER = (
    "COOL_VOL_DONOR_ADD_ONLY",
    "COOL_VOL_LIQUID_DONOR_ADD_ONLY",
)
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


def _assert_parent(parent: list[dict[str, Any]]) -> dict[str, Any]:
    m = metrics(parent)
    parent_payoff = payoff(parent)
    checks = {
        "T": int(m["trades"]) == EXPECTED_PARENT_T,
        "WR": _close(m["win_rate"], EXPECTED_PARENT_WR, 1e-12),
        "NET": _close(m["net_pnl_bps"], EXPECTED_PARENT_NET, 0.1),
        "EXPECTANCY": _close(m["net_expectancy_bps"], EXPECTED_PARENT_EXPECTANCY, 0.1),
        "PF": _close(m["profit_factor"], EXPECTED_PARENT_PF, 1e-6),
        "PAYOFF": _close(parent_payoff, EXPECTED_PARENT_PAYOFF, 1e-6),
        "DD": _close(m["drawdown_bps"], EXPECTED_PARENT_DD, 0.1),
    }
    if not all(checks.values()):
        raise RuntimeError(f"TOP5_BREAK_FROZEN_PARENT_MISMATCH:{checks}:{m}:payoff={parent_payoff}")
    return {**m, "payoff": parent_payoff}


def _candidate(name: str, parent: list[dict[str, Any]], donor: list[dict[str, Any]], broad: dict[str, Any], bars_by: dict[str, list[dict[str, Any]]], maps: dict[str, dict[int, int]]) -> dict[str, Any]:
    if name == "COOL_VOL_DONOR_ADD_ONLY":
        added = [dict(x) for x in donor if not keep_volatility_regime(x, bars_by, maps)]
        mechanism = "Frozen Top5 parent preserved; admit only historical donor rows where frozen ATR14<ATR50 volatility regime is cool. This is the qualitative complement of the pre-existing A5 volatility owner geometry; no ATR_PCT numeric cutoff is derived from outcomes."
        changed_axis_count = 1
    elif name == "COOL_VOL_LIQUID_DONOR_ADD_ONLY":
        added = [dict(x) for x in donor if (not keep_volatility_regime(x, bars_by, maps)) and keep_liquidity(x, bars_by, maps)]
        mechanism = "Frozen Top5 parent preserved; cool-volatility donor rows additionally require the pre-existing current quote-liquidity >= prior20 median confirmation. Both geometries predate this result; no numeric sweep."
        changed_axis_count = 2
    else:
        raise RuntimeError(f"UNKNOWN_CANDIDATE:{name}")

    pkeys = {trade_key(x) for x in parent}
    if any(trade_key(x) in pkeys for x in added):
        raise RuntimeError(f"PARENT_DONOR_OVERLAP:{name}")
    ok, checks, added_metrics, combined_metrics, combined_payoff = strict(parent, added)
    return {
        "candidate_id": name,
        "mechanism": mechanism,
        "changed_axis_count": changed_axis_count,
        "added_T": len(added),
        "added_metrics": added_metrics,
        "combined_T": len(parent) + len(added),
        "combined_metrics": combined_metrics,
        "combined_payoff": combined_payoff,
        "strict_checks": checks,
        "development_economic_pass": bool(ok and len(added) > 0),
        "added_trade_keys": [list(trade_key(x)) for x in added],
        "old_history_is_development_only": True,
        "promotion_evidence": False,
    }


def run(source: Path) -> dict[str, Any]:
    broad = json.loads(source.read_text(encoding="utf-8"))
    if broad.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError(f"BROAD_STRATEGY_MISMATCH:{broad.get('strategy_id')}")
    if broad.get("receipt_sha256") != EXPECTED_BROAD_RECEIPT:
        raise RuntimeError(f"BROAD_RECEIPT_MISMATCH:{broad.get('receipt_sha256')}")
    trades = [dict(x) for x in broad.get("trades") or []]
    if int(broad.get("completed_trades") or 0) != EXPECTED_BROAD_T or len(trades) != EXPECTED_BROAD_T:
        raise RuntimeError(f"BROAD_T_MISMATCH:{broad.get('completed_trades')}:{len(trades)}")
    if broad.get("integrity_defects"):
        raise RuntimeError(f"BROAD_INTEGRITY_DEFECT:{broad.get('integrity_defects')}")
    if int(broad.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("BROAD_LOOKAHEAD_NONZERO")

    parent = select_break_parent(broad)
    parent_metrics = _assert_parent(parent)
    pkeys = {trade_key(x) for x in parent}
    donor = [dict(x) for x in trades if trade_key(x) not in pkeys]
    if len(donor) != EXPECTED_BROAD_T - EXPECTED_PARENT_T:
        raise RuntimeError(f"DONOR_T_MISMATCH:{len(donor)}")

    bars_by, maps = _maps(broad)
    candidates = [_candidate(name, parent, donor, broad, bars_by, maps) for name in CANDIDATE_ORDER]
    passing = [x for x in candidates if x["development_economic_pass"]]
    selected = next((x for name in CANDIDATE_ORDER for x in candidates if x["candidate_id"] == name and x["development_economic_pass"]), None)

    if selected is None:
        state = "FALSIFIED_TOP5_BREAK_COOL_VOL_DONOR_ARCHITECTURES"
        nxt = "ARCHITECTURE_REPLACEMENT_NEXT_DISTINCT_MECHANISM"
    else:
        state = "PASS_TOP5_BREAK_EXACT_PARENT_DEVELOPMENT_CANDIDATE"
        nxt = "PREREGISTER_SELECTED_CANDIDATE_FRESH_PROSPECTIVE_FROM_POST_MERGE_BOUNDARY"

    out = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "scope": "TOP5_FROZEN_BREAK_PARENT_ONLY",
        "source_artifact_id": 9603011773,
        "source_broad_receipt_sha256": EXPECTED_BROAD_RECEIPT,
        "source_broad_T": EXPECTED_BROAD_T,
        "exact_parent_reconstruction": "PR1051_SELECT_UTC_13_14_15_FROM_IMMUTABLE_BROAD",
        "exact_parent_T": len(parent),
        "exact_parent_metrics": parent_metrics,
        "exact_parent_trade_keys": [list(trade_key(x)) for x in parent],
        "distinct_historical_donor_T": len(donor),
        "root_evidence": ROOT_EVIDENCE,
        "candidate_order_preregistered": list(CANDIDATE_ORDER),
        "candidates": candidates,
        "development_pass_count": len(passing),
        "selected_candidate": selected,
        "numeric_threshold_sweep": False,
        "outcome_fitted_atr_pct_cutoff": False,
        "frozen_parent_deleted_or_rewritten": False,
        "historical_donor_union_promotable": False,
        "fresh_prospective_required_before_any_promotion": True,
        "next": nxt,
        **AUTH,
    }
    out["receipt_sha256"] = stable(out)
    return out


def self_test() -> int:
    assert CANDIDATE_ORDER[0] == "COOL_VOL_DONOR_ADD_ONLY"
    assert ROOT_EVIDENCE["relative_delta"] > 0.5
    assert EXPECTED_PARENT_T == 9 and EXPECTED_BROAD_T == 51
    print("PASS_A1_TOP5_BREAK_EXACT_PARENT_ATR_ARCHITECTURE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_break_exact_parent_atr_architecture_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.source is None:
        raise SystemExit("--source required")
    r = run(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "parent_T": r["exact_parent_T"],
        "parent": r["exact_parent_metrics"],
        "candidates": [{"id": x["candidate_id"], "added_T": x["added_T"], "combined_T": x["combined_T"], "pass": x["development_economic_pass"], "combined": x["combined_metrics"]} for x in r["candidates"]],
        "selected": None if r["selected_candidate"] is None else r["selected_candidate"]["candidate_id"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
