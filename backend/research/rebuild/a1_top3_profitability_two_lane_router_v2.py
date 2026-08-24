#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import a2_forward_cost_turnover_v1 as a2
from backend.research.prep import a3_exact25_forward_durability_v3 as a3
from backend.research.rebuild import a1_top3_profitability_survivor_router_v1 as strict

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/rebuild/a1_top3_two_lane_contract_v1.json"
TRENDMA = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
KELTNER = ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_fresh_latest.json"
A3_CONTEXT = ROOT / "backend/research/prep/a3_forward_context_ledger_v2.json"
PREVIOUS = ROOT / "backend/research/rebuild/a1_top3_profitability_survivor_latest.json"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def read_optional(path: Path) -> dict[str, Any]:
    try:
        return read(path)
    except FileNotFoundError:
        return {}


def stable(value: Any) -> str:
    return a3.stable_sha(value)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except Exception:
        return None
    return v if v == v and abs(v) != float("inf") else None


def validate_contract(c: Mapping[str, Any]) -> None:
    if c.get("state") != "PASS_TOP3_TWO_LANE_CONTRACT_SEALED":
        raise RuntimeError("TOP3_TWO_LANE_CONTRACT_NOT_SEALED")
    if c.get("strict_reference", {}).get("preserved") is not True:
        raise RuntimeError("STRICT_REFERENCE_NOT_PRESERVED")
    if c.get("strict_reference", {}).get("global_h4_h5_policy_mutated") is not False:
        raise RuntimeError("GLOBAL_HARDENING_MUTATION_FORBIDDEN")
    if c.get("strict_reference", {}).get("global_a3_contract_mutated") is not False:
        raise RuntimeError("GLOBAL_A3_MUTATION_FORBIDDEN")
    if c.get("profit_lane", {}).get("a2_cost_turnover_gate_unchanged_and_mandatory") is not True:
        raise RuntimeError("A2_MUST_REMAIN_STRICT")
    if c.get("certification_pilot_lane", {}).get("a2_cost_turnover_gate_unchanged_and_mandatory") is not True:
        raise RuntimeError("A2_MUST_REMAIN_STRICT_CERT")


