from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

VERSION = "ZEL_EXACT25_SELECTED_INDICATOR_SCREEN_V1"
SCHEMA = "zel.exact25.selected_indicator_screen.receipt.v1"

ECONOMIC_FIELDS = (
    "event_id", "position_id", "strategy_id", "owner_sha256", "symbol",
    "interval", "data_interval", "window_id", "side", "entry_ts", "exit_ts",
    "entry_price", "exit_price", "qty", "original_qty", "initial_risk_usdt",
    "gross_pnl_usdt", "realized_R", "realized_R_including_funding_estimate",
    "fee", "slippage", "funding_pnl_estimate_usdt", "funding_event_count",
    "exit_reason", "MFE_R", "MAE_R", "time_exposure_min", "add_count",
    "partial_count", "data_source_sha256",
)


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


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def normalized(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 12) if math.isfinite(number) else None
    return value


def economic_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: normalized(row.get(key)) for key in ECONOMIC_FIELDS if key in row}


def economic_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (economic_row(row) for row in rows),
        key=lambda row: (
            str(row.get("event_id") or ""),
            str(row.get("entry_ts") or ""),
            str(row.get("exit_ts") or ""),
        ),
    )
    return stable_sha(ordered)


def read_terminal_rows(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            current = str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "")
            if current == strategy_id:
                rows.append(row)
    return rows


def copy_source(source_root: Path, destination: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {".git", ".venv", "venv", "__pycache__", "node_modules"}}
    shutil.copytree(source_root, destination, symlinks=True, ignore=ignore)


def source_root_from_report(terminal_root: Path) -> Path:
    report = load_json(terminal_root / "report.json")
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    root = source.get("root")
    if not isinstance(root, str) or not root:
        raise RuntimeError("TERMINAL_SOURCE_ROOT_MISSING")
    return Path(root)


def safe_pf(metrics: Mapping[str, Any]) -> float:
    value = metrics.get("profit_factor")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else 0.0


def metric_delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_count = int(base.get("sample_count") or 0)
    candidate_count = int(candidate.get("sample_count") or 0)
    return {
        "retention_pct": (candidate_count / base_count * 100.0) if base_count else 0.0,
        "delta_trade_count": candidate_count - base_count,
        "delta_net_R": float(candidate.get("net_R") or 0.0) - float(base.get("net_R") or 0.0),
        "delta_profit_factor": safe_pf(candidate) - safe_pf(base),
        "delta_max_drawdown_R": float(base.get("max_drawdown_R") or 0.0) - float(candidate.get("max_drawdown_R") or 0.0),
    }


def entry_side(result: Mapping[str, Any], producer: Any, strategy_id: str, owner_sha: str, symbol: str, interval: str, current: pd.DataFrame) -> str | None:
    def normalize_side(value: Any) -> str | None:
        text = str(value or "").lower()
        if any(token in text for token in ("long", "buy")):
            return "long"
        if any(token in text for token in ("short", "sell")):
            return "short"
        return None
    for key in ("side", "direction", "position_side", "signal_side"):
        side = normalize_side(result.get(key))
        if side:
            return side
    side = normalize_side(result.get("action"))
    if side:
        return side
    try:
        position = producer.make_position(strategy_id, owner_sha, symbol, interval, dict(result), current, 1.0, 0.0005, 1.0)
    except Exception:
        position = None
    return normalize_side(position.get("side")) if isinstance(position, Mapping) else None


def macd_histogram(close: pd.Series, fast: int, slow: int, signal: int) -> pd.Series:
    fast_line = close.ewm(span=fast, adjust=False).mean()
    slow_line = close.ewm(span=slow, adjust=False).mean()
    macd = fast_line - slow_line
    return macd - macd.ewm(span=signal, adjust=False).mean()


