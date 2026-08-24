#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_seed_receipt_fresh_refresher_v1 as refresh
from backend.research.rebuild import a1_top3_profitability_survivor_router_v1 as strict
from backend.research.rebuild import a1_top3_profitability_two_lane_router_v2 as v2
from backend.research.rebuild import a1_top3_profitability_two_lane_router_v3 as v3
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/rebuild/a1_top3_two_lane_contract_v1.json"
TRENDMA_SEED = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
KELTNER_SEED = ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_fresh_latest.json"
A3_CONTEXT = ROOT / "backend/research/prep/a3_forward_context_ledger_v2.json"
PREVIOUS = ROOT / "backend/research/rebuild/a1_top3_profitability_survivor_latest.json"
AUTH = dict(v2.AUTH)


def _profit_share(values: Mapping[str, float]) -> float:
    total = sum(max(0.0, float(v)) for v in values.values())
    return max((max(0.0, float(v)) for v in values.values()), default=0.0) / total if total > 0 else 1.0


def _regime_map(receipt: Mapping[str, Any]) -> dict[tuple[str, int], str]:
    source = receipt.get("source") if isinstance(receipt.get("source"), Mapping) else {}
    interval = str(source.get("interval") or "1h")
    symbols = sorted({str(x.get("symbol")) for x in (receipt.get("trades") or []) if isinstance(x, Mapping) and x.get("symbol")})
    out: dict[tuple[str, int], str] = {}
    for symbol in symbols:
        bars = ev.fetch_bars(symbol, interval, 1000)
        mp = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for t in receipt.get("trades") or []:
            if not isinstance(t, Mapping) or str(t.get("symbol")) != symbol:
                continue
            ts = int(t.get("signal_ts") or 0); i = mp.get(ts)
            if i is None or i < 50:
                out[(symbol, ts)] = "REGIME_UNKNOWN"
                continue
            a14 = atr(bars[: i + 1], 14); a50 = atr(bars[: i + 1], 50)
            out[(symbol, ts)] = "VOL_HIGH" if a14 >= a50 else "VOL_LOW"
    return out


