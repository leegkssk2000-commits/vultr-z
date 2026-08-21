from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import a3_exact25_forward_durability_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/prep/a3_durability_contract_v1.json"
HARDENING = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
AUTH = v1.AUTH


def read(path: Path) -> dict[str, Any]:
    return v1.read(path)


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def _pf_payoff(values: list[float]) -> tuple[float | None, float | None]:
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    pf = None if gl <= 0 else gp / gl
    payoff = None if not wins or not losses else (gp / len(wins)) / (gl / len(losses))
    return pf, payoff


def _group_key(row: Mapping[str, Any], dimension: str) -> str:
    regime = row.get("regime") if isinstance(row.get("regime"), Mapping) else {}
    if dimension == "symbol":
        return str(row.get("symbol") or "UNKNOWN")
    if dimension == "side":
        return str(row.get("side") or "UNKNOWN")
    if dimension == "session":
        return str(regime.get("session_state") or "UNKNOWN")
    if dimension == "regime":
        return "|".join(str(regime.get(k) or "UNKNOWN") for k in ("trend_state", "vol_state", "liquidity_state", "funding_oi_state"))
    if dimension == "window":
        ts = int(row.get("entry_ts") or 0)
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    raise RuntimeError(f"UNKNOWN_A3_DIMENSION:{dimension}")


