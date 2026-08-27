#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import (
    metrics,
    payoff,
    strict,
    trade_key,
)
from backend.research.rebuild.a1_trend_rider_wr80_winner_restore_attribution_v1 import _enrich

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2 = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.causal_rescue_broad_hardening.v2"
AXES = ("session", "st_gap_state", "chase_state", "atr_state", "geometry_balance")
MIN_DISCOVERY_T = 3
MIN_BROAD_PROFILE_T = 5


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def avg_win(rows: list[Mapping[str, Any]]) -> float | None:
    w = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0]
    return sum(w) / len(w) if w else None


def avg_loss(rows: list[Mapping[str, Any]]) -> float | None:
    l = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0]
    return sum(l) / len(l) if l else None


def semantic_row(x: Mapping[str, Any]) -> dict[str, Any]:
    return {k: x.get(k) for k in (
        "symbol", "signal_ts", "entry_ts", "side", "net_bps", "reason",
        "session", "st_gap_state", "chase_state", "atr_state", "geometry_balance",
    )}


def gate_id(terms: tuple[tuple[str, str], ...]) -> str:
    return "&".join(f"{a}={v}" for a, v in terms)


def candidate_gates(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, str], ...]]:
    out: set[tuple[tuple[str, str], ...]] = set()
    for axis in AXES:
        for value in sorted({str(x.get(axis)) for x in rows}):
            out.add(((axis, value),))
    for a, b in itertools.combinations(AXES, 2):
        for x in rows:
            out.add(((a, str(x.get(a))), (b, str(x.get(b)))))
    return sorted(out, key=lambda g: (len(g), gate_id(g)))


