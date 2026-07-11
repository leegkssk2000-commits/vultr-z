from __future__ import annotations

import html
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
OVERLAY_ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-router-audit"))
V2_PATH = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"
ROUTER_TRADES_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_regime_router_trades_latest.json"
ROUTER_RESULT_SOURCE = ROOT / "runtime" / "q4r3_route_a_raschke_regime_router_latest.json"

AUDIT_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_router_failure_audit_latest.json"
CONTRIB_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_second_window_loss_contribution_latest.json"
CANDIDATES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_split_candidates_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_router_failure_audit_latest.html"

BASE_ROUTER = "router_off"
PRIOR_WINDOW = "prior_holdout_90d"
SECOND_WINDOW = "second_holdout_90d"
WINDOWS = (PRIOR_WINDOW, SECOND_WINDOW)
COST_PCT = 0.15
COST_STRESS_PCT = 0.20
MINUTE_MS = 60_000

CAUSAL_SPLIT_AXES = ("symbol", "side", "session", "symbol_side", "side_session")
DIAGNOSTIC_AXES = (
    "symbol",
    "side",
    "month",
    "session",
    "outcome",
    "duration_bucket",
    "mfe_bucket",
    "mae_bucket",
    "symbol_side",
    "side_session",
    "outcome_duration",
    "mfe_outcome",
)

SPLIT_GATE = {
    "group_events_second_min": 5,
    "group_net_R_second_max": -1.0,
    "second_loss_share_pct_min": 15.0,
    "prior_group_avg_R_max": 0.05,
    "combined_retention_pct_min": 70.0,
    "second_avg_R_improvement_min": 0.05,
    "combined_cost_0.20_avg_R_min_exclusive": 0.0,
    "positive_symbols_min": 3,
}


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_module("q4r3_router_failure_audit_v2", V2_PATH)


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


def trade_id(row: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("window", "")),
            str(row.get("symbol", "")),
            str(row.get("side", "")),
            str(int(row.get("signal_ts", row.get("entry_ts", 0)))),
        ]
    )


def net_r(row: Dict[str, Any], cost_pct: float = COST_PCT) -> float:
    return V2.net_r(row, cost_pct)


def normalize_trade(row: Dict[str, Any], *, router: str, window: str) -> Dict[str, Any]:
    result = dict(row)
    result["router"] = router
    result["window"] = window
    result["trade_id"] = trade_id(result)
    result["net_R_0.15"] = net_r(result, COST_PCT)
    result["net_R_0.20"] = net_r(result, COST_STRESS_PCT)
    result["duration_min"] = max(
        0,
        int((int(result.get("exit_ts", 0)) - int(result.get("entry_ts", 0))) / MINUTE_MS),
    )
    result["month"] = pd.to_datetime(int(result.get("entry_ts", 0)), unit="ms", utc=True).strftime("%Y-%m")
    result["session"] = utc_session(int(result.get("entry_ts", 0)))
    return result


def load_router_trades() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    payload = load_json(ROUTER_TRADES_SOURCE)
    source = payload.get("trades", {})
    if not isinstance(source, dict) or BASE_ROUTER not in source:
        raise RuntimeError("ROUTER_TRADES_CONTRACT_INVALID")
    output: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for router, windows in source.items():
        if not isinstance(windows, dict):
            continue
        output[router] = {}
        for window in WINDOWS:
            rows = windows.get(window, [])
            if not isinstance(rows, list):
                raise RuntimeError(f"INVALID_ROUTER_ROWS:{router}:{window}")
            output[router][window] = [
                normalize_trade(row, router=router, window=window)
                for row in rows
                if isinstance(row, dict)
            ]
    return output


def utc_session(stamp_ms: int) -> str:
    hour = int(pd.to_datetime(int(stamp_ms), unit="ms", utc=True).hour)
    if hour < 8:
        return "utc_00_07"
    if hour < 16:
        return "utc_08_15"
    return "utc_16_23"


def path_is_contiguous(frame: pd.DataFrame) -> bool:
    if len(frame) < 2:
        return True
    return bool((frame["ts"].diff().dropna() == MINUTE_MS).all())


