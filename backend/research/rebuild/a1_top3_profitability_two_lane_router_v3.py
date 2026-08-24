#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top3_profitability_survivor_router_v1 as strict
from backend.research.rebuild import a1_top3_profitability_two_lane_router_v2 as v2

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/rebuild/a1_top3_two_lane_contract_v1.json"
TRENDMA = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
KELTNER = ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_fresh_latest.json"
A3_CONTEXT = ROOT / "backend/research/prep/a3_forward_context_ledger_v2.json"
PREVIOUS = ROOT / "backend/research/rebuild/a1_top3_profitability_survivor_latest.json"

AUTH = dict(v2.AUTH)


def normalize_hardening(full: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not full:
        return None
    h4 = full.get("h4_receipt") if isinstance(full.get("h4_receipt"), Mapping) else {}
    h5 = full.get("h5_receipt") if isinstance(full.get("h5_receipt"), Mapping) else {}
    results = h4.get("control_results") if isinstance(h4.get("control_results"), Mapping) else {}
    return {
        "state": full.get("state"),
        "H4": h4.get("state"),
        "H4_results": dict(results),
        "H5": h5.get("state"),
        "H5_max_shares": dict(h5.get("maximum_profit_share_by_dimension") or {}),
        "top10": h5.get("top10_trade_profit_share"),
        "H5_blockers": list(h5.get("blockers") or []),
        "full_receipt_sha256": full.get("receipt_sha256"),
    }


def a2_pilot(strict_a2: Mapping[str, Any] | None, c: Mapping[str, Any]) -> dict[str, Any]:
    cfg = c["certification_pilot_lane"]["a2_pilot"]
    if not strict_a2:
        return {"state": "NOT_RUN_A2_PILOT_STRICT_REFERENCE_REQUIRED", "pass": False, "blockers": ["STRICT_A2_REFERENCE_REQUIRED"]}
    stress = strict_a2.get("stress") if isinstance(strict_a2.get("stress"), Mapping) else {}
    blockers: list[str] = []
    for name in cfg["required_non_maturity_stresses"]:
        row = stress.get(name) if isinstance(stress.get(name), Mapping) else {}
        if row.get("pass") is not True:
            blockers.append(f"A2_PILOT_REQUIRED_STRESS:{name}:{row.get('pass')}")
    plus = stress.get("PLUS_ONE_BAR") if isinstance(stress.get("PLUS_ONE_BAR"), Mapping) else {}
    total = int(plus.get("candidate_trade_count") or 0)
    mature = int(plus.get("stress_trade_count") or 0)
    fraction = mature / total if total else 0.0
    exp_r = v2._finite(plus.get("expectancy_R"))
    raw_blockers = [str(x) for x in (plus.get("blockers") or [])]
    prefixes = tuple(str(x) for x in cfg["allowed_incomplete_blocker_prefixes"])
    disallowed = [x for x in raw_blockers if not x.startswith(prefixes)]
    if disallowed:
        blockers.append("A2_PILOT_NON_MATURITY_OR_LINEAGE_BLOCKER:" + "|".join(disallowed[:8]))
    if mature < int(cfg["minimum_mature_plus_one_bar_trades"]):
        blockers.append(f"A2_PILOT_MATURE_TRADES:{mature}<{cfg['minimum_mature_plus_one_bar_trades']}")
    if fraction < float(cfg["minimum_mature_plus_one_bar_fraction"]):
        blockers.append(f"A2_PILOT_MATURE_FRACTION:{fraction}<{cfg['minimum_mature_plus_one_bar_fraction']}")
    if exp_r is None or exp_r <= float(cfg["minimum_mature_plus_one_bar_expectancy_R_exclusive"]):
        blockers.append(f"A2_PILOT_MATURE_EXPECTANCY_R:{exp_r}<=0")
    passed = not blockers
    return {
        "state": cfg["pass_state"] if passed else "HOLD_A2_PILOT_MATURE_SUBSET",
        "pass": passed,
        "strict_reference_state": strict_a2.get("state"),
        "non_maturity_stress_states": {name: (stress.get(name) or {}).get("pass") for name in cfg["required_non_maturity_stresses"]},
        "plus_one_bar": {
            "strict_state": plus.get("state"),
            "candidate_trade_count": total,
            "mature_trade_count": mature,
            "mature_fraction": fraction,
            "mature_net_R": plus.get("net_R"),
            "mature_expectancy_R": exp_r,
            "pending_or_other_blockers": raw_blockers,
            "only_allowed_pending_blockers": not disallowed,
        },
        "cost_thresholds_relaxed": False,
        "strict_a2_reference_preserved": True,
        "blockers": blockers,
    }


def run_a3_from_pilot(receipt: Mapping[str, Any], strict_a2: Mapping[str, Any] | None, pilot_a2: Mapping[str, Any], context: Mapping[str, Any], c: Mapping[str, Any], specialization: Mapping[str, Any]) -> dict[str, Any]:
    if pilot_a2.get("pass") is not True or not strict_a2:
        return {"state": "NOT_RUN_A3_PILOT_A2_PILOT_REQUIRED", "pass": False, "coverage": {"causally_matched_trade_count": 0, "match_fraction": 0.0}, "blockers": ["A2_PILOT_PASS_REQUIRED"]}
    # v2 A3 pilot only reads the A2 state as an admission proof. Use a local proxy
    # while preserving the real strict A2 row unchanged in the output.
    proxy = dict(strict_a2)
    proxy["state"] = "PASS_A2_COST_TURNOVER"
    out = v2.a3_pilot(receipt, proxy, context, c, specialization)
    out["a2_admission_source"] = "PASS_A2_PILOT_MATURE_SUBSET"
    out["strict_a2_reference_state"] = strict_a2.get("state")
    return out


def candidate(identity: str, receipt: Mapping[str, Any], hard_full: Mapping[str, Any] | None, context: Mapping[str, Any], c: Mapping[str, Any]) -> dict[str, Any]:
    hard = normalize_hardening(hard_full)
    strict_a1 = strict.a1_status(receipt, explicit_hardening=hard_full)
    profit = v2.profit_lane(receipt, hard_full, c)
    strict_a2 = None
    a2_errors: list[str] = []
    if profit["pass"]:
        strict_a2, a2_errors = v2.run_a2(receipt)
    strict_a2_state = strict_a2.get("state") if strict_a2 else ("NOT_RUN_PROFIT_GATE_REQUIRED" if not profit["pass"] else "A2_RUNTIME_ERROR")
    pilot2 = a2_pilot(strict_a2, c) if profit["pass"] else {"state": "NOT_RUN_A2_PILOT_PROFIT_REQUIRED", "pass": False, "blockers": ["PROFIT_LANE_REQUIRED"]}
    cert = v2.pilot_hardening(receipt, hard, c)
    specialization = (cert.get("h5") or {}).get("side_specialization") if isinstance(cert.get("h5"), Mapping) else v2._side_specialization(receipt)
    pilot3 = run_a3_from_pilot(receipt, strict_a2, pilot2, context, c, specialization) if cert.get("pass") else {"state": "NOT_RUN_A3_PILOT_CERT_A1_REQUIRED", "pass": False, "coverage": {"causally_matched_trade_count": 0, "match_fraction": 0.0}, "blockers": ["CERT_PILOT_A1_REQUIRED"]}
    pilot_survivor = bool(cert.get("pass") and pilot2.get("pass") and pilot3.get("pass"))
    return {
        "identity": identity,
        "strategy_id": receipt.get("strategy_id"),
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "strict_reference": {"a1": strict_a1, "a2_state": strict_a2_state, "strict_survivor": False},
        "profit_lane": profit,
        "strict_a2_state": strict_a2_state,
        "strict_a2": strict_a2,
        "a2_pilot_state": pilot2["state"],
        "a2_pilot": pilot2,
        "a2_errors": a2_errors,
        "certification_pilot": cert,
        "a3_pilot": pilot3,
        "pilot_survivor": pilot_survivor,
        "label": "SURVIVOR_PILOT" if pilot_survivor else "TOP3_CANDIDATE",
        "next": "PILOT_SURVIVOR_READY_FOR_G4_PILOT_COUNT" if pilot_survivor else "ADVANCE_ONLY_CURRENT_PROFIT_OR_CERTIFICATION_GATE",
        **AUTH,
    }


def stage_rank(row: Mapping[str, Any]) -> int:
    if row.get("pilot_survivor") is True: return 6
    if row.get("a3_pilot", {}).get("state") == "WAIT_A3_PILOT_PROSPECTIVE_SAMPLE": return 5
    if row.get("a2_pilot_state") == "PASS_A2_PILOT_MATURE_SUBSET": return 4
    if row.get("certification_pilot", {}).get("pass") is True: return 3
    if row.get("profit_lane", {}).get("pass") is True: return 2
    if int(row.get("profit_lane", {}).get("metrics", {}).get("completed_trades") or 0) > 0: return 1
    return 0


def checkpoint(current: list[dict[str, Any]], previous: Mapping[str, Any]) -> dict[str, Any]:
    prev_rows = {str(x.get("identity")): x for x in (previous.get("candidates") or []) if isinstance(x, Mapping)}
    rows = []
    for x in current:
        identity = str(x["identity"]); p = prev_rows.get(identity, {})
        cm = x["profit_lane"]["metrics"]
        pm = (p.get("profit_lane") or {}).get("metrics") if isinstance(p.get("profit_lane"), Mapping) else {}
        ca3 = x.get("a3_pilot") or {}; pa3 = p.get("a3_pilot") if isinstance(p.get("a3_pilot"), Mapping) else {}
        cc = ca3.get("coverage") if isinstance(ca3.get("coverage"), Mapping) else {}; pc = pa3.get("coverage") if isinstance(pa3.get("coverage"), Mapping) else {}
        prior_rank = stage_rank(p) if p else 0
        deltas = {
            "completed_trades": int(cm.get("completed_trades") or 0) - int((pm or {}).get("completed_trades") or 0),
            "net_pnl_bps": (v2._finite(cm.get("net_pnl_bps")) or 0.0) - (v2._finite((pm or {}).get("net_pnl_bps")) or 0.0),
            "a3_causally_matched_trades": int(cc.get("causally_matched_trade_count") or 0) - int((pc or {}).get("causally_matched_trade_count") or 0),
            "stage_rank": stage_rank(x) - prior_rank,
        }
        progressing = any(v > 0 for v in deltas.values())
        rows.append({
            "identity": identity,
            "progressing": progressing,
            "deltas": deltas,
            "current_stage_rank": stage_rank(x),
            "profit_lane_state": x["profit_lane"]["state"],
            "strict_a2_state": x["strict_a2_state"],
            "a2_pilot_state": x["a2_pilot_state"],
            "certification_pilot_state": x["certification_pilot"]["state"],
            "a3_pilot_state": ca3.get("state"),
        })
    return {
        "checkpoint_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "previous_receipt_found": bool(previous),
        "rows": rows,
        "progressing_count": sum(r["progressing"] for r in rows),
    }


def run(out: Path) -> dict[str, Any]:
    c = v2.read(CONTRACT_PATH); v2.validate_contract(c)
    context = v2.read(A3_CONTEXT)
    previous = v2.read_optional(PREVIOUS)
    with tempfile.TemporaryDirectory(prefix="top3_two_lane_v3_") as td:
        trend_receipt, trend_hard = strict.trend_rider_current(Path(td))
        trendma = v2.read(TRENDMA); keltner = v2.read(KELTNER)
        rows = [
            candidate(strict.TOP3[0], trend_receipt, trend_hard, context, c),
            candidate(strict.TOP3[1], trendma, None, context, c),
            candidate(strict.TOP3[2], keltner, None, context, c),
        ]
    profit_lane_pass = sum(x["profit_lane"]["pass"] for x in rows)
    strict_a2_pass = sum(x["strict_a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows)
    cert_a1 = sum(x["certification_pilot"]["pass"] for x in rows)
    pilot_a2 = sum(x["a2_pilot_state"] == "PASS_A2_PILOT_MATURE_SUBSET" for x in rows)
    a3_count = sum(x["a3_pilot"].get("pass") is True for x in rows)
    pilots = sum(x["pilot_survivor"] for x in rows)
    result = {
        "schema_version": "zel.a1.top3_profitability_two_lane_router.v3",
        "state": "PASS_G4_PILOT_ELIGIBLE" if pilots >= 2 else "ACTIVE_TOP3_TWO_LANE_PROFITABILITY",
        "profitability_first": True,
        "two_lane_mode": True,
        "top3_only": True,
        "strict_reference_preserved": True,
        "strict_global_gate_mutation": False,
        "strict_a2_gate_relaxed": False,
        "pilot_hurdles_relaxed": True,
        "new_strategy_generation_enabled": False,
        "new_filter_generation_enabled": False,
        "contract_sha256": v2.stable(c),
        "top3_identities": list(strict.TOP3),
        "profit_lane_pass_count": profit_lane_pass,
        "strict_a2_pass_count": strict_a2_pass,
        "certification_pilot_a1_pass_count": cert_a1,
        "a2_pilot_pass_count": pilot_a2,
        "a3_pilot_pass_count": a3_count,
        "pilot_survivor_count": pilots,
        "g4_pilot_minimum_survivors": 2,
        "candidates": rows,
        "checkpoint": checkpoint(rows, previous),
        "next": "ENTER_G4_PILOT_WITH_2_TO_3_PILOT_SURVIVORS" if pilots >= 2 else "KEEP_TOP3_FIXED; PROFIT_LANE_CONTINUES_WHILE_CERTIFICATION_PILOT_ADVANCES",
        **AUTH,
    }
    result["receipt_sha256"] = v2.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = v2.read(CONTRACT_PATH); v2.validate_contract(c)
    cfg = c["certification_pilot_lane"]["a2_pilot"]
    assert cfg["minimum_mature_plus_one_bar_trades"] == 12
    assert cfg["minimum_mature_plus_one_bar_fraction"] == 0.70
    fake = {
        "state": "HOLD_A2_COST_TURNOVER",
        "stress": {
            "1X_COST": {"pass": True}, "2X_COST": {"pass": True}, "P95_FUNDING": {"pass": True}, "TURNOVER": {"pass": True},
            "PLUS_ONE_BAR": {"pass": False, "state": "HOLD_PLUS_ONE_BAR", "candidate_trade_count": 26, "stress_trade_count": 20, "net_R": 249.2, "expectancy_R": 12.46, "blockers": ["PENDING_DELAYED_TIMEOUT:BTC-USDT:1", "PENDING_DELAYED_TIMEOUT:ETH-USDT:2"]},
        },
    }
    p = a2_pilot(fake, c); assert p["pass"] is True, p
    bad = json.loads(json.dumps(fake)); bad["stress"]["PLUS_ONE_BAR"]["blockers"].append("INTENT_SHA_MISMATCH:BTC-USDT:1")
    assert a2_pilot(bad, c)["pass"] is False
    hard_full = {"state": "HOLD_HARDENING_EVIDENCE", "h4_receipt": {"state": "NO_PROVEN_EDGE", "control_results": {"a": {"pass": True}}}, "h5_receipt": {"state": "HOLD_CONCENTRATION_FRAGILITY", "maximum_profit_share_by_dimension": {"symbol": .8}, "top10_trade_profit_share": .88, "blockers": []}}
    n = normalize_hardening(hard_full); assert n and n["H4_results"]["a"]["pass"] is True and n["top10"] == .88
    print("PASS_A1_TOP3_PROFITABILITY_TWO_LANE_ROUTER_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, default=Path("out/a1_top3_profitability_survivor_latest.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    r = run(args.out)
    print("TOP3_TWO_LANE_V3=" + json.dumps({
        "state": r["state"], "profit": r["profit_lane_pass_count"], "strict_A2": r["strict_a2_pass_count"], "cert_A1": r["certification_pilot_a1_pass_count"], "pilot_A2": r["a2_pilot_pass_count"], "A3_pilot": r["a3_pilot_pass_count"], "pilot_survivors": r["pilot_survivor_count"], "progressing": r["checkpoint"]["progressing_count"],
        "rows": [{"id": x["identity"], "profit": x["profit_lane"]["state"], "strict_A2": x["strict_a2_state"], "pilot_A2": x["a2_pilot_state"], "cert": x["certification_pilot"]["state"], "A3": x["a3_pilot"]["state"], "coverage": x["a3_pilot"].get("coverage"), "pilot": x["pilot_survivor"]} for x in r["candidates"]]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