def _strict_non_hardening_blockers(receipt: Mapping[str, Any], hard: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    s = strict.a1_status(receipt, explicit_hardening=hard)
    return s, [x for x in s["blockers"] if not str(x).startswith("HARDENING:") and not str(x).startswith("FRESH_TRADES:")]


def profit_lane(receipt: Mapping[str, Any], hard: Mapping[str, Any] | None, c: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["profit_lane"]
    m = strict.metrics(receipt)
    n = int(m.get("completed_trades") or 0)
    strict_a1, other = _strict_non_hardening_blockers(receipt, hard)
    blockers: list[str] = []
    if n < int(cfg["minimum_completed_trades"]):
        blockers.append(f"PROFIT_TRADES:{n}<{cfg['minimum_completed_trades']}")
    # Preserve strict source/integrity/lookahead/economic blockers. Only the old 25-trade
    # and hardening blockers are relaxed in this lane.
    blockers.extend(other)
    net = _finite(m.get("net_pnl_bps")); exp = _finite(m.get("net_expectancy_bps")); pf = _finite(m.get("profit_factor"))
    if net is None or net <= float(cfg["minimum_net_pnl_bps_exclusive"]):
        if not any(str(x).startswith("NET_PNL_BPS:") for x in blockers): blockers.append(f"NET_PNL_BPS:{net}")
    if exp is None or exp <= float(cfg["minimum_net_expectancy_bps_exclusive"]):
        if not any(str(x).startswith("EXPECTANCY_BPS:") for x in blockers): blockers.append(f"EXPECTANCY_BPS:{exp}")
    if pf is None or pf < float(cfg["minimum_profit_factor"]):
        if not any(str(x).startswith("PROFIT_FACTOR:") for x in blockers): blockers.append(f"PROFIT_FACTOR:{pf}")
    passed = not blockers
    state = cfg["pass_state"] if passed else ("WAIT_PROFIT_SAMPLE" if n < int(cfg["minimum_completed_trades"]) else "HOLD_PROFIT_ECONOMICS")
    return {
        "state": state,
        "pass": passed,
        "metrics": m,
        "blockers": blockers,
        "strict_a1_reference": strict_a1,
        "h4_h5_advisory": True,
    }


def _side_specialization(receipt: Mapping[str, Any]) -> dict[str, Any]:
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in receipt.get("trades") or []:
        if not isinstance(t, Mapping): continue
        side = str(t.get("side") or "UNKNOWN")
        sums[side] += float(t.get("net_bps") or 0.0)
        counts[side] += 1
    positive = [s for s, v in sums.items() if v > 0]
    nonpositive = [s for s, v in sums.items() if v <= 0]
    allowed = len(positive) == 1 and len(nonpositive) >= 1
    return {"allowed": allowed, "positive_sides": positive, "nonpositive_sides": nonpositive, "net_bps_by_side": dict(sums), "trade_count_by_side": dict(counts)}


def pilot_hardening(receipt: Mapping[str, Any], hard: Mapping[str, Any] | None, c: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["certification_pilot_lane"]
    h4c = cfg["h4"]; h5c = cfg["h5"]
    m = strict.metrics(receipt); n = int(m.get("completed_trades") or 0)
    if n < int(cfg["minimum_completed_trades"]):
        return {"state": "WAIT_CERT_PILOT_SAMPLE", "pass": False, "blockers": [f"CERT_TRADES:{n}<{cfg['minimum_completed_trades']}"]}
    if not hard or not isinstance(hard.get("H4_results"), Mapping):
        return {"state": "WAIT_CERT_PILOT_H4_H5", "pass": False, "blockers": ["IDENTITY_H4_H5_REQUIRED_AT_PILOT_SAMPLE"]}

    results = hard["H4_results"]
    raw_positive = sum((_finite(v.get("candidate_minus_control_net_R")) or 0.0) > 0 for v in results.values() if isinstance(v, Mapping))
    ci_positive = sum((_finite(v.get("candidate_minus_control_ci_low_R")) or 0.0) > 0 for v in results.values() if isinstance(v, Mapping))
    strict_pass = sum(v.get("pass") is True for v in results.values() if isinstance(v, Mapping))
    h4_blockers: list[str] = []
    if len(results) < int(h4c["required_control_count"]): h4_blockers.append(f"H4_CONTROLS:{len(results)}<{h4c['required_control_count']}")
    if raw_positive < int(h4c["minimum_positive_raw_delta_controls"]): h4_blockers.append(f"H4_RAW_POSITIVE:{raw_positive}<{h4c['minimum_positive_raw_delta_controls']}")
    if ci_positive < int(h4c["minimum_positive_ci_low_controls"]): h4_blockers.append(f"H4_CI_POSITIVE:{ci_positive}<{h4c['minimum_positive_ci_low_controls']}")
    if strict_pass < int(h4c["minimum_strict_pass_controls"]): h4_blockers.append(f"H4_STRICT_PASS:{strict_pass}<{h4c['minimum_strict_pass_controls']}")

    shares = hard.get("H5_max_shares") if isinstance(hard.get("H5_max_shares"), Mapping) else {}
    top10 = _finite(hard.get("top10"))
    specialization = _side_specialization(receipt)
    h5_blockers: list[str] = []
    limits = {
        "regime": float(h5c["maximum_single_regime_profit_share"]),
        "symbol": float(h5c["maximum_single_symbol_profit_share"]),
        "session": float(h5c["maximum_single_session_profit_share"]),
        "window": float(h5c["maximum_single_window_profit_share"]),
    }
    for dim, limit in limits.items():
        v = _finite(shares.get(dim))
        if v is None or v > limit: h5_blockers.append(f"H5_{dim.upper()}:{v}>{limit}")
    side_share = _finite(shares.get("side"))
    if side_share is not None and side_share > 0.85 and not (h5c.get("one_sided_specialization_allowed_when_opposite_side_nonpositive") and specialization["allowed"]):
        h5_blockers.append(f"H5_SIDE:{side_share}>0.85")
    if top10 is None or top10 > float(h5c["maximum_top10_trade_profit_share"]):
        h5_blockers.append(f"H5_TOP10:{top10}>{h5c['maximum_top10_trade_profit_share']}")

    blockers = h4_blockers + h5_blockers
    return {
        "state": "PASS_CERT_PILOT_H4_H5" if not blockers else "HOLD_CERT_PILOT_H4_H5",
        "pass": not blockers,
        "blockers": blockers,
        "h4": {"raw_positive_controls": raw_positive, "positive_ci_controls": ci_positive, "strict_pass_controls": strict_pass, "control_count": len(results), "strict_reference_state": hard.get("H4")},
        "h5": {"max_shares": dict(shares), "top10": top10, "strict_reference_state": hard.get("H5"), "strict_reference_blockers": hard.get("H5_blockers") or [], "leave_one_group_out_advisory": True, "side_specialization": specialization},
    }


def run_a2(receipt: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        row = a2.evaluate(strict.transition(receipt), receipt)
        return row, []
    except Exception as exc:
        return None, [f"A2_RUNTIME:{type(exc).__name__}:{exc}"]


def _group_key(r: Mapping[str, Any], dim: str) -> str:
    if dim == "regime": return str(r.get("regime"))
    if dim == "session": return str(r.get("session_state"))
    if dim == "window": return datetime.fromtimestamp(int(r["entry_ts"])/1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(r.get(dim))


def a3_pilot(receipt: Mapping[str, Any], a2_row: Mapping[str, Any] | None, context: Mapping[str, Any], c: Mapping[str, Any], specialization: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["certification_pilot_lane"]["a3_pilot"]
    if not a2_row or a2_row.get("state") != "PASS_A2_COST_TURNOVER":
        return {"state": "NOT_RUN_A3_PILOT_A2_REQUIRED", "pass": False, "coverage": {"causally_matched_trade_count": 0, "match_fraction": 0.0}, "blockers": ["A2_COST_PASS_REQUIRED"]}
    strict_contract = a3.read(a3.CONTRACT)
    taxonomy = a3.read(a3.TAXONOMY)
    activation = a3.dt_ms(strict_contract["activation_boundary_utc"])
    stale_ms = int(taxonomy["input_contract"]["stale_after_ms"])
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping) and int(x.get("entry_ts") or 0) >= activation]
    by = a3._context_index(context)
    joined: list[dict[str, Any]] = []; unmatched: list[dict[str, Any]] = []
    for t in trades:
        row, reason = a3.join_trade(t, by, stale_ms)
        if row is None: unmatched.append({"symbol": t.get("symbol"), "entry_ts": t.get("entry_ts"), "reason": reason})
        else: joined.append(row)
    matched = len(joined); total = len(trades); fraction = matched / total if total else 0.0
    blockers: list[str] = []
    min_n = int(cfg["minimum_causally_matched_trades"])
    if matched < min_n: blockers.append(f"A3_PILOT_MATCHED:{matched}<{min_n}")
    if total and fraction < float(cfg["minimum_match_fraction"]): blockers.append(f"A3_PILOT_COVERAGE:{fraction}<{cfg['minimum_match_fraction']}")
    if not total: blockers.append("A3_PILOT_NO_PROSPECTIVE_TRADES")

    vals = [a3.net_r(x) for x in joined]
    net = sum(vals); exp = net / len(vals) if vals else None; pf = a3._pf(vals) if vals else None; payoff = a3._payoff(vals) if vals else None
    economic_fail: list[str] = []
    if matched >= min_n:
        if not net > float(cfg["minimum_net_R_exclusive"]): economic_fail.append(f"NET_R:{net}<=0")
        if exp is None or not exp > float(cfg["minimum_expectancy_R_exclusive"]): economic_fail.append(f"EXPECTANCY_R:{exp}<=0")
        if pf is None or pf < float(cfg["minimum_profit_factor"]): economic_fail.append(f"PF:{pf}<1")
        if payoff is None or payoff < float(cfg["minimum_payoff_ratio"]): economic_fail.append(f"PAYOFF:{payoff}<1")

    concentration: dict[str, Any] = {"profit_shares": {}, "leave_one_group_out_net_R": {}}
    concentration_fail: list[str] = []
    if matched >= min_n:
        positives = [max(0.0, a3.net_r(x)) for x in joined]; total_profit = sum(positives)
        for dim, limit in (("regime", float(cfg["maximum_single_regime_profit_share"])), ("symbol", float(cfg["maximum_single_symbol_profit_share"]))):
            sums: dict[str, float] = defaultdict(float)
            for r, p in zip(joined, positives): sums[_group_key(r, dim)] += p
            mx = max(sums.values(), default=0.0) / total_profit if total_profit > 0 else 1.0
            concentration["profit_shares"][dim] = mx
            if mx > limit: concentration_fail.append(f"{dim.upper()}_PROFIT_SHARE:{mx}>{limit}")
        top10 = sum(sorted(positives, reverse=True)[:10]) / total_profit if total_profit > 0 else 1.0
        concentration["profit_shares"]["top10_trade"] = top10
        if top10 > float(cfg["maximum_top10_trade_profit_share"]): concentration_fail.append(f"TOP10_PROFIT_SHARE:{top10}>{cfg['maximum_top10_trade_profit_share']}")
        for dim in cfg["leave_one_dimensions"]:
            keys = sorted({_group_key(r, dim) for r in joined}); concentration["leave_one_group_out_net_R"][dim] = {}
            for key in keys:
                remain = [r for r in joined if _group_key(r, dim) != key]; v = sum(a3.net_r(r) for r in remain)
                concentration["leave_one_group_out_net_R"][dim][key] = v
                if v < float(cfg["leave_one_group_out_min_R"]): concentration_fail.append(f"LEAVE_ONE_{dim.upper()}:{key}:{v}<0")

    all_fail = blockers + economic_fail + concentration_fail
    if matched < min_n or (total and fraction < float(cfg["minimum_match_fraction"])) or not total:
        state = "WAIT_A3_PILOT_PROSPECTIVE_SAMPLE"
    elif economic_fail or concentration_fail:
        state = "FAIL_A3_PILOT_DURABILITY"
    else:
        state = "PASS_A3_PILOT_DURABILITY"
    return {
        "state": state,
        "pass": state == "PASS_A3_PILOT_DURABILITY",
        "coverage": {"prospective_trade_count": total, "causally_matched_trade_count": matched, "unmatched_trade_count": len(unmatched), "match_fraction": fraction, "minimum_required": min_n},
        "economics": {"net_R": net, "expectancy_R": exp, "profit_factor": pf, "payoff_ratio": payoff, "trade_count": matched},
        "concentration_fragility": concentration,
        "blockers": all_fail,
        "unmatched_trades": unmatched,
        "side_specialization": dict(specialization),
    }


def stage_rank(row: Mapping[str, Any]) -> int:
    if row.get("pilot_survivor") is True: return 6
    if row.get("a3_pilot", {}).get("state") == "WAIT_A3_PILOT_PROSPECTIVE_SAMPLE": return 5
    if row.get("a2_state") == "PASS_A2_COST_TURNOVER": return 4
    if row.get("certification_pilot", {}).get("pass") is True: return 3
    if row.get("profit_lane", {}).get("pass") is True: return 2
    if int(row.get("profit_lane", {}).get("metrics", {}).get("completed_trades") or 0) > 0: return 1
    return 0


def checkpoint(current: list[dict[str, Any]], previous: Mapping[str, Any]) -> dict[str, Any]:
    prev_rows = {str(x.get("identity")): x for x in (previous.get("candidates") or []) if isinstance(x, Mapping)}
    rows = []
    for x in current:
        identity = str(x["identity"]); p = prev_rows.get(identity, {})
        cm = x["profit_lane"]["metrics"]; pm = (p.get("profit_lane") or {}).get("metrics") if isinstance(p.get("profit_lane"), Mapping) else {}
        ca3 = x.get("a3_pilot") or {}; pa3 = p.get("a3_pilot") if isinstance(p.get("a3_pilot"), Mapping) else {}
        c_cov = ca3.get("coverage") if isinstance(ca3.get("coverage"), Mapping) else {}; p_cov = pa3.get("coverage") if isinstance(pa3.get("coverage"), Mapping) else {}
        deltas = {
            "completed_trades": int(cm.get("completed_trades") or 0) - int((pm or {}).get("completed_trades") or 0),
            "net_pnl_bps": (_finite(cm.get("net_pnl_bps")) or 0.0) - (_finite((pm or {}).get("net_pnl_bps")) or 0.0),
            "a3_causally_matched_trades": int(c_cov.get("causally_matched_trade_count") or 0) - int((p_cov or {}).get("causally_matched_trade_count") or 0),
            "stage_rank": stage_rank(x) - stage_rank(p) if p else stage_rank(x),
        }
        progressing = any(v > 0 for v in deltas.values())
        rows.append({"identity": identity, "progressing": progressing, "deltas": deltas, "current_stage_rank": stage_rank(x), "profit_lane_state": x["profit_lane"]["state"], "a2_state": x["a2_state"], "certification_pilot_state": x["certification_pilot"]["state"], "a3_pilot_state": ca3.get("state")})
    return {"checkpoint_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "previous_receipt_found": bool(previous), "rows": rows, "progressing_count": sum(r["progressing"] for r in rows)}


def candidate(identity: str, receipt: Mapping[str, Any], hard: Mapping[str, Any] | None, context: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    strict_a1 = strict.a1_status(receipt, explicit_hardening=hard)
    profit = profit_lane(receipt, hard, c)
    a2_row = None; a2_errors: list[str] = []
    if profit["pass"]:
        a2_row, a2_errors = run_a2(receipt)
    a2_state = a2_row.get("state") if a2_row else ("NOT_RUN_PROFIT_GATE_REQUIRED" if not profit["pass"] else "A2_RUNTIME_ERROR")
    cert = pilot_hardening(receipt, hard, c)
    specialization = (cert.get("h5") or {}).get("side_specialization") if isinstance(cert.get("h5"), Mapping) else _side_specialization(receipt)
    pilot3 = a3_pilot(receipt, a2_row, context, c, specialization) if cert.get("pass") else {"state": "NOT_RUN_A3_PILOT_CERT_A1_REQUIRED", "pass": False, "coverage": {"causally_matched_trade_count": 0, "match_fraction": 0.0}, "blockers": ["CERT_PILOT_A1_REQUIRED"]}
    pilot_survivor = bool(cert.get("pass") and a2_state == "PASS_A2_COST_TURNOVER" and pilot3.get("pass"))
    return {
        "identity": identity,
        "strategy_id": receipt.get("strategy_id"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "strict_reference": {"a1": strict_a1, "strict_survivor": False},
        "profit_lane": profit,
        "a2_state": a2_state,
        "a2": a2_row,
        "a2_errors": a2_errors,
        "certification_pilot": cert,
        "a3_pilot": pilot3,
        "pilot_survivor": pilot_survivor,
        "label": "SURVIVOR_PILOT" if pilot_survivor else "TOP3_CANDIDATE",
        "next": "PILOT_SURVIVOR_READY_FOR_G4_PILOT_COUNT" if pilot_survivor else "ADVANCE_ONLY_CURRENT_PROFIT_OR_CERTIFICATION_GATE",
        **AUTH,
    }


def run(out: Path) -> dict[str, Any]:
    c = read(CONTRACT_PATH); validate_contract(c)
    context = read(A3_CONTEXT)
    previous = read_optional(PREVIOUS)
    with tempfile.TemporaryDirectory(prefix="top3_two_lane_") as td:
        trend_receipt, trend_hard = strict.trend_rider_current(Path(td))
        trendma = read(TRENDMA); keltner = read(KELTNER)
        rows = [
            candidate(strict.TOP3[0], trend_receipt, trend_hard, context, c),
            candidate(strict.TOP3[1], trendma, None, context, c),
            candidate(strict.TOP3[2], keltner, None, context, c),
        ]
    profit_active = sum(x["profit_lane"]["state"] == "PROFIT_ACTIVE_SHADOW" and x["a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows)
    cert_a1 = sum(x["certification_pilot"]["pass"] for x in rows)
    a2_count = sum(x["a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows)
    a3_count = sum(x["a3_pilot"].get("pass") is True for x in rows)
    pilots = sum(x["pilot_survivor"] for x in rows)
    result = {
        "schema_version": "zel.a1.top3_profitability_two_lane_router.v2",
        "state": "PASS_G4_PILOT_ELIGIBLE" if pilots >= 2 else "ACTIVE_TOP3_TWO_LANE_PROFITABILITY",
        "profitability_first": True,
        "two_lane_mode": True,
        "top3_only": True,
        "strict_reference_preserved": True,
        "strict_global_gate_mutation": False,
        "a2_gate_relaxed": False,
        "new_strategy_generation_enabled": False,
        "new_filter_generation_enabled": False,
        "contract_sha256": stable(c),
        "top3_identities": list(strict.TOP3),
        "profit_active_count": profit_active,
        "certification_pilot_a1_pass_count": cert_a1,
        "a2_pass_count": a2_count,
        "a3_pilot_pass_count": a3_count,
        "pilot_survivor_count": pilots,
        "g4_pilot_minimum_survivors": 2,
        "candidates": rows,
        "checkpoint": checkpoint(rows, previous),
        "next": "ENTER_G4_PILOT_WITH_2_TO_3_PILOT_SURVIVORS" if pilots >= 2 else "KEEP_TOP3_FIXED; PROFIT_LANE_CONTINUES_WHILE_CERTIFICATION_LANE_ADVANCES",
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT_PATH); validate_contract(c)
    assert c["profit_lane"]["minimum_completed_trades"] == 10
    assert c["certification_pilot_lane"]["minimum_completed_trades"] == 12
    assert c["certification_pilot_lane"]["a3_pilot"]["minimum_causally_matched_trades"] == 12
    assert c["certification_pilot_lane"]["a3_pilot"]["minimum_match_fraction"] == 0.90
    fake = {
        "completed_trades": 12,
        "metrics": {"net_pnl_bps": 100.0, "net_expectancy_bps": 8.0, "net_profit_factor": 1.2, "win_rate": 0.5},
        "source_quality_gate": {"state": "PASS"}, "integrity_defects": [], "leakage_lookahead": 0,
        "trades": [
            {"side": "long", "net_bps": 30.0}, {"side": "long", "net_bps": 20.0}, {"side": "short", "net_bps": -5.0}
        ],
    }
    p = profit_lane(fake, {"state": "HOLD_HARDENING_EVIDENCE"}, c)
    assert p["pass"] is True, p
    spec = _side_specialization(fake); assert spec["allowed"] is True, spec
    hard = {
        "H4": "NO_PROVEN_EDGE",
        "H4_results": {
            "a": {"candidate_minus_control_net_R": 1, "candidate_minus_control_ci_low_R": 1, "pass": True},
            "b": {"candidate_minus_control_net_R": 1, "candidate_minus_control_ci_low_R": 1, "pass": True},
            "c": {"candidate_minus_control_net_R": 1, "candidate_minus_control_ci_low_R": 1, "pass": False},
            "d": {"candidate_minus_control_net_R": 1, "candidate_minus_control_ci_low_R": -1, "pass": False},
            "e": {"candidate_minus_control_net_R": -1, "candidate_minus_control_ci_low_R": -1, "pass": False}
        },
        "H5": "HOLD_CONCENTRATION_FRAGILITY",
        "H5_max_shares": {"regime": 0.82, "symbol": 0.78, "session": 0.54, "window": 0.64, "side": 1.0},
        "top10": 0.88,
    }
    hp = pilot_hardening(fake, hard, c); assert hp["pass"] is True, hp
    print("PASS_A1_TOP3_PROFITABILITY_TWO_LANE_ROUTER_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("out/a1_top3_profitability_survivor_latest.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    r = run(args.out)
    print("TOP3_TWO_LANE=" + json.dumps({
        "state": r["state"], "profit_active": r["profit_active_count"], "cert_a1": r["certification_pilot_a1_pass_count"], "A2": r["a2_pass_count"], "A3_pilot": r["a3_pilot_pass_count"], "pilot_survivors": r["pilot_survivor_count"], "progressing": r["checkpoint"]["progressing_count"],
        "rows": [{"id": x["identity"], "profit": x["profit_lane"]["state"], "A2": x["a2_state"], "cert": x["certification_pilot"]["state"], "A3": x["a3_pilot"]["state"], "pilot": x["pilot_survivor"]} for x in r["candidates"]]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