def enrich_excursion(row: Dict[str, Any], raw: pd.DataFrame) -> Dict[str, Any]:
    result = dict(row)
    entry_ts = int(result.get("entry_ts", 0))
    exit_ts = int(result.get("exit_ts", 0))
    entry = float(result.get("entry", 0.0))
    risk = max(float(result.get("base_risk", 0.0)), 1e-12)
    side = str(result.get("side", ""))
    path = raw[(raw["ts"] >= entry_ts) & (raw["ts"] <= exit_ts)].copy()
    if path.empty or not path_is_contiguous(path):
        result.update({"path_valid": False, "mfe_R": None, "mae_R": None})
        result["duration_bucket"] = duration_bucket(result["duration_min"])
        result["mfe_bucket"] = "unavailable"
        result["mae_bucket"] = "unavailable"
        return result

    if side == "long":
        favorable = (path["high"] - entry) / risk
        adverse = (entry - path["low"]) / risk
    else:
        favorable = (entry - path["low"]) / risk
        adverse = (path["high"] - entry) / risk
    result["path_valid"] = True
    result["mfe_R"] = float(favorable.max())
    result["mae_R"] = float(adverse.max())
    result["minutes_to_mfe"] = int(
        (int(path.loc[favorable.idxmax(), "ts"]) - entry_ts) / MINUTE_MS
    )
    result["minutes_to_mae"] = int(
        (int(path.loc[adverse.idxmax(), "ts"]) - entry_ts) / MINUTE_MS
    )
    result["duration_bucket"] = duration_bucket(result["duration_min"])
    result["mfe_bucket"] = mfe_bucket(result["mfe_R"])
    result["mae_bucket"] = mae_bucket(result["mae_R"])
    return result


def enrich_baseline(
    trades: Dict[str, Dict[str, List[Dict[str, Any]]]]
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[Tuple[str, str], pd.DataFrame]]:
    output: Dict[str, List[Dict[str, Any]]] = {window: [] for window in WINDOWS}
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    for window in WINDOWS:
        for row in trades[BASE_ROUTER][window]:
            symbol = str(row["symbol"])
            key = (window, symbol)
            if key not in raw_cache:
                raw_cache[key] = V2.load_raw(V2.raw_path(window, symbol))[0]
            output[window].append(enrich_excursion(row, raw_cache[key]))
    return output, raw_cache


def duration_bucket(minutes: Any) -> str:
    value = int(minutes)
    if value <= 60:
        return "d00_060"
    if value <= 120:
        return "d061_120"
    if value <= 240:
        return "d121_240"
    return "d241_480"


