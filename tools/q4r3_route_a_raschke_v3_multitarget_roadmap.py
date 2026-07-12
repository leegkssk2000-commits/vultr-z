from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
LEDGER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
ATTRIBUTION_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_drift_attribution_latest.json"
INVENTORY_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sample_inventory_latest.json"

PLAN_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_multitarget_sample_plan_latest.json"
LADDER_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_label_ladder_latest.json"
ROADMAP_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_research_roadmap_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_multitarget_roadmap_latest.html"

WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
SIDES = ("long", "short")
MFE_THRESHOLDS_R = (0.5, 1.0, 1.5, 2.0)
TP_TIERS = {
    "diagnostic_univariate": 30,
    "penalized_pilot": 60,
    "production_candidate": 100,
}

RESEARCH_BASIS = [
    {
        "topic": "prediction_model_sample_size",
        "reference": "Riley et al., Minimum sample size for developing a multivariable prediction model: Part II",
        "use": "Do not treat a fixed total event count as sufficient; condition model scope on outcome prevalence, predictor count, shrinkage and calibration precision.",
    },
    {
        "topic": "rare_event_bias",
        "reference": "King and Zeng, Logistic Regression in Rare Events Data; Firth bias reduction",
        "use": "Penalized or bias-reduced logistic regression may reduce small-sample bias but cannot manufacture missing positive events.",
    },
    {
        "topic": "dynamic_regime_change",
        "reference": "Adams and MacKay, Bayesian Online Changepoint Detection",
        "use": "Treat regime change as an online probability observer before promoting it to a hard routing gate.",
    },
    {
        "topic": "competing_risks",
        "reference": "Fine and Gray competing-risks framework",
        "use": "TP, SL and 480-minute timeout are competing outcomes with event times; avoid collapsing all non-TP outcomes into one class prematurely.",
    },
    {
        "topic": "backtest_selection_bias",
        "reference": "Bailey and Lopez de Prado, Probability of Backtest Overfitting; Deflated Sharpe Ratio",
        "use": "Register every tested lane and correct final selection for repeated trials rather than selecting the best raw backtest.",
    },
]


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(errors="ignore"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"INVALID_JSON_OBJECT:{path}")
    return payload


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def class_name(event: Dict[str, Any]) -> str:
    label = str(event.get("label", "UNKNOWN"))
    if label == "TP_FIRST":
        return "TP"
    if label.startswith("SL_FIRST"):
        return "SL"
    if label == "TIMEOUT":
        return "TIMEOUT"
    return "OTHER"


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(
        probability * (1.0 - probability) / total + z * z / (4.0 * total * total)
    ) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def expected_total_for_positive_target(target: int, prevalence: float) -> Optional[int]:
    if target <= 0:
        return 0
    if prevalence <= 0:
        return None
    return int(math.ceil(target / prevalence))


