from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_STRATEGY_LOSS_ATTRIBUTION_GEMINI_V1"
SCHEMA = "zel.strategy_loss_attribution_gemini.receipt.v1"
NUMERIC_FIELDS = {
    "realized_R",
    "net_R",
    "pnl_r",
    "net_reference_R",
    "MFE_R",
    "MAE_R",
    "time_exposure_min",
    "fee",
    "slippage",
    "funding_pnl_estimate_usdt",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def number(row: Mapping[str, Any], keys: Sequence[str], default: float | None = None) -> float | None:
    for key in keys:
        parsed = finite_number(row.get(key))
        if parsed is not None:
            return parsed
    return default


def text_value(row: Mapping[str, Any], keys: Sequence[str], default: str = "unknown") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def parse_ts(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return numeric
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def normalized_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    strategy_id = text_value(raw, ("strategy_id", "strategy", "strategy_name", "source_strategy_id"))
    realized_r = number(raw, ("realized_R", "net_R", "pnl_r", "net_reference_R", "net_return_R"), 0.0) or 0.0
    entry_ts = parse_ts(raw.get("entry_ts") or raw.get("entry_time") or raw.get("opened_at"))
    exit_ts = parse_ts(raw.get("exit_ts") or raw.get("exit_time") or raw.get("closed_at"))
    hour_bucket = "unknown"
    if entry_ts is not None:
        hour = datetime.fromtimestamp(entry_ts, tz=timezone.utc).hour
        if 0 <= hour < 6:
            hour_bucket = "utc_00_06"
        elif hour < 12:
            hour_bucket = "utc_06_12"
        elif hour < 18:
            hour_bucket = "utc_12_18"
        else:
            hour_bucket = "utc_18_24"
    return {
        "event_id": text_value(raw, ("event_id", "trade_id", "position_id"), stable_sha(raw)[:20]),
        "strategy_id": strategy_id,
        "window_id": text_value(raw, ("window_id", "window", "dataset_window")),
        "symbol": text_value(raw, ("symbol", "market")),
        "side": text_value(raw, ("side", "direction")).lower(),
        "regime": text_value(raw, ("regime", "market_regime")).lower(),
        "hour_bucket": hour_bucket,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "realized_R": realized_r,
        "MFE_R": number(raw, ("MFE_R", "mfe_R", "mfe_r", "max_favorable_excursion_R")),
        "MAE_R": number(raw, ("MAE_R", "mae_R", "mae_r", "max_adverse_excursion_R")),
        "time_exposure_min": number(raw, ("time_exposure_min", "exposure_min", "holding_minutes")),
        "fee": number(raw, ("fee", "fee_usdt"), 0.0) or 0.0,
        "slippage": number(raw, ("slippage", "slippage_usdt"), 0.0) or 0.0,
        "funding": number(raw, ("funding_pnl_estimate_usdt", "funding", "funding_usdt"), 0.0) or 0.0,
    }


def read_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt"
    with opener(path, mode, encoding="utf-8") as handle:  # type: ignore[arg-type]
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"TRADE_ROW_NOT_OBJECT:{line_number}")
            rows.append(normalized_row(payload))
    return rows


def read_strategy_inventory(path: Path, expected_count: int) -> tuple[list[str], str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    if not rows or not reader.fieldnames:
        raise RuntimeError("SCOREBOARD_EMPTY_OR_HEADER_MISSING")
    preferred = ("strategy_id", "strategy", "strategy_name", "source_strategy_id", "id", "name")
    candidates = [field for field in preferred if field in reader.fieldnames]
    candidates.extend(field for field in reader.fieldnames if field not in candidates)
    for field in candidates:
        values: list[str] = []
        seen: set[str] = set()
        for row in rows:
            value = str(row.get(field) or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        if len(values) == expected_count:
            return values, field, len(rows)
    raise RuntimeError(
        "SCOREBOARD_STRATEGY_COLUMN_NOT_FOUND:"
        + json.dumps({"fields": reader.fieldnames, "row_count": len(rows)}, sort_keys=True)
    )


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row.get("exit_ts") is None, row.get("exit_ts") or 0.0, str(row.get("event_id"))))
    values = [float(row.get("realized_R") or 0.0) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    mfe = [finite_number(row.get("MFE_R")) for row in ordered]
    mae = [finite_number(row.get("MAE_R")) for row in ordered]
    exposure = [finite_number(row.get("time_exposure_min")) for row in ordered]
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else None,
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "median_R": statistics.median(values) if values else None,
        "gross_profit_R": gross_profit,
        "gross_loss_R": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_drawdown_R": max_drawdown(values),
        "average_MFE_R": statistics.fmean(value for value in mfe if value is not None)
        if any(value is not None for value in mfe)
        else None,
        "average_MAE_R": statistics.fmean(value for value in mae if value is not None)
        if any(value is not None for value in mae)
        else None,
        "average_exposure_min": statistics.fmean(value for value in exposure if value is not None)
        if any(value is not None for value in exposure)
        else None,
        "fee_total_usdt": sum(float(row.get("fee") or 0.0) for row in ordered),
        "slippage_total_usdt": sum(float(row.get("slippage") or 0.0) for row in ordered),
        "funding_total_usdt": sum(float(row.get("funding") or 0.0) for row in ordered),
    }


def group_rows(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return dict(grouped)


def group_metrics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {name: metrics(group) for name, group in sorted(group_rows(rows, key).items())}


def chronological_segments(rows: Sequence[Mapping[str, Any]], count: int = 4) -> dict[str, dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row.get("entry_ts") is None, row.get("entry_ts") or 0.0, str(row.get("event_id"))))
    if not ordered:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index in range(count):
        start = len(ordered) * index // count
        end = len(ordered) * (index + 1) // count
        segment = ordered[start:end]
        if segment:
            result[f"Q{index + 1}"] = metrics(segment)
    return result


def loss_clusters(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    loss_r = Counter()
    for row in rows:
        realized = float(row.get("realized_R") or 0.0)
        if realized >= 0:
            continue
        magnitude = -realized
        mfe = finite_number(row.get("MFE_R"))
        mae = finite_number(row.get("MAE_R"))
        exposure = finite_number(row.get("time_exposure_min"))
        labels: list[str] = []
        if mfe is not None and mfe < 0.25:
            labels.append("immediate_fail_mfe_lt_0_25R")
        if mfe is not None and mfe >= 0.50:
            labels.append("favorable_then_loss_mfe_ge_0_50R")
        if mae is not None and mae <= -0.75:
            labels.append("deep_adverse_mae_le_neg_0_75R")
        if exposure is not None and exposure >= 30.0:
            labels.append("long_exposure_ge_30m")
        if not labels:
            labels.append("unclassified_loss")
        for label in labels:
            counts[label] += 1
            loss_r[label] += magnitude
    return {
        label: {"loss_count": counts[label], "gross_loss_R": loss_r[label]}
        for label in sorted(counts)
    }


def filter_rows(rows: Sequence[Mapping[str, Any]], axis: str, excluded_value: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if str(row.get(axis) or "unknown") != excluded_value]


def delta_metrics(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = finite_number(base.get("profit_factor"))
    candidate_pf = finite_number(candidate.get("profit_factor"))
    return {
        "delta_net_R": float(candidate.get("net_R") or 0.0) - float(base.get("net_R") or 0.0),
        "delta_max_drawdown_R": float(candidate.get("max_drawdown_R") or 0.0) - float(base.get("max_drawdown_R") or 0.0),
        "delta_profit_factor": candidate_pf - base_pf if base_pf is not None and candidate_pf is not None else None,
        "trade_retention_pct": float(candidate.get("trade_count") or 0) / max(float(base.get("trade_count") or 0), 1.0) * 100.0,
    }


def simple_filter_screen(
    rows: Sequence[Mapping[str, Any]],
    windows: Sequence[str],
    min_window_trades: int,
    min_retention_pct: float,
) -> dict[str, Any]:
    window_rows = group_rows(rows, "window_id")
    selection_name = windows[0]
    selection = window_rows.get(selection_name, [])
    if len(selection) < min_window_trades:
        return {"state": "HOLD_SELECTION_WINDOW_INSUFFICIENT", "selection_window": selection_name, "candidates": []}
    base_selection = metrics(selection)
    candidates: list[dict[str, Any]] = []
    for axis in ("symbol", "side", "regime", "hour_bucket"):
        values = Counter(str(row.get(axis) or "unknown") for row in selection)
        for excluded_value, removed_count in sorted(values.items()):
            if excluded_value == "unknown" or removed_count < 3:
                continue
            candidate_selection_rows = filter_rows(selection, axis, excluded_value)
            candidate_selection = metrics(candidate_selection_rows)
            selection_delta = delta_metrics(base_selection, candidate_selection)
            if selection_delta["trade_retention_pct"] < min_retention_pct:
                continue
            if selection_delta["delta_net_R"] <= 0:
                continue
            evaluations: dict[str, Any] = {}
            oos_passes: list[bool] = []
            for window in windows:
                base_rows = window_rows.get(window, [])
                if len(base_rows) < min_window_trades:
                    evaluations[window] = {"state": "HOLD_WINDOW_INSUFFICIENT", "trade_count": len(base_rows)}
                    continue
                base = metrics(base_rows)
                candidate = metrics(filter_rows(base_rows, axis, excluded_value))
                delta = delta_metrics(base, candidate)
                evaluations[window] = {"state": "PASS_EVALUATED", "base": base, "candidate": candidate, "delta": delta}
                if window != selection_name:
                    oos_passes.append(
                        delta["trade_retention_pct"] >= min_retention_pct
                        and delta["delta_net_R"] > 0
                        and delta["delta_max_drawdown_R"] >= -0.25
                    )
            state = "PASS_NONOVERLAP_FILTER_CANDIDATE" if len(oos_passes) >= 2 and all(oos_passes) else "HOLD_FILTER_NOT_OOS_DURABLE"
            candidates.append(
                {
                    "state": state,
                    "axis": axis,
                    "excluded_value": excluded_value,
                    "removed_selection_trades": removed_count,
                    "selection_delta": selection_delta,
                    "window_evaluations": evaluations,
                    "production_applied": False,
                    "selection_authority": False,
                    "promotion_authority": False,
                }
            )
    candidates.sort(
        key=lambda row: (
            row["state"] == "PASS_NONOVERLAP_FILTER_CANDIDATE",
            float(row["selection_delta"]["delta_net_R"]),
            float(row["selection_delta"]["delta_max_drawdown_R"]),
        ),
        reverse=True,
    )
    return {
        "state": "PASS_FILTER_SCREEN_COMPLETE",
        "selection_window": selection_name,
        "candidate_count": len(candidates),
        "oos_pass_count": sum(row["state"] == "PASS_NONOVERLAP_FILTER_CANDIDATE" for row in candidates),
        "candidates": candidates[:20],
    }


def parse_gemini_text(payload: Mapping[str, Any]) -> str:
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content")
        if not isinstance(content, Mapping):
            continue
        for part in content.get("parts", []):
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("EMPTY_GEMINI_RESPONSE")
    return text


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].lstrip()
    payload = json.loads(stripped)
    if not isinstance(payload, Mapping):
        raise RuntimeError("GEMINI_RESPONSE_NOT_OBJECT")
    return dict(payload)


def call_gemini(
    api_key: str,
    models: Sequence[str],
    prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, Any]]:
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
            },
        }
    ).encode("utf-8")
    errors: list[str] = []
    for attempt in range(3):
        for model in models:
            try:
                request = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                    data=body,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=900) as response:
                    generated = json.load(response)
                return model, parse_json_response(parse_gemini_text(generated))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:600]
                errors.append(f"{model}:HTTP_{exc.code}:{detail}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}:{type(exc).__name__}:{exc}")
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors[-12:]))


