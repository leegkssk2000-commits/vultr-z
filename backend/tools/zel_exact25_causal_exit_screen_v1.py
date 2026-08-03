from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import pandas as pd

VERSION = "ZEL_EXACT25_CAUSAL_EXIT_SCREEN_V1"
SCHEMA = "zel.exact25.causal_exit_screen.receipt.v1"
ECONOMIC_FIELDS = (
    "event_id", "position_id", "strategy_id", "owner_sha256", "symbol",
    "interval", "data_interval", "window_id", "side", "entry_ts", "exit_ts",
    "entry_price", "exit_price", "qty", "original_qty", "initial_risk_usdt",
    "gross_pnl_usdt", "realized_R", "realized_R_including_funding_estimate",
    "fee", "slippage", "funding_pnl_estimate_usdt", "funding_event_count",
    "exit_reason", "reason", "MFE_R", "MAE_R", "time_exposure_min",
    "add_count", "partial_count", "data_source_sha256",
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalized(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 12) if math.isfinite(number) else None
    return value


def economic_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {key: normalized(row.get(key)) for key in ECONOMIC_FIELDS if key in row}
        for row in rows
    ]
    payload.sort(
        key=lambda row: (
            str(row.get("event_id") or ""),
            str(row.get("entry_ts") or ""),
            str(row.get("exit_ts") or ""),
        )
    )
    return stable_sha(payload)


def terminal_rows(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or "") == strategy_id:
                rows.append(row)
    return rows


def reason_text(value: Any) -> str:
    return str(value or "unknown").lower().replace("-", "_").replace(" ", "_")


def is_hard_risk_reason(reason: Any) -> bool:
    text = reason_text(reason)
    exact = {
        "sl", "stop_loss", "hard_stop", "hard_stop_loss", "loss_cap",
        "liquidation", "liquidation_guard", "risk_stop", "emergency_stop",
    }
    return text in exact or any(
        token in text
        for token in ("liquidat", "loss_cap", "hard_stop", "stop_loss")
    )


def elapsed_min(engine: Any, position: Mapping[str, Any], now_epoch: float) -> float:
    entry_epoch = engine.parse_epoch(position.get("entry_ts"))
    if entry_epoch is None:
        return 0.0
    return max(0.0, (float(now_epoch) - float(entry_epoch)) / 60.0)


def running_mfe_R(position: Mapping[str, Any]) -> float | None:
    for key in ("MFE_R", "mfe_R", "mfe_r", "max_favorable_R"):
        value = finite(position.get(key))
        if value is not None:
            return value
    return None


def suppress_soft_exit(
    engine: Any,
    position: Mapping[str, Any],
    now_epoch: float,
    reason: Any,
    config: Mapping[str, Any],
) -> bool:
    if is_hard_risk_reason(reason):
        return False
    mode = str(config["mode"])
    hold = elapsed_min(engine, position, now_epoch) < float(
        config.get("minimum_hold_min") or 0.0
    )
    threshold = float(config.get("mfe_arm_R") or 0.0)
    mfe = running_mfe_R(position)
    not_armed = threshold > 0.0 and (mfe is None or mfe < threshold)
    if mode == "SOFT_MIN_HOLD":
        return hold
    if mode == "SOFT_MFE_ARM":
        return not_armed
    if mode == "SOFT_MIN_HOLD_AND_MFE_ARM":
        return hold or not_armed
    raise RuntimeError(f"UNKNOWN_EXIT_CONTROL_MODE:{mode}")


