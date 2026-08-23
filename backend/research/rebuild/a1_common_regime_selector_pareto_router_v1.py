#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
LATEST = ROOT / "backend/research/rebuild/a1_common_regime_selector_pareto_latest.json"

EVIDENCE = {
    "loss": ROOT / "backend/research/rebuild/a1_recent_loss_cluster_actionable_latest.json",
    "keltner_loss": ROOT / "backend/research/rebuild/a1_keltner_loss_preentry_attribution_latest.json",
    "no_idle": ROOT / "backend/research/rebuild/a1_finalist_sample_stall_no_idle_latest.json",
    "fresh_growth": ROOT / "backend/research/rebuild/a1_finalist_fresh_growth_latest.json",
    "trend_restore": ROOT / "backend/research/rebuild/a1_trend_rider_wr80_winner_restore_attribution_latest.json",
    "trend_fresh": ROOT / "backend/research/rebuild/a1_trend_rider_wr80_us_chase_cooling_forward_latest.json",
    "ema21_prereg": ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_prereg_v1.json",
    "ema21_fresh": ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_fresh_latest.json",
}

STRATEGY_FEATURES = {
    "trend_rider": ["ATR_PCT", "CHASE_ATR", "ST_GAP_ATR", "SESSION"],
    "supertrend_pullback": ["ALIGNED_RECLAIM", "PULLBACK_DEPTH_ATR", "CHASE_ATR"],
    "break_and_continue": ["PRIOR_RANGE_BREAK", "EMA_ALIGNMENT", "BOX_HEIGHT_ATR", "CHASE_ATR"],
    "trend_ma_macd": ["EMA_ALIGNMENT", "MACD_ZERO_CROSS", "MACD_REACCELERATION", "CHASE_ATR"],
    "keltner_trend": ["ATR_PCT", "EMA_SPREAD_ATR", "CHASE_ATR", "SESSION"],
    "regime_ema21_reclaim_v1": ["VOL_HIGH", "EMA21_TOUCH", "EMA21_RECLAIM", "EMA21_EMA55_ALIGNMENT"],
}

FORBIDDEN_RUNTIME_AXES = {
    "REASON", "HOLD_BARS", "REALIZED_COST_BPS", "COST_TO_ABS_GROSS",
    "NET_BPS", "GROSS_BPS", "PNL", "WIN", "LOSS",
}

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}