def mfe_bucket(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "unavailable"
    if number < 0.5:
        return "mfe_lt_0.5R"
    if number < 1.0:
        return "mfe_0.5_1.0R"
    if number < 2.0:
        return "mfe_1.0_2.0R"
    return "mfe_ge_2.0R"


def mae_bucket(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "unavailable"
    if number < 0.25:
        return "mae_lt_0.25R"
    if number < 0.5:
        return "mae_0.25_0.5R"
    if number < 0.75:
        return "mae_0.5_0.75R"
    return "mae_ge_0.75R"


def group_label(row: Dict[str, Any], axis: str) -> str:
    if axis in {"symbol", "side", "month", "session", "outcome", "duration_bucket", "mfe_bucket", "mae_bucket"}:
        return str(row.get(axis, "missing"))
    if axis == "symbol_side":
        return f"{row.get('symbol')}|{row.get('side')}"
    if axis == "side_session":
        return f"{row.get('side')}|{row.get('session')}"
    if axis == "outcome_duration":
        return f"{row.get('outcome')}|{row.get('duration_bucket')}"
    if axis == "mfe_outcome":
        return f"{row.get('mfe_bucket')}|{row.get('outcome')}"
    raise KeyError(axis)


def metrics(rows: Sequence[Dict[str, Any]], cost_pct: float = COST_PCT) -> Dict[str, Any]:
    return V2.metrics(rows, cost_pct)


def router_window_audit(
    baseline_rows: Sequence[Dict[str, Any]],
    router_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    baseline = {str(row["trade_id"]): row for row in baseline_rows}
    routed = {str(row["trade_id"]): row for row in router_rows}
    blocked = [baseline[key] for key in sorted(set(baseline) - set(routed))]
    kept = [baseline[key] for key in sorted(set(baseline) & set(routed))]
    added = [routed[key] for key in sorted(set(routed) - set(baseline))]

    blocked_wins = [row for row in blocked if float(row["net_R_0.15"]) > 0]
    blocked_losses = [row for row in blocked if float(row["net_R_0.15"]) < 0]
    kept_wins = [row for row in kept if float(row["net_R_0.15"]) > 0]
    kept_losses = [row for row in kept if float(row["net_R_0.15"]) < 0]
    blocked_net = float(sum(float(row["net_R_0.15"]) for row in blocked))
    baseline_net = float(sum(float(row["net_R_0.15"]) for row in baseline_rows))
    router_net = float(sum(float(row["net_R_0.15"]) for row in router_rows))
    prevented_loss = abs(float(sum(float(row["net_R_0.15"]) for row in blocked_losses)))
    destroyed_profit = float(sum(float(row["net_R_0.15"]) for row in blocked_wins))
    denominator = prevented_loss + destroyed_profit

    return {
        "baseline_events": len(baseline_rows),
        "router_events": len(router_rows),
        "blocked_events": len(blocked),
        "kept_events": len(kept),
        "added_by_cooldown_shift_events": len(added),
        "useful_blocked_losses": len(blocked_losses),
        "useful_blocked_loss_R": prevented_loss,
        "false_blocked_wins": len(blocked_wins),
        "false_blocked_win_R": destroyed_profit,
        "false_passed_losses": len(kept_losses),
        "false_passed_loss_R": abs(float(sum(float(row["net_R_0.15"]) for row in kept_losses))),
        "kept_wins": len(kept_wins),
        "blocked_group_net_R": blocked_net,
        "expected_delta_from_blocking_only_R": -blocked_net,
        "actual_router_delta_R": router_net - baseline_net,
        "block_precision_loss_R_pct": float(prevented_loss / denominator * 100.0) if denominator > 0 else 0.0,
        "top_false_blocked_wins": compact_trades(sorted(blocked_wins, key=lambda row: float(row["net_R_0.15"]), reverse=True)[:10]),
        "top_false_passed_losses": compact_trades(sorted(kept_losses, key=lambda row: float(row["net_R_0.15"]))[:10]),
        "added_by_cooldown_shift": compact_trades(added[:10]),
    }


def compact_trades(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = (
        "trade_id",
        "window",
        "symbol",
        "side",
        "session",
        "month",
        "signal_ts",
        "entry_ts",
        "exit_ts",
        "outcome",
        "net_R_0.15",
        "duration_min",
        "mfe_R",
        "mae_R",
    )
    return [{key: row.get(key) for key in keys} for row in rows]


def audit_routers(
    trades: Dict[str, Dict[str, List[Dict[str, Any]]]],
    enriched_baseline: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    baseline_by_window = {
        window: {row["trade_id"]: row for row in enriched_baseline[window]}
        for window in WINDOWS
    }
    for router, windows in trades.items():
        if router == BASE_ROUTER:
            continue
        result[router] = {}
        for window in WINDOWS:
            normalized_router = []
            for row in windows[window]:
                enriched = baseline_by_window[window].get(row["trade_id"])
                normalized_router.append(enriched if enriched is not None else row)
            result[router][window] = router_window_audit(
                enriched_baseline[window], normalized_router
            )
        result[router]["diagnosis"] = diagnose_router(result[router])
    return result


def diagnose_router(window_audit: Dict[str, Any]) -> Dict[str, Any]:
    second = window_audit[SECOND_WINDOW]
    prior = window_audit[PRIOR_WINDOW]
    reasons: List[str] = []
    if second["false_blocked_win_R"] > second["useful_blocked_loss_R"]:
        reasons.append("blocked_more_profit_than_loss_in_second_window")
    if second["false_passed_loss_R"] > second["useful_blocked_loss_R"]:
        reasons.append("left_most_second_window_loss_untouched")
    if second["blocked_events"] <= max(3, int(second["baseline_events"] * 0.10)):
        reasons.append("insufficient_separation_power")
    if second["block_precision_loss_R_pct"] < 50.0:
        reasons.append("negative_block_precision")
    if prior["false_blocked_win_R"] > 0:
        reasons.append("damaged_prior_profitable_regime")
    return {
        "reasons": reasons,
        "second_window_net_filter_value_R": second["useful_blocked_loss_R"] - second["false_blocked_win_R"],
        "prior_window_net_filter_value_R": prior["useful_blocked_loss_R"] - prior["false_blocked_win_R"],
    }


def total_negative_R(rows: Sequence[Dict[str, Any]]) -> float:
    return abs(float(sum(min(float(row["net_R_0.15"]), 0.0) for row in rows)))


def contribution_records(
    prior_rows: Sequence[Dict[str, Any]],
    second_rows: Sequence[Dict[str, Any]],
    axis: str,
) -> List[Dict[str, Any]]:
    labels = sorted(
        {group_label(row, axis) for row in prior_rows}
        | {group_label(row, axis) for row in second_rows}
    )
    all_rows = list(prior_rows) + list(second_rows)
    base_second = metrics(second_rows, COST_PCT)
    base_combined_020 = metrics(all_rows, COST_STRESS_PCT)
    negative_total = total_negative_R(second_rows)
    records: List[Dict[str, Any]] = []
    for label in labels:
        prior_group = [row for row in prior_rows if group_label(row, axis) == label]
        second_group = [row for row in second_rows if group_label(row, axis) == label]
        remaining_prior = [row for row in prior_rows if group_label(row, axis) != label]
        remaining_second = [row for row in second_rows if group_label(row, axis) != label]
        remaining_combined = remaining_prior + remaining_second
        prior_report = metrics(prior_group, COST_PCT)
        second_report = metrics(second_group, COST_PCT)
        combined_report = metrics(prior_group + second_group, COST_PCT)
        remaining_second_report = metrics(remaining_second, COST_PCT)
        remaining_combined_015 = metrics(remaining_combined, COST_PCT)
        remaining_combined_020 = metrics(remaining_combined, COST_STRESS_PCT)
        group_negative = total_negative_R(second_group)
        records.append(
            {
                "axis": axis,
                "group": label,
                "prior": prior_report,
                "second": second_report,
                "combined": combined_report,
                "second_loss_share_pct": float(group_negative / negative_total * 100.0) if negative_total > 0 else 0.0,
                "counterfactual_remove_group": {
                    "retention_combined_pct": float(len(remaining_combined) / max(len(all_rows), 1) * 100.0),
                    "retention_second_pct": float(len(remaining_second) / max(len(second_rows), 1) * 100.0),
                    "second": remaining_second_report,
                    "combined_cost_0.15": remaining_combined_015,
                    "combined_cost_0.20": remaining_combined_020,
                    "second_avg_R_improvement": float(remaining_second_report["avg_net_R"]) - float(base_second["avg_net_R"]),
                    "combined_cost_0.20_avg_R_delta": float(remaining_combined_020["avg_net_R"]) - float(base_combined_020["avg_net_R"]),
                },
            }
        )
    records.sort(
        key=lambda row: (
            float(row["second"]["net_sum_R"]),
            -float(row["second_loss_share_pct"]),
        )
    )
    return records


def build_contribution_matrix(
    prior_rows: Sequence[Dict[str, Any]],
    second_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        axis: contribution_records(prior_rows, second_rows, axis)
        for axis in DIAGNOSTIC_AXES
    }


def split_candidates(contribution: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for axis in CAUSAL_SPLIT_AXES:
        for row in contribution[axis]:
            prior = row["prior"]
            second = row["second"]
            counterfactual = row["counterfactual_remove_group"]
            combined020 = counterfactual["combined_cost_0.20"]
            combined015 = counterfactual["combined_cost_0.15"]
            checks = {
                "events_second": int(second["events"]) >= SPLIT_GATE["group_events_second_min"],
                "group_net_second": float(second["net_sum_R"]) <= SPLIT_GATE["group_net_R_second_max"],
                "loss_share": float(row["second_loss_share_pct"]) >= SPLIT_GATE["second_loss_share_pct_min"],
                "prior_not_strong": float(prior["avg_net_R"]) <= SPLIT_GATE["prior_group_avg_R_max"],
                "retention": float(counterfactual["retention_combined_pct"]) >= SPLIT_GATE["combined_retention_pct_min"],
                "second_improvement": float(counterfactual["second_avg_R_improvement"]) >= SPLIT_GATE["second_avg_R_improvement_min"],
                "cost020": float(combined020["avg_net_R"]) > SPLIT_GATE["combined_cost_0.20_avg_R_min_exclusive"],
                "positive_symbols": int(combined015["positive_symbols"]) >= SPLIT_GATE["positive_symbols_min"],
            }
            if not all(checks.values()):
                continue
            score = (
                float(counterfactual["second_avg_R_improvement"])
                * math.sqrt(max(int(second["events"]), 1))
                * max(float(row["second_loss_share_pct"]) / 100.0, 0.01)
            )
            candidates.append(
                {
                    "title": f"reserve_{axis}_{row['group']}",
                    "axis": axis,
                    "group": row["group"],
                    "why": "This pre-entry observable group contributes disproportionate second-window loss without strong prior-window expectancy.",
                    "action": "route_group_to_reserve_observer_only",
                    "auto_apply": False,
                    "single_axis_only": True,
                    "checks": checks,
                    "evidence": row,
                    "score": float(score),
                    "next_validation": "causal_independent_rerun_then_untouched_third_holdout",
                }
            )
    candidates.sort(key=lambda row: float(row["score"]), reverse=True)
    return candidates[:3]


def exit_failure_diagnostics(second_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    timeouts = [row for row in second_rows if str(row.get("outcome")) == "TIMEOUT"]
    stops = [row for row in second_rows if str(row.get("outcome")) == "SL"]
    timeout_mfe_1r = [row for row in timeouts if (safe_float(row.get("mfe_R")) or -999.0) >= 1.0]
    stop_mfe_half = [row for row in stops if (safe_float(row.get("mfe_R")) or -999.0) >= 0.5]
    early_stops = [row for row in stops if int(row.get("duration_min", 0)) <= 120]
    return {
        "timeout": metrics(timeouts, COST_PCT),
        "sl": metrics(stops, COST_PCT),
        "timeout_reached_1R_before_exit": {
            "events": len(timeout_mfe_1r),
            "pct_of_timeouts": float(len(timeout_mfe_1r) / len(timeouts) * 100.0) if timeouts else 0.0,
            "net_sum_R": float(sum(float(row["net_R_0.15"]) for row in timeout_mfe_1r)),
            "diagnosis": "possible_profit_realization_failure_not_entry_failure",
        },
        "stops_reached_0.5R_before_stop": {
            "events": len(stop_mfe_half),
            "pct_of_stops": float(len(stop_mfe_half) / len(stops) * 100.0) if stops else 0.0,
            "net_sum_R": float(sum(float(row["net_R_0.15"]) for row in stop_mfe_half)),
            "diagnosis": "possible_giveback_or_confirmation_failure",
        },
        "stops_within_120m": {
            "events": len(early_stops),
            "pct_of_stops": float(len(early_stops) / len(stops) * 100.0) if stops else 0.0,
            "net_sum_R": float(sum(float(row["net_R_0.15"]) for row in early_stops)),
            "diagnosis": "possible_entry_timing_failure",
        },
    }


def write_html(
    router_audit: Dict[str, Any],
    contribution: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
    exit_diag: Dict[str, Any],
) -> None:
    router_rows: List[str] = []
    for router, report in router_audit.items():
        second = report[SECOND_WINDOW]
        router_rows.append(
            "<tr>"
            f"<td>{html.escape(router)}</td>"
            f"<td>{second['blocked_events']}</td>"
            f"<td>{second['useful_blocked_loss_R']:.3f}</td>"
            f"<td>{second['false_blocked_win_R']:.3f}</td>"
            f"<td>{second['false_passed_loss_R']:.3f}</td>"
            f"<td>{second['actual_router_delta_R']:.3f}</td>"
            f"<td>{html.escape(', '.join(report['diagnosis']['reasons']))}</td>"
            "</tr>"
        )

    contribution_rows: List[str] = []
    for axis in ("symbol", "side", "session", "symbol_side", "outcome", "mfe_bucket"):
        for row in contribution[axis][:5]:
            contribution_rows.append(
                "<tr>"
                f"<td>{html.escape(axis)}</td>"
                f"<td>{html.escape(str(row['group']))}</td>"
                f"<td>{row['second']['events']}</td>"
                f"<td>{row['second']['net_sum_R']:.3f}</td>"
                f"<td>{row['second_loss_share_pct']:.1f}%</td>"
                f"<td>{row['prior']['avg_net_R']:.3f}</td>"
                f"<td>{row['counterfactual_remove_group']['second_avg_R_improvement']:.3f}</td>"
                "</tr>"
            )

    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke router failure audit</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%;margin-bottom:30px}td,th{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke router failure and second-window loss attribution</h1>",
            "<h2>Why routers failed</h2><table><thead><tr><th>Router</th><th>Blocked</th><th>Loss removed R</th><th>Profit destroyed R</th><th>Loss left R</th><th>Actual delta R</th><th>Diagnosis</th></tr></thead><tbody>",
            "".join(router_rows),
            "</tbody></table>",
            "<h2>Worst contribution groups</h2><table><thead><tr><th>Axis</th><th>Group</th><th>Events</th><th>Second net R</th><th>Loss share</th><th>Prior avg R</th><th>Second avg improvement if removed</th></tr></thead><tbody>",
            "".join(contribution_rows),
            "</tbody></table>",
            "<h2>Split candidates</h2><pre>",
            html.escape(json.dumps(list(candidates), ensure_ascii=False, indent=2)),
            "</pre><h2>Exit diagnostics</h2><pre>",
            html.escape(json.dumps(exit_diag, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    trades = load_router_trades()
    baseline, _ = enrich_baseline(trades)
    router_audit = audit_routers(trades, baseline)
    contribution = build_contribution_matrix(
        baseline[PRIOR_WINDOW], baseline[SECOND_WINDOW]
    )
    candidates = split_candidates(contribution)
    exit_diag = exit_failure_diagnostics(baseline[SECOND_WINDOW])

    router_result = load_json(ROUTER_RESULT_SOURCE)
    audit_payload = {
        "status": "PASS_Q4R3_RASCHKE_ROUTER_FAILURE_AUDIT",
        "verdict": "ROUTER_FAILURE_CAUSE_DECOMPOSED_NO_STRATEGY_MUTATION",
        "source_router_verdict": router_result.get("verdict"),
        "base_router": BASE_ROUTER,
        "cost_pct": COST_PCT,
        "router_audit": router_audit,
        "diagnostic_summary": {
            "router_count": len(router_audit),
            "routers_that_improved_second_window": [
                router
                for router, report in router_audit.items()
                if float(report[SECOND_WINDOW]["actual_router_delta_R"]) > 0
            ],
            "routers_with_positive_second_window_filter_value": [
                router
                for router, report in router_audit.items()
                if float(report["diagnosis"]["second_window_net_filter_value_R"]) > 0
            ],
        },
        "outputs": {
            "loss_contribution": str(CONTRIB_OUT),
            "split_candidates": str(CANDIDATES_OUT),
            "html": str(HTML_OUT),
        },
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
        },
    }
    contribution_payload = {
        "status": "PASS_Q4R3_RASCHKE_SECOND_WINDOW_LOSS_CONTRIBUTION",
        "base_lane": "proximity_guard_fixed_2R",
        "prior_metrics_cost_0.15": metrics(baseline[PRIOR_WINDOW], COST_PCT),
        "second_metrics_cost_0.15": metrics(baseline[SECOND_WINDOW], COST_PCT),
        "combined_metrics_cost_0.15": metrics(baseline[PRIOR_WINDOW] + baseline[SECOND_WINDOW], COST_PCT),
        "contribution": contribution,
        "exit_failure_diagnostics": exit_diag,
        "rule": "month, outcome, MFE and MAE are diagnostic only; only pre-entry observable axes may become split candidates",
    }
    candidates_payload = {
        "status": "PASS_Q4R3_RASCHKE_SPLIT_CANDIDATES",
        "gate": SPLIT_GATE,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "auto_apply": False,
        "next": (
            "CAUSAL_SINGLE_AXIS_RERUN"
            if candidates
            else "NO_CAUSAL_SPLIT_FOUND_RETAIN_AS_REGIME_DEPENDENT_RESERVE"
        ),
    }

    write_html(router_audit, contribution, candidates, exit_diag)
    atomic_json(AUDIT_OUT, audit_payload)
    atomic_json(CONTRIB_OUT, contribution_payload)
    atomic_json(CANDIDATES_OUT, candidates_payload)
    print(json.dumps(audit_payload, ensure_ascii=False, indent=2))
    print(json.dumps(candidates_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