def rsi(close: pd.Series, period: int) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    last_loss = float(loss.iloc[-1]) if pd.notna(loss.iloc[-1]) else math.nan
    last_gain = float(gain.iloc[-1]) if pd.notna(gain.iloc[-1]) else math.nan
    if not math.isfinite(last_gain) or not math.isfinite(last_loss):
        return None
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + last_gain / last_loss)


def allowed(axis_id: str, config: Mapping[str, Any], current: pd.DataFrame, side: str) -> bool:
    close = current["close"].astype(float)
    if axis_id == "MACD_HISTOGRAM_SIGN":
        hist = macd_histogram(close, int(config["fast"]), int(config["slow"]), int(config["signal"]))
        last = float(hist.iloc[-1])
        if not math.isfinite(last):
            return False
        if config["mode"] == "ALIGN_SIGN":
            return last > 0 if side == "long" else last < 0
        if config["mode"] == "RECENT_CROSS":
            recent = hist.iloc[-(int(config["lookback"]) + 1):]
            if side == "long":
                return bool(((recent.shift(1) <= 0) & (recent > 0)).fillna(False).any())
            return bool(((recent.shift(1) >= 0) & (recent < 0)).fillna(False).any())
        raise RuntimeError(f"UNKNOWN_MACD_MODE:{config['mode']}")
    if axis_id == "FIB_RETRACE_ZONE":
        sample = current.iloc[-int(config["lookback"]):]
        low = float(sample["low"].min())
        high = float(sample["high"].max())
        price = float(close.iloc[-1])
        span = high - low
        if span <= 0:
            return False
        retracement = (high - price) / span if side == "long" else (price - low) / span
        return float(config["lower"]) <= retracement <= float(config["upper"])
    if axis_id == "RSI_BAND":
        value = rsi(close, int(config["period"]))
        if value is None:
            return False
        lower = float(config["lower"]); upper = float(config["upper"])
        if config["mode"] == "BLOCK_EXTREME":
            return value < upper if side == "long" else value > lower
        if config["mode"] == "MOMENTUM":
            return value >= upper if side == "long" else value <= lower
        if config["mode"] == "BALANCED":
            return lower <= value <= upper
        raise RuntimeError(f"UNKNOWN_RSI_MODE:{config['mode']}")
    raise RuntimeError(f"UNSUPPORTED_AXIS:{axis_id}")


class FilteredOwner:
    def __init__(self, base: Any, producer: Any, strategy_id: str, symbol: str, interval: str, axis_id: str, config: Mapping[str, Any]) -> None:
        self.base = base; self.producer = producer; self.strategy_id = strategy_id
        self.symbol = symbol; self.interval = interval; self.axis_id = axis_id; self.config = dict(config)
        self.owner_sha256 = stable_sha({"base_owner_sha256": str(getattr(base, "owner_sha256", "")), "axis_id": axis_id, "config": self.config, "version": VERSION})
        self.valid_entry_count = self.blocked_entry_count = self.unknown_side_count = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def strategy(self, current: pd.DataFrame, state: Any = None, risk_action: str = "hold") -> dict[str, Any]:
        result = self.base.strategy(current, state=state, risk_action=risk_action)
        if not isinstance(result, dict) or state is not None:
            return result
        current_price = float(current["close"].iloc[-1])
        if self.producer.valid_entry(result, current_price) is None:
            return result
        self.valid_entry_count += 1
        side = entry_side(result, self.producer, self.strategy_id, str(getattr(self.base, "owner_sha256", "")), self.symbol, self.interval, current)
        if side is None:
            self.unknown_side_count += 1
            return result
        if allowed(self.axis_id, self.config, current, side):
            return result
        self.blocked_entry_count += 1
        return {"action": "hold", "reason": f"research_indicator_filter:{self.axis_id}", "research_only": True}


