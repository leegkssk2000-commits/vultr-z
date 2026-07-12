from __future__ import annotations

import html
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
DATA_ROOT = ROOT / "data"
LEDGER_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_all_signal_ledger_latest.json"
DRIFT_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_feature_drift_latest.json"
PATH_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_v3_event_aligned_paths_latest.json"

ATTRIBUTION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_drift_attribution_latest.json"
INVENTORY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sample_inventory_latest.json"
NEXT_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_next_design_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_drift_attribution_latest.html"

WINDOWS = ("prior_holdout_90d", "second_holdout_90d")
SIDES = ("long", "short")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
CATEGORICAL_AXES = (
    "symbol",
    "side",
    "utc_session",
    "proximity_pass",
    "direction_alignment_pass",
    "macd_strength_pass",
)
DECOMPOSITION_AXES = ("side", "symbol", "utc_session", "symbol_side", "side_session")
CHECKPOINTS = (15, 30, 60, 120, 240, 480)

TARGETS = {
    "events": 200,
    "each_side": 50,
    "each_window": 80,
    "tp_class": 30,
    "sl_class": 30,
}

CONSUMED_PATH_MARKERS = (
    "oos_a2/frozen_pre30d",
    "oos_a3/raschke_second_holdout",
)
RESERVED_PATH_TOKENS = (
    "third",
    "holdout3",
    "holdout_3",
    "oos_a4",
    "oos_a5",
    "final",
    "sealed",
    "untouched",
    "forward",
    "paper",
    "live",
)
MAX_INVENTORY_FILES = 5000


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


def feature_value(event: Dict[str, Any], feature: str) -> Optional[float]:
    return safe_float(event.get("features", {}).get(feature))


def mean_or_none(values: Iterable[Any]) -> Optional[float]:
    clean = [number for value in values if (number := safe_float(value)) is not None]
    return float(statistics.fmean(clean)) if clean else None


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
    }


def rank_auc(positive: Sequence[float], negative: Sequence[float]) -> Optional[float]:
    if not positive or not negative:
        return None
    wins = 0.0
    total = len(positive) * len(negative)
    for left in positive:
        for right in negative:
            if left > right:
                wins += 1.0
            elif left == right:
                wins += 0.5
    return float(wins / total)


def feature_window_report(events: Sequence[Dict[str, Any]], feature: str) -> Dict[str, Any]:
    tp = [value for event in events if class_name(event) == "TP" and (value := feature_value(event, feature)) is not None]
    sl = [value for event in events if class_name(event) == "SL" and (value := feature_value(event, feature)) is not None]
    timeout = [value for event in events if class_name(event) == "TIMEOUT" and (value := feature_value(event, feature)) is not None]
    auc = rank_auc(tp, sl)
    oriented_strength = None if auc is None else float((auc - 0.5) * 2.0)
    return {
        "tp_n": len(tp),
        "sl_n": len(sl),
        "timeout_n": len(timeout),
        "tp_mean": float(statistics.fmean(tp)) if tp else None,
        "sl_mean": float(statistics.fmean(sl)) if sl else None,
        "timeout_mean": float(statistics.fmean(timeout)) if timeout else None,
        "tp_vs_sl_auc": auc,
        "oriented_strength": oriented_strength,
    }