def grouped_counts(events: Sequence[Dict[str, Any]], predicate: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
    selected = [event for event in events if predicate(event)]
    return {
        "total": len(selected),
        "by_window": {
            window: sum(predicate(event) for event in events if str(event.get("window")) == window)
            for window in WINDOWS
        },
        "by_side": {
            side: sum(predicate(event) for event in events if str(event.get("side")) == side)
            for side in SIDES
        },
        "by_symbol": dict(
            sorted(
                Counter(
                    str(event.get("symbol"))
                    for event in selected
                ).items()
            )
        ),
    }


def binary_label_report(
    events: Sequence[Dict[str, Any]],
    *,
    name: str,
    predicate: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    positives = grouped_counts(events, predicate)
    total = len(events)
    positive = int(positives["total"])
    negative = total - positive
    prevalence = positive / total if total else 0.0
    lower, upper = wilson_interval(positive, total)
    window_totals = Counter(str(event.get("window")) for event in events)
    side_totals = Counter(str(event.get("side")) for event in events)
    negative_by_window = {
        window: int(window_totals.get(window, 0) - positives["by_window"].get(window, 0))
        for window in WINDOWS
    }
    negative_by_side = {
        side: int(side_totals.get(side, 0) - positives["by_side"].get(side, 0))
        for side in SIDES
    }
    readiness = {
        "descriptive_ready": positive >= 10 and negative >= 10,
        "univariate_screen_ready": (
            positive >= 20
            and negative >= 20
            and all(positives["by_window"].get(window, 0) >= 5 for window in WINDOWS)
        ),
        "penalized_pilot_ready": (
            positive >= 30
            and negative >= 30
            and all(positives["by_window"].get(window, 0) >= 10 for window in WINDOWS)
            and all(positives["by_side"].get(side, 0) >= 10 for side in SIDES)
        ),
        "production_candidate_ready": (
            positive >= 100
            and negative >= 100
            and all(positives["by_window"].get(window, 0) >= 30 for window in WINDOWS)
            and all(positives["by_side"].get(side, 0) >= 30 for side in SIDES)
        ),
    }
    return {
        "label": name,
        "events": total,
        "positive": positive,
        "negative": negative,
        "prevalence": prevalence,
        "wilson_95": {"lower": lower, "upper": upper},
        "positive_distribution": positives,
        "negative_distribution": {
            "total": negative,
            "by_window": negative_by_window,
            "by_side": negative_by_side,
        },
        "readiness": readiness,
    }


def label_ladder(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    reports: List[Dict[str, Any]] = []
    for threshold in MFE_THRESHOLDS_R:
        reports.append(
            binary_label_report(
                events,
                name=f"MFE_GE_{threshold:.1f}R",
                predicate=lambda event, threshold=threshold: float(event.get("mfe_R", 0.0)) >= threshold,
            )
        )
    reports.append(
        binary_label_report(
            events,
            name="NET_R_POSITIVE_0.15_COST",
            predicate=lambda event: float(event.get("net_R_0.15", 0.0)) > 0.0,
        )
    )
    reports.append(
        binary_label_report(
            events,
            name="TP_FIRST_2R",
            predicate=lambda event: class_name(event) == "TP",
        )
    )
    feasible = [
        report
        for report in reports
        if report["readiness"]["univariate_screen_ready"]
    ]
    preferred = None
    mfe_feasible = [report for report in feasible if report["label"].startswith("MFE_GE_")]
    if mfe_feasible:
        preferred = max(
            mfe_feasible,
            key=lambda report: float(report["label"].split("_")[-1].rstrip("R")),
        )["label"]
    elif feasible:
        preferred = feasible[0]["label"]
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_LABEL_LADDER",
        "events": len(events),
        "reports": reports,
        "preferred_diagnostic_label": preferred,
        "rule": "Use the highest economically meaningful threshold that keeps both windows and both sides represented; retain 2R TP as the final business target, not necessarily the first learnable label.",
    }


def tp_sample_plan(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(events)
    tp = sum(class_name(event) == "TP" for event in events)
    prevalence = tp / total if total else 0.0
    lower, upper = wilson_interval(tp, total)
    scenarios: Dict[str, Any] = {}
    for tier, target in TP_TIERS.items():
        observed_total = expected_total_for_positive_target(target, prevalence)
        lower_total = expected_total_for_positive_target(target, lower)
        scenarios[tier] = {
            "target_tp_events": target,
            "expected_total_at_observed_prevalence": observed_total,
            "additional_events_at_observed_prevalence": (
                max(0, observed_total - total) if observed_total is not None else None
            ),
            "stress_total_at_wilson_lower_prevalence": lower_total,
            "stress_additional_events": (
                max(0, lower_total - total) if lower_total is not None else None
            ),
            "interpretation": (
                "diagnostic_only_no_multivariable_promotion"
                if tier == "diagnostic_univariate"
                else (
                    "penalized_small_feature_pilot_only"
                    if tier == "penalized_pilot"
                    else "candidate_for_nested_validation_not_live_authority"
                )
            ),
        }
    return {
        "current": {
            "events": total,
            "tp_events": tp,
            "tp_prevalence": prevalence,
            "tp_prevalence_wilson_95": {"lower": lower, "upper": upper},
        },
        "scenarios": scenarios,
        "correction": "The former fixed 200-event/30-TP gate was optimistic. Sample planning must be positive-event-driven and recalculated after stable predictor count and anticipated signal strength are known.",
    }


def continuous_target_report(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    mfe = [float(event.get("mfe_R", 0.0)) for event in events]
    mae = [float(event.get("mae_R", 0.0)) for event in events]
    return {
        "events": len(events),
        "mfe_mean_R": float(statistics.fmean(mfe)) if mfe else 0.0,
        "mfe_median_R": float(statistics.median(mfe)) if mfe else 0.0,
        "mae_mean_R": float(statistics.fmean(mae)) if mae else 0.0,
        "mae_median_R": float(statistics.median(mae)) if mae else 0.0,
        "diagnostic_ready": len(events) >= 100,
        "small_feature_quantile_pilot_ready": (
            len(events) >= 250
            and all(sum(str(event.get("window")) == window for event in events) >= 100 for window in WINDOWS)
        ),
        "recommended_models": ["median_quantile_regression", "huber_regression"],
        "feature_cap": 4,
        "promotion_rule": "Use only cross-window stable pre-entry features; no tree search before larger history is appended.",
    }


def competing_risk_report(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(class_name(event) for event in events)
    by_window = {
        window: dict(
            Counter(
                class_name(event)
                for event in events
                if str(event.get("window")) == window
            )
        )
        for window in WINDOWS
    }
    return {
        "counts": dict(sorted(counts.items())),
        "by_window": by_window,
        "nonparametric_cumulative_incidence_ready": all(counts.get(label, 0) >= 10 for label in ("TP", "SL", "TIMEOUT")),
        "cause_specific_model_ready": (
            counts.get("TP", 0) >= 30
            and counts.get("SL", 0) >= 30
            and all(by_window[window].get("TP", 0) >= 10 for window in WINDOWS)
        ),
        "timeout_treatment": "right_censor_at_480m_for_cause_specific_hazard_and_separate_competing_outcome_for_cumulative_incidence",
    }


def stable_feature_budget(attribution: Dict[str, Any], tp_events: int) -> Dict[str, Any]:
    numeric = attribution.get("numeric_feature_attribution", {})
    stable_numeric: List[Dict[str, Any]] = []
    if isinstance(numeric, dict):
        for scope in ("long", "short", "all"):
            rows = numeric.get(scope, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and bool(row.get("stable_candidate")):
                    stable_numeric.append(row)
    stable_numeric.sort(key=lambda row: float(row.get("stable_score", 0.0)), reverse=True)

    categorical = attribution.get("categorical_attribution", {})
    stable_categorical: List[Dict[str, Any]] = []
    if isinstance(categorical, dict):
        for rows in categorical.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and bool(row.get("stable_candidate")):
                    stable_categorical.append(row)
    stable_categorical.sort(key=lambda row: float(row.get("stable_score", 0.0)), reverse=True)

    return {
        "tp_events": tp_events,
        "stable_numeric_count": len(stable_numeric),
        "stable_categorical_count": len(stable_categorical),
        "top_stable_numeric": stable_numeric[:10],
        "top_stable_categorical": stable_categorical[:10],
        "binary_tp2r_feature_cap_now": 0 if tp_events < 30 else min(2, len(stable_numeric)),
        "continuous_mfe_diagnostic_feature_cap": min(4, len(stable_numeric)),
        "rule": "Feature count is capped before fitting; bias correction does not relax the positive-event requirement.",
    }


def inventory_plan(inventory: Dict[str, Any]) -> Dict[str, Any]:
    full = inventory.get("full_symbol_candidate_groups", [])
    candidates = inventory.get("candidate_groups", [])
    return {
        "full_symbol_candidate_group_count": len(full) if isinstance(full, list) else 0,
        "candidate_group_count": len(candidates) if isinstance(candidates, list) else 0,
        "top_full_symbol_candidates": full[:10] if isinstance(full, list) else [],
        "manual_checks_required": [
            "timestamp range does not overlap either consumed 90-day window",
            "not third/final/sealed/untouched/forward/paper/live",
            "all five symbols present with continuous 1-minute timestamps",
            "same exchange and price convention",
            "duplicate timestamps and copied snapshots removed",
            "history remains training-only; final third holdout stays sealed",
        ],
        "automatic_append_allowed": False,
    }


def build_roadmap(
    *,
    events: Sequence[Dict[str, Any]],
    ladder: Dict[str, Any],
    sample: Dict[str, Any],
    continuous: Dict[str, Any],
    competing: Dict[str, Any],
    feature_budget: Dict[str, Any],
    inventory: Dict[str, Any],
) -> Dict[str, Any]:
    tp = int(sample["current"]["tp_events"])
    preferred = ladder.get("preferred_diagnostic_label")
    history_available = int(inventory.get("full_symbol_candidate_group_count", 0)) > 0

    immediate: List[Dict[str, Any]] = [
        {
            "priority": 1,
            "module": "nonparametric_competing_risk_observer",
            "action": "Estimate TP/SL cumulative incidence and median event time by side, symbol and window without fitting a predictive router.",
            "why": "Uses event type and timing from all observations instead of reducing timeout to a generic negative class.",
            "ready_now": bool(competing["nonparametric_cumulative_incidence_ready"]),
        },
        {
            "priority": 2,
            "module": "ordinal_mfe_ladder",
            "action": f"Use {preferred or 'the best represented MFE threshold'} as a diagnostic intermediate target while preserving 2R TP as the final economic target.",
            "why": "Learns continuation quality before the very rare 2R event and retains ordering across 0.5R/1R/1.5R/2R.",
            "ready_now": preferred is not None,
        },
        {
            "priority": 3,
            "module": "bocpd_expectancy_observer",
            "action": "Run Bayesian online changepoint probability on rolling expectancy and TP/SL incidence as observer-only state metadata.",
            "why": "The first and second 90-day windows exhibit a structural shift that static thresholds did not separate.",
            "ready_now": True,
        },
        {
            "priority": 4,
            "module": "continuous_mfe_mae_diagnostic",
            "action": "Fit no deployment model yet; prepare capped-feature median/Huber diagnostics for MFE and MAE after history expansion.",
            "why": "Continuous targets use more information than 11 binary TP events.",
            "ready_now": bool(continuous["diagnostic_ready"]),
        },
    ]

    phases = [
        {
            "phase": "P0_FREEZE_AND_TRIAL_LEDGER",
            "actions": [
                "keep production, registry, paper, live and order authority unchanged",
                "seal the third/final holdout",
                "record every filter, label and model trial for later PBO/DSR correction",
            ],
            "gate": "no missing runtime inputs and no sealed-history access",
        },
        {
            "phase": "P1_MULTI_TARGET_DIAGNOSTICS",
            "actions": [
                "nonparametric TP/SL/timeout cumulative incidence",
                "MFE threshold ladder 0.5R/1R/1.5R/2R",
                "event-aligned path and giveback analysis",
                "BOCPD observer on rolling expectancy",
            ],
            "gate": "diagnostics reproduce directionally across both 90-day windows",
        },
        {
            "phase": "P2_SAFE_HISTORY_EXPANSION",
            "actions": [
                "manually approve only non-reserved five-symbol 1-minute history",
                "deduplicate timestamps and reject overlap with consumed windows",
                "append chronologically and rerun the event ledger without changing the strategy",
            ],
            "gate": "integrity PASS plus positive-event-driven sample target",
        },
        {
            "phase": "P3_MODEL_LADDER",
            "actions": [
                "Model A: side-separated median/Huber MFE regression with at most four stable features",
                "Model B: ordinal MFE threshold model after each level has representation in both windows and sides",
                "Model C: cause-specific discrete-time TP-vs-SL hazard only after at least 30 TP events",
                "Model D: bias-reduced or regularized binary 2R meta-label pilot only after at least 60 TP events",
                "GBDT remains blocked until at least 100 TP events and nested validation",
            ],
            "gate": "calibration, expected-R and worst-fold gates all pass",
        },
        {
            "phase": "P4_VALIDATION_AND_SELECTION_BIAS",
            "actions": [
                "purged walk-forward with 480-minute embargo",
                "nested feature and threshold selection",
                "long and short reported separately before any pooling",
                "report Brier/log-loss/calibration plus net R, PF, MDD and cost 0.20%",
                "calculate PBO/DSR using the complete trial ledger",
            ],
            "gate": "median fold positive, worst fold bounded, calibration stable, PBO acceptable",
        },
        {
            "phase": "P5_FINAL_SINGLE_OPEN",
            "actions": [
                "open the untouched third holdout once for the single pre-registered winner",
                "failure returns Raschke to reserve without reopening the holdout",
            ],
            "gate": "single-shot final holdout PASS before any paper route",
        },
    ]

    if tp < 30:
        next_action = (
            "MANUAL_CONFIRM_SAFE_HISTORY_AND_RUN_NONPARAMETRIC_PLUS_MFE_LADDER"
            if history_available
            else "RUN_NONPARAMETRIC_PLUS_MFE_LADDER_AND_FORWARD_COLLECT"
        )
    elif tp < 60:
        next_action = "RUN_CAUSE_SPECIFIC_HAZARD_DIAGNOSTIC_NO_BINARY_PROMOTION"
    elif tp < 100:
        next_action = "RUN_PENALIZED_BINARY_PILOT_WITH_NESTED_PURGED_VALIDATION"
    else:
        next_action = "RUN_PRE_REGISTERED_MODEL_TOURNAMENT_WITH_SELECTION_BIAS_CORRECTION"

    return {
        "status": "PASS_Q4R3_RASCHKE_V3_RESEARCH_ROADMAP",
        "verdict": "MULTI_TARGET_POSITIVE_EVENT_DRIVEN_ROADMAP_READY_NO_MODEL_OR_STRATEGY_MUTATION",
        "next_action": next_action,
        "immediate_modules": immediate,
        "phases": phases,
        "hard_rules": {
            "fixed_200_event_gate_retired": True,
            "binary_tp2r_training_now": False,
            "synthetic_oversampling": False,
            "smote_or_duplicate_tp": False,
            "final_holdout_access": False,
            "model_family_count_pre_registered_max": 4,
            "stable_feature_cap_enforced": True,
            "production_strategy_modified": False,
        },
        "research_basis": RESEARCH_BASIS,
    }


def write_html(plan: Dict[str, Any], ladder: Dict[str, Any], roadmap: Dict[str, Any]) -> None:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(report['label'])}</td>"
        f"<td>{report['positive']}</td>"
        f"<td>{report['negative']}</td>"
        f"<td>{report['prevalence']:.3f}</td>"
        f"<td>{report['readiness']['univariate_screen_ready']}</td>"
        f"<td>{report['readiness']['penalized_pilot_ready']}</td>"
        "</tr>"
        for report in ladder["reports"]
    )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v3 multi-target roadmap</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke v3 positive-event-driven multi-target roadmap</h1>",
            "<h2>Label ladder</h2><table><thead><tr><th>Label</th><th>Positive</th><th>Negative</th><th>Prevalence</th><th>Univariate ready</th><th>Pilot ready</th></tr></thead><tbody>",
            rows,
            "</tbody></table><h2>Sample plan</h2><pre>",
            html.escape(json.dumps(plan, ensure_ascii=False, indent=2)),
            "</pre><h2>Roadmap</h2><pre>",
            html.escape(json.dumps(roadmap, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    ledger = load_json(LEDGER_SOURCE)
    attribution = load_json(ATTRIBUTION_SOURCE)
    inventory_source = load_json(INVENTORY_SOURCE)
    events = ledger.get("events", [])
    if not isinstance(events, list) or not events:
        raise RuntimeError("EVENT_LEDGER_EMPTY")
    events = [event for event in events if isinstance(event, dict)]

    ladder = label_ladder(events)
    tp_plan = tp_sample_plan(events)
    continuous = continuous_target_report(events)
    competing = competing_risk_report(events)
    feature_budget = stable_feature_budget(attribution, int(tp_plan["current"]["tp_events"]))
    inventory = inventory_plan(inventory_source)

    plan = {
        "status": "PASS_Q4R3_RASCHKE_V3_MULTITARGET_SAMPLE_PLAN",
        "verdict": "FORMER_FIXED_GATE_RETIRED_POSITIVE_EVENT_AND_MULTI_TARGET_PLAN_READY",
        "tp2r_sample_plan": tp_plan,
        "continuous_mfe_mae": continuous,
        "competing_risk": competing,
        "feature_budget": feature_budget,
        "safe_history": inventory,
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
    }
    roadmap = build_roadmap(
        events=events,
        ladder=ladder,
        sample=tp_plan,
        continuous=continuous,
        competing=competing,
        feature_budget=feature_budget,
        inventory=inventory,
    )

    atomic_json(PLAN_OUT, plan)
    atomic_json(LADDER_OUT, ladder)
    atomic_json(ROADMAP_OUT, roadmap)
    write_html(plan, ladder, roadmap)
    print(json.dumps({
        "plan": plan,
        "label_ladder_summary": {
            "preferred_diagnostic_label": ladder["preferred_diagnostic_label"],
            "reports": [
                {
                    "label": report["label"],
                    "positive": report["positive"],
                    "negative": report["negative"],
                    "prevalence": report["prevalence"],
                    "readiness": report["readiness"],
                }
                for report in ladder["reports"]
            ],
        },
        "roadmap": roadmap,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