def _group_nets(rows: list[Mapping[str, Any]], dimension: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        out[_group_key(row, dimension)] += float(row.get("net_bps") or 0.0)
    return dict(sorted(out.items()))


def _positive_group_share(rows: list[Mapping[str, Any]], dimension: str) -> tuple[float, dict[str, float]]:
    nets = _group_nets(rows, dimension)
    positive = {k: max(0.0, v) for k, v in nets.items()}
    denom = sum(positive.values())
    shares = {k: (v / denom if denom > 0 else 0.0) for k, v in positive.items()}
    return (max(shares.values()) if shares else 0.0), shares


def _top10_profit_share(rows: list[Mapping[str, Any]]) -> float:
    profits = sorted((max(0.0, float(x.get("net_bps") or 0.0)) for x in rows), reverse=True)
    denom = sum(profits)
    return (sum(profits[:10]) / denom) if denom > 0 else 1.0


def _leave_one_group_out(rows: list[Mapping[str, Any]], dimension: str) -> dict[str, float]:
    total = sum(float(x.get("net_bps") or 0.0) for x in rows)
    nets = _group_nets(rows, dimension)
    return {group: (total - value) / 100.0 for group, value in nets.items()}


def _validate_contract(contract: Mapping[str, Any], hardening: Mapping[str, Any]) -> None:
    if contract.get("state") != "PASS_A3_DURABILITY_CONTRACT_SEALED":
        raise RuntimeError("A3_DURABILITY_CONTRACT_NOT_SEALED")
    if contract.get("sealed_before_activation") is not True:
        raise RuntimeError("A3_CONTRACT_NOT_PRESEALED")
    sg = hardening.get("survivor_gate") or {}
    cg = hardening.get("h5_concentration_fragility") or {}
    econ = contract.get("global_economic_gate") or {}
    frag = contract.get("concentration_fragility_gate") or {}
    checks = [
        (float(econ["minimum_net_R"]), float(sg["minimum_net_R"]), "MIN_NET_R"),
        (float(econ["minimum_expectancy_R"]), float(sg["minimum_expectancy_R"]), "MIN_EXPECTANCY_R"),
        (float(econ["minimum_profit_factor"]), float(sg["minimum_profit_factor"]), "MIN_PF"),
        (float(econ["minimum_payoff_ratio"]), float(sg["minimum_payoff_ratio"]), "MIN_PAYOFF"),
        (float(frag["maximum_single_regime_profit_share"]), float(cg["maximum_single_regime_profit_share"]), "MAX_REGIME_SHARE"),
        (float(frag["maximum_single_symbol_profit_share"]), float(cg["maximum_single_symbol_profit_share"]), "MAX_SYMBOL_SHARE"),
        (float(frag["maximum_top10_trade_profit_share"]), float(cg["maximum_top10_trade_profit_share"]), "MAX_TOP10_SHARE"),
        (float(frag["minimum_leave_one_group_out_net_R"]), float(cg["minimum_leave_one_group_out_net_R"]), "MIN_LOO_NET_R"),
    ]
    for actual, source, name in checks:
        if actual != source:
            raise RuntimeError(f"A3_CONTRACT_SOURCE_DRIFT:{name}:{actual}:{source}")
    if list(frag.get("required_dimensions") or []) != list(cg.get("required_dimensions") or []):
        raise RuntimeError("A3_CONTRACT_DIMENSION_DRIFT")
    if int((contract.get("prospective_cohort") or {}).get("minimum_causally_matched_trades") or 0) != 25:
        raise RuntimeError("A3_TIER_A_SAMPLE_NOT_25")


def evaluate(receipt: Mapping[str, Any], a2: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    contract = read(CONTRACT)
    hardening = read(HARDENING)
    _validate_contract(contract, hardening)
    if a2.get("state") != "PASS_A2_COST_TURNOVER":
        raise RuntimeError("A2_PASS_REQUIRED")
    candidate_id = str(receipt.get("strategy_id") or "")
    if not candidate_id or a2.get("candidate_id") != candidate_id:
        raise RuntimeError("A2_A3_IDENTITY_MISMATCH")
    if a2.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("A2_A3_RECEIPT_LINEAGE_MISMATCH")

    taxonomy = read(v1.TAXONOMY)
    ready = read(v1.A3_READY)
    if taxonomy.get("stage") != "A3_PREP" or ready.get("state") != "A3_PREP_READY":
        raise RuntimeError("A3_PREP_NOT_READY")
    stale_after_ms = int((taxonomy.get("input_contract") or {}).get("stale_after_ms") or 0)
    boundary_ms = _ms(str(contract["activation_boundary_utc"]))
    minimum = int(contract["prospective_cohort"]["minimum_causally_matched_trades"])
    required_match = float(contract["prospective_cohort"]["minimum_match_fraction"])

    all_trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    cohort = [x for x in all_trades if int(x.get("entry_ts") or 0) >= boundary_ms]
    context_rows = [x for x in (context.get("rows") or []) if isinstance(x, Mapping)]
    joined: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    ages: list[int] = []
    for trade in cohort:
        ctx, reason, age = v1.match_context(trade, context_rows, stale_after_ms)
        if ctx is None:
            unmatched.append({"symbol": trade.get("symbol"), "signal_ts": trade.get("signal_ts"), "entry_ts": trade.get("entry_ts"), "reason": reason})
            continue
        assert age is not None
        ages.append(age)
        joined.append({
            "symbol": trade.get("symbol"), "signal_ts": trade.get("signal_ts"), "entry_ts": trade.get("entry_ts"), "exit_ts": trade.get("exit_ts"),
            "side": trade.get("side"), "gross_bps": float(trade["gross_bps"]), "net_bps": float(trade["net_bps"]),
            "context_capture_completed_at_ms": v1.capture_ms(ctx), "context_age_ms_at_entry": age,
            "context_row_sha256": v1.stable_sha(ctx), "regime": v1.classify(ctx),
        })

    match_fraction = len(joined) / len(cohort) if cohort else 1.0
    coverage = {
        "activation_boundary_utc": contract["activation_boundary_utc"],
        "pre_activation_trade_count_excluded": len(all_trades) - len(cohort),
        "prospective_candidate_trade_count": len(cohort),
        "matched_trade_count": len(joined),
        "unmatched_trade_count": len(unmatched),
        "matched_fraction": match_fraction,
        "minimum_causally_matched_trades": minimum,
        "minimum_match_fraction": required_match,
        "context_valid_row_count": sum(1 for x in context_rows if x.get("valid_for_a3") is True and x.get("causal_snapshot_eligible") is True),
        "context_legacy_ineligible_count": sum(1 for x in context_rows if x.get("legacy_causal_ineligible") is True),
        "maximum_context_age_ms_observed": max(ages) if ages else None,
        "minimum_context_age_ms_observed": min(ages) if ages else None,
        "sealed_stale_after_ms": stale_after_ms,
    }

    values = [float(x["net_bps"]) for x in joined]
    net_bps = sum(values)
    net_R = net_bps / 100.0
    expectancy_R = net_R / len(values) if values else None
    pf, payoff = _pf_payoff(values)
    economics = {
        "net_bps": net_bps,
        "net_R": net_R,
        "expectancy_R": expectancy_R,
        "profit_factor": pf,
        "payoff_ratio": payoff,
        "win_rate": (sum(1 for x in values if x > 0) / len(values)) if values else None,
    }

    dimensions = [str(x) for x in contract["concentration_fragility_gate"]["required_dimensions"]]
    loo = {dim: _leave_one_group_out(joined, dim) for dim in dimensions}
    regime_share, regime_shares = _positive_group_share(joined, "regime")
    symbol_share, symbol_shares = _positive_group_share(joined, "symbol")
    top10 = _top10_profit_share(joined)
    concentration = {
        "single_regime_profit_share": regime_share,
        "single_symbol_profit_share": symbol_share,
        "top10_trade_profit_share": top10,
        "regime_positive_profit_shares": regime_shares,
        "symbol_positive_profit_shares": symbol_shares,
        "leave_one_group_out_net_R": loo,
        "group_net_bps": {dim: _group_nets(joined, dim) for dim in dimensions},
    }

    blockers: list[str] = []
    failures: list[str] = []
    state: str
    if cohort and match_fraction < required_match:
        state = "HOLD_A3_CAUSAL_COVERAGE"
        blockers.append(f"A3_MATCH_FRACTION_LT_SEALED:{match_fraction:.8f}<{required_match:.8f}")
    elif len(joined) < minimum:
        state = "WAIT_A3_PROSPECTIVE_SAMPLE"
        blockers.append(f"A3_MATCHED_SAMPLE_LT25:{len(joined)}")
    else:
        econ_gate = contract["global_economic_gate"]
        if net_R <= float(econ_gate["minimum_net_R"]): failures.append(f"NET_R:{net_R:.8f}")
        if expectancy_R is None or expectancy_R <= float(econ_gate["minimum_expectancy_R"]): failures.append(f"EXPECTANCY_R:{expectancy_R}")
        if pf is None or pf < float(econ_gate["minimum_profit_factor"]): failures.append(f"PROFIT_FACTOR:{pf}")
        if payoff is None or payoff < float(econ_gate["minimum_payoff_ratio"]): failures.append(f"PAYOFF:{payoff}")
        frag = contract["concentration_fragility_gate"]
        if regime_share > float(frag["maximum_single_regime_profit_share"]): failures.append(f"REGIME_PROFIT_SHARE:{regime_share:.8f}")
        if symbol_share > float(frag["maximum_single_symbol_profit_share"]): failures.append(f"SYMBOL_PROFIT_SHARE:{symbol_share:.8f}")
        if top10 > float(frag["maximum_top10_trade_profit_share"]): failures.append(f"TOP10_PROFIT_SHARE:{top10:.8f}")
        min_loo = float(frag["minimum_leave_one_group_out_net_R"])
        for dim, groups in loo.items():
            for group, value in groups.items():
                if float(value) < min_loo:
                    failures.append(f"LOO_NET_R:{dim}:{group}:{float(value):.8f}")
        state = "FAIL_A3_GLOBAL_DURABILITY" if failures else "PASS_A3_GLOBAL_DURABILITY"

    result = {
        "schema_version": "zel.a3_exact25.forward_durability.v2",
        "stage": "A3", "candidate_id": candidate_id, "state": state,
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "a2_receipt_sha256": a2.get("receipt_sha256"), "context_receipt_sha256": context.get("receipt_sha256"),
        "contract_sha256": v1.stable_sha(contract), "hardening_policy_sha256": v1.stable_sha(hardening),
        "taxonomy_sha256": v1.stable_sha(taxonomy), "a3_ready_sha256": v1.stable_sha(ready),
        "prospective_only": True, "outcome_threshold_retune": False,
        "coverage": coverage, "economics": economics, "concentration_fragility": concentration,
        "joined_trades": joined, "unmatched_trades": unmatched,
        "regime_performance": {name: v1._aggregate(joined, name) for name in ("trend_state", "vol_state", "liquidity_state", "session_state", "funding_oi_state")},
        "entry_time_regime_owner": None,
        "explicit_regime_owner_pass_enabled": False,
        "global_durability_pass": state == "PASS_A3_GLOBAL_DURABILITY",
        "blockers": blockers, "failures": failures,
        "next_required_action": "ACCUMULATE_PROSPECTIVE_CAUSAL_A3_EVIDENCE" if state.startswith(("WAIT_", "HOLD_")) else "ROUTE_PASS_TO_S_GRADE" if state.startswith("PASS_") else "ROUTE_FAIL_TO_BOUNDED_REDESIGN_OR_SYNTHESIS",
        **AUTH,
    }
    result["receipt_sha256"] = v1.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    contract = read(CONTRACT); hardening = read(HARDENING); _validate_contract(contract, hardening)
    assert contract["activation_boundary_utc"] == "2026-08-21T17:00:00Z"
    assert contract["prospective_cohort"]["minimum_causally_matched_trades"] == 25
    assert _group_key({"entry_ts": 1787331600000}, "window") == "2026-08-21"
    print("PASS_A3_EXACT25_FORWARD_DURABILITY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--receipt", type=Path); ap.add_argument("--a2", type=Path); ap.add_argument("--context", type=Path); ap.add_argument("--output", type=Path, default=Path("out/a3_exact25_forward_durability_v2.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    if not args.receipt or not args.a2 or not args.context: raise SystemExit("--receipt --a2 --context required")
    result = evaluate(read(args.receipt), read(args.a2), read(args.context)); args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "candidate_id": result["candidate_id"], "coverage": result["coverage"], "economics": result["economics"], "failures": result["failures"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