def feature_attribution(
    events: Sequence[Dict[str, Any]],
    numeric_drift: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}
    scopes: Dict[str, List[Dict[str, Any]]] = {
        "all": list(events),
        "long": [event for event in events if str(event.get("side")) == "long"],
        "short": [event for event in events if str(event.get("side")) == "short"],
    }
    for scope, scope_events in scopes.items():
        reports: List[Dict[str, Any]] = []
        for feature, drift_report in numeric_drift.items():
            windows = {
                window: feature_window_report(
                    [event for event in scope_events if str(event.get("window")) == window],
                    feature,
                )
                for window in WINDOWS
            }
            first_strength = safe_float(windows[WINDOWS[0]]["oriented_strength"])
            second_strength = safe_float(windows[WINDOWS[1]]["oriented_strength"])
            min_class = min(
                windows[WINDOWS[0]]["tp_n"],
                windows[WINDOWS[0]]["sl_n"],
                windows[WINDOWS[1]]["tp_n"],
                windows[WINDOWS[1]]["sl_n"],
            )
            sign_consistent = bool(
                first_strength is not None
                and second_strength is not None
                and first_strength != 0
                and second_strength != 0
                and (first_strength > 0) == (second_strength > 0)
            )
            minimum_strength = (
                min(abs(first_strength), abs(second_strength))
                if first_strength is not None and second_strength is not None
                else 0.0
            )
            drift_score = float(drift_report.get("drift_score", 0.0))
            stable_score = float(
                minimum_strength
                * math.sqrt(max(min_class, 0) / 30.0)
                / (1.0 + drift_score)
            )
            stable_candidate = bool(sign_consistent and min_class >= 3 and minimum_strength >= 0.15)
            reports.append(
                {
                    "feature": feature,
                    "scope": scope,
                    "windows": windows,
                    "sign_consistent": sign_consistent,
                    "minimum_tp_sl_class_per_window": min_class,
                    "minimum_oriented_strength": minimum_strength,
                    "drift_score": drift_score,
                    "drift_flags": drift_report.get("flags", []),
                    "stable_score": stable_score,
                    "stable_candidate": stable_candidate,
                    "interpretation": (
                        "higher_values_favor_tp"
                        if sign_consistent and first_strength is not None and first_strength > 0
                        else (
                            "lower_values_favor_tp"
                            if sign_consistent and first_strength is not None
                            else "direction_not_stable"
                        )
                    ),
                }
            )
        reports.sort(
            key=lambda row: (
                bool(row["stable_candidate"]),
                float(row["stable_score"]),
                float(row["minimum_oriented_strength"]),
            ),
            reverse=True,
        )
        output[scope] = reports
    return output


def category_value(event: Dict[str, Any], axis: str) -> str:
    return str(event.get(axis, "missing"))


def categorical_attribution(events: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}
    for axis in CATEGORICAL_AXES:
        categories = sorted({category_value(event, axis) for event in events})
        rows: List[Dict[str, Any]] = []
        for category in categories:
            reports: Dict[str, Any] = {}
            for window in WINDOWS:
                window_events = [event for event in events if str(event.get("window")) == window]
                selected = [event for event in window_events if category_value(event, axis) == category]
                remaining = [event for event in window_events if category_value(event, axis) != category]
                reports[window] = {
                    "group": event_metrics(selected),
                    "rest": event_metrics(remaining),
                    "avg_R_edge_vs_rest": float(event_metrics(selected)["avg_net_R"] - event_metrics(remaining)["avg_net_R"]),
                }
            first_edge = float(reports[WINDOWS[0]]["avg_R_edge_vs_rest"])
            second_edge = float(reports[WINDOWS[1]]["avg_R_edge_vs_rest"])
            minimum_events = min(
                int(reports[WINDOWS[0]]["group"]["events"]),
                int(reports[WINDOWS[1]]["group"]["events"]),
            )
            sign_consistent = first_edge != 0 and second_edge != 0 and (first_edge > 0) == (second_edge > 0)
            score = float(min(abs(first_edge), abs(second_edge)) * math.sqrt(max(minimum_events, 0) / 10.0))
            rows.append(
                {
                    "axis": axis,
                    "category": category,
                    "windows": reports,
                    "minimum_events_per_window": minimum_events,
                    "sign_consistent": sign_consistent,
                    "stable_candidate": bool(sign_consistent and minimum_events >= 5 and min(abs(first_edge), abs(second_edge)) >= 0.05),
                    "stable_score": score,
                    "interpretation": "favorable" if sign_consistent and first_edge > 0 else ("adverse" if sign_consistent else "unstable"),
                }
            )
        rows.sort(key=lambda row: (bool(row["stable_candidate"]), float(row["stable_score"])), reverse=True)
        output[axis] = rows
    return output


def group_key(event: Dict[str, Any], axis: str) -> str:
    if axis in {"side", "symbol", "utc_session"}:
        return str(event.get(axis, "missing"))
    if axis == "symbol_side":
        return f"{event.get('symbol')}|{event.get('side')}"
    if axis == "side_session":
        return f"{event.get('side')}|{event.get('utc_session')}"
    raise KeyError(axis)


