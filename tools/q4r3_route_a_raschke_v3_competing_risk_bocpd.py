from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
LEDGER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
LADDER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_label_ladder_latest.json"
PLAN_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_multitarget_sample_plan_latest.json"

COMPETING_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_competing_risk_latest.json"
MFE_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_mfe_ladder_diagnostic_latest.json"
BOCPD_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_bocpd_observer_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_diagnostic_decision_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_competing_risk_bocpd_latest.html"

WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
SIDES = ("long", "short")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
CAUSES = ("TP", "SL", "TIMEOUT")
CHECKPOINTS_MIN = (15, 30, 60, 120, 240, 480)
MFE_THRESHOLDS_R = (0.5, 1.0, 1.5, 2.0)
COST_PCT = 0.15

RESEARCH_CONTRACT = {
    "competing_risk": "Aalen-Johansen style nonparametric cumulative incidence for mutually exclusive TP, SL and timeout events.",
    "change_point": "Adams-MacKay Bayesian online changepoint observer with Beta-Bernoulli TP incidence and Gaussian mean-shift streams.",
    "rare_event": "Two-R TP remains a business endpoint; intermediate MFE and continuous path targets are diagnostic, not a substitute final objective.",
    "selection_bias": "No predictive lane is promoted here; every later trial must remain in the trial ledger for PBO/DSR correction.",
}


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


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def class_name(event: Dict[str, Any]) -> str:
    label = str(event.get("label", "UNKNOWN"))
    if label == "TP_FIRST":
        return "TP"
    if label.startswith("SL_FIRST"):
        return "SL"
    if label == "TIMEOUT":
        return "TIMEOUT"
    return "OTHER"


def event_time_min(event: Dict[str, Any]) -> int:
    value = int(event.get("duration_min", 480))
    return min(max(value, 0), 480)


def mean_or_none(values: Iterable[Any]) -> Optional[float]:
    clean = [number for value in values if (number := safe_float(value)) is not None]
    return float(statistics.fmean(clean)) if clean else None


def median_or_none(values: Iterable[Any]) -> Optional[float]:
    clean = [number for value in values if (number := safe_float(value)) is not None]
    return float(statistics.median(clean)) if clean else None