def configurations(axis_id: str) -> list[dict[str, Any]]:
    if axis_id == "MACD_HISTOGRAM_SIGN":
        return [
            {"config_id": "MACD_ALIGN_12_26_9", "mode": "ALIGN_SIGN", "fast": 12, "slow": 26, "signal": 9},
            {"config_id": "MACD_ALIGN_8_21_5", "mode": "ALIGN_SIGN", "fast": 8, "slow": 21, "signal": 5},
            {"config_id": "MACD_CROSS_12_26_9_L3", "mode": "RECENT_CROSS", "fast": 12, "slow": 26, "signal": 9, "lookback": 3},
        ]
    if axis_id == "FIB_RETRACE_ZONE":
        return [
            {"config_id": "FIB_20_382_618", "lookback": 20, "lower": 0.382, "upper": 0.618},
            {"config_id": "FIB_50_382_618", "lookback": 50, "lower": 0.382, "upper": 0.618},
            {"config_id": "FIB_100_382_618", "lookback": 100, "lower": 0.382, "upper": 0.618},
            {"config_id": "FIB_50_500_786", "lookback": 50, "lower": 0.5, "upper": 0.786},
        ]
    if axis_id == "RSI_BAND":
        return [
            {"config_id": "RSI14_BLOCK_30_70", "mode": "BLOCK_EXTREME", "period": 14, "lower": 30, "upper": 70},
            {"config_id": "RSI7_BLOCK_30_70", "mode": "BLOCK_EXTREME", "period": 7, "lower": 30, "upper": 70},
            {"config_id": "RSI21_BLOCK_35_65", "mode": "BLOCK_EXTREME", "period": 21, "lower": 35, "upper": 65},
            {"config_id": "RSI14_MOMENTUM_45_55", "mode": "MOMENTUM", "period": 14, "lower": 45, "upper": 55},
            {"config_id": "RSI14_BALANCED_35_65", "mode": "BALANCED", "period": 14, "lower": 35, "upper": 65},
        ]
    raise RuntimeError(f"UNSUPPORTED_AXIS:{axis_id}")