def outcome_shift_decomposition(events: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}
    for axis in DECOMPOSITION_AXES:
        categories = sorted({group_key(event, axis) for event in events})
        rows: List[Dict[str, Any]] = []
        for category in categories:
            reports: Dict[str, Any] = {}
            for window in WINDOWS:
                selected = [
                    event
                    for event in events
                    if str(event.get("window")) == window and group_key(event, axis) == category
                ]
                reports[window] = event_metrics(selected)
            delta = float(reports[WINDOWS[1]]["avg_net_R"] - reports[WINDOWS[0]]["avg_net_R"])
            rows.append(
                {
                    "axis": axis,
                    "group": category,
                    "prior": reports[WINDOWS[0]],
                    "second": reports[WINDOWS[1]],
                    "avg_R_shift": delta,
                    "second_net_R": float(reports[WINDOWS[1]]["net_sum_R"]),
                }
            )
        rows.sort(key=lambda row: (float(row["avg_R_shift"]), float(row["second_net_R"])))
        output[axis] = rows
    return output


def path_mechanism(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for window in WINDOWS:
        output[window] = {}
        for side in SIDES:
            rows = [event for event in events if event.get("window") == window and event.get("side") == side]
            sl = [event for event in rows if class_name(event) == "SL"]
            tp = [event for event in rows if class_name(event) == "TP"]
            timeout = [event for event in rows if class_name(event) == "TIMEOUT"]
            early_sl = [event for event in sl if int(event.get("duration_min", 0)) <= 120]
            stop_after_mfe_half = [event for event in sl if float(event.get("mfe_R", 0.0)) >= 0.5]
            timeout_after_mfe_one = [event for event in timeout if float(event.get("mfe_R", 0.0)) >= 1.0]
            checkpoints: Dict[str, Any] = {}
            for minute in CHECKPOINTS:
                values = [
                    safe_float(event.get("checkpoint_close_R", {}).get(str(minute)))
                    for event in rows
                ]
                clean = [value for value in values if value is not None]
                checkpoints[str(minute)] = {
                    "n": len(clean),
                    "mean_close_R": float(statistics.fmean(clean)) if clean else None,
                    "median_close_R": float(statistics.median(clean)) if clean else None,
                }
            entry_failure_score = float(len(early_sl) / len(sl)) if sl else 0.0
            exit_failure_score = float(len(timeout_after_mfe_one) / len(timeout)) if timeout else 0.0
            output[window][side] = {
                "events": len(rows),
                "tp_events": len(tp),
                "sl_events": len(sl),
                "timeout_events": len(timeout),
                "early_sl_120m_pct": float(len(early_sl) / len(sl) * 100.0) if sl else 0.0,
                "sl_reached_0.5R_before_stop_pct": float(len(stop_after_mfe_half) / len(sl) * 100.0) if sl else 0.0,
                "timeout_reached_1R_pct": float(len(timeout_after_mfe_one) / len(timeout) * 100.0) if timeout else 0.0,
                "mean_mfe_R": mean_or_none(event.get("mfe_R") for event in rows),
                "mean_mae_R": mean_or_none(event.get("mae_R") for event in rows),
                "mean_duration_min": mean_or_none(event.get("duration_min") for event in rows),
                "checkpoints": checkpoints,
                "entry_failure_score": entry_failure_score,
                "exit_failure_score": exit_failure_score,
                "dominant_mechanism": (
                    "entry_timing_failure"
                    if entry_failure_score >= 0.50 and entry_failure_score >= exit_failure_score
                    else (
                        "profit_realization_failure"
                        if exit_failure_score >= 0.35
                        else "mixed_or_insufficient"
                    )
                ),
            }
    return output


def event_span_days(events: Sequence[Dict[str, Any]]) -> float:
    stamps = sorted(int(event.get("signal_ts", 0)) for event in events if int(event.get("signal_ts", 0)) > 0)
    if len(stamps) < 2:
        return 0.0
    return max((stamps[-1] - stamps[0]) / 86_400_000.0, 1.0)


def sample_gap_plan(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_side = Counter(str(event.get("side")) for event in events)
    by_window = Counter(str(event.get("window")) for event in events)
    by_class = Counter(class_name(event) for event in events)
    second_events = [event for event in events if event.get("window") == WINDOWS[1]]
    second_days = event_span_days(second_events)
    second_rate = float(len(second_events) / second_days) if second_days > 0 else 0.0
    deficits = {
        "events": max(0, TARGETS["events"] - len(events)),
        "long": max(0, TARGETS["each_side"] - by_side.get("long", 0)),
        "short": max(0, TARGETS["each_side"] - by_side.get("short", 0)),
        "prior_window": max(0, TARGETS["each_window"] - by_window.get(WINDOWS[0], 0)),
        "second_window": max(0, TARGETS["each_window"] - by_window.get(WINDOWS[1], 0)),
        "tp": max(0, TARGETS["tp_class"] - by_class.get("TP", 0)),
        "sl": max(0, TARGETS["sl_class"] - by_class.get("SL", 0)),
    }
    maximum_deficit = max(deficits.values()) if deficits else 0
    return {
        "targets": TARGETS,
        "current": {
            "events": len(events),
            "by_side": dict(sorted(by_side.items())),
            "by_window": dict(sorted(by_window.items())),
            "by_class": dict(sorted(by_class.items())),
        },
        "deficits": deficits,
        "second_window_span_days": second_days,
        "second_window_event_rate_per_day": second_rate,
        "estimated_forward_days_for_largest_event_deficit": (
            float(maximum_deficit / second_rate) if second_rate > 0 else None
        ),
        "ready": all(value == 0 for value in deficits.values()),
    }


def inventory_history(data_root: Path = DATA_ROOT) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    excluded = Counter()
    scanned = 0
    if not data_root.exists():
        return {
            "manifest_only": True,
            "data_root": str(data_root),
            "scanned_json_files": 0,
            "candidate_groups": [],
            "full_symbol_candidate_groups": [],
            "excluded": {"data_root_missing": 1},
        }
    for path in data_root.rglob("*.json"):
        if scanned >= MAX_INVENTORY_FILES:
            excluded["scan_limit_reached"] += 1
            break
        scanned += 1
        try:
            relative = path.relative_to(data_root).as_posix()
        except ValueError:
            relative = path.as_posix()
        lowered = relative.lower()
        if any(marker in lowered for marker in CONSUMED_PATH_MARKERS):
            excluded["already_consumed"] += 1
            continue
        reserved = next((token for token in RESERVED_PATH_TOKENS if token in lowered), None)
        if reserved is not None:
            excluded[f"reserved_token:{reserved}"] += 1
            continue
        symbol = next((candidate for candidate in SYMBOLS if candidate.lower() in lowered), None)
        if symbol is None or "1m" not in lowered:
            excluded["not_supported_1m_symbol_file"] += 1
            continue
        parent = path.parent.relative_to(data_root).as_posix()
        group = groups.setdefault(
            parent,
            {
                "directory": parent,
                "symbols": set(),
                "files": [],
                "total_bytes": 0,
            },
        )
        group["symbols"].add(symbol)
        try:
            size = int(path.stat().st_size)
        except OSError:
            size = 0
        group["files"].append({"name": path.name, "symbol": symbol, "bytes": size})
        group["total_bytes"] += size

    normalized: List[Dict[str, Any]] = []
    for group in groups.values():
        symbols = sorted(group["symbols"])
        normalized.append(
            {
                "directory": group["directory"],
                "symbols": symbols,
                "symbol_coverage": len(symbols),
                "file_count": len(group["files"]),
                "total_bytes": int(group["total_bytes"]),
                "files": sorted(group["files"], key=lambda row: (row["symbol"], row["name"]))[:25],
                "safe_to_consume": False,
                "requires_manual_non_reserved_confirmation": True,
            }
        )
    normalized.sort(key=lambda row: (int(row["symbol_coverage"]), int(row["total_bytes"])), reverse=True)
    full = [row for row in normalized if int(row["symbol_coverage"]) == len(SYMBOLS)]
    return {
        "manifest_only": True,
        "data_root": str(data_root),
        "scanned_json_files": scanned,
        "candidate_groups": normalized[:50],
        "full_symbol_candidate_groups": full[:20],
        "excluded": dict(sorted(excluded.items())),
        "contract": {
            "file_contents_read": False,
            "reserved_or_final_paths_consumed": False,
            "known_two_training_windows_excluded": True,
            "automatic_append_allowed": False,
        },
    }


def write_html(
    attribution: Dict[str, Any],
    inventory: Dict[str, Any],
    next_design: Dict[str, Any],
) -> None:
    feature_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['scope'])}</td>"
        f"<td>{html.escape(row['feature'])}</td>"
        f"<td>{row['minimum_oriented_strength']:.3f}</td>"
        f"<td>{row['drift_score']:.3f}</td>"
        f"<td>{row['stable_score']:.3f}</td>"
        f"<td>{row['stable_candidate']}</td>"
        f"<td>{html.escape(row['interpretation'])}</td>"
        "</tr>"
        for scope in ("all", "long", "short")
        for row in attribution["numeric_feature_attribution"][scope][:10]
    )
    inventory_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['directory'])}</td>"
        f"<td>{row['symbol_coverage']}</td>"
        f"<td>{row['file_count']}</td>"
        f"<td>{row['total_bytes']}</td>"
        "</tr>"
        for row in inventory.get("candidate_groups", [])[:20]
    )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke v3 drift attribution</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke v3 class-conditional drift attribution</h1>",
            "<h2>Next design</h2><pre>",
            html.escape(json.dumps(next_design, ensure_ascii=False, indent=2)),
            "</pre><h2>Stable feature diagnostics</h2><table><thead><tr><th>Scope</th><th>Feature</th><th>Min TP/SL strength</th><th>Drift</th><th>Stable score</th><th>Candidate</th><th>Direction</th></tr></thead><tbody>",
            feature_rows,
            "</tbody></table><h2>Safe history manifest</h2><table><thead><tr><th>Directory</th><th>Symbol coverage</th><th>Files</th><th>Bytes</th></tr></thead><tbody>",
            inventory_rows,
            "</tbody></table></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    ledger = load_json(LEDGER_SOURCE)
    drift_payload = load_json(DRIFT_SOURCE)
    load_json(PATH_SOURCE)
    events = ledger.get("events", [])
    if not isinstance(events, list) or not events:
        raise RuntimeError("EVENT_LEDGER_EMPTY")
    events = [event for event in events if isinstance(event, dict)]
    numeric_drift = drift_payload.get("drift", {}).get("numeric", {})
    if not isinstance(numeric_drift, dict) or not numeric_drift:
        raise RuntimeError("NUMERIC_DRIFT_EMPTY")

    numeric = feature_attribution(events, numeric_drift)
    categorical = categorical_attribution(events)
    decomposition = outcome_shift_decomposition(events)
    mechanism = path_mechanism(events)
    gap = sample_gap_plan(events)
    inventory = inventory_history()

    stable_numeric = [
        row
        for scope in ("long", "short", "all")
        for row in numeric[scope]
        if row["stable_candidate"]
    ]
    stable_numeric.sort(key=lambda row: float(row["stable_score"]), reverse=True)
    stable_categorical = [
        row
        for axis in CATEGORICAL_AXES
        for row in categorical[axis]
        if row["stable_candidate"]
    ]
    stable_categorical.sort(key=lambda row: float(row["stable_score"]), reverse=True)

    if gap["ready"]:
        next_action = "PURGED_WALK_FORWARD_META_LABELER_DESIGN"
    elif inventory.get("full_symbol_candidate_groups"):
        next_action = "MANUAL_CONFIRM_NON_RESERVED_HISTORY_THEN_APPEND_EVENT_LEDGER"
    else:
        next_action = "FORWARD_COLLECT_EVENTS_UNTIL_SAMPLE_GATE"

    next_design = {
        "status": "PASS_Q4R3_RASCHKE_V3_NEXT_DESIGN",
        "verdict": "DRIFT_ATTRIBUTED_SAMPLE_GAP_AND_SAFE_HISTORY_MANIFEST_READY",
        "next_action": next_action,
        "sample_gap": gap,
        "stable_numeric_candidates": stable_numeric[:10],
        "stable_categorical_candidates": stable_categorical[:10],
        "rules": {
            "model_training_now": False,
            "synthetic_oversampling": False,
            "final_third_holdout_access": False,
            "history_append_requires_manual_non_reserved_confirmation": True,
            "next_model_family_after_gate": ["regularized_logistic", "shallow_monotone_gbdt"],
            "validation": "purged_walk_forward_side_separated",
        },
    }
    attribution = {
        "status": "PASS_Q4R3_RASCHKE_V3_DRIFT_ATTRIBUTION",
        "verdict": "CLASS_CONDITIONAL_DRIFT_AND_PATH_MECHANISM_MEASURED_NO_MODEL",
        "events": len(events),
        "numeric_feature_attribution": numeric,
        "categorical_attribution": categorical,
        "outcome_shift_decomposition": decomposition,
        "path_mechanism": mechanism,
        "sample_gap": gap,
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
    }

    atomic_json(ATTRIBUTION_OUT, attribution)
    atomic_json(INVENTORY_OUT, {
        "status": "PASS_Q4R3_RASCHKE_V3_SAMPLE_INVENTORY",
        **inventory,
    })
    atomic_json(NEXT_OUT, next_design)
    write_html(attribution, inventory, next_design)
    print(json.dumps(next_design, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
