#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, strict, trade_key
from backend.research.rebuild.a1_trend_rider_wr80_winner_restore_attribution_v1 import _enrich

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2 = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.causal_rescue_broad_hardening.v3"
AXES = ("session", "st_gap_state", "chase_state", "atr_state", "geometry_balance")
MIN_PRIMARY_DISCOVERY_T = 3
MIN_BROAD_PROFILE_T = 5
EPS = 1e-12


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def avg_win(rows: list[Mapping[str, Any]]) -> float | None:
    xs = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0]
    return sum(xs) / len(xs) if xs else None


def avg_loss(rows: list[Mapping[str, Any]]) -> float | None:
    xs = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0]
    return sum(xs) / len(xs) if xs else None


def row(x: Mapping[str, Any]) -> dict[str, Any]:
    return {k: x.get(k) for k in (
        "symbol", "signal_ts", "entry_ts", "side", "net_bps", "reason",
        "session", "st_gap_state", "chase_state", "atr_state", "geometry_balance",
    )}


def gate_id(g: tuple[tuple[str, str], ...]) -> str:
    return "&".join(f"{a}={v}" for a, v in g)


def gates(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, str], ...]]:
    out: set[tuple[tuple[str, str], ...]] = set()
    for axis in AXES:
        for value in sorted({str(x.get(axis)) for x in rows}):
            out.add(((axis, value),))
    for a, b in itertools.combinations(AXES, 2):
        for x in rows:
            out.add(((a, str(x.get(a))), (b, str(x.get(b)))))
    return sorted(out, key=lambda x: (len(x), gate_id(x)))