def apply_gate(rows: list[dict[str, Any]], terms: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    return [dict(x) for x in rows if all(str(x.get(a)) == v for a, v in terms)]


def failed(checks: Mapping[str, Any]) -> list[str]:
    return [k for k, v in checks.items() if not bool(v)]


def broad_profile_checks(parent: list[dict[str, Any]], cohort: list[dict[str, Any]]) -> dict[str, bool]:
    pm, cm = metrics(parent), metrics(cohort)
    pp, cp = payoff(parent), payoff(cohort)
    paw, caw = avg_win(parent), avg_win(cohort)
    pal, cal = avg_loss(parent), avg_loss(cohort)
    cohort_pf_ok = bool(cm.get("profit_factor_unbounded")) or (
        cm.get("profit_factor") is not None and float(cm["profit_factor"]) >= float(pm["profit_factor"])
    )
    payoff_like_ok = (
        (cp is not None and pp is not None and cp >= pp)
        or (cp is None and float(cm.get("win_rate") or 0) == 1.0 and caw is not None and paw is not None and caw >= paw)
    )
    return {
        "selected_T_at_least_min": len(cohort) >= MIN_BROAD_PROFILE_T,
        "selected_symbols_at_least_2": len({str(x["symbol"]) for x in cohort}) >= 2,
        "selected_wr_at_least_parent": float(cm.get("win_rate") or 0) >= float(pm.get("win_rate") or 0),
        "selected_expectancy_at_least_parent": float(cm.get("net_expectancy_bps") or 0) >= float(pm.get("net_expectancy_bps") or 0),
        "selected_pf_at_least_parent": cohort_pf_ok,
        "selected_avg_win_at_least_parent": caw is not None and paw is not None and caw >= paw,
        "selected_payoff_like_at_least_parent": payoff_like_ok,
        "selected_avg_loss_no_worse": cal is None or pal is None or cal <= pal,
        "selected_pnl_positive": float(cm.get("net_pnl_bps") or 0) > 0,
    }


def rank_primary(item: dict[str, Any]) -> tuple[Any, ...]:
    checks = item["checks"]
    return (
        bool(item["strict_pass"]),
        sum(bool(v) for v in checks.values()),
        -abs(int(item["combined_T"]) - 25),
        float(item["combined_metrics"].get("net_expectancy_bps") or -1e99),
        float(item.get("combined_payoff") or -1e99),
        int(item["selected_T"]),
    )


def rank_broad(item: dict[str, Any]) -> tuple[Any, ...]:
    checks = item["profile_checks"]
    return (
        bool(item["profile_pass"]),
        sum(bool(v) for v in checks.values()),
        int(item["selected_T"]),
        float(item["selected_metrics"].get("net_expectancy_bps") or -1e99),
        float(item.get("selected_payoff") or -1e99),
    )


def run(broad_path: Path) -> dict[str, Any]:
    pd, fd, bd = read(PARENT), read(FRESH2), read(broad_path)
    parent = [dict(x) for x in pd.get("trades") or []]
    fresh2 = [dict(x) for x in fd.get("trades") or []]
    broad = [dict(x) for x in bd.get("trades") or []]
    if len(parent) != 16 or abs(float(pd["metrics"]["win_rate"]) - 0.8125) > 1e-12:
        raise RuntimeError("PRIMARY_16T_8125_AUTHORITY_MISMATCH")
    if len(fresh2) != 2 or any(float(x["net_bps"]) <= 0 for x in fresh2):
        raise RuntimeError("FRESH2_AUTHORITY_MISMATCH")
    if len(broad) != 30 or abs(float(bd["metrics"]["win_rate"]) - 0.70) > 1e-12:
        raise RuntimeError("BROAD30_70_AUTHORITY_MISMATCH")

    current_doc = rebuild_current()
    current = [dict(x) for x in current_doc.get("trades") or []]
    if not current:
        raise RuntimeError("CURRENT_REBUILD_EMPTY")

    # Feature enrichment is entry-time only. Outcome is never read by a gate predicate.
    all_enrich = [dict(x) for x in broad] + [dict(x) for x in current]
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for x in all_enrich:
        by_key[trade_key(x)] = x
    enrich_rows = list(by_key.values())
    _enrich(bd, enrich_rows)
    if any(bool(x.get("feature_missing")) for x in enrich_rows):
        missing = [list(trade_key(x)) for x in enrich_rows if bool(x.get("feature_missing"))]
        raise RuntimeError(f"PREENTRY_FEATURE_MISSING:{missing[:3]}:{len(missing)}")
    enriched = {trade_key(x): x for x in enrich_rows}
    broad = [dict(enriched[trade_key(x)]) for x in broad]
    current = [dict(enriched[trade_key(x)]) for x in current]

    pkeys = {trade_key(x) for x in parent}
    fkeys = {trade_key(x) for x in fresh2}
    bkeys = {trade_key(x) for x in broad}
    donor = [dict(x) for x in broad if trade_key(x) not in pkeys and trade_key(x) not in fkeys]
    overlap = [x for x in broad if trade_key(x) in pkeys]
    if len(overlap) != 15 or len(donor) != 15:
        raise RuntimeError(f"BROAD_MEMBERSHIP_MISMATCH:{len(overlap)}:{len(donor)}")

    broad_max_signal_ts = max(int(x["signal_ts"]) for x in broad)
    validation = [
        dict(x) for x in current
        if int(x["signal_ts"]) > broad_max_signal_ts and trade_key(x) not in bkeys and trade_key(x) not in fkeys
    ]

    gates = candidate_gates(broad)
    primary_results: list[dict[str, Any]] = []
    for g in gates:
        selected = apply_gate(donor, g)
        if len(selected) < MIN_DISCOVERY_T:
            continue
        ok, checks, am, cm, cp = strict(parent, fresh2 + selected)
        primary_results.append({
            "gate_id": gate_id(g),
            "terms": [{"field": a, "op": "eq", "value": v} for a, v in g],
            "depth": len(g),
            "selected_T": len(selected),
            "selected_rows": [semantic_row(x) for x in selected],
            "strict_pass": bool(ok),
            "checks": checks,
            "failed_checks": failed(checks),
            "added_metrics_with_fresh2": am,
            "combined_T": len(parent) + len(fresh2) + len(selected),
            "combined_metrics": cm,
            "combined_payoff": cp,
            "outcome_blind_at_runtime": True,
            "numeric_threshold_sweep": False,
        })
    primary_results.sort(key=rank_primary, reverse=True)
    primary_gate = primary_results[0] if primary_results else None

    primary_validation = None
    if primary_gate is not None:
        terms = tuple((str(x["field"]), str(x["value"])) for x in primary_gate["terms"])
        historical_selected = apply_gate(donor, terms)
        validation_selected = apply_gate(validation, terms)
        ok, checks, am, cm, cp = strict(parent, fresh2 + historical_selected + validation_selected)
        primary_validation = {
            "validation_source_T": len(validation),
            "validation_selected_T": len(validation_selected),
            "validation_selected_rows": [semantic_row(x) for x in validation_selected],
            "historical_selected_T": len(historical_selected),
            "combined_T": len(parent) + len(fresh2) + len(historical_selected) + len(validation_selected),
            "strict_pass": bool(ok),
            "checks": checks,
            "failed_checks": failed(checks),
            "added_metrics": am,
            "combined_metrics": cm,
            "combined_payoff": cp,
            "validation_is_pre_freeze_only": True,
            "promotion_evidence": False,
        }

    broad_results: list[dict[str, Any]] = []
    for g in gates:
        selected = apply_gate(broad, g)
        if len(selected) < MIN_BROAD_PROFILE_T:
            continue
        checks = broad_profile_checks(broad, selected)
        broad_results.append({
            "gate_id": gate_id(g),
            "terms": [{"field": a, "op": "eq", "value": v} for a, v in g],
            "depth": len(g),
            "selected_T": len(selected),
            "selected_symbols": sorted({str(x["symbol"]) for x in selected}),
            "selected_metrics": metrics(selected),
            "selected_payoff": payoff(selected),
            "selected_avg_win_bps": avg_win(selected),
            "selected_avg_loss_bps": avg_loss(selected),
            "profile_checks": checks,
            "profile_pass": all(checks.values()),
            "outcome_blind_at_runtime": True,
            "numeric_threshold_sweep": False,
        })
    broad_results.sort(key=rank_broad, reverse=True)
    broad_gate = broad_results[0] if broad_results else None

    broad_validation = None
    if broad_gate is not None:
        terms = tuple((str(x["field"]), str(x["value"])) for x in broad_gate["terms"])
        selected = apply_gate(validation, terms)
        if selected:
            ok, checks, am, cm, cp = strict(broad, selected)
            broad_validation = {
                "validation_source_T": len(validation),
                "validation_selected_T": len(selected),
                "validation_selected_rows": [semantic_row(x) for x in selected],
                "strict_add_only_pass": bool(ok),
                "checks": checks,
                "failed_checks": failed(checks),
                "added_metrics": am,
                "combined_T": len(broad) + len(selected),
                "combined_metrics": cm,
                "combined_payoff": cp,
                "validation_is_pre_freeze_only": True,
                "promotion_evidence": False,
            }
        else:
            broad_validation = {
                "validation_source_T": len(validation),
                "validation_selected_T": 0,
                "strict_add_only_pass": False,
                "failed_checks": ["NO_VALIDATION_MATCH"],
                "validation_is_pre_freeze_only": True,
                "promotion_evidence": False,
            }

    state = "PASS_CAUSAL_GATES_PREREGISTERABLE"
    if primary_gate is None or broad_gate is None:
        state = "HOLD_CAUSAL_GATE_DISCOVERY_EMPTY"
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
            "broad_distinct_donor_T": len(donor),
            "candidate_gate_count": len(primary_results),
            "recommended_causal_gate": primary_gate,
            "pre_freeze_validation": primary_validation,
        },
        "broad30": {
            "parent_T": 30,
            "parent_metrics": metrics(broad),
            "parent_payoff": payoff(broad),
            "parent_avg_win_bps": avg_win(broad),
            "parent_avg_loss_bps": avg_loss(broad),
            "candidate_gate_count": len(broad_results),
            "recommended_future_add_gate": broad_gate,
            "pre_freeze_validation": broad_validation,
        },
        "validation_corpus": {
            "current_native_T": len(current),
            "broad_max_signal_ts": broad_max_signal_ts,
            "post_broad_distinct_T": len(validation),
            "max_validation_signal_ts": max([int(x["signal_ts"]) for x in validation], default=broad_max_signal_ts),
        },
        "gate_contract": {
            "feature_axes": list(AXES),
            "max_conjunction_depth": 2,
            "numeric_threshold_sweep": False,
            "symbol_specific_gate_forbidden": True,
            "outcome_used_for_historical_discovery_only": True,
            "outcome_used_at_runtime": False,
            "parent_trade_deletion_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "fresh_prospective_confirmation_required": True,
            "pre_freeze_validation_not_promotion_evidence": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": "FREEZE_RECOMMENDED_GATES_AT_CURRENT_VALIDATION_BOUNDARY_THEN_ACCEPT_ONLY_NEW_PROSPECTIVE_MATCHES",
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_causal_rescue_broad_hardening_v2.json"))
    args = ap.parse_args()
    r = run(args.broad_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "primary_gate": (r["primary"]["recommended_causal_gate"] or {}).get("gate_id"),
        "primary_pre_freeze": r["primary"]["pre_freeze_validation"],
        "broad_gate": (r["broad30"]["recommended_future_add_gate"] or {}).get("gate_id"),
        "broad_pre_freeze": r["broad30"]["pre_freeze_validation"],
        "validation": r["validation_corpus"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
