from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_ema_path_semantics_reconciliation_v1 as reconcile
import zel_ema_ribbon_intratrade_path_audit_v1 as audit
import zel_ema_trailing_counterfactual_v1 as common

VERSION = "ZEL_EMA_TIME_STOP_COUNTERFACTUAL_V1"
SCHEMA = "zel.ema.time_stop_counterfactual.receipt.v1"
EXPECTED_TRADES = 424
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")
TIME_STOP_BARS = (5, 10, 15, 30, 60, 120)
EXPECTED_CONTRACT = "high_low|exclude_entry|risk_usdt_div_quantity"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    contract = reconciliation.get("best_entry_known_candidate")
    if (
        reconciliation.get("state") != "PASS_EMA_PATH_SEMANTICS_RECONCILED"
        or reconciliation.get("entry_known_exact_match") is not True
        or not isinstance(contract, Mapping)
        or contract.get("candidate_id") != EXPECTED_CONTRACT
    ):
        raise RuntimeError("EXACT_PATH_CONTRACT_NOT_READY")
    risk_mode = str(contract["risk_mode"])

    rows = audit.read_rows(args.terminal_root / "trades.jsonl.gz")
    if len(rows) != EXPECTED_TRADES:
        raise RuntimeError(f"TRADE_COUNT_MISMATCH:{len(rows)}")
    engine = common.load_module(args.engine, "zel_ema_time_stop_engine")
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
    candidate_values: dict[int, dict[str, list[tuple[str, float]]]] = {
        bars: defaultdict(list) for bars in TIME_STOP_BARS
    }
    triggered_counts: dict[int, dict[str, int]] = {
        bars: defaultdict(int) for bars in TIME_STOP_BARS
    }
    cost_adjustments: list[float] = []
    original_holding_bars: list[int] = []
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
            side = audit.normalized_side(row)
            entry_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.ENTRY_TS_KEYS)[1])
            exit_epoch = audit.parse_timestamp(engine.pd, audit.first_text(row, audit.EXIT_TS_KEYS)[1])
            entry_index = index_by_timestamp.get(entry_epoch) if entry_epoch is not None else None
            exit_index = index_by_timestamp.get(exit_epoch) if exit_epoch is not None else None
            if None in {entry, exit_px, original_r, entry_index, exit_index} or side not in {"long", "short"} or int(exit_index) < int(entry_index):
                failures.append("TRADE_CONTRACT_INVALID")
                continue
            risks = reconcile.risk_candidates(row, float(entry), float(exit_px))
            risk = risks.get(risk_mode)
            if risk is None or risk <= 0:
                failures.append("PINNED_RISK_MODE_MISSING")
                continue
            gross_original_r = common.signed_r(float(exit_px), float(entry), float(risk), side)
            cost_adjustment = float(original_r) - gross_original_r
            cost_adjustments.append(cost_adjustment)
            holding_bars = int(exit_index) - int(entry_index)
            original_holding_bars.append(holding_bars)
            order_key = common.chronology_key(row) + "|" + trade_id
            baseline_values[window].append((order_key, float(original_r)))
            baseline_values["all"].append((order_key, float(original_r)))

            for bars in TIME_STOP_BARS:
                target_index = int(entry_index) + int(bars)
                if target_index < int(exit_index):
                    close_px = common.finite(frame["close"].iloc[target_index])
                    if close_px is None:
                        failures.append("TIME_STOP_CLOSE_INVALID")
                        candidate_r = float(original_r)
                    else:
                        candidate_r = common.signed_r(float(close_px), float(entry), float(risk), side) + cost_adjustment
                        triggered_counts[bars][window] += 1
                        triggered_counts[bars]["all"] += 1
                else:
                    candidate_r = float(original_r)
                candidate_values[bars][window].append((order_key, candidate_r))
                candidate_values[bars]["all"].append((order_key, candidate_r))

    baseline_metrics = {window: common.values_metrics(baseline_values[window]) for window in (*WINDOWS, "all")}
    tournament: list[dict[str, Any]] = []
    for bars in TIME_STOP_BARS:
        metrics = {window: common.values_metrics(candidate_values[bars][window]) for window in (*WINDOWS, "all")}
        deltas = {window: common.metric_delta(baseline_metrics[window], metrics[window]) for window in (*WINDOWS, "all")}
        w1_pass = common.candidate_pass(baseline_metrics["1m_w1"], metrics["1m_w1"], deltas["1m_w1"])
        tournament.append({
            "candidate_id": f"TIME_STOP_{bars}B",
            "time_stop_bars": bars,
            "w1_pass": w1_pass,
            "metrics": metrics,
            "delta": deltas,
            "triggered_counts": dict(triggered_counts[bars]),
            "selection_scope": "W1_ONLY",
            "exit_price": "target_bar_close",
            "original_exit_preserved_when_earlier_or_equal": True,
            "production_applied": False,
        })

    eligible = [row for row in tournament if row["w1_pass"]]
    eligible.sort(key=lambda row: (
        -float(row["delta"]["1m_w1"]["delta_net_R"]),
        -float(row["delta"]["1m_w1"]["delta_max_drawdown_R"]),
        int(row["time_stop_bars"]),
    ))
    selected = eligible[0] if eligible else None
    holdout_pass = False
    if selected is not None:
        holdout_pass = all(
            common.candidate_pass(baseline_metrics[window], selected["metrics"][window], selected["delta"][window])
            for window in ("1m_w2", "1m_w3", "all")
        )

    blockers: list[str] = []
    if failures:
        blockers.append("TIME_STOP_PATH_CONTRACT_INCOMPLETE")
    if selected is None:
        blockers.append("NO_W1_TIME_STOP_CANDIDATE_PASS")
    elif not holdout_pass:
        blockers.append("FROZEN_TIME_STOP_FAILED_W2_W3")
    state = "PASS_EMA_TIME_STOP_COUNTERFACTUAL" if not blockers else "HOLD_EMA_TIME_STOP_COUNTERFACTUAL_REJECTED"

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": audit.STRATEGY_ID,
        "trade_count": len(rows),
        "path_semantics_contract": dict(contract),
        "time_stop_candidates_bars": list(TIME_STOP_BARS),
        "selection_window": "1m_w1",
        "holdout_windows": ["1m_w2", "1m_w3"],
        "baseline_metrics": baseline_metrics,
        "tournament": tournament,
        "selected_candidate": selected,
        "holdout_pass": holdout_pass,
        "holding_bars_min": min(original_holding_bars) if original_holding_bars else None,
        "holding_bars_max": max(original_holding_bars) if original_holding_bars else None,
        "holding_bars_mean": sum(original_holding_bars) / len(original_holding_bars) if original_holding_bars else None,
        "cost_adjustment_mean_R": sum(cost_adjustments) / len(cost_adjustments) if cost_adjustments else None,
        "failure_count": len(failures),
        "failure_counts": dict(Counter(failures)),
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "GEMINI_RED_TEAM_TIME_STOP_SURVIVOR" if not blockers else "RETIRE_OR_REBUILD_EMA_ENTRY_LOGIC",
    }
    receipt["receipt_sha256"] = common.stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "selected": (selected or {}).get("candidate_id"), "holdout_pass": holdout_pass, "blockers": blockers, "next": receipt["next"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