def run_replay(engine_path: Path, source_root: Path, data_root: Path, strategy_id: str, axis_id: str | None = None, config: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    engine = load_module(engine_path, f"zel_indicator_engine_{strategy_id}_{os.getpid()}_{stable_sha(config or {})[:8]}")
    engine.init_worker(str(source_root), str(data_root), "1m")
    registry = engine._WORKER_REGISTRY; manifest = engine._WORKER_MANIFEST
    funding = engine._WORKER_FUNDING; producer = engine._WORKER_PRODUCER
    if not isinstance(registry, Mapping) or strategy_id not in registry:
        raise RuntimeError(f"STRATEGY_OWNER_MISSING:{strategy_id}")
    owner = registry[strategy_id]; lanes: list[dict[str, Any]] = []
    blocked = valid = unknown = 0
    for file_row in sorted([row for row in manifest.get("files", []) if isinstance(row, Mapping) and row.get("kind") == "market" and row.get("interval") == "1m"], key=lambda row: (str(row["window_id"]), str(row["symbol"]))):
        frame = engine.frame_from_csv(data_root / str(file_row["path"]))
        lane_owner: Any = owner; wrapper: FilteredOwner | None = None
        if axis_id and config:
            wrapper = FilteredOwner(owner, producer, strategy_id, str(file_row["symbol"]), "1m", axis_id, config)
            lane_owner = wrapper
        lane = engine.replay_lane(strategy_id, lane_owner, file_row, frame, funding.get(str(file_row["symbol"]), []))
        lanes.append(lane)
        if wrapper:
            blocked += wrapper.blocked_entry_count; valid += wrapper.valid_entry_count; unknown += wrapper.unknown_side_count
    result = {"strategy_id": strategy_id, "owner_sha256": str(getattr(owner, "owner_sha256", "")), "lanes": lanes}
    card, rows = engine.aggregate_strategy(result)
    return card, rows, {"lane_count": len(lanes), "error_count": sum(int(lane.get("error_count") or 0) for lane in lanes), "censored_open_count": sum(int(lane.get("censored_open_at_window_end") or 0) for lane in lanes), "valid_entry_count": valid, "blocked_entry_count": blocked, "unknown_side_count": unknown}


def metrics_by_window(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {window: engine.metrics([row for row in rows if str(row.get("window_id")) == window], "realized_R_including_funding_estimate") for window in ("1m_w1", "1m_w2", "1m_w3")}
    result["all"] = engine.metrics(rows, "realized_R_including_funding_estimate")
    return result


def window_pass(base: Mapping[str, Any], candidate: Mapping[str, Any], minimum_retention: float, minimum_count: int) -> tuple[bool, dict[str, Any], list[str]]:
    delta = metric_delta(base, candidate); blockers: list[str] = []
    if int(candidate.get("sample_count") or 0) < minimum_count: blockers.append("SAMPLE_BELOW_MIN")
    if delta["retention_pct"] < minimum_retention: blockers.append("RETENTION_BELOW_MIN")
    if delta["delta_net_R"] < 0: blockers.append("NET_R_WORSE")
    if delta["delta_profit_factor"] < 0: blockers.append("PROFIT_FACTOR_WORSE")
    if delta["delta_max_drawdown_R"] < 0: blockers.append("MAX_DRAWDOWN_WORSE")
    return not blockers, delta, blockers


def evaluate(policy: Mapping[str, Any], engine_path: Path, terminal_root: Path, data_root: Path) -> dict[str, Any]:
    source_root = source_root_from_report(terminal_root)
    terminal_report = load_json(terminal_root / "report.json")
    terminal_scorecards = {str(row.get("strategy_id")): row for row in terminal_report.get("scorecards", []) if isinstance(row, Mapping)}
    with tempfile.TemporaryDirectory(prefix="zel-indicator-source-") as temp_dir:
        copied_root = Path(temp_dir) / "source"; copy_source(source_root, copied_root)
        strategy_results: list[dict[str, Any]] = []
        for experiment in policy["experiments"]:
            strategy_id = str(experiment["strategy_id"]); axis_id = str(experiment["axis_id"])
            baseline_card, baseline_rows, baseline_meta = run_replay(engine_path, copied_root, data_root, strategy_id)
            terminal_rows = read_terminal_rows(terminal_root / "trades.jsonl.gz", strategy_id)
            terminal_metrics = terminal_scorecards[strategy_id]["closed_metrics_including_funding_estimate"]
            baseline_metrics = baseline_card["closed_metrics_including_funding_estimate"]
            parity = {
                "trade_count": len(baseline_rows) == len(terminal_rows),
                "economic_digest": economic_digest(baseline_rows) == economic_digest(terminal_rows),
                "net_R": abs(float(baseline_metrics.get("net_R") or 0.0) - float(terminal_metrics.get("net_R") or 0.0)) <= 1e-9,
                "profit_factor": abs(safe_pf(baseline_metrics) - safe_pf(terminal_metrics)) <= 1e-9,
                "max_drawdown_R": abs(float(baseline_metrics.get("max_drawdown_R") or 0.0) - float(terminal_metrics.get("max_drawdown_R") or 0.0)) <= 1e-9,
                "errors_zero": baseline_meta["error_count"] == 0,
                "censored_zero": baseline_meta["censored_open_count"] == 0,
            }
            metric_engine = load_module(engine_path, f"zel_indicator_metric_engine_{strategy_id}_{os.getpid()}")
            base_windows = metrics_by_window(metric_engine, baseline_rows); candidates: list[dict[str, Any]] = []
            for config in configurations(axis_id):
                _, rows, meta = run_replay(engine_path, copied_root, data_root, strategy_id, axis_id, config)
                candidate_windows = metrics_by_window(metric_engine, rows)
                w1_ok, w1_delta, w1_blockers = window_pass(base_windows["1m_w1"], candidate_windows["1m_w1"], float(policy["thresholds"]["minimum_retention_pct"]), int(policy["thresholds"]["minimum_w1_trade_count"]))
                candidates.append({"config": config, "config_sha256": stable_sha({"axis_id": axis_id, "config": config}), "metrics": candidate_windows, "meta": meta, "w1_pass": w1_ok and meta["error_count"] == 0 and meta["censored_open_count"] == 0 and meta["blocked_entry_count"] > 0 and meta["unknown_side_count"] == 0, "w1_delta": w1_delta, "w1_blockers": w1_blockers, "economic_digest_sha256": economic_digest(rows)})
            eligible = [row for row in candidates if row["w1_pass"]]
            selected = max(eligible, key=lambda row: (row["w1_delta"]["delta_net_R"], row["w1_delta"]["delta_profit_factor"], row["w1_delta"]["delta_max_drawdown_R"]), default=None)
            confirmation: dict[str, Any] = {}; survivor = False
            if selected:
                all_pass = True
                for window in ("1m_w2", "1m_w3"):
                    passed, delta, blockers = window_pass(base_windows[window], selected["metrics"][window], float(policy["thresholds"]["minimum_retention_pct"]), int(policy["thresholds"]["minimum_confirmation_trade_count"]))
                    confirmation[window] = {"pass": passed, "delta": delta, "blockers": blockers, "baseline": base_windows[window], "candidate": selected["metrics"][window]}
                    all_pass = all_pass and passed
                survivor = all(parity.values()) and all_pass
            strategy_results.append({"strategy_id": strategy_id, "axis_id": axis_id, "baseline_parity": parity, "baseline": base_windows, "candidate_count": len(candidates), "candidates": candidates, "selected_config": selected["config"] if selected else None, "selected_config_sha256": selected["config_sha256"] if selected else None, "confirmation": confirmation, "survivor": survivor, "state": "PASS_INDICATOR_CHILD_SURVIVOR" if survivor else "HOLD_INDICATOR_AXIS_REJECTED"})
    survivor_count = sum(row["survivor"] for row in strategy_results)
    receipt = {"schema_version": SCHEMA, "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(), "state": "PASS_SELECTED_INDICATOR_SCREEN_COMPLETE", "experiment_count": len(strategy_results), "survivor_count": survivor_count, "strategies": strategy_results, "source_root": str(source_root), "source_tree_sha256": terminal_report["source"]["strategy_tree_sha256_before"], "raw_trade_rows_published": False, "raw_prices_published": False, "source_copy_deleted": True, "canonical_mutated": False, "registry_mutated": False, "runtime_mutated": False, "formal_ledger_mutated": False, "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "action": "hold", "next": "ROUTE_SURVIVORS_TO_SELECTED_INTERACTIONS" if survivor_count else "ADVANCE_TO_NEXT_UNTESTED_SINGLE_AXIS"}
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    close = pd.Series([100.0 + index * 0.1 for index in range(300)])
    assert math.isfinite(float(macd_histogram(close, 12, 26, 9).iloc[-1]))
    assert rsi(close, 14) is not None
    assert len(configurations("MACD_HISTOGRAM_SIGN")) == 3
    assert len(configurations("FIB_RETRACE_ZONE")) == 4
    assert len(configurations("RSI_BAND")) == 5
    delta = metric_delta({"sample_count": 100, "net_R": -10.0, "profit_factor": 0.5, "max_drawdown_R": 20.0}, {"sample_count": 70, "net_R": -5.0, "profit_factor": 0.6, "max_drawdown_R": 12.0})
    assert delta["retention_pct"] == 70.0 and delta["delta_net_R"] == 5.0
    print("PASS"); return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--out", type=Path); parser.add_argument("--stdout", action="store_true"); parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test: return self_test()
    if not args.policy: parser.error("--policy required")
    receipt = evaluate(load_json(args.policy), args.engine, args.terminal_root, args.data_root)
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out: args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out: print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