QUALITY_HIGHER_IS_BETTER = ("win_rate", "net_pnl_bps", "net_expectancy_bps", "winner_retention")
QUALITY_LOWER_IS_BETTER = ("realized_exit_bucket_max_drawdown_bps", "max_drawdown_bps")


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def read_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def targets_by_id(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in value.get("targets", []) if isinstance(value.get("targets"), list) else []:
        if isinstance(row, Mapping) and row.get("strategy_id"):
            out[str(row["strategy_id"])] = dict(row)
    return out


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def pick_metric(row: Mapping[str, Any], name: str) -> float | None:
    candidates: list[Any] = []
    metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    candidates.append(metrics.get(name))
    candidates.append(row.get(name))
    aliases = {
        "net_pnl_bps": ("net_bps", "pnl_bps"),
        "net_expectancy_bps": ("expectancy_bps", "net_expectancy"),
        "realized_exit_bucket_max_drawdown_bps": ("realized_max_drawdown_bps",),
        "max_drawdown_bps": ("dd_bps",),
        "winner_retention": ("winner_retention_rate",),
    }
    for alias in aliases.get(name, ()):
        candidates.append(metrics.get(alias))
        candidates.append(row.get(alias))
    for value in candidates:
        parsed = finite(value)
        if parsed is not None:
            return parsed
    return None


def normalize_metrics(row: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        name: pick_metric(row, name)
        for name in QUALITY_HIGHER_IS_BETTER + QUALITY_LOWER_IS_BETTER
    }


def pareto(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    pm = normalize_metrics(parent)
    cm = normalize_metrics(child)
    improved: list[str] = []
    worsened: list[str] = []
    equal: list[str] = []
    compared: list[str] = []

    for name in QUALITY_HIGHER_IS_BETTER:
        p, c = pm[name], cm[name]
        if p is None or c is None:
            continue
        compared.append(name)
        if c > p:
            improved.append(name)
        elif c < p:
            worsened.append(name)
        else:
            equal.append(name)

    for name in QUALITY_LOWER_IS_BETTER:
        p, c = pm[name], cm[name]
        if p is None or c is None:
            continue
        compared.append(name)
        if c < p:
            improved.append(name)
        elif c > p:
            worsened.append(name)
        else:
            equal.append(name)

    if improved and not worsened:
        relation = "PARETO_DOMINATES_PARENT"
    elif improved and worsened:
        relation = "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND"
    elif worsened and not improved:
        relation = "DOMINATED_DO_NOT_PROMOTE"
    else:
        relation = "NEUTRAL_OR_INSUFFICIENT_COMPARABLE_METRICS"

    return {
        "relation": relation,
        "compared_metrics": compared,
        "improved_metrics": improved,
        "worsened_metrics": worsened,
        "equal_metrics": equal,
        "parent_metrics": pm,
        "child_metrics": cm,
        "partial_success_preserved": relation == "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND",
        "promotion_claim": False,
    }


def fresh_status(value: Mapping[str, Any]) -> dict[str, Any] | None:
    if not value:
        return None
    completed = value.get("completed_trades")
    if completed is None and isinstance(value.get("fresh"), Mapping):
        completed = value["fresh"].get("completed_trades")
    sample_gap = value.get("sample_gap")
    if sample_gap is None and finite(completed) is not None:
        sample_gap = max(0, 25 - int(float(completed)))
    hardening = value.get("hardening") if isinstance(value.get("hardening"), Mapping) else {}
    return {
        "state": value.get("state"),
        "completed_trades": completed,
        "sample_gap": sample_gap,
        "h4_state": value.get("h4_state") or hardening.get("h4_state"),
        "h5_state": value.get("h5_state") or hardening.get("h5_state"),
    }


def loss_candidate(strategy_id: str, loss_targets: Mapping[str, Any], keltner_loss: Mapping[str, Any]) -> dict[str, Any] | None:
    row: Mapping[str, Any] = loss_targets.get(strategy_id) or {}
    if strategy_id == "keltner_trend" and keltner_loss:
        row = keltner_loss
    root = row.get("actionable_root_cause") if isinstance(row.get("actionable_root_cause"), Mapping) else None
    if not root:
        return None
    axis = str(root.get("axis") or "")
    if not axis or axis.upper() in FORBIDDEN_RUNTIME_AXES:
        return None
    return {
        "axis": axis,
        "value": root.get("value"),
        "relative_delta": root.get("relative_delta"),
        "diagnostic_score": root.get("diagnostic_score"),
        "source_state": row.get("state"),
        "preentry_only": True,
        "runtime_enabled": False,
        "required_next": "ONE_AXIS_AVOIDANCE_CHILD_THEN_PARETO_AND_FRESH_PROOF",
    }


def no_idle_trigger(strategy_id: str, no_idle_targets: Mapping[str, Any]) -> dict[str, Any] | None:
    row = no_idle_targets.get(strategy_id)
    if not isinstance(row, Mapping):
        return None
    diag = row.get("parent_diagnostic") if isinstance(row.get("parent_diagnostic"), Mapping) else {}
    root = str(diag.get("root_cause_class") or "")
    if not root or root == "NORMAL_ACCUMULATION":
        return None
    return {
        "root_cause_class": root,
        "tail_loss_streak": diag.get("tail_loss_streak"),
        "max_loss_streak": diag.get("max_loss_streak"),
        "sample_stall_triggered": diag.get("sample_stall_triggered"),
        "closure_lag_triggered": diag.get("closure_lag_triggered"),
        "projected_remaining_hours_to_25": diag.get("projected_remaining_hours_to_25"),
        "largest_funnel_drop_stage": (diag.get("feature_funnel") or {}).get("largest_sequential_drop_stage") if isinstance(diag.get("feature_funnel"), Mapping) else None,
        "recommended_route": diag.get("recommended_route"),
    }


def no_idle_good_candidate(strategy_id: str, no_idle_targets: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    row = no_idle_targets.get(strategy_id)
    if not isinstance(row, Mapping):
        return None, None
    comp = row.get("comparison") if isinstance(row.get("comparison"), Mapping) else {}
    if not comp:
        comp = row.get("child_comparison") if isinstance(row.get("child_comparison"), Mapping) else {}
    if not comp:
        return None, None
    parent = comp.get("parent") if isinstance(comp.get("parent"), Mapping) else {}
    child = comp.get("child") if isinstance(comp.get("child"), Mapping) else {}
    p = pareto(parent, child) if parent and child else None
    eligible = bool(comp.get("development_prereg_eligible"))
    if not eligible and not (p and p["relation"] in {"PARETO_DOMINATES_PARENT", "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND"}):
        return None, p
    return {
        "child_id": row.get("child_id"),
        "changed_axis": row.get("changed_axis"),
        "development_prereg": row.get("development_prereg"),
        "preentry_only": True,
        "runtime_enabled": False,
        "fresh_proof_required": True,
    }, p


def trend_good_candidate(attribution: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not attribution:
        return None, None
    rec = attribution.get("recommended_discovery_child")
    if not isinstance(rec, Mapping):
        return None, None
    base = attribution.get("non_us_partial_success") if isinstance(attribution.get("non_us_partial_success"), Mapping) else {}
    child = rec.get("candidate") if isinstance(rec.get("candidate"), Mapping) else {}
    p = pareto(base, child) if base and child else None
    return {
        "axis": rec.get("axis"),
        "value": rec.get("value"),
        "us_winner_reintroduced": rec.get("us_winner_reintroduced"),
        "us_loser_reintroduced": rec.get("us_loser_reintroduced"),
        "preentry_only": True,
        "runtime_enabled": False,
        "fresh_proof_required": True,
    }, p


def route_for(
    *,
    bad: Mapping[str, Any] | None,
    trigger: Mapping[str, Any] | None,
    good: Mapping[str, Any] | None,
    fresh: Mapping[str, Any] | None,
    relation: str | None,
) -> str:
    if good and fresh and finite(fresh.get("completed_trades")) is not None and int(float(fresh["completed_trades"])) >= 25:
        return "RUN_IDENTITY_H4_H5; PRESERVE_PARENT_AND_CHILD_UNTIL_RESULT"
    if good:
        return "PRESERVE_PARTIAL_SUCCESS; COLLECT_FRESH; CONTINUE_WINNER_PNL_RESTORE_WITHOUT_RETUNE"
    if bad:
        return "BUILD_DISTINCT_PREENTRY_AVOIDANCE_CHILD; KEEP_PARENT; PARETO_COMPARE; FRESH_PROOF"
    if trigger:
        root = str(trigger.get("root_cause_class") or "")
        if root == "LOSS_CLUSTER":
            return "USE_LOSS_CLUSTER_PREENTRY_DIAGNOSTIC_NOW"
        if root == "EXIT_CLOSURE_LAG":
            return "DIAGNOSE_LIFECYCLE_OR_UNIVERSE; DO_NOT_RELAX_ENTRY"
        if root == "ADMISSION_SAMPLE_STALL":
            return "RUN_STRATEGY_SPECIFIC_SAMPLE_EXPANSION_CHILD_NOW"
    if relation == "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND":
        return "PRESERVE_PARTIAL_SUCCESS_AND_EXTEND_ONE_AXIS"
    return "NEUTRAL_PARENT_COLLECT; RECHECK_TRIGGER_HOURLY"


def run(out: Path) -> dict[str, Any]:
    evidence = {name: read_optional(path) for name, path in EVIDENCE.items()}
    loss_targets = targets_by_id(evidence["loss"])
    no_idle_targets = targets_by_id(evidence["no_idle"])
    fresh_growth_targets = targets_by_id(evidence["fresh_growth"])

    rows: list[dict[str, Any]] = []
    for strategy_id in STRATEGY_FEATURES:
        bad = loss_candidate(strategy_id, loss_targets, evidence["keltner_loss"])
        trigger = no_idle_trigger(strategy_id, no_idle_targets)

        good: dict[str, Any] | None = None
        p: dict[str, Any] | None = None
        fresh: dict[str, Any] | None = None

        if strategy_id == "trend_rider":
            good, p = trend_good_candidate(evidence["trend_restore"])
            fresh = fresh_status(evidence["trend_fresh"])
        elif strategy_id in {"supertrend_pullback", "break_and_continue", "trend_ma_macd"}:
            good, p = no_idle_good_candidate(strategy_id, no_idle_targets)
            fresh = fresh_status(fresh_growth_targets.get(strategy_id) or {})
        elif strategy_id == "keltner_trend":
            fresh = fresh_status(fresh_growth_targets.get(strategy_id) or {})
        elif strategy_id == "regime_ema21_reclaim_v1":
            prereg = evidence["ema21_prereg"]
            if prereg:
                good = {
                    "axis": "EMA21_TOUCH_RECLAIM_WITHIN_VOL_HIGH_DIRECTIONAL_REGIME",
                    "prereg_state": prereg.get("state"),
                    "fresh_boundary_utc": prereg.get("fresh_boundary_utc") or prereg.get("boundary_utc"),
                    "preentry_only": True,
                    "runtime_enabled": False,
                    "fresh_proof_required": True,
                }
            fresh = fresh_status(evidence["ema21_fresh"])

        if bad and str(bad.get("axis") or "").upper() not in set(STRATEGY_FEATURES[strategy_id]):
            bad["registry_match"] = False
            bad["runtime_enabled"] = False
        elif bad:
            bad["registry_match"] = True

        trigger_classes: list[str] = []
        if bad:
            trigger_classes.append("LOSS_OR_BAD_REGIME_CANDIDATE")
        if trigger:
            root = str(trigger.get("root_cause_class") or "")
            if root and root != "NORMAL_ACCUMULATION":
                trigger_classes.append(root)
        if good:
            trigger_classes.append("GOOD_REGIME_OR_PARTIAL_SUCCESS_CANDIDATE")

        relation = p.get("relation") if p else None
        rows.append({
            "strategy_id": strategy_id,
            "allowed_preentry_feature_axes": STRATEGY_FEATURES[strategy_id],
            "trigger_classes": sorted(set(trigger_classes)),
            "bad_regime_candidate": bad,
            "good_regime_candidate": good,
            "pareto": p,
            "fresh_status": fresh,
            "selector_mode": "BAD_AVOID__NEUTRAL_PARENT__GOOD_ADMISSION_CANDIDATE",
            "bad_runtime_block_enabled": False,
            "good_runtime_boost_enabled": False,
            "partial_success_preserved": bool(p and p.get("partial_success_preserved")) or bool(good),
            "route": route_for(bad=bad, trigger=trigger, good=good, fresh=fresh, relation=relation),
            "strategy_parameters_changed": False,
            "numeric_threshold_sweep": False,
            "post_outcome_runtime_feature_use": False,
            **AUTH,
        })

    payload = {
        "schema_version": "zel.a1.common_regime_selector_pareto.v1",
        "state": "PASS_COMMON_REGIME_SELECTOR_RESEARCH_ACTIVE",
        "purpose": (
            "Unify finalist handling under one research-only selector: detect BAD pre-entry contexts, "
            "preserve NEUTRAL incumbent behavior, retain GOOD/partial-success branches, compare WR/PnL/"
            "expectancy/winner-retention/DD by Pareto relation, and route every selected child to fresh/OOS "
            "plus identity H4/H5 without copying strategy-specific filters."
        ),
        "selector_contract": {
            "BAD": "avoidance candidate only after pre-entry causal diagnosis; never activate from post-outcome labels",
            "NEUTRAL": "keep frozen incumbent unchanged",
            "GOOD": "preserve partial-success branch and strengthen admission only after independent fresh proof",
        },
        "trigger_contract": {
            "loss_streak_min": 3,
            "sample_stall": "use installed no-idle research SLA; not a strategy threshold",
            "trade_stagnation": "diagnose feature funnel/lifecycle/universe immediately instead of passive WAIT",
            "common_mode_concentration": "diagnose exposure context; do not hard-block repeated winners by default",
        },
        "required_upgrade_dimensions": [
            "win_rate",
            "net_pnl_bps",
            "net_expectancy_bps",
            "winner_retention",
            "realized_exit_bucket_max_drawdown_bps",
        ],
        "partial_success_policy": "PRESERVE_AND_EXTEND_NOT_RESET_TO_ZERO",
        "cross_strategy_filter_copy_forbidden": True,
        "post_outcome_threshold_fitting_forbidden": True,
        "fresh_oos_required": True,
        "identity_h4_h5_required": True,
        "strategy_parameters_changed": False,
        "numeric_threshold_sweep": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "evidence_sources": {name: str(path.relative_to(ROOT)) for name, path in EVIDENCE.items()},
        "available_evidence": {name: bool(value) for name, value in evidence.items()},
        "strategies": rows,
        **AUTH,
    }
    payload["receipt_sha256"] = stable(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> int:
    p = {"win_rate": 0.58, "net_pnl_bps": 24800.0, "net_expectancy_bps": 1000.0, "max_drawdown_bps": 570.0}
    partial = {"win_rate": 0.80, "net_pnl_bps": 21200.0, "net_expectancy_bps": 1300.0, "max_drawdown_bps": 400.0}
    r = pareto(p, partial)
    assert r["relation"] == "PARTIAL_SUCCESS_PRESERVE_AND_EXTEND", r
    dom = {"win_rate": 0.70, "net_pnl_bps": 26000.0, "net_expectancy_bps": 1200.0, "max_drawdown_bps": 500.0}
    r2 = pareto(p, dom)
    assert r2["relation"] == "PARETO_DOMINATES_PARENT", r2
    bad = {"win_rate": 0.40, "net_pnl_bps": 10000.0, "net_expectancy_bps": 400.0, "max_drawdown_bps": 900.0}
    r3 = pareto(p, bad)
    assert r3["relation"] == "DOMINATED_DO_NOT_PROMOTE", r3
    assert set(STRATEGY_FEATURES) == {
        "trend_rider", "supertrend_pullback", "break_and_continue",
        "trend_ma_macd", "keltner_trend", "regime_ema21_reclaim_v1",
    }
    assert not (set(STRATEGY_FEATURES["trend_rider"]) & FORBIDDEN_RUNTIME_AXES)
    print("PASS_A1_COMMON_REGIME_SELECTOR_PARETO_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_common_regime_selector_pareto_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "routes": {x["strategy_id"]: x["route"] for x in result["strategies"]},
        "partial_success": [x["strategy_id"] for x in result["strategies"] if x["partial_success_preserved"]],
        "available_evidence": result["available_evidence"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
