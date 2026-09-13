from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_ema_path_semantics_reconciliation_v1 as reconcile
import zel_ema_ribbon_intratrade_path_audit_v1 as audit

VERSION = "ZEL_EMA_TRAILING_COUNTERFACTUAL_V1"
SCHEMA = "zel.ema_trailing_counterfactual.receipt.v1"
ACTIVATION_R = 0.50
TRAIL_DISTANCE_CANDIDATES_R = (0.15, 0.25, 0.35, 0.50, 0.65)
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")
EXPECTED_TRADES = 424


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float | None:
    return audit.finite(value)


def signed_r(price: float, entry: float, risk: float, side: str) -> float:
    if side == "long":
        return (price - entry) / risk
    if side == "short":
        return (entry - price) / risk
    raise RuntimeError(f"INVALID_SIDE:{side}")


def values_metrics(values: Sequence[tuple[str, float]]) -> dict[str, Any]:
    ordered = sorted(values, key=lambda row: row[0])
    returns = [float(value) for _, value in ordered]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(returns),
        "net_R": sum(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(returns) * 100.0 if returns else None,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "max_drawdown_R": max_drawdown,
    }


def metric_delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = finite(base.get("profit_factor"))
    candidate_pf = finite(candidate.get("profit_factor"))
    return {
        "delta_net_R": float(candidate.get("net_R") or 0.0) - float(base.get("net_R") or 0.0),
        "delta_max_drawdown_R": float(candidate.get("max_drawdown_R") or 0.0) - float(base.get("max_drawdown_R") or 0.0),
        "delta_profit_factor": candidate_pf - base_pf if base_pf is not None and candidate_pf is not None else None,
        "trade_retention_pct": int(candidate.get("trade_count") or 0) / max(int(base.get("trade_count") or 0), 1) * 100.0,
    }


def chronology_key(row: Mapping[str, Any]) -> str:
    return str(audit.first_text(row, audit.EXIT_TS_KEYS)[1] or audit.first_text(row, audit.ENTRY_TS_KEYS)[1] or audit.event_id(row))


def bar_r_extremes(bar: Mapping[str, Any], price_mode: str, entry: float, risk: float, side: str) -> tuple[float, float, float]:
    open_price = finite(bar.get("open"))
    close_price = finite(bar.get("close"))
    high_price = finite(bar.get("high"))
    low_price = finite(bar.get("low"))
    if None in {open_price, close_price, high_price, low_price}:
        raise RuntimeError("BAR_OHLC_INVALID")
    open_r = signed_r(float(open_price), entry, risk, side)
    if price_mode == "close":
        point = signed_r(float(close_price), entry, risk, side)
        return open_r, point, point
    if price_mode == "open_close":
        close_r = signed_r(float(close_price), entry, risk, side)
        return open_r, max(open_r, close_r), min(open_r, close_r)
    if price_mode == "high_low":
        if side == "long":
            favorable = signed_r(float(high_price), entry, risk, side)
            adverse = signed_r(float(low_price), entry, risk, side)
        else:
            favorable = signed_r(float(low_price), entry, risk, side)
            adverse = signed_r(float(high_price), entry, risk, side)
        return open_r, favorable, adverse
    raise RuntimeError(f"UNKNOWN_PRICE_MODE:{price_mode}")


def simulate_trailing(path: Any, price_mode: str, entry: float, risk: float, side: str, trail_distance_r: float) -> dict[str, Any]:
    active = False
    watermark_r: float | None = None
    stop_r: float | None = None
    activation_bar: int | None = None
    exit_bar: int | None = None
    exit_r: float | None = None
    for offset, (_, bar) in enumerate(path.iterrows()):
        open_r, favorable_r, adverse_r = bar_r_extremes(bar, price_mode, entry, risk, side)
        if active and stop_r is not None:
            if open_r <= stop_r:
                exit_r = open_r
                exit_bar = offset
                break
            if adverse_r <= stop_r:
                exit_r = stop_r
                exit_bar = offset
                break
            watermark_r = max(float(watermark_r), favorable_r)
            stop_r = watermark_r - trail_distance_r
            continue
        if favorable_r >= ACTIVATION_R:
            active = True
            activation_bar = offset
            watermark_r = favorable_r
            stop_r = watermark_r - trail_distance_r
    return {
        "activated": active,
        "activation_bar": activation_bar,
        "trailing_exit": exit_r is not None,
        "trailing_exit_bar": exit_bar,
        "trailing_exit_gross_R": exit_r,
        "same_bar_new_stop_execution_allowed": False,
        "adverse_first_existing_stop": True,
    }