def compact_profile(strategy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "alias": strategy["alias"],
        "overall": strategy["overall"],
        "by_window": strategy["by_window"],
        "by_symbol": strategy["by_symbol"],
        "by_side": strategy["by_side"],
        "by_regime": strategy["by_regime"],
        "by_hour_bucket": strategy["by_hour_bucket"],
        "chronological_quartiles": strategy["chronological_quartiles"],
        "loss_clusters": strategy["loss_clusters"],
        "filter_screen": strategy["filter_screen"],
        "loss_contribution_pct": strategy["loss_contribution_pct"],
        "net_loss_contribution_pct": strategy["net_loss_contribution_pct"],
    }


def global_prompt(profile: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "system_failure_modes": [{"mode": "...", "evidence": ["..."], "causal_confidence_pct": 0, "scope": "..."}],
        "priority_strategies": [{"alias": "S01", "why": "...", "first_axis": "entry_filter|exit_logic|indicator_contract|risk_geometry|NO_CHANGE"}],
        "cross_strategy_actions": [{"action": "...", "required_test": "...", "risk": "..."}],
        "warnings": ["..."],
    }
    return (
        "You are the senior quantitative failure-analysis layer for a 25-strategy crypto futures research system. "
        "Use only the anonymized aggregate evidence below. Separate observation, causal hypothesis and test. "
        "Do not claim profitability, do not infer private code, and do not recommend multi-axis parameter sweeps. "
        "Prioritize loss concentration, W1/W2/W3 durability, symbol/side/regime concentration, immediate-fail versus favorable-then-loss clusters, fees/slippage and drawdown. Return strict JSON only.\n\n"
        f"ANONYMIZED_SYSTEM_PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def strategy_prompt(profile: Mapping[str, Any], global_review: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "alias": profile["alias"],
        "failure_clusters": [{"cluster": "...", "evidence": ["..."], "causal_confidence_pct": 0, "does_not_prove": "..."}],
        "hypotheses": [
            {
                "change_type": "entry_filter|loss_cap|break_even|partial|trailing|time_stop|indicator_contract|risk_geometry|NO_CHANGE",
                "single_axis_change": "...",
                "bounded_parameter_space": ["..."],
                "why": "...",
                "required_replay": "ledger_nonoverlap|intratrade_path|source_patch_and_full_replay|none",
                "falsification_test": "...",
                "overfit_risk": "LOW|MEDIUM|HIGH",
                "priority": 1,
            }
        ],
        "recommended_next": "TEST_ONE|KEEP_CONTROL|WAIT_EVIDENCE",
    }
    return (
        "You are diagnosing one anonymized trading strategy. Use the loss attribution, non-overlap filter screen and system review. "
        "Propose NO_CHANGE plus at most two distinct single-axis hypotheses. A W1-selected filter is not valid unless W2 and W3 both support it. "
        "MFE/MAE-based stop, break-even, partial, trailing or time-stop changes require intratrade path evidence and must be marked as such. "
        "Do not combine entry and exit changes. Do not use broad parameter sweeps. Return strict JSON only.\n\n"
        f"STRATEGY_PROFILE={json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n"
        f"GLOBAL_REVIEW={json.dumps(global_review, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(reviews: Mapping[str, Any], profiles: Sequence[Mapping[str, Any]]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "approved_queue": [
            {
                "alias": "S01",
                "change_type": "...",
                "single_axis_change": "...",
                "required_replay": "...",
                "falsification_test": "...",
                "priority": 1,
                "approval_reason": "...",
            }
        ],
        "rejected": [{"alias": "S02", "reason": "unsupported|multi_axis|selection_bias|path_missing|duplicate|weak_materiality"}],
        "hold_reasons": ["..."],
    }
    return (
        "You are the independent red-team for strategy improvement. Reject selection bias, W1-only wins, hidden multi-axis changes, unsupported path-dependent exits, duplicated hypotheses and weak materiality. "
        "Approve at most six hypotheses globally and at most one per strategy. Every approved item remains research-only and must specify an exact falsification test. Return strict JSON only.\n\n"
        f"STRATEGY_PROFILES={json.dumps(list(profiles), ensure_ascii=False, sort_keys=True)}\n"
        f"GEMINI_STRATEGY_REVIEWS={json.dumps(reviews, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--scoreboard", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    rows = read_trades(args.trades)
    if len(rows) != int(policy["expected_trade_count"]):
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")
    expected_strategy_count = int(policy["expected_strategy_count"])
    strategy_inventory, inventory_field, scoreboard_row_count = read_strategy_inventory(
        args.scoreboard, expected_strategy_count
    )
    trade_strategies_grouped = group_rows(rows, "strategy_id")
    unknown_trade_strategy_ids = sorted(set(trade_strategies_grouped) - set(strategy_inventory))
    if unknown_trade_strategy_ids:
        raise RuntimeError(
            "TRADE_STRATEGY_NOT_IN_SCOREBOARD:" + json.dumps(unknown_trade_strategy_ids)
        )
    strategies_grouped = {
        strategy_id: trade_strategies_grouped.get(strategy_id, [])
        for strategy_id in strategy_inventory
    }
    traded_strategy_count = sum(bool(group) for group in strategies_grouped.values())
    zero_trade_strategy_count = expected_strategy_count - traded_strategy_count

    overall = metrics(rows)
    total_gross_loss = float(overall["gross_loss_R"] or 0.0)
    negative_strategy_net = sum(
        max(0.0, -float(metrics(group)["net_R"] or 0.0)) for group in strategies_grouped.values()
    )
    windows = [str(value) for value in policy["windows"]]
    strategy_rows: list[dict[str, Any]] = []
    ordered_ids = sorted(
        strategies_grouped,
        key=lambda strategy_id: (
            -float(metrics(strategies_grouped[strategy_id])["gross_loss_R"] or 0.0),
            -int(metrics(strategies_grouped[strategy_id])["trade_count"] or 0),
            strategy_id,
        ),
    )
    alias_map = {strategy_id: f"S{index + 1:02d}" for index, strategy_id in enumerate(ordered_ids)}
    for strategy_id in ordered_ids:
        group = strategies_grouped[strategy_id]
        row_metrics = metrics(group)
        strategy_rows.append(
            {
                "strategy_id": strategy_id,
                "alias": alias_map[strategy_id],
                "state": "PASS_TRADE_BEARING_STRATEGY" if group else "HOLD_ZERO_TRADE_STRATEGY",
                "overall": row_metrics,
                "loss_contribution_pct": float(row_metrics["gross_loss_R"] or 0.0) / max(total_gross_loss, 1e-12) * 100.0,
                "net_loss_contribution_pct": max(0.0, -float(row_metrics["net_R"] or 0.0)) / max(negative_strategy_net, 1e-12) * 100.0,
                "by_window": group_metrics(group, "window_id"),
                "by_symbol": group_metrics(group, "symbol"),
                "by_side": group_metrics(group, "side"),
                "by_regime": group_metrics(group, "regime"),
                "by_hour_bucket": group_metrics(group, "hour_bucket"),
                "chronological_quartiles": chronological_segments(group),
                "loss_clusters": loss_clusters(group),
                "filter_screen": simple_filter_screen(
                    group,
                    windows,
                    int(policy["min_window_trades"]),
                    float(policy["min_retention_pct"]),
                ),
            }
        )

    attribution = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_STRATEGY_LOSS_ATTRIBUTION_COMPLETE",
        "trade_count": len(rows),
        "strategy_count": len(strategy_rows),
        "traded_strategy_count": traded_strategy_count,
        "zero_trade_strategy_count": zero_trade_strategy_count,
        "strategy_inventory_source": {
            "path_role": "terminal_scoreboard",
            "identity_field": inventory_field,
            "row_count": scoreboard_row_count,
        },
        "overall": overall,
        "by_window": group_metrics(rows, "window_id"),
        "by_symbol": group_metrics(rows, "symbol"),
        "by_side": group_metrics(rows, "side"),
        "by_regime": group_metrics(rows, "regime"),
        "by_hour_bucket": group_metrics(rows, "hour_bucket"),
        "strategies": strategy_rows,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_data_published": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "selection_authority": False,
        "promotion_authority": False,
        "action": "hold",
    }
    attribution["receipt_sha256"] = stable_sha(attribution)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "attribution.json", attribution)

    top_count = int(policy["top_strategy_count"])
    top = [row for row in strategy_rows if int(row["overall"]["trade_count"] or 0) > 0][:top_count]
    anonymized_profiles = [compact_profile(row) for row in top]
    global_profile = {
        "overall": overall,
        "by_window": attribution["by_window"],
        "by_symbol": attribution["by_symbol"],
        "by_side": attribution["by_side"],
        "by_regime": attribution["by_regime"],
        "top_strategies": anonymized_profiles,
    }
    manifest = {
        "schema_version": "zel.gemini.anonymized_payload_manifest.v1",
        "strategy_alias_map": alias_map,
        "raw_trades_sent": False,
        "private_code_sent": False,
        "account_data_sent": False,
        "credentials_sent": False,
        "numeric_fields_allowed": sorted(NUMERIC_FIELDS),
        "global_profile_sha256": stable_sha(global_profile),
    }
    atomic_json(args.out / "gemini_payload_manifest.json", manifest)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    models = [str(value) for value in policy["models"]]
    max_tokens = int(policy["max_output_tokens"])
    temperature = float(policy["temperature"])
    call_log: list[dict[str, Any]] = []

    model, global_review = call_gemini(api_key, models, global_prompt(global_profile), max_tokens, temperature)
    call_log.append({"kind": "global", "model": model, "response_sha256": stable_sha(global_review)})
    atomic_json(args.out / "gemini_global_review.json", global_review)

    reviews: dict[str, Any] = {}
    for profile in anonymized_profiles:
        model, review = call_gemini(api_key, models, strategy_prompt(profile, global_review), max_tokens, temperature)
        alias = str(profile["alias"])
        reviews[alias] = review
        call_log.append({"kind": "strategy", "alias": alias, "model": model, "response_sha256": stable_sha(review)})
        atomic_json(args.out / "strategy_reviews" / f"{alias}.json", review)

    model, red_team = call_gemini(api_key, models, red_team_prompt(reviews, anonymized_profiles), max_tokens, temperature)
    call_log.append({"kind": "red_team", "model": model, "response_sha256": stable_sha(red_team)})
    atomic_json(args.out / "gemini_red_team.json", red_team)

    approved = red_team.get("approved_queue") if isinstance(red_team.get("approved_queue"), list) else []
    alias_to_strategy = {alias: strategy_id for strategy_id, alias in alias_map.items()}
    improvement_queue: list[dict[str, Any]] = []
    for item in approved:
        if not isinstance(item, Mapping):
            continue
        alias = str(item.get("alias") or "")
        improvement_queue.append(
            {
                **dict(item),
                "strategy_id": alias_to_strategy.get(alias),
                "state": "HOLD_APPROVED_FOR_COUNTERFACTUAL_REPLAY_ONLY",
                "production_applied": False,
                "shadow_started": False,
                "paper_started": False,
                "live_enabled": False,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "action": "hold",
            }
        )
    atomic_json(args.out / "improvement_queue.json", {"items": improvement_queue})

    summary = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_ATTRIBUTION_AND_GEMINI_IMPROVEMENT_QUEUE_READY",
        "trade_count": len(rows),
        "strategy_count": len(strategy_rows),
        "traded_strategy_count": traded_strategy_count,
        "zero_trade_strategy_count": zero_trade_strategy_count,
        "top_strategy_count": len(top),
        "gemini_used": True,
        "gemini_call_count": len(call_log),
        "gemini_models": sorted({str(row["model"]) for row in call_log}),
        "approved_hypothesis_count": len(improvement_queue),
        "oos_filter_candidate_count": sum(
            int(row["filter_screen"].get("oos_pass_count") or 0) for row in strategy_rows
        ),
        "attribution_receipt_sha256": attribution["receipt_sha256"],
        "call_log": call_log,
        "raw_trades_sent_to_gemini": False,
        "private_code_sent_to_gemini": False,
        "account_data_sent_to_gemini": False,
        "credentials_sent_to_gemini": False,
        "raw_trade_data_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RUN_APPROVED_SINGLE_AXIS_COUNTERFACTUAL_REPLAYS",
    }
    if summary["gemini_call_count"] < int(policy["min_gemini_calls"]):
        raise RuntimeError("GEMINI_CALL_COVERAGE_INSUFFICIENT")
    summary["receipt_sha256"] = stable_sha(summary)
    atomic_json(args.out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