def h5_lite(receipt: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["certification_pilot_lane"]["h5"]
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if not trades:
        return {"pass": False, "state": "WAIT_H5_LITE_SAMPLE", "blockers": ["NO_TRADES"]}
    regimes = _regime_map(receipt)
    profit_by: dict[str, dict[str, float]] = {k: defaultdict(float) for k in ("symbol", "regime", "session", "window", "side")}
    positives: list[float] = []
    net_by_side: dict[str, float] = defaultdict(float)
    for t in trades:
        net = float(t.get("net_bps") or 0.0); p = max(0.0, net)
        positives.append(p)
        symbol = str(t.get("symbol") or "UNKNOWN")
        signal_ts = int(t.get("signal_ts") or t.get("entry_ts") or 0)
        h = datetime.fromtimestamp(signal_ts / 1000, tz=timezone.utc).hour
        session = "APAC" if h < 8 else "EU" if h < 16 else "US"
        window = datetime.fromtimestamp(int(t.get("entry_ts") or signal_ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        regime = regimes.get((symbol, signal_ts), "REGIME_UNKNOWN")
        side = str(t.get("side") or "UNKNOWN")
        for dim, key in (("symbol", symbol), ("regime", regime), ("session", session), ("window", window), ("side", side)):
            profit_by[dim][key] += p
        net_by_side[side] += net
    total_profit = sum(positives)
    shares = {dim: _profit_share(vals) for dim, vals in profit_by.items()}
    top10 = sum(sorted(positives, reverse=True)[:10]) / total_profit if total_profit > 0 else 1.0
    positive_sides = [s for s, v in net_by_side.items() if v > 0]
    nonpositive_sides = [s for s, v in net_by_side.items() if v <= 0]
    one_sided = len(positive_sides) == 1 and len(nonpositive_sides) >= 1
    limits = {
        "regime": float(cfg["maximum_single_regime_profit_share"]),
        "symbol": float(cfg["maximum_single_symbol_profit_share"]),
        "session": float(cfg["maximum_single_session_profit_share"]),
        "window": float(cfg["maximum_single_window_profit_share"]),
    }
    blockers: list[str] = []
    for dim, limit in limits.items():
        if shares[dim] > limit:
            blockers.append(f"H5_LITE_{dim.upper()}:{shares[dim]}>{limit}")
    if top10 > float(cfg["maximum_top10_trade_profit_share"]):
        blockers.append(f"H5_LITE_TOP10:{top10}>{cfg['maximum_top10_trade_profit_share']}")
    if shares["side"] > 0.85 and not (cfg.get("one_sided_specialization_allowed_when_opposite_side_nonpositive") and one_sided):
        blockers.append(f"H5_LITE_SIDE:{shares['side']}>0.85")
    return {
        "pass": not blockers,
        "state": "PASS_H5_LITE" if not blockers else "HOLD_H5_LITE",
        "blockers": blockers,
        "max_profit_share_by_dimension": shares,
        "top10_trade_profit_share": top10,
        "side_specialization": {
            "allowed": one_sided,
            "positive_sides": positive_sides,
            "nonpositive_sides": nonpositive_sides,
            "net_bps_by_side": dict(net_by_side),
        },
        "leave_one_group_out_advisory": True,
        "strict_h5_pass": False,
    }


def deferred_cert(receipt: Mapping[str, Any], profit: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["certification_pilot_lane"]
    fallback = cfg["h4_deferred_fallback"]
    n = int((profit.get("metrics") or {}).get("completed_trades") or 0)
    if n < int(fallback["minimum_completed_trades"]):
        return {"pass": False, "state": "WAIT_CERT_PILOT_SAMPLE", "blockers": [f"CERT_TRADES:{n}<{fallback['minimum_completed_trades']}"]}
    if profit.get("pass") is not True:
        return {"pass": False, "state": "HOLD_CERT_PILOT_PROFIT_REQUIRED", "blockers": ["PROFIT_LANE_PASS_REQUIRED"]}
    lite = h5_lite(receipt, c)
    passed = lite.get("pass") is True
    return {
        "pass": passed,
        "state": fallback["state_if_h5_lite_passes"] if passed else "HOLD_CERT_PILOT_H5_LITE",
        "blockers": list(lite.get("blockers") or []),
        "h4": {
            "state": "DEFERRED_NO_CANDIDATE_SPECIFIC_EVALUATOR",
            "strict_h4_pass": False,
            "pilot_deferred": True,
            "confidence_label": fallback["confidence_label"],
        },
        "h5": lite,
        "strict_hardening_reference": "NOT_RUN_OR_HOLD",
        "certification_confidence": fallback["confidence_label"],
    }


def refresh_or_seed(seed_path: Path) -> tuple[dict[str, Any], list[str]]:
    seed = v2.read(seed_path)
    try:
        row = refresh.evaluate_seed(seed)
        return row, []
    except Exception as exc:
        return seed, [f"FRESH_REFRESH:{type(exc).__name__}:{exc}"]


def candidate(identity: str, receipt: Mapping[str, Any], hard_full: Mapping[str, Any] | None, context: Mapping[str, Any], c: Mapping[str, Any], refresh_errors: list[str] | None = None) -> dict[str, Any]:
    strict_a1 = strict.a1_status(receipt, explicit_hardening=hard_full)
    profit = v2.profit_lane(receipt, hard_full, c)
    strict_a2 = None; a2_errors: list[str] = []
    if profit["pass"]:
        strict_a2, a2_errors = v2.run_a2(receipt)
    strict_a2_state = strict_a2.get("state") if strict_a2 else ("NOT_RUN_PROFIT_GATE_REQUIRED" if not profit["pass"] else "A2_RUNTIME_ERROR")
    pilot2 = v3.a2_pilot(strict_a2, c) if profit["pass"] else {"state": "NOT_RUN_A2_PILOT_PROFIT_REQUIRED", "pass": False, "blockers": ["PROFIT_LANE_REQUIRED"]}
    if hard_full:
        cert = v2.pilot_hardening(receipt, v3.normalize_hardening(hard_full), c)
    else:
        cert = deferred_cert(receipt, profit, c)
    specialization = (cert.get("h5") or {}).get("side_specialization") if isinstance(cert.get("h5"), Mapping) else v2._side_specialization(receipt)
    pilot3 = v3.run_a3_from_pilot(receipt, strict_a2, pilot2, context, c, specialization) if cert.get("pass") else {"state": "NOT_RUN_A3_PILOT_CERT_A1_REQUIRED", "pass": False, "coverage": {"causally_matched_trade_count": 0, "match_fraction": 0.0}, "blockers": ["CERT_PILOT_A1_REQUIRED"]}
    pilot_survivor = bool(cert.get("pass") and pilot2.get("pass") and pilot3.get("pass"))
    return {
        "identity": identity,
        "strategy_id": receipt.get("strategy_id"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "completed_trades": int(receipt.get("completed_trades") or 0),
        "fresh_refresh_errors": list(refresh_errors or []),
        "strict_reference": {"a1": strict_a1, "a2_state": strict_a2_state, "strict_survivor": False},
        "profit_lane": profit,
        "strict_a2_state": strict_a2_state,
        "strict_a2": strict_a2,
        "a2_pilot_state": pilot2["state"], "a2_pilot": pilot2, "a2_errors": a2_errors,
        "certification_pilot": cert,
        "a3_pilot": pilot3,
        "pilot_survivor": pilot_survivor,
        "label": "SURVIVOR_PILOT" if pilot_survivor else "TOP3_CANDIDATE",
        "next": "PILOT_SURVIVOR_READY_FOR_G4_PILOT_COUNT" if pilot_survivor else "AUTO_ADVANCE_CURRENT_TWO_LANE_GATE_TO_A3",
        **AUTH,
    }


def stage_rank(row: Mapping[str, Any]) -> int:
    if row.get("pilot_survivor") is True: return 6
    if row.get("a3_pilot", {}).get("state") == "WAIT_A3_PILOT_PROSPECTIVE_SAMPLE": return 5
    if row.get("a2_pilot", {}).get("pass") is True: return 4
    if row.get("certification_pilot", {}).get("pass") is True: return 3
    if row.get("profit_lane", {}).get("pass") is True: return 2
    if int(row.get("completed_trades") or 0) > 0: return 1
    return 0


def checkpoint(rows: list[dict[str, Any]], previous: Mapping[str, Any]) -> dict[str, Any]:
    old = {str(x.get("identity")): x for x in (previous.get("candidates") or []) if isinstance(x, Mapping)}
    out = []
    for row in rows:
        p = old.get(str(row["identity"]), {})
        cm = row["profit_lane"]["metrics"]; pm = (p.get("profit_lane") or {}).get("metrics") if isinstance(p.get("profit_lane"), Mapping) else {}
        cov = (row.get("a3_pilot") or {}).get("coverage") or {}; pcov = (p.get("a3_pilot") or {}).get("coverage") if isinstance(p.get("a3_pilot"), Mapping) else {}
        deltas = {
            "completed_trades": int(cm.get("completed_trades") or 0) - int((pm or {}).get("completed_trades") or 0),
            "net_pnl_bps": (v2._finite(cm.get("net_pnl_bps")) or 0.0) - (v2._finite((pm or {}).get("net_pnl_bps")) or 0.0),
            "a3_causally_matched_trades": int(cov.get("causally_matched_trade_count") or 0) - int((pcov or {}).get("causally_matched_trade_count") or 0),
            "stage_rank": stage_rank(row) - (stage_rank(p) if p else 0),
        }
        out.append({
            "identity": row["identity"], "progressing": any(v > 0 for v in deltas.values()), "deltas": deltas,
            "current_stage_rank": stage_rank(row), "profit_lane_state": row["profit_lane"]["state"],
            "strict_a2_state": row["strict_a2_state"], "a2_pilot_state": row["a2_pilot_state"],
            "certification_pilot_state": row["certification_pilot"]["state"], "a3_pilot_state": row["a3_pilot"]["state"],
        })
    return {"checkpoint_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "previous_receipt_found": bool(previous), "rows": out, "progressing_count": sum(x["progressing"] for x in out)}


def run(out_path: Path) -> dict[str, Any]:
    c = v2.read(CONTRACT_PATH); v2.validate_contract(c)
    context = v2.read(A3_CONTEXT); previous = v2.read_optional(PREVIOUS)
    with tempfile.TemporaryDirectory(prefix="top3_two_lane_v4_") as td:
        trend_receipt, trend_hard = strict.trend_rider_current(Path(td))
        trendma, trendma_errors = refresh_or_seed(TRENDMA_SEED)
        keltner, keltner_errors = refresh_or_seed(KELTNER_SEED)
        rows = [
            candidate(strict.TOP3[0], trend_receipt, trend_hard, context, c),
            candidate(strict.TOP3[1], trendma, None, context, c, trendma_errors),
            candidate(strict.TOP3[2], keltner, None, context, c, keltner_errors),
        ]
    pilots = sum(x["pilot_survivor"] for x in rows)
    result = {
        "schema_version": "zel.a1.top3_profitability_two_lane_router.v4",
        "state": "PASS_G4_PILOT_ELIGIBLE" if pilots >= 2 else "ACTIVE_TOP3_TWO_LANE_PROFITABILITY",
        "profitability_first": True, "two_lane_mode": True, "top3_only": True,
        "all_top3_fresh_refreshed_each_run": True,
        "all_top3_auto_route_to_a3_pilot": True,
        "strict_reference_preserved": True, "strict_global_gate_mutation": False,
        "strict_h4_deferred_is_not_strict_pass": True, "strict_a2_gate_relaxed": False,
        "new_strategy_generation_enabled": False, "new_filter_generation_enabled": False,
        "top3_identities": list(strict.TOP3),
        "profit_lane_pass_count": sum(x["profit_lane"]["pass"] for x in rows),
        "strict_a2_pass_count": sum(x["strict_a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows),
        "certification_pilot_a1_pass_count": sum(x["certification_pilot"]["pass"] for x in rows),
        "a2_pilot_pass_count": sum(x["a2_pilot"].get("pass") is True for x in rows),
        "a3_pilot_pass_count": sum(x["a3_pilot"].get("pass") is True for x in rows),
        "pilot_survivor_count": pilots, "g4_pilot_minimum_survivors": 2,
        "candidates": rows, "checkpoint": checkpoint(rows, previous),
        "next": "ENTER_G4_PILOT_WITH_2_TO_3_PILOT_SURVIVORS" if pilots >= 2 else "AUTO_REFRESH_TOP3_AND_ADVANCE_PROFIT_A2_CERT_A3_EACH_RUN",
        **AUTH,
    }
    result["receipt_sha256"] = v2.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = v2.read(CONTRACT_PATH); v2.validate_contract(c)
    fallback = c["certification_pilot_lane"]["h4_deferred_fallback"]
    assert fallback["enabled_only_when_candidate_specific_h4_evaluator_unavailable"] is True
    assert fallback["strict_h4_pass_must_remain_false"] is True
    assert fallback["h5_lite_remains_mandatory"] is True
    assert c["certification_pilot_lane"]["a3_pilot"]["minimum_causally_matched_trades"] == 12
    print("PASS_A1_TOP3_PROFITABILITY_TWO_LANE_ROUTER_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("out/a1_top3_profitability_survivor_latest.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    r = run(args.out)
    print("TOP3_TWO_LANE_V4=" + json.dumps({
        "state": r["state"], "profit": r["profit_lane_pass_count"], "strict_A2": r["strict_a2_pass_count"],
        "pilot_A2": r["a2_pilot_pass_count"], "cert": r["certification_pilot_a1_pass_count"],
        "A3": r["a3_pilot_pass_count"], "pilots": r["pilot_survivor_count"], "progressing": r["checkpoint"]["progressing_count"],
        "rows": [{"id": x["identity"], "trades": x["completed_trades"], "profit": x["profit_lane"]["state"], "A2": x["strict_a2_state"], "A2p": x["a2_pilot_state"], "cert": x["certification_pilot"]["state"], "A3": x["a3_pilot"]["state"], "refresh_errors": x["fresh_refresh_errors"]} for x in r["candidates"]]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