def apply(rows: list[dict[str, Any]], g: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    return [dict(x) for x in rows if all(str(x.get(a)) == v for a, v in g)]


def failed(checks: Mapping[str, Any]) -> list[str]:
    return [k for k, v in checks.items() if not bool(v)]


def broad_checks(parent: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, bool]:
    pm, sm = metrics(parent), metrics(selected)
    pp, sp = payoff(parent), payoff(selected)
    paw, saw = avg_win(parent), avg_win(selected)
    pal, sal = avg_loss(parent), avg_loss(selected)
    pf_ok = bool(sm.get("profit_factor_unbounded")) or (
        sm.get("profit_factor") is not None and float(sm["profit_factor"]) + EPS >= float(pm["profit_factor"])
    )
    payoff_like_ok = (
        sp is not None and pp is not None and sp + EPS >= pp
    ) or (
        sp is None and float(sm.get("win_rate") or 0) == 1.0 and saw is not None and paw is not None and saw + EPS >= paw
    )
    strict_quality_improvement = (
        float(sm.get("win_rate") or 0) > float(pm.get("win_rate") or 0) + EPS
        or float(sm.get("net_expectancy_bps") or 0) > float(pm.get("net_expectancy_bps") or 0) + EPS
        or (saw is not None and paw is not None and saw > paw + EPS)
        or (sp is not None and pp is not None and sp > pp + EPS)
    )
    return {
        "selected_T_at_least_min": len(selected) >= MIN_BROAD_PROFILE_T,
        "selected_is_discriminative": len(selected) < len(parent),
        "selected_symbols_at_least_2": len({str(x["symbol"]) for x in selected}) >= 2,
        "selected_wr_at_least_parent": float(sm.get("win_rate") or 0) + EPS >= float(pm.get("win_rate") or 0),
        "selected_expectancy_at_least_parent": float(sm.get("net_expectancy_bps") or 0) + EPS >= float(pm.get("net_expectancy_bps") or 0),
        "selected_pf_at_least_parent": pf_ok,
        "selected_avg_win_at_least_parent": saw is not None and paw is not None and saw + EPS >= paw,
        "selected_payoff_like_at_least_parent": payoff_like_ok,
        "selected_avg_loss_no_worse": sal is None or pal is None or sal <= pal + EPS,
        "selected_pnl_positive": float(sm.get("net_pnl_bps") or 0) > 0,
        "strict_quality_improvement": strict_quality_improvement,
    }


def primary_rank(x: dict[str, Any]) -> tuple[Any, ...]:
    return (
        bool(x["historical_strict_pass"]),
        sum(bool(v) for v in x["checks"].values()),
        -abs(int(x["combined_T"]) - 25),
        float(x["combined_metrics"].get("net_expectancy_bps") or -1e99),
        float(x.get("combined_payoff") or -1e99),
        -int(x["depth"]),
    )


def broad_rank(x: dict[str, Any]) -> tuple[Any, ...]:
    return (
        bool(x["historical_profile_pass"]),
        sum(bool(v) for v in x["checks"].values()),
        float(x["selected_metrics"].get("win_rate") or 0),
        float(x["selected_metrics"].get("net_expectancy_bps") or -1e99),
        float(x.get("selected_payoff") or -1e99),
        int(x["selected_T"]),
        -int(x["depth"]),
    )


def validate_inputs(pd: Mapping[str, Any], fd: Mapping[str, Any], bd: Mapping[str, Any]) -> None:
    if len(pd.get("trades") or []) != 16 or abs(float(pd["metrics"]["win_rate"]) - 0.8125) > EPS:
        raise RuntimeError("PRIMARY_16T_8125_AUTHORITY_MISMATCH")
    if len(fd.get("trades") or []) != 2 or any(float(x["net_bps"]) <= 0 for x in fd.get("trades") or []):
        raise RuntimeError("FRESH2_AUTHORITY_MISMATCH")
    if len(bd.get("trades") or []) != 30 or abs(float(bd["metrics"]["win_rate"]) - 0.70) > EPS:
        raise RuntimeError("BROAD30_70_AUTHORITY_MISMATCH")


def run(broad_path: Path) -> dict[str, Any]:
    pd, fd, bd = read(PARENT), read(FRESH2), read(broad_path)
    validate_inputs(pd, fd, bd)
    parent = [dict(x) for x in pd["trades"]]
    fresh2 = [dict(x) for x in fd["trades"]]
    broad = [dict(x) for x in bd["trades"]]
    current_doc = rebuild_current()
    current = [dict(x) for x in current_doc.get("trades") or []]
    if not current:
        raise RuntimeError("CURRENT_REBUILD_EMPTY")

    # Entry-observable enrichment only; gate predicates never read outcome.
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for x in broad + current:
        by_key[trade_key(x)] = dict(x)
    enriched_rows = list(by_key.values())
    _enrich(bd, enriched_rows)
    missing = [x for x in enriched_rows if bool(x.get("feature_missing"))]
    if missing:
        raise RuntimeError(f"PREENTRY_FEATURE_MISSING:{len(missing)}")
    enriched = {trade_key(x): x for x in enriched_rows}
    broad = [dict(enriched[trade_key(x)]) for x in broad]
    current = [dict(enriched[trade_key(x)]) for x in current]

    pkeys = {trade_key(x) for x in parent}
    fkeys = {trade_key(x) for x in fresh2}
    bkeys = {trade_key(x) for x in broad}
    donor = [dict(x) for x in broad if trade_key(x) not in pkeys and trade_key(x) not in fkeys]
    overlap = [x for x in broad if trade_key(x) in pkeys]
    if len(overlap) != 15 or len(donor) != 15:
        raise RuntimeError(f"BROAD_MEMBERSHIP_MISMATCH:{len(overlap)}:{len(donor)}")

    boundary_ts = max(int(x["signal_ts"]) for x in broad)
    holdout = [
        dict(x) for x in current
        if int(x["signal_ts"]) > boundary_ts and trade_key(x) not in bkeys and trade_key(x) not in fkeys
    ]

    all_gates = gates(broad)

    # PRIMARY: choose one gate strictly from historical donor ranking, then test it once on holdout.
    primary_candidates: list[dict[str, Any]] = []
    for g in all_gates:
        sel = apply(donor, g)
        if len(sel) < MIN_PRIMARY_DISCOVERY_T:
            continue
        ok, checks, am, cm, cp = strict(parent, fresh2 + sel)
        primary_candidates.append({
            "gate_id": gate_id(g),
            "terms": [{"field": a, "op": "eq", "value": v} for a, v in g],
            "depth": len(g),
            "historical_selected_T": len(sel),
            "historical_selected_rows": [row(x) for x in sel],
            "historical_strict_pass": bool(ok),
            "checks": checks,
            "failed_checks": failed(checks),
            "added_metrics_with_fresh2": am,
            "combined_T": len(parent) + len(fresh2) + len(sel),
            "combined_metrics": cm,
            "combined_payoff": cp,
        })
    primary_candidates.sort(key=primary_rank, reverse=True)
    primary_gate = primary_candidates[0] if primary_candidates else None
    primary_holdout: dict[str, Any] | None = None
    primary_preregisterable = False
    if primary_gate is not None:
        g = tuple((str(x["field"]), str(x["value"])) for x in primary_gate["terms"])
        hist = apply(donor, g)
        val = apply(holdout, g)
        ok, checks, am, cm, cp = strict(parent, fresh2 + hist + val)
        primary_holdout = {
            "holdout_source_T": len(holdout),
            "holdout_selected_T": len(val),
            "holdout_selected_rows": [row(x) for x in val],
            "combined_T": len(parent) + len(fresh2) + len(hist) + len(val),
            "strict_pass": bool(ok),
            "checks": checks,
            "failed_checks": failed(checks),
            "added_metrics": am,
            "combined_metrics": cm,
            "combined_payoff": cp,
            "promotion_evidence": False,
        }
        primary_preregisterable = bool(primary_gate["historical_strict_pass"] and ok)

    # BROAD30: identity gates are impossible by contract. Select a genuinely better historical profile, then one-shot holdout.
    broad_candidates: list[dict[str, Any]] = []
    for g in all_gates:
        sel = apply(broad, g)
        if len(sel) < MIN_BROAD_PROFILE_T:
            continue
        checks = broad_checks(broad, sel)
        broad_candidates.append({
            "gate_id": gate_id(g),
            "terms": [{"field": a, "op": "eq", "value": v} for a, v in g],
            "depth": len(g),
            "selected_T": len(sel),
            "selected_symbols": sorted({str(x["symbol"]) for x in sel}),
            "selected_metrics": metrics(sel),
            "selected_payoff": payoff(sel),
            "selected_avg_win_bps": avg_win(sel),
            "selected_avg_loss_bps": avg_loss(sel),
            "checks": checks,
            "failed_checks": failed(checks),
            "historical_profile_pass": all(checks.values()),
        })
    broad_candidates.sort(key=broad_rank, reverse=True)
    broad_gate = next((x for x in broad_candidates if x["historical_profile_pass"]), None)
    if broad_gate is None and broad_candidates:
        broad_gate = broad_candidates[0]

    broad_holdout: dict[str, Any] | None = None
    broad_preregisterable = False
    if broad_gate is not None:
        g = tuple((str(x["field"]), str(x["value"])) for x in broad_gate["terms"])
        val = apply(holdout, g)
        if val:
            ok, checks, am, cm, cp = strict(broad, val)
            broad_holdout = {
                "holdout_source_T": len(holdout),
                "holdout_selected_T": len(val),
                "holdout_selected_rows": [row(x) for x in val],
                "strict_add_only_pass": bool(ok),
                "checks": checks,
                "failed_checks": failed(checks),
                "added_metrics": am,
                "combined_T": len(broad) + len(val),
                "combined_metrics": cm,
                "combined_payoff": cp,
                "promotion_evidence": False,
            }
            broad_preregisterable = bool(broad_gate["historical_profile_pass"] and ok)
        else:
            broad_holdout = {
                "holdout_source_T": len(holdout),
                "holdout_selected_T": 0,
                "strict_add_only_pass": False,
                "failed_checks": ["NO_HOLDOUT_MATCH"],
                "promotion_evidence": False,
            }

    if primary_preregisterable and broad_preregisterable:
        state = "PASS_PRIMARY_AND_BROAD_CAUSAL_GATES_PREREGISTERABLE"
    elif primary_preregisterable:
        state = "HOLD_BROAD_GATE_REJECTED_PRIMARY_GATE_PREREGISTERABLE"
    elif broad_preregisterable:
        state = "HOLD_PRIMARY_GATE_REJECTED_BROAD_GATE_PREREGISTERABLE"
    else:
        state = "HOLD_NO_CAUSAL_GATE_SURVIVES_HOLDOUT"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary": {
            "parent_T": 16,
            "parent_metrics": metrics(parent),
            "parent_payoff": payoff(parent),
            "fresh2_fixed_T": 2,
            "fresh2_metrics": metrics(fresh2),
            "historical_donor_distinct_T": len(donor),
            "candidate_gate_count": len(primary_candidates),
            "historical_recommended_gate": primary_gate,
            "holdout_validation": primary_holdout,
            "causal_gate_preregisterable": primary_preregisterable,
        },
        "broad30": {
            "parent_T": 30,
            "parent_metrics": metrics(broad),
            "parent_payoff": payoff(broad),
            "parent_avg_win_bps": avg_win(broad),
            "parent_avg_loss_bps": avg_loss(broad),
            "candidate_gate_count": len(broad_candidates),
            "historical_recommended_gate": broad_gate,
            "holdout_validation": broad_holdout,
            "causal_gate_preregisterable": broad_preregisterable,
        },
        "holdout_corpus": {
            "current_native_T": len(current),
            "broad_boundary_signal_ts": boundary_ts,
            "post_broad_distinct_T": len(holdout),
            "max_holdout_signal_ts": max([int(x["signal_ts"]) for x in holdout], default=boundary_ts),
        },
        "gate_contract": {
            "feature_axes": list(AXES),
            "max_conjunction_depth": 2,
            "numeric_threshold_sweep": False,
            "symbol_specific_gate_forbidden": True,
            "identity_gate_forbidden": True,
            "strict_historical_quality_improvement_required_for_broad": True,
            "outcome_used_for_historical_discovery_only": True,
            "outcome_used_at_runtime": False,
            "one_shot_holdout_required_before_freeze": True,
            "holdout_not_promotion_evidence": True,
            "parent_trade_deletion_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "fresh_prospective_confirmation_required_after_freeze": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": (
            "FREEZE_ONLY_PREREGISTERABLE_GATES_AT_HOLDOUT_BOUNDARY_AND_ACCEPT_NEW_PROSPECTIVE_MATCHES"
            if primary_preregisterable or broad_preregisterable
            else "REJECT_CURRENT_NAMED_CAUSAL_AXES_AND_ROTATE_TO_NEW_ENTRY_OBSERVABLE_MECHANISM"
        ),
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_causal_rescue_broad_hardening_v3.json"))
    args = ap.parse_args()
    r = run(args.broad_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    p = r["primary"]["historical_recommended_gate"] or {}
    b = r["broad30"]["historical_recommended_gate"] or {}
    print(json.dumps({
        "state": r["state"],
        "primary_gate": p.get("gate_id"),
        "primary_historical_pass": p.get("historical_strict_pass"),
        "primary_holdout": r["primary"]["holdout_validation"],
        "primary_preregisterable": r["primary"]["causal_gate_preregisterable"],
        "broad_gate": b.get("gate_id"),
        "broad_profile_pass": b.get("historical_profile_pass"),
        "broad_selected_T": b.get("selected_T"),
        "broad_selected_metrics": b.get("selected_metrics"),
        "broad_selected_payoff": b.get("selected_payoff"),
        "broad_holdout": r["broad30"]["holdout_validation"],
        "broad_preregisterable": r["broad30"]["causal_gate_preregisterable"],
        "holdout": r["holdout_corpus"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
