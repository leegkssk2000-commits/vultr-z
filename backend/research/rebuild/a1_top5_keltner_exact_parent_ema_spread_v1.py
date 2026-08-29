#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps, stable
from backend.research.rebuild.a1_top5_highamp_rescue_scan_v1 import select_semantic_parent
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, strict, trade_key
from backend.research.rebuild.policy_kernel_v1 import ema

ROOT = Path(__file__).resolve().parents[3]
INCUMBENT = ROOT / "backend/research/rebuild/a1_keltner_58pct_research_incumbent_v1.json"
SCHEMA = "zel.a1.top5.keltner.exact_parent_ema_spread.v1"
STRATEGY_ID = "keltner_trend"
EXPECTED_BROAD_RECEIPT = "66a477f40f0d71a6f90513aecde150427692345e4872c6d9820e7e871e781c38"
EXPECTED_BROAD_T = 60
EXPECTED_PARENT_T = 12
EXPECTED_PARENT_WR = 7.0 / 12.0
EXPECTED_PARENT_NET = 16213.02695520102
EXPECTED_PARENT_EXPECTANCY = 1351.0855796000849
EXPECTED_PARENT_PF = 31.35081608201582
EXPECTED_PARENT_DD = 212.6882556068265
ROOT_EVIDENCE = {
    "axis": "EMA_SPREAD_ATR",
    "loss_streak_mean": 1.0216371216023135,
    "winner_reference_mean": 1.8726828294294766,
    "relative_delta": -0.45445266782653154,
    "source": "a1_keltner_loss_preentry_attribution_latest.json",
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


def keep_directional_ema_spread_widening(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"])
    idx = _signal_index(trade, maps)
    if idx is None or idx < 56:
        return False
    closes = [float(x["close"]) for x in bars_by[symbol][: idx + 1]]
    e21 = ema(closes, 21)
    e55 = ema(closes, 55)
    now = float(e21[-1] - e55[-1])
    prev = float(e21[-2] - e55[-2])
    side = str(trade["side"])
    aligned = (side == "long" and now > 0.0) or (side == "short" and now < 0.0)
    return aligned and abs(now) > abs(prev)


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
        raise RuntimeError(f"TOP5_KELTNER_FROZEN_PARENT_MISMATCH:{checks}:{pm}")

    pkeys = {trade_key(x) for x in parent}
    donor = [dict(x) for x in trades if trade_key(x) not in pkeys]
    if len(donor) != EXPECTED_BROAD_T - EXPECTED_PARENT_T:
        raise RuntimeError(f"DONOR_T_MISMATCH:{len(donor)}")
    bars_by, maps = _maps(broad)
    added = [dict(x) for x in donor if keep_directional_ema_spread_widening(x, bars_by, maps)]
    if any(trade_key(x) in pkeys for x in added):
        raise RuntimeError("PARENT_DONOR_OVERLAP")

    ok, strict_checks, added_metrics, combined_metrics, combined_payoff = strict(parent, added)
    state = "PASS_TOP5_KELTNER_EMA_SPREAD_DEVELOPMENT_CANDIDATE" if (ok and added) else "FALSIFIED_TOP5_KELTNER_EMA_SPREAD_WIDENING_DONOR"
    nxt = "PREREGISTER_FRESH_PROSPECTIVE_CHILD" if (ok and added) else "ROUTE_TO_DISTINCT_ARCHITECTURE_OR_SUPERTREND"
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "scope": "TOP5_FROZEN_KELTNER_PARENT_ONLY",
        "source_artifact_id": 9614562185,
        "source_broad_receipt_sha256": EXPECTED_BROAD_RECEIPT,
        "source_broad_T": EXPECTED_BROAD_T,
        "incumbent_receipt_sha256": incumbent.get("receipt_sha256"),
        "exact_parent_T": len(parent),
        "exact_parent_metrics": pm,
        "exact_parent_trade_keys": [list(trade_key(x)) for x in parent],
        "root_evidence": ROOT_EVIDENCE,
        "architecture": {
            "id": "DIRECTIONAL_EMA21_55_SPREAD_WIDENING_DONOR_ADD_ONLY",
            "description": "Preserve all frozen 12T. Admit only distinct donor rows where EMA21/EMA55 is directionally aligned with trade side and absolute separation is wider than on the immediately prior closed bar.",
            "numeric_threshold_sweep": False,
            "outcome_fitted_cutoff": False,
            "changed_axis_count": 1,
            "preentry_only": True,
        },
        "distinct_historical_donor_T": len(donor),
        "added_T": len(added),
        "added_metrics": added_metrics,
        "combined_T": len(parent) + len(added),
        "combined_metrics": combined_metrics,
        "combined_payoff": combined_payoff,
        "strict_checks": strict_checks,
        "development_economic_pass": bool(ok and added),
        "added_trade_keys": [list(trade_key(x)) for x in added],
        "parent_deleted_or_rewritten": False,
        "historical_donor_is_development_only": True,
        "fresh_prospective_required_before_any_promotion": True,
        "next": nxt,
        **AUTH,
    }
    out["receipt_sha256"] = stable(out)
    return out


def self_test() -> int:
    assert EXPECTED_PARENT_T == 12 and EXPECTED_BROAD_T == 60
    assert ROOT_EVIDENCE["relative_delta"] < -0.4
    assert AUTH["execution_authority"] == "NONE"
    print("PASS_A1_TOP5_KELTNER_EXACT_PARENT_EMA_SPREAD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_keltner_exact_parent_ema_spread_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.source is None:
        raise SystemExit("--source required")
    r = run(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state":r["state"],"parent":r["exact_parent_metrics"],"added_T":r["added_T"],"added":r["added_metrics"],"combined_T":r["combined_T"],"combined":r["combined_metrics"],"pass":r["development_economic_pass"],"next":r["next"]},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