def payoff_metrics(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(engine.metrics(rows, "realized_R_including_funding_estimate"))
    values = [
        float(value)
        for row in rows
        if (value := finite(row.get("realized_R_including_funding_estimate")))
        is not None
    ]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    result.update(
        {
            "average_win_R": average_win,
            "average_loss_abs_R": average_loss_abs,
            "payoff_ratio": (
                average_win / average_loss_abs
                if average_loss_abs
                else (999.0 if average_win else 0.0)
            ),
        }
    )
    return result


def by_window(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for window in ("1m_w1", "1m_w2", "1m_w3"):
        result[window] = payoff_metrics(
            engine, [row for row in rows if str(row.get("window_id")) == window]
        )
    result["all"] = payoff_metrics(engine, rows)
    return result


def close_row(
    engine: Any,
    producer: Any,
    position: Mapping[str, Any],
    exit_price: float,
    exit_ts: str,
    reason: str,
    features: Mapping[str, Any],
    funding_rows: Sequence[Mapping[str, Any]],
    file_row: Mapping[str, Any],
) -> dict[str, Any]:
    funding_pnl, funding_count = engine.funding_estimate(
        position, exit_ts, funding_rows
    )
    row = producer.close_position(
        position,
        exit_price,
        exit_ts,
        reason,
        features,
        engine.FEE_RATE,
        engine.SLIPPAGE_BPS,
    )
    interval = str(file_row["interval"])
    window_id = str(file_row["window_id"])
    row.update(
        {
            "event_id": f"historical.{interval}.{window_id}.{row['event_id']}",
            "position_id": f"historical.{interval}.{window_id}.{row['position_id']}",
            "data_interval": interval,
            "window_id": window_id,
            "data_source_path": file_row["path"],
            "data_source_sha256": file_row["sha256"],
            "historical_oos": True,
            "funding_pnl_estimate_usdt": funding_pnl,
            "funding_event_count": funding_count,
            "realized_R_including_funding_estimate": float(row["realized_R"])
            + funding_pnl / float(row["initial_risk_usdt"]),
            "funding_model": "ENTRY_NOTIONAL_STATIC_ESTIMATE_NON_PROMOTABLE",
            "captured_at": exit_ts,
        }
    )
    return row


def replay_lane_controlled(
    engine: Any,
    producer: Any,
    strategy_id: str,
    owner: Any,
    file_row: Mapping[str, Any],
    frame: pd.DataFrame,
    funding_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    interval = str(file_row["interval"])
    symbol = str(file_row["symbol"])
    window_id = str(file_row["window_id"])
    position: MutableMapping[str, Any] | None = None
    closed: list[dict[str, Any]] = []
    calls = signals = valid_entries = opens = adds = partials = strategy_exits = 0
    suppressed_price_exits = suppressed_strategy_exits = 0
    hard_risk_exits_preserved = 0
    error_count = 0
    error_samples: list[dict[str, Any]] = []
    first_index = max(int(engine.WARMUP_BARS) - 1, 0)

    for index in range(first_index, len(frame)):
        last = frame.iloc[index]
        current = frame.iloc[
            max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1
        ].copy()
        current_price = float(last["close"])
        last_ts_iso = pd.Timestamp(last["timestamp"]).isoformat()
        candle = {key: float(last[key]) for key in ("open", "high", "low", "close")}
        now_epoch = producer.parse_time(last_ts_iso) or 0.0
        features = producer.feature_snapshot(current)
        strategy_state = None

        try:
            if isinstance(position, dict):
                producer.mark_excursions(position, candle)
                price_exit = producer.bar_exit(
                    position, candle, now_epoch, engine.MAX_HOLD_MIN
                )
                if price_exit is not None:
                    exit_price, reason = price_exit
                    if config is not None and suppress_soft_exit(
                        engine, position, now_epoch, reason, config
                    ):
                        price_exit = None
                        suppressed_price_exits += 1
                    else:
                        if is_hard_risk_reason(reason):
                            hard_risk_exits_preserved += 1
                        closed.append(
                            close_row(
                                engine,
                                producer,
                                position,
                                float(exit_price),
                                last_ts_iso,
                                str(reason),
                                features,
                                funding_rows,
                                file_row,
                            )
                        )
                        position = None
                if isinstance(position, dict):
                    strategy_state = {
                        "position_side": position.get("side"),
                        "position_qty": position.get("qty"),
                        "avg_entry": position.get("entry_price"),
                        "add_count": position.get("add_count", 0),
                        "last_add_price": position.get("entry_price"),
                    }

            calls += 1
            result = owner.strategy(
                current, state=strategy_state, risk_action="hold"
            )
            if not isinstance(result, dict):
                raise RuntimeError("STRATEGY_RESULT_NOT_DICT")
            action = str(result.get("action") or "hold").lower()
            if action not in {"hold", "none", "flat"}:
                signals += 1

            if isinstance(position, dict):
                if action in {"reduce", "partial", "partial30"}:
                    if producer.apply_partial_reduce(
                        position,
                        result,
                        current_price,
                        engine.FEE_RATE,
                        engine.SLIPPAGE_BPS,
                    ):
                        partials += 1
                elif action == "add":
                    if producer.apply_add(
                        position,
                        result,
                        current_price,
                        engine.RISK_UNIT_USDT,
                        engine.FEE_RATE,
                        engine.SLIPPAGE_BPS,
                    ):
                        adds += 1
                elif action in {"exit", "close", "stop"}:
                    strategy_reason = str(
                        result.get("reason")
                        or result.get("exit_reason")
                        or f"strategy_{action}"
                    )
                    strategy_hard = action == "stop" or is_hard_risk_reason(
                        strategy_reason
                    )
                    suppress = (
                        config is not None
                        and not strategy_hard
                        and suppress_soft_exit(
                            engine,
                            position,
                            now_epoch,
                            strategy_reason,
                            config,
                        )
                    )
                    if suppress:
                        suppressed_strategy_exits += 1
                    else:
                        if strategy_hard:
                            hard_risk_exits_preserved += 1
                        closed.append(
                            close_row(
                                engine,
                                producer,
                                position,
                                current_price,
                                last_ts_iso,
                                f"strategy_{action}",
                                features,
                                funding_rows,
                                file_row,
                            )
                        )
                        position = None
                        strategy_exits += 1
            else:
                if producer.valid_entry(result, current_price) is not None:
                    valid_entries += 1
                new_position = producer.make_position(
                    strategy_id,
                    str(getattr(owner, "owner_sha256", "")),
                    symbol,
                    interval,
                    result,
                    current,
                    engine.RISK_UNIT_USDT,
                    engine.FEE_RATE,
                    engine.SLIPPAGE_BPS,
                )
                if new_position is not None:
                    new_position["position_id"] = (
                        f"historical.{interval}.{window_id}."
                        f"{new_position['position_id']}"
                    )
                    new_position["event_id"] = new_position["position_id"]
                    position = new_position
                    opens += 1
        except Exception as exc:
            error_count += 1
            if len(error_samples) < 20:
                error_samples.append(
                    {
                        "index": index,
                        "timestamp": last_ts_iso,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                )

    return {
        "strategy_id": strategy_id,
        "owner_sha256": str(getattr(owner, "owner_sha256", "")),
        "symbol": symbol,
        "interval": interval,
        "window_id": window_id,
        "source_path": file_row["path"],
        "source_sha256": file_row["sha256"],
        "bar_count": len(frame),
        "strategy_call_count": calls,
        "signal_count": signals,
        "valid_entry_count": valid_entries,
        "open_count": opens,
        "close_count": len(closed),
        "add_count": adds,
        "partial_count": partials,
        "strategy_exit_count": strategy_exits,
        "suppressed_price_exit_count": suppressed_price_exits,
        "suppressed_strategy_exit_count": suppressed_strategy_exits,
        "hard_risk_exit_preserved_count": hard_risk_exits_preserved,
        "censored_open_at_window_end": 1 if isinstance(position, dict) else 0,
        "error_count": error_count,
        "error_samples": error_samples,
        "closed_rows": closed,
    }


def replay(
    engine: Any,
    source_root: Path,
    data_root: Path,
    strategy_id: str,
    config: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    engine.init_worker(str(source_root), str(data_root), "1m")
    registry = engine._WORKER_REGISTRY
    manifest = engine._WORKER_MANIFEST
    funding = engine._WORKER_FUNDING
    producer = engine._WORKER_PRODUCER
    if not isinstance(registry, Mapping) or strategy_id not in registry:
        raise RuntimeError(f"STRATEGY_NOT_IN_REGISTRY:{strategy_id}")
    owner = registry[strategy_id]
    lanes = []
    for file_row in sorted(
        [
            row
            for row in manifest.get("files", [])
            if isinstance(row, Mapping)
            and row.get("kind") == "market"
            and row.get("interval") == "1m"
        ],
        key=lambda row: (str(row["window_id"]), str(row["symbol"])),
    ):
        frame = engine.frame_from_csv(data_root / str(file_row["path"]))
        lanes.append(
            replay_lane_controlled(
                engine,
                producer,
                strategy_id,
                owner,
                file_row,
                frame,
                funding.get(str(file_row["symbol"]), []),
                config,
            )
        )
    result = {
        "strategy_id": strategy_id,
        "owner_sha256": str(getattr(owner, "owner_sha256", "")),
        "lanes": lanes,
    }
    card, rows = engine.aggregate_strategy(result)
    extra = {
        key: sum(int(lane.get(key) or 0) for lane in lanes)
        for key in (
            "suppressed_price_exit_count",
            "suppressed_strategy_exit_count",
            "hard_risk_exit_preserved_count",
            "error_count",
            "censored_open_at_window_end",
        )
    }
    return card, rows, extra


def gate_window(
    candidate: Mapping[str, Any],
    baseline_count: int,
    minimum_count: int,
    policy: Mapping[str, Any],
) -> tuple[bool, list[str], float]:
    retention = (
        int(candidate.get("sample_count") or 0) / baseline_count * 100.0
        if baseline_count
        else 0.0
    )
    blockers: list[str] = []
    if int(candidate.get("sample_count") or 0) < minimum_count:
        blockers.append("SAMPLE_BELOW_MIN")
    if retention < float(policy["minimum_retention_pct"]):
        blockers.append("RETENTION_BELOW_MIN")
    if float(candidate.get("net_R") or 0.0) <= float(policy["net_R_gt"]):
        blockers.append("NET_R_NOT_POSITIVE")
    if float(candidate.get("profit_factor") or 0.0) < float(
        policy["profit_factor_gte"]
    ):
        blockers.append("PF_BELOW_ONE")
    if float(candidate.get("expectancy_R") or 0.0) <= float(
        policy["expectancy_R_gt"]
    ):
        blockers.append("EXPECTANCY_NOT_POSITIVE")
    if float(candidate.get("payoff_ratio") or 0.0) < float(
        policy["payoff_ratio_gte"]
    ):
        blockers.append("PAYOFF_BELOW_ONE")
    return not blockers, blockers, retention


def run(
    policy: Mapping[str, Any],
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
) -> dict[str, Any]:
    strategy_id = str(policy["strategy_id"])
    engine = load_module(
        engine_path, f"zel_causal_exit_engine_{os.getpid()}"
    )
    baseline_card, baseline_rows, baseline_extra = replay(
        engine, source_root, data_root, strategy_id, None
    )
    immutable_rows = terminal_rows(
        terminal_root / "trades.jsonl.gz", strategy_id
    )
    report = read_json(terminal_root / "report.json")
    terminal_card = next(
        row
        for row in report.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id") == strategy_id
    )
    baseline_metrics = baseline_card[
        "closed_metrics_including_funding_estimate"
    ]
    terminal_metrics = terminal_card[
        "closed_metrics_including_funding_estimate"
    ]
    parity = {
        "trade_count": len(baseline_rows) == len(immutable_rows),
        "economic_digest": economic_digest(baseline_rows)
        == economic_digest(immutable_rows),
        "net_R": abs(
            float(baseline_metrics.get("net_R") or 0.0)
            - float(terminal_metrics.get("net_R") or 0.0)
        )
        <= 1e-9,
        "profit_factor": abs(
            float(baseline_metrics.get("profit_factor") or 0.0)
            - float(terminal_metrics.get("profit_factor") or 0.0)
        )
        <= 1e-9,
        "max_drawdown_R": abs(
            float(baseline_metrics.get("max_drawdown_R") or 0.0)
            - float(terminal_metrics.get("max_drawdown_R") or 0.0)
        )
        <= 1e-9,
        "errors_zero": baseline_extra["error_count"] == 0,
        "censored_zero": baseline_extra["censored_open_at_window_end"] == 0,
    }
    baseline_windows = by_window(engine, baseline_rows)
    candidates = []
    gate_policy = policy["positive_gate"]
    for config in policy["candidate_configs"]:
        card, rows, extra = replay(
            engine, source_root, data_root, strategy_id, config
        )
        windows = by_window(engine, rows)
        w1_ok, w1_blockers, w1_retention = gate_window(
            windows["1m_w1"],
            int(baseline_windows["1m_w1"]["sample_count"] or 0),
            int(gate_policy["minimum_w1_trade_count"]),
            gate_policy,
        )
        operational_ok = (
            extra["error_count"] <= int(gate_policy["error_count_max"])
            and extra["censored_open_at_window_end"]
            <= int(gate_policy["censored_open_count_max"])
            and (
                extra["suppressed_price_exit_count"]
                + extra["suppressed_strategy_exit_count"]
            )
            > 0
        )
        candidates.append(
            {
                "config": dict(config),
                "config_sha256": stable_sha(config),
                "metrics": windows,
                "counters": extra,
                "economic_digest_sha256": economic_digest(rows),
                "w1_pass": w1_ok and operational_ok,
                "w1_blockers": w1_blockers,
                "w1_retention_pct": w1_retention,
            }
        )
    eligible = [row for row in candidates if row["w1_pass"]]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["metrics"]["1m_w1"].get("net_R") or 0.0),
            float(row["metrics"]["1m_w1"].get("profit_factor") or 0.0),
            float(row["metrics"]["1m_w1"].get("payoff_ratio") or 0.0),
        ),
        default=None,
    )
    confirmation: dict[str, Any] = {}
    survivor = False
    if selected is not None:
        all_pass = True
        for window in ("1m_w2", "1m_w3"):
            passed, blockers, retention = gate_window(
                selected["metrics"][window],
                int(baseline_windows[window]["sample_count"] or 0),
                int(gate_policy["minimum_confirmation_trade_count"]),
                gate_policy,
            )
            confirmation[window] = {
                "pass": passed,
                "blockers": blockers,
                "retention_pct": retention,
                "baseline": baseline_windows[window],
                "candidate": selected["metrics"][window],
            }
            all_pass = all_pass and passed
        overall_pass, overall_blockers, overall_retention = gate_window(
            selected["metrics"]["all"],
            int(baseline_windows["all"]["sample_count"] or 0),
            int(gate_policy["minimum_confirmation_trade_count"]),
            gate_policy,
        )
        confirmation["all"] = {
            "pass": overall_pass,
            "blockers": overall_blockers,
            "retention_pct": overall_retention,
            "baseline": baseline_windows["all"],
            "candidate": selected["metrics"]["all"],
        }
        all_pass = all_pass and overall_pass
        survivor = all(parity.values()) and all_pass

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_CAUSAL_EXIT_SCREEN_COMPLETE",
        "strategy_id": strategy_id,
        "axis_id": policy["axis_id"],
        "parent_route": policy["parent_route"],
        "baseline_parity": parity,
        "baseline": baseline_windows,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_config": selected["config"] if selected else None,
        "selected_config_sha256": (
            selected["config_sha256"] if selected else None
        ),
        "confirmation": confirmation,
        "survivor": survivor,
        "survivor_state": (
            "PASS_POSITIVE_W1_W2_W3_CAUSAL_EXIT_SURVIVOR"
            if survivor
            else "HOLD_NO_POSITIVE_CAUSAL_EXIT_SURVIVOR"
        ),
        "hard_risk_exit_always_preserved": True,
        "oracle_future_mfe_used": False,
        "position_running_mfe_only": True,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "SEAL_RESEARCH_HOLDBACK_AND_INTERACTION_TEST"
            if survivor
            else "ADVANCE_NEXT_CAUSAL_EXIT_AXIS_OR_STRATEGY"
        ),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    assert is_hard_risk_reason("stop_loss") is True
    assert is_hard_risk_reason("time_stop") is False
    position = {"entry_ts": "2026-01-01T00:00:00+00:00", "MFE_R": 0.05}
    class Engine:
        @staticmethod
        def parse_epoch(value: Any) -> float:
            return pd.Timestamp(value).timestamp()
    config = {
        "mode": "SOFT_MIN_HOLD_AND_MFE_ARM",
        "minimum_hold_min": 5.0,
        "mfe_arm_R": 0.1,
    }
    assert suppress_soft_exit(
        Engine, position, pd.Timestamp("2026-01-01T00:03:00Z").timestamp(),
        "take_profit", config
    ) is True
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.policy,
        args.engine,
        args.source_root,
        args.data_root,
        args.terminal_root,
    )
    if any(value is None for value in required):
        parser.error("policy, engine, source-root, data-root and terminal-root required")
    receipt = run(
        read_json(args.policy),
        args.engine.resolve(),
        args.source_root.resolve(),
        args.data_root.resolve(),
        args.terminal_root.resolve(),
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
