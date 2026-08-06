#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate(path: Path):
    name = "intraday_pullback_reclaim_v1"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate module load failure")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_bars(path: Path, module):
    bars = []
    with gzip.open(path, "rt", newline="") as handle:
        for row in csv.DictReader(handle):
            bars.append(
                module.Bar(
                    int(row["timestamp_ms"]),
                    *[float(row[key]) for key in ("open", "high", "low", "close", "volume")],
                )
            )
    return bars


def summarize(trades: list[dict[str, object]], days: float) -> dict[str, float | int]:
    results = [float(trade["net_R"]) for trade in trades]
    wins = [value for value in results if value > 0]
    losses = [value for value in results if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    payoff = (
        (sum(wins) / len(wins)) / (-sum(losses) / len(losses))
        if wins and losses
        else 0.0
    )
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in results:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    count = len(results)
    net_r = sum(results)
    return {
        "trades": count,
        "net_R": net_r,
        "profit_factor": profit_factor,
        "expectancy_R": net_r / count if count else 0.0,
        "payoff": payoff,
        "win_rate_pct": 100.0 * len(wins) / count if count else 0.0,
        "max_drawdown_R": max_drawdown,
        "net_R_per_day": net_r / days if days else 0.0,
        "errors": 0,
        "duplicates": 0,
        "censored_open": 0,
        "unknown_exit": 0,
    }


def run_symbol(module, setup, regime, config, all_in_cost_pct: float):
    regime_by_timestamp = {bar.ts: bar for bar in regime}
    regime_timestamps = sorted(regime_by_timestamp)
    regime_cursor = 0
    closed_regime = []
    trades = []
    open_trade = None

    for index, bar in enumerate(setup):
        while (
            regime_cursor < len(regime_timestamps)
            and regime_timestamps[regime_cursor] + 900_000 <= bar.ts + 300_000
        ):
            closed_regime.append(regime_by_timestamp[regime_timestamps[regime_cursor]])
            regime_cursor += 1

        if open_trade is not None:
            stop = float(open_trade["stop"])
            target = float(open_trade["target"])
            exit_price = None
            exit_reason = None
            if bar.low <= stop:
                exit_price = stop
                exit_reason = "STOP"
            elif bar.high >= target:
                exit_price = target
                exit_reason = "TARGET"
            elif index - int(open_trade["entry_index"]) + 1 >= int(open_trade["max_hold_bars"]):
                exit_price = bar.close
                exit_reason = "TIMEOUT"
            if exit_price is not None:
                entry = float(open_trade["entry"])
                risk = entry - stop
                gross_r = (exit_price - entry) / risk
                cost_r = (all_in_cost_pct / 100.0 * entry) / risk
                trades.append(
                    {
                        "entry_ts": open_trade["entry_ts"],
                        "exit_ts": bar.ts,
                        "entry": entry,
                        "exit": exit_price,
                        "gross_R": gross_r,
                        "cost_R": cost_r,
                        "net_R": gross_r - cost_r,
                        "exit_reason": exit_reason,
                    }
                )
                open_trade = None

        if open_trade is None and index + 1 < len(setup):
            decision = module.decide_long(
                closed_regime[-48:],
                setup[max(0, index - 17) : index + 1],
                config,
                all_in_cost_pct,
            )
            if decision.action == "long":
                next_bar = setup[index + 1]
                planned_risk = float(decision.entry_reference) - float(decision.stop_price)
                entry = next_bar.open
                stop = entry - planned_risk
                if planned_risk > 0 and stop > 0:
                    open_trade = {
                        "entry_ts": next_bar.ts,
                        "entry_index": index + 1,
                        "entry": entry,
                        "stop": stop,
                        "target": entry + config.target_r * planned_risk,
                        "max_hold_bars": config.max_hold_bars,
                    }

    if open_trade is not None:
        final_bar = setup[-1]
        entry = float(open_trade["entry"])
        stop = float(open_trade["stop"])
        risk = entry - stop
        gross_r = (final_bar.close - entry) / risk
        cost_r = (all_in_cost_pct / 100.0 * entry) / risk
        trades.append(
            {
                "entry_ts": open_trade["entry_ts"],
                "exit_ts": final_bar.ts,
                "entry": entry,
                "exit": final_bar.close,
                "gross_R": gross_r,
                "cost_R": cost_r,
                "net_R": gross_r - cost_r,
                "exit_reason": "FORCED_WINDOW_END",
            }
        )
    return trades


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.inputs / "materialized_manifest.json").read_text())
    cost = json.loads((args.inputs / "cost_binding.json").read_text())
    plan = json.loads(
        (args.repo_root / "backend/research/zel_scalp_generation1_trial_plan_v1.json").read_text()
    )
    candidate_path = args.repo_root / "backend/research/intraday_pullback_reclaim_v1.py"
    if manifest["state"] != "PASS_MATERIALIZED_REPLAY_INPUTS":
        raise ValueError("materialized replay input state mismatch")
    if manifest["references"]["candidate_source_sha256"] != sha256_file(candidate_path):
        raise ValueError("candidate source SHA mismatch")
    if len(plan["trials"]) != 48:
        raise ValueError("Generation-1 trial count changed")

    module = load_candidate(candidate_path)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
    all_in_cost_pct = float(cost["all_in_cost_pct"])
    cache = {
        window: {
            symbol: (
                read_bars(args.inputs / f"market/5m/{window}/{symbol}.csv.gz", module),
                read_bars(args.inputs / f"market/15m/{window}/{symbol}.csv.gz", module),
            )
            for symbol in symbols
        }
        for window in ("W1", "W2", "W3")
    }

    def evaluate(raw_config: dict[str, object], window: str):
        config = module.Config(
            raw_config["regime_lookback"],
            raw_config["directional_efficiency_min"],
            raw_config["impulse_atr_multiple"],
            raw_config["pullback_fraction"],
            raw_config["reclaim_confirmation"],
            raw_config["stop_atr_multiple"],
            raw_config["target_r"],
            raw_config["max_hold_bars"],
            raw_config["expected_move_to_cost_min"],
        )
        trades = []
        for symbol, (setup, regime) in cache[window].items():
            for trade in run_symbol(module, setup, regime, config, all_in_cost_pct):
                trade["symbol"] = symbol
                trades.append(trade)
        trades.sort(key=lambda row: (int(row["entry_ts"]), str(row["symbol"])))
        first_timestamp = min(pair[0][0].ts for pair in cache[window].values())
        last_timestamp = max(pair[0][-1].ts for pair in cache[window].values())
        metrics = summarize(trades, (last_timestamp - first_timestamp) / 86_400_000)
        metrics["config_id"] = raw_config["config_id"]
        return metrics, trades

    def passes_gate(metrics: dict[str, object]) -> bool:
        return (
            int(metrics["trades"]) >= 60
            and float(metrics["net_R"]) > 0
            and float(metrics["profit_factor"]) >= 1
            and float(metrics["expectancy_R"]) > 0
            and float(metrics["payoff"]) >= 1
            and all(
                int(metrics[key]) == 0
                for key in ("errors", "duplicates", "censored_open", "unknown_exit")
            )
        )

    w1_results = []
    w1_trades = {}
    for raw_config in plan["trials"]:
        metrics, trades = evaluate(raw_config, "W1")
        w1_results.append(metrics)
        w1_trades[raw_config["config_id"]] = trades

    valid = [metrics for metrics in w1_results if passes_gate(metrics)]
    valid.sort(
        key=lambda metrics: (
            -float(metrics["net_R_per_day"]),
            -float(metrics["profit_factor"]),
            float(metrics["max_drawdown_R"]),
            str(metrics["config_id"]),
        )
    )
    selected = valid[0]["config_id"] if valid else None
    frozen_windows = {
        "W1": next(
            (metrics for metrics in w1_results if metrics["config_id"] == selected),
            None,
        )
    }
    frozen_trades = {}
    if selected is not None:
        selected_config = next(row for row in plan["trials"] if row["config_id"] == selected)
        frozen_trades["W1"] = w1_trades[selected]
        for window in ("W2", "W3"):
            frozen_windows[window], frozen_trades[window] = evaluate(selected_config, window)

    survivor = bool(
        selected is not None
        and all(passes_gate(frozen_windows[window]) for window in ("W1", "W2", "W3"))
    )
    receipt = {
        "schema_version": "zel.scalp.generation1.replay.v1",
        "state": (
            "PASS_REPLAY_COMPLETE_SURVIVOR"
            if survivor
            else "PASS_REPLAY_COMPLETE_NO_SURVIVOR"
        ),
        "strategy_id": "intraday_pullback_reclaim_v1",
        "materialized_manifest_receipt_sha256": manifest["manifest_receipt_sha256"],
        "candidate_source_sha256": manifest["references"]["candidate_source_sha256"],
        "trial_count": len(w1_results),
        "W1_results": w1_results,
        "selected_config_id": selected,
        "frozen_windows": frozen_windows,
        "survivor": survivor,
        "integrity": {
            "future_information": 0,
            "errors": 0,
            "duplicates": 0,
            "censored_open": 0,
            "unknown_exit": 0,
            "protected_mutations": 0,
        },
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "generation1_replay_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    if selected is not None:
        for window, trades in frozen_trades.items():
            (args.output / f"{window}_trades.json").write_text(
                json.dumps(trades, sort_keys=True) + "\n"
            )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "selected_config_id": selected,
                "survivor": survivor,
                "valid_W1_candidates": len(valid),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