def candidate_pass(base: Mapping[str, Any], candidate: Mapping[str, Any], delta: Mapping[str, Any]) -> bool:
    base_pf = finite(base.get("profit_factor"))
    candidate_pf = finite(candidate.get("profit_factor"))
    return (
        float(delta["delta_net_R"]) > 0
        and float(delta["delta_max_drawdown_R"]) >= 0
        and candidate_pf is not None
        and base_pf is not None
        and candidate_pf > base_pf
        and int(candidate.get("trade_count") or 0) == int(base.get("trade_count") or 0)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    base_safety = {
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    if reconciliation.get("state") != "PASS_EMA_PATH_SEMANTICS_RECONCILED" or reconciliation.get("entry_known_exact_match") is not True:
        receipt = {
            "schema_version": SCHEMA,
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": "HOLD_EMA_TRAILING_BLOCKED_BY_PATH_SEMANTICS",
            "strategy_id": audit.STRATEGY_ID,
            "reconciliation_state": reconciliation.get("state"),
            "reconciliation_blockers": reconciliation.get("blockers"),
            "tournament_started": False,
            "next": "TRACE_EXACT_MFE_MAE_UPDATE_ORDER",
            **base_safety,
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0

    contract = reconciliation.get("best_entry_known_candidate")
    if not isinstance(contract, Mapping):
        raise RuntimeError("ENTRY_KNOWN_CONTRACT_MISSING")
    price_mode = str(contract["price_mode"])
    slice_mode = str(contract["slice_mode"])
    risk_mode = str(contract["risk_mode"])

    rows = audit.read_rows(args.terminal_root / "trades.jsonl.gz")
    if len(rows) != EXPECTED_TRADES:
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")
    engine = load_module(args.engine, "zel_ema_trailing_engine")
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
    if not isinstance(manifest, Mapping):
        raise RuntimeError("DATA_MANIFEST_INVALID")
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in list(manifest.get("files") or []):
        if isinstance(file_row, Mapping):
            file_map[(str(file_row.get("window_id") or file_row.get("window") or "unknown"), str(file_row.get("symbol") or "").upper())] = file_row
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(audit.window_id(row), audit.symbol(row))].append(row)

    baseline_values: dict[str, list[tuple[str, float]]] = defaultdict(list)
    candidate_values: dict[float, dict[str, list[tuple[str, float]]]] = {
        distance: defaultdict(list) for distance in TRAIL_DISTANCE_CANDIDATES_R
    }
    activated_counts: dict[float, dict[str, int]] = {distance: defaultdict(int) for distance in TRAIL_DISTANCE_CANDIDATES_R}
    exit_counts: dict[float, dict[str, int]] = {distance: defaultdict(int) for distance in TRAIL_DISTANCE_CANDIDATES_R}
    cost_adjustments: list[float] = []
    failures: list[str] = []

    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            failures.extend("LANE_FILE_MISSING" for _ in lane_rows)
            continue
        frame = engine.frame_from_csv(audit.resolve_file(args.data_root, file_row))
        index_by_timestamp: dict[int, int] = {}
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch = audit.parse_timestamp(engine.pd, value)
            if epoch is not None:
                index_by_timestamp[epoch] = index
        for row in lane_rows:
            trade_id = audit.event_id(row)
            window = audit.window_id(row)
            entry = audit.first_number(row, audit.ENTRY_PRICE_KEYS)[1]
            exit_px = audit.first_number(row, audit.EXIT_PRICE_KEYS)[1]
            original_r = audit.first_number(row, audit.REALIZED_R_KEYS)[1]
            trade_side = audit.normalized_side(row)
            entry_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.ENTRY_TS_KEYS)[1])
            exit_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.EXIT_TS_KEYS)[1])
            entry_index = index_by_timestamp.get(entry_epoch) if entry_epoch is not None else None
            exit_index = index_by_timestamp.get(exit_epoch) if exit_epoch is not None else None
            if None in {entry, exit_px, original_r, entry_index, exit_index} or trade_side not in {"long", "short"} or int(exit_index) < int(entry_index):
                failures.append("TRADE_CONTRACT_INVALID")
                continue
            risks = reconcile.risk_candidates(row, float(entry), float(exit_px))
            risk = risks.get(risk_mode)
            if risk is None or risk <= 0:
                failures.append("PINNED_RISK_MODE_MISSING")
                continue
            path = reconcile.slice_frame(frame, int(entry_index), int(exit_index), slice_mode)
            if path.empty:
                failures.append("PINNED_PATH_EMPTY")
                continue
            gross_original_r = signed_r(float(exit_px), float(entry), float(risk), trade_side)
            cost_adjustment = float(original_r) - gross_original_r
            cost_adjustments.append(cost_adjustment)
            order_key = chronology_key(row) + "|" + trade_id
            baseline_values[window].append((order_key, float(original_r)))
            baseline_values["all"].append((order_key, float(original_r)))
            for distance in TRAIL_DISTANCE_CANDIDATES_R:
                simulation = simulate_trailing(path, price_mode, float(entry), float(risk), trade_side, float(distance))
                if simulation["activated"]:
                    activated_counts[distance][window] += 1
                    activated_counts[distance]["all"] += 1
                if simulation["trailing_exit"]:
                    exit_counts[distance][window] += 1
                    exit_counts[distance]["all"] += 1
                    candidate_r = float(simulation["trailing_exit_gross_R"]) + cost_adjustment
                else:
                    candidate_r = float(original_r)
                candidate_values[distance][window].append((order_key, candidate_r))
                candidate_values[distance]["all"].append((order_key, candidate_r))

    baseline_metrics = {window: values_metrics(baseline_values[window]) for window in (*WINDOWS, "all")}
    tournament: list[dict[str, Any]] = []
    for distance in TRAIL_DISTANCE_CANDIDATES_R:
        metrics_by_window = {window: values_metrics(candidate_values[distance][window]) for window in (*WINDOWS, "all")}
        deltas = {window: metric_delta(baseline_metrics[window], metrics_by_window[window]) for window in (*WINDOWS, "all")}
        w1_pass = candidate_pass(baseline_metrics["1m_w1"], metrics_by_window["1m_w1"], deltas["1m_w1"])
        tournament.append({
            "candidate_id": f"ACT0.50_TRAIL{distance:.2f}",
            "activation_R": ACTIVATION_R,
            "trail_distance_R": distance,
            "price_mode": price_mode,
            "slice_mode": slice_mode,
            "risk_mode": risk_mode,
            "w1_pass": w1_pass,
            "metrics": metrics_by_window,
            "delta": deltas,
            "activated_counts": dict(activated_counts[distance]),
            "trailing_exit_counts": dict(exit_counts[distance]),
            "same_bar_new_stop_execution_allowed": False,
            "selection_scope": "W1_ONLY",
            "production_applied": False,
        })
    eligible = [row for row in tournament if row["w1_pass"]]
    eligible.sort(key=lambda row: (-float(row["delta"]["1m_w1"]["delta_net_R"]), -float(row["delta"]["1m_w1"]["delta_max_drawdown_R"]), float(row["trail_distance_R"])))
    selected = eligible[0] if eligible else None

    holdout_pass = False
    if selected is not None:
        holdout_pass = all(
            candidate_pass(baseline_metrics[window], selected["metrics"][window], selected["delta"][window])
            for window in ("1m_w2", "1m_w3")
        ) and candidate_pass(baseline_metrics["all"], selected["metrics"]["all"], selected["delta"]["all"])

    blockers: list[str] = []
    if failures:
        blockers.append("TRAILING_PATH_CONTRACT_INCOMPLETE")
    if selected is None:
        blockers.append("NO_W1_TRAILING_CANDIDATE_PASS")
    elif not holdout_pass:
        blockers.append("FROZEN_TRAILING_POLICY_FAILED_W2_W3")
    state = "PASS_EMA_TRAILING_COUNTERFACTUAL_NONOVERLAP" if not blockers else "HOLD_EMA_TRAILING_COUNTERFACTUAL_REJECTED"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": audit.STRATEGY_ID,
        "trade_count": len(rows),
        "path_semantics_contract": dict(contract),
        "activation_R_fixed": ACTIVATION_R,
        "trail_distance_candidates_R": list(TRAIL_DISTANCE_CANDIDATES_R),
        "selection_window": "1m_w1",
        "holdout_windows": ["1m_w2", "1m_w3"],
        "same_bar_policy": "existing_stop_adverse_first_then_update_watermark_for_next_bar",
        "baseline_metrics": baseline_metrics,
        "tournament": tournament,
        "selected_candidate": selected,
        "holdout_pass": holdout_pass,
        "cost_adjustment_mean_R": sum(cost_adjustments) / len(cost_adjustments) if cost_adjustments else None,
        "cost_adjustment_min_R": min(cost_adjustments) if cost_adjustments else None,
        "cost_adjustment_max_R": max(cost_adjustments) if cost_adjustments else None,
        "failure_count": len(failures),
        "failure_counts": dict(__import__('collections').Counter(failures)),
        "blockers": blockers,
        "research_candidate_selected": selected is not None,
        "frozen_before_holdout": selected is not None,
        "production_applied": False,
        "next": "GEMINI_RED_TEAM_EMA_TRAILING_SURVIVOR" if not blockers else "REJECT_TRAILING_AND_TEST_IMMEDIATE_FAIL_AXIS",
        **base_safety,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "selected": selected["candidate_id"] if selected else None, "holdout_pass": holdout_pass, "blockers": blockers, "next": receipt["next"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