def event_metrics(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [float(event.get("net_R_0.15", 0.0)) for event in events]
    labels = Counter(class_name(event) for event in events)
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = float(sum(wins))
    gross_loss = abs(float(sum(losses)))
    return {
        "events": len(events),
        "avg_net_R": float(statistics.fmean(values)) if values else 0.0,
        "median_net_R": float(statistics.median(values)) if values else 0.0,
        "net_sum_R": float(sum(values)),
        "positive_rate_pct": float(len(wins) / len(values) * 100.0) if values else 0.0,
        "profit_factor_R": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "labels": dict(sorted(labels.items())),
        "mean_mfe_R": mean_or_none(event.get("mfe_R") for event in events),
        "median_mfe_R": median_or_none(event.get("mfe_R") for event in events),
        "mean_mae_R": mean_or_none(event.get("mae_R") for event in events),
        "mean_duration_min": mean_or_none(event.get("duration_min") for event in events),
    }


def aalen_johansen(events: Sequence[Dict[str, Any]], checkpoints: Sequence[int] = CHECKPOINTS_MIN) -> Dict[str, Any]:
    valid = [event for event in events if class_name(event) in CAUSES]
    n_total = len(valid)
    if n_total == 0:
        return {
            "events": 0,
            "checkpoint_cif": {str(point): {cause: 0.0 for cause in CAUSES} for point in checkpoints},
            "final_cif": {cause: 0.0 for cause in CAUSES},
            "survival_after_last_event": 1.0,
        }

    by_time: Dict[int, Counter[str]] = defaultdict(Counter)
    for event in valid:
        by_time[event_time_min(event)][class_name(event)] += 1

    survival = 1.0
    at_risk = n_total
    cif = {cause: 0.0 for cause in CAUSES}
    timeline: List[Dict[str, Any]] = []
    for time_min in sorted(by_time):
        counts = by_time[time_min]
        total_events = int(sum(counts.values()))
        if at_risk <= 0:
            break
        before = survival
        increments: Dict[str, float] = {}
        for cause in CAUSES:
            increment = before * float(counts.get(cause, 0)) / float(at_risk)
            cif[cause] += increment
            increments[cause] = increment
        survival = before * (1.0 - float(total_events) / float(at_risk))
        timeline.append(
            {
                "time_min": time_min,
                "at_risk": at_risk,
                "counts": {cause: int(counts.get(cause, 0)) for cause in CAUSES},
                "cif_increment": increments,
                "cif": dict(cif),
                "survival": survival,
            }
        )
        at_risk -= total_events

    checkpoint_cif: Dict[str, Dict[str, float]] = {}
    for point in checkpoints:
        state = {cause: 0.0 for cause in CAUSES}
        for row in timeline:
            if int(row["time_min"]) <= int(point):
                state = dict(row["cif"])
            else:
                break
        checkpoint_cif[str(point)] = state

    median_time_by_cause: Dict[str, Optional[float]] = {}
    for cause in CAUSES:
        times = [event_time_min(event) for event in valid if class_name(event) == cause]
        median_time_by_cause[cause] = float(statistics.median(times)) if times else None

    return {
        "events": n_total,
        "checkpoint_cif": checkpoint_cif,
        "final_cif": dict(cif),
        "survival_after_last_event": survival,
        "median_event_time_min": median_time_by_cause,
        "timeline": timeline,
    }


def subgroup_reports(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    scopes: Dict[str, List[Dict[str, Any]]] = {
        "all": list(events),
    }
    for window in WINDOWS:
        scopes[f"window:{window}"] = [event for event in events if str(event.get("window")) == window]
    for side in SIDES:
        scopes[f"side:{side}"] = [event for event in events if str(event.get("side")) == side]
    for symbol in SYMBOLS:
        scopes[f"symbol:{symbol}"] = [event for event in events if str(event.get("symbol")) == symbol]
    for window in WINDOWS:
        for side in SIDES:
            scopes[f"window_side:{window}|{side}"] = [
                event
                for event in events
                if str(event.get("window")) == window and str(event.get("side")) == side
            ]
    return {
        scope: {
            "metrics": event_metrics(rows),
            "cumulative_incidence": aalen_johansen(rows),
        }
        for scope, rows in scopes.items()
    }


def threshold_report(events: Sequence[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    selected = [event for event in events if float(event.get("mfe_R", 0.0)) >= threshold]
    total = len(events)
    by_window: Dict[str, Any] = {}
    for window in WINDOWS:
        rows = [event for event in events if str(event.get("window")) == window]
        positive = [event for event in rows if float(event.get("mfe_R", 0.0)) >= threshold]
        by_window[window] = {
            "events": len(rows),
            "positive": len(positive),
            "rate_pct": float(len(positive) / len(rows) * 100.0) if rows else 0.0,
        }
    by_side: Dict[str, Any] = {}
    for side in SIDES:
        rows = [event for event in events if str(event.get("side")) == side]
        positive = [event for event in rows if float(event.get("mfe_R", 0.0)) >= threshold]
        by_side[side] = {
            "events": len(rows),
            "positive": len(positive),
            "rate_pct": float(len(positive) / len(rows) * 100.0) if rows else 0.0,
        }
    by_window_side: Dict[str, Any] = {}
    for window in WINDOWS:
        for side in SIDES:
            key = f"{window}|{side}"
            rows = [
                event
                for event in events
                if str(event.get("window")) == window and str(event.get("side")) == side
            ]
            positive = [event for event in rows if float(event.get("mfe_R", 0.0)) >= threshold]
            by_window_side[key] = {
                "events": len(rows),
                "positive": len(positive),
                "rate_pct": float(len(positive) / len(rows) * 100.0) if rows else 0.0,
            }
    readiness = {
        "descriptive": len(selected) >= 10 and total - len(selected) >= 10,
        "cross_window_univariate": (
            len(selected) >= 20
            and total - len(selected) >= 20
            and all(by_window[window]["positive"] >= 5 for window in WINDOWS)
        ),
        "side_separated_pilot": (
            len(selected) >= 30
            and total - len(selected) >= 30
            and all(by_window[window]["positive"] >= 10 for window in WINDOWS)
            and all(by_side[side]["positive"] >= 10 for side in SIDES)
        ),
    }
    return {
        "threshold_R": threshold,
        "events": total,
        "positive": len(selected),
        "negative": total - len(selected),
        "rate_pct": float(len(selected) / total * 100.0) if total else 0.0,
        "by_window": by_window,
        "by_side": by_side,
        "by_window_side": by_window_side,
        "median_minutes_to_peak_mfe": median_or_none(event.get("minutes_to_mfe") for event in selected),
        "readiness": readiness,
    }


def giveback_report(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for threshold in MFE_THRESHOLDS_R:
        reached = [event for event in events if float(event.get("mfe_R", 0.0)) >= threshold]
        givebacks = [
            float(event.get("mfe_R", 0.0)) - float(event.get("net_R_0.15", 0.0))
            for event in reached
        ]
        finished_nonpositive = [event for event in reached if float(event.get("net_R_0.15", 0.0)) <= 0.0]
        timeout_nonpositive = [event for event in finished_nonpositive if class_name(event) == "TIMEOUT"]
        stopped_after_reach = [event for event in finished_nonpositive if class_name(event) == "SL"]
        rows.append(
            {
                "threshold_R": threshold,
                "reached_events": len(reached),
                "finished_nonpositive_events": len(finished_nonpositive),
                "finished_nonpositive_pct": float(len(finished_nonpositive) / len(reached) * 100.0) if reached else 0.0,
                "timeout_nonpositive_events": len(timeout_nonpositive),
                "sl_after_reach_events": len(stopped_after_reach),
                "mean_giveback_R": float(statistics.fmean(givebacks)) if givebacks else None,
                "median_giveback_R": float(statistics.median(givebacks)) if givebacks else None,
                "net_sum_R_after_reach": float(sum(float(event.get("net_R_0.15", 0.0)) for event in reached)),
            }
        )
    return {
        "thresholds": rows,
        "interpretation_rule": "High reached-then-nonpositive rate indicates profit-realization or continuation failure; low MFE among losses indicates entry failure.",
    }


def beta_bernoulli_bocpd(
    observations: Sequence[int],
    *,
    hazard: float = 1.0 / 30.0,
    alpha0: float = 1.0,
    beta0: float = 1.0,
    max_run_length: int = 120,
) -> List[float]:
    if not observations:
        return []
    run_prob = [1.0]
    alphas = [alpha0]
    betas = [beta0]
    cp_probabilities: List[float] = []
    for raw in observations:
        x = 1 if int(raw) else 0
        prior_predictive = alpha0 / (alpha0 + beta0) if x else beta0 / (alpha0 + beta0)
        growth: List[float] = [0.0] * min(len(run_prob) + 1, max_run_length + 1)
        growth[0] = sum(run_prob) * hazard * prior_predictive
        next_alphas = [alpha0 + x]
        next_betas = [beta0 + (1 - x)]
        for index, probability in enumerate(run_prob):
            if index + 1 >= len(growth):
                break
            predictive = alphas[index] / (alphas[index] + betas[index]) if x else betas[index] / (alphas[index] + betas[index])
            growth[index + 1] += probability * (1.0 - hazard) * predictive
            next_alphas.append(alphas[index] + x)
            next_betas.append(betas[index] + (1 - x))
        normalizer = sum(growth)
        if normalizer <= 0 or not math.isfinite(normalizer):
            growth = [1.0]
            next_alphas = [alpha0 + x]
            next_betas = [beta0 + (1 - x)]
        else:
            growth = [value / normalizer for value in growth]
        run_prob = growth
        alphas = next_alphas[: len(run_prob)]
        betas = next_betas[: len(run_prob)]
        cp_probabilities.append(float(run_prob[0]))
    return cp_probabilities


def normal_pdf(value: float, mean: float, variance: float) -> float:
    variance = max(float(variance), 1e-9)
    return math.exp(-0.5 * (value - mean) ** 2 / variance) / math.sqrt(2.0 * math.pi * variance)


def gaussian_mean_bocpd(
    observations: Sequence[float],
    *,
    hazard: float = 1.0 / 30.0,
    max_run_length: int = 120,
) -> List[float]:
    if not observations:
        return []
    clean = [float(value) for value in observations]
    global_mean = float(statistics.median(clean))
    sigma2 = float(statistics.pvariance(clean)) if len(clean) > 1 else 1.0
    sigma2 = max(sigma2, 0.05 ** 2)
    tau20 = sigma2 * 4.0
    run_prob = [1.0]
    means = [global_mean]
    variances = [tau20]
    cp_probabilities: List[float] = []
    for value in clean:
        prior_predictive = normal_pdf(value, global_mean, sigma2 + tau20)
        next_prob = [0.0] * min(len(run_prob) + 1, max_run_length + 1)
        next_prob[0] = sum(run_prob) * hazard * prior_predictive
        next_means = []
        next_variances = []
        prior_precision = 1.0 / tau20
        observation_precision = 1.0 / sigma2
        post_variance0 = 1.0 / (prior_precision + observation_precision)
        post_mean0 = post_variance0 * (prior_precision * global_mean + observation_precision * value)
        next_means.append(post_mean0)
        next_variances.append(post_variance0)
        for index, probability in enumerate(run_prob):
            if index + 1 >= len(next_prob):
                break
            predictive = normal_pdf(value, means[index], sigma2 + variances[index])
            next_prob[index + 1] += probability * (1.0 - hazard) * predictive
            precision = 1.0 / variances[index]
            post_variance = 1.0 / (precision + observation_precision)
            post_mean = post_variance * (precision * means[index] + observation_precision * value)
            next_means.append(post_mean)
            next_variances.append(post_variance)
        normalizer = sum(next_prob)
        if normalizer <= 0 or not math.isfinite(normalizer):
            next_prob = [1.0]
            next_means = [post_mean0]
            next_variances = [post_variance0]
        else:
            next_prob = [probability / normalizer for probability in next_prob]
        run_prob = next_prob
        means = next_means[: len(run_prob)]
        variances = next_variances[: len(run_prob)]
        cp_probabilities.append(float(run_prob[0]))
    return cp_probabilities


def local_context(events: Sequence[Dict[str, Any]], index: int, radius: int = 10) -> Dict[str, Any]:
    before = list(events[max(0, index - radius) : index])
    after = list(events[index : min(len(events), index + radius)])
    return {
        "before": event_metrics(before),
        "after": event_metrics(after),
    }


def changepoint_report(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(events, key=lambda event: int(event.get("signal_ts", 0)))
    tp_binary = [1 if class_name(event) == "TP" else 0 for event in ordered]
    sl_binary = [1 if class_name(event) == "SL" else 0 for event in ordered]
    net_values = [float(event.get("net_R_0.15", 0.0)) for event in ordered]
    tp_cp = beta_bernoulli_bocpd(tp_binary)
    sl_cp = beta_bernoulli_bocpd(sl_binary)
    net_cp = gaussian_mean_bocpd(net_values)
    rows: List[Dict[str, Any]] = []
    for index, event in enumerate(ordered):
        combined = max(tp_cp[index], sl_cp[index], net_cp[index])
        rows.append(
            {
                "index": index,
                "event_id": event.get("event_id"),
                "signal_ts": event.get("signal_ts"),
                "signal_utc": event.get("signal_utc"),
                "window": event.get("window"),
                "symbol": event.get("symbol"),
                "side": event.get("side"),
                "class": class_name(event),
                "net_R_0.15": float(event.get("net_R_0.15", 0.0)),
                "cp_probability": {
                    "tp_incidence": tp_cp[index],
                    "sl_incidence": sl_cp[index],
                    "net_R_mean": net_cp[index],
                    "max": combined,
                },
                "context_10_events": local_context(ordered, index, 10),
            }
        )
    rows.sort(key=lambda row: float(row["cp_probability"]["max"]), reverse=True)
    boundary_index = next(
        (
            index
            for index, event in enumerate(ordered)
            if str(event.get("window")) == WINDOWS[1]
        ),
        None,
    )
    boundary = None
    if boundary_index is not None:
        event = ordered[boundary_index]
        boundary = {
            "index": boundary_index,
            "signal_ts": event.get("signal_ts"),
            "signal_utc": event.get("signal_utc"),
            "cp_probability": {
                "tp_incidence": tp_cp[boundary_index],
                "sl_incidence": sl_cp[boundary_index],
                "net_R_mean": net_cp[boundary_index],
            },
            "context_20_events": local_context(ordered, boundary_index, 20),
        }
    return {
        "events": len(ordered),
        "hazard_expected_run_length_events": 30,
        "observer_only": True,
        "top_change_points": rows[:15],
        "second_window_boundary": boundary,
        "promotion_rule": "A change probability is metadata only until direction and economic effect repeat in independent chronological blocks.",
    }


def choose_diagnostic_path(
    threshold_rows: Sequence[Dict[str, Any]],
    competing: Dict[str, Any],
    giveback: Dict[str, Any],
) -> Dict[str, Any]:
    cross_window = [row for row in threshold_rows if row["readiness"]["cross_window_univariate"]]
    pilot = [row for row in threshold_rows if row["readiness"]["side_separated_pilot"]]
    preferred = max(cross_window, key=lambda row: float(row["threshold_R"]), default=None)
    giveback_1r = next((row for row in giveback["thresholds"] if float(row["threshold_R"]) == 1.0), None)
    all_cif = competing["subgroups"]["all"]["cumulative_incidence"]
    decision = {
        "preferred_intermediate_label": (
            f"MFE_GE_{preferred['threshold_R']:.1f}R" if preferred is not None else None
        ),
        "side_separated_pilot_labels": [f"MFE_GE_{row['threshold_R']:.1f}R" for row in pilot],
        "tp2r_binary_model_allowed": False,
        "next_modules": [],
    }
    decision["next_modules"].append("NONPARAMETRIC_COMPETING_RISK_COMPLETE")
    if preferred is not None:
        decision["next_modules"].append("CROSS_WINDOW_STABLE_FEATURE_SCREEN_FOR_INTERMEDIATE_MFE_LABEL")
    if giveback_1r and float(giveback_1r["finished_nonpositive_pct"]) >= 25.0:
        decision["next_modules"].append("CONDITIONAL_PROFIT_REALIZATION_DIAGNOSTIC")
    if float(all_cif["final_cif"].get("TP", 0.0)) < 0.15:
        decision["next_modules"].append("SAFE_HISTORY_EXPANSION_FOR_RARE_2R_ENDPOINT")
    decision["next_modules"].append("BOCPD_OBSERVER_CROSS_CHECK_WITH_WINDOW_AND_MONTH_BLOCKS")
    return decision


def write_html(
    competing: Dict[str, Any],
    mfe: Dict[str, Any],
    bocpd: Dict[str, Any],
    decision: Dict[str, Any],
) -> None:
    rows = "".join(
        "<tr>"
        f"<td>{row['threshold_R']:.1f}R</td>"
        f"<td>{row['positive']}</td>"
        f"<td>{row['rate_pct']:.1f}%</td>"
        f"<td>{row['readiness']['cross_window_univariate']}</td>"
        f"<td>{row['readiness']['side_separated_pilot']}</td>"
        "</tr>"
        for row in mfe["thresholds"]
    )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v3 competing risk and BOCPD</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke v3 competing risk, MFE ladder and changepoint observer</h1>",
            "<h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre><h2>MFE ladder</h2><table><thead><tr><th>Threshold</th><th>Positive</th><th>Rate</th><th>Cross-window ready</th><th>Side-pilot ready</th></tr></thead><tbody>",
            rows,
            "</tbody></table><h2>Competing risk</h2><pre>",
            html.escape(json.dumps(competing, ensure_ascii=False, indent=2)),
            "</pre><h2>BOCPD top changes</h2><pre>",
            html.escape(json.dumps(bocpd.get("top_change_points", [])[:10], ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    ledger = load_json(LEDGER_SOURCE)
    load_json(LADDER_SOURCE)
    load_json(PLAN_SOURCE)
    events = ledger.get("events", [])
    if not isinstance(events, list) or not events:
        raise RuntimeError("EVENT_LEDGER_EMPTY")
    events = [event for event in events if isinstance(event, dict)]

    subgroups = subgroup_reports(events)
    competing = {
        "status": "PASS_Q4R3_RASCHKE_V3_COMPETING_RISK",
        "verdict": "NONPARAMETRIC_TP_SL_TIMEOUT_CUMULATIVE_INCIDENCE_MEASURED",
        "method": "Aalen-Johansen style cumulative incidence with TP, SL and timeout as mutually exclusive causes",
        "subgroups": subgroups,
        "research_contract": RESEARCH_CONTRACT,
    }

    thresholds = [threshold_report(events, threshold) for threshold in MFE_THRESHOLDS_R]
    giveback = giveback_report(events)
    mfe = {
        "status": "PASS_Q4R3_RASCHKE_V3_MFE_LADDER_DIAGNOSTIC",
        "verdict": "MULTI_THRESHOLD_CONTINUATION_AND_GIVEBACK_MEASURED",
        "thresholds": thresholds,
        "giveback": giveback,
        "rule": "Intermediate MFE labels may support diagnostics; +2R TP remains the final economic endpoint.",
    }

    bocpd = {
        "status": "PASS_Q4R3_RASCHKE_V3_BOCPD_OBSERVER",
        "verdict": "CHANGEPOINT_PROBABILITIES_MEASURED_OBSERVER_ONLY",
        **changepoint_report(events),
    }
    decision = {
        "status": "PASS_Q4R3_RASCHKE_V3_DIAGNOSTIC_DECISION",
        "verdict": "COMPETING_RISK_MFE_AND_CHANGEPOINT_DIAGNOSTICS_COMPLETE_NO_MODEL_OR_STRATEGY_MUTATION",
        **choose_diagnostic_path(thresholds, competing, giveback),
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
    }

    atomic_json(COMPETING_OUT, competing)
    atomic_json(MFE_OUT, mfe)
    atomic_json(BOCPD_OUT, bocpd)
    atomic_json(DECISION_OUT, decision)
    write_html(competing, mfe, bocpd, decision)
    print(json.dumps({"decision": decision, "mfe_thresholds": thresholds, "competing_all": subgroups["all"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
