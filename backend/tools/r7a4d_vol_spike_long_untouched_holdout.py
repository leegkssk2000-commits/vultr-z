from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.strategy25.strategy_family_indicator_search_v2 import variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_DIR = "artifacts/vol_spike_long_untouched_holdout_v1"
STRATEGY_ID = "vol_spike_fade"
WINDOW_BARS = 1200
WINDOW_COUNT = 6
WARMUP_BARS = 220
HISTORY_BARS = 260
COST_BPS_PER_SIDE = 4.0


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load(BASE_PATH, "r7a4d_vol_spike_long_holdout_base_v1")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _aggregate(windows: list[Mapping[str, Any]]) -> dict[str, Any]:
    trades = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    wins = sum(int(row["stats"].get("win_count") or 0) for row in windows)
    losses = sum(int(row["stats"].get("loss_count") or 0) for row in windows)
    net = sum(_number(row["stats"].get("net_return_pct_sum")) for row in windows)
    gross_gain = sum(_number(row["stats"].get("average_win_pct")) * int(row["stats"].get("win_count") or 0) for row in windows)
    gross_loss = sum(_number(row["stats"].get("average_loss_pct_abs")) * int(row["stats"].get("loss_count") or 0) for row in windows)
    avg_win = gross_gain / wins if wins else None
    avg_loss = gross_loss / losses if losses else None
    return {
        "trade_count": trades,
        "win_count": wins,
        "loss_count": losses,
        "win_rate_pct": wins / trades * 100.0 if trades else None,
        "net_return_pct_sum": net,
        "net_profit_factor": gross_gain / gross_loss if gross_loss > 0.0 else (999.0 if gross_gain > 0.0 else None),
        "average_win_pct": avg_win,
        "average_loss_pct_abs": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0.0) else None,
        "max_drawdown_pct_conservative_sum": sum(_number(row["stats"].get("max_drawdown_pct")) for row in windows),
    }


def _window(frames: Mapping[str, pd.DataFrame], strategy, index: int) -> dict[str, Any]:
    start = index * WINDOW_BARS
    end = start + WINDOW_BARS
    runs = []
    symbols = []
    for symbol in base.SYMBOLS:
        replay = base._replay(
            frames[symbol].iloc[start:end].reset_index(drop=True),
            strategy,
            warmup_bars=WARMUP_BARS,
            history_bars=HISTORY_BARS,
            cost_bps_per_side=COST_BPS_PER_SIDE,
        )
        runs.append(replay)
        symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
    stats = base._aggregate(runs)
    return {
        "window_id": f"LONG_H{index + 1}",
        "stats": stats,
        "positive_symbols": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols),
        "symbols": symbols,
    }


def _contract(windows: list[Mapping[str, Any]], combined: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    positive_windows = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows)
    positive_symbol_windows = sum(int(row["positive_symbols"]) for row in windows)
    severe_loss_windows = sum(_number(row["stats"].get("net_return_pct_sum")) < -1.5 for row in windows)
    if int(combined.get("trade_count") or 0) < 30:
        reasons.append("TRADES_LT_30")
    if _number(combined.get("net_return_pct_sum")) <= 0.0:
        reasons.append("NET_NOT_POSITIVE")
    if _number(combined.get("net_profit_factor")) <= 1.05:
        reasons.append("PF_LE_1_05")
    if _number(combined.get("payoff_ratio")) <= 1.50:
        reasons.append("PAYOFF_LE_1_50")
    if positive_windows < 4:
        reasons.append("POSITIVE_WINDOWS_LT_4_OF_6")
    if positive_symbol_windows < 12:
        reasons.append("POSITIVE_SYMBOL_WINDOWS_LT_12_OF_30")
    if severe_loss_windows > 1:
        reasons.append("SEVERE_LOSS_WINDOWS_GT_1")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    # This range ends before every prior family/focused holdout used in this branch.
    prior_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    prior_end_ms = (prior_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    prior_start_ms = prior_end_ms - (int(base.WINDOW_BARS) * 2 - 1) * base.INTERVAL_MS
    prior_single_end_ms = prior_start_ms - base.INTERVAL_MS
    prior_single_start_ms = prior_single_end_ms - (1200 - 1) * base.INTERVAL_MS
    family_end_ms = prior_single_start_ms - base.INTERVAL_MS
    family_start_ms = family_end_ms - (700 * 5 - 1) * base.INTERVAL_MS
    prior_fresh_end_ms = family_start_ms - base.INTERVAL_MS
    prior_fresh_start_ms = prior_fresh_end_ms - (700 * 2 - 1) * base.INTERVAL_MS
    end_ms = prior_fresh_start_ms - base.INTERVAL_MS
    total_bars = WINDOW_BARS * WINDOW_COUNT
    start_ms = end_ms - (total_bars - 1) * base.INTERVAL_MS

    blockers = []
    frames = {}
    fetch_results = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=total_bars)
            frames[symbol] = frame
            fetch_results.append({
                "symbol": symbol,
                "status": "PASS",
                "rows": len(frame),
                "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                "endpoint": endpoint,
                "request_count": requests,
            })
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    registry = base._load_registry(root)
    canonical = base._load_canonical_strategy(root, STRATEGY_ID, registry[STRATEGY_ID])
    base_spec = next(spec for spec in variants_for(STRATEGY_ID) if spec.variant_id == "BASE")
    strategy = wrap_strategy(canonical, base_spec)
    windows = [_window(frames, strategy, index) for index in range(WINDOW_COUNT)] if not blockers else []
    combined = _aggregate(windows) if windows else None
    passed, reasons = _contract(windows, combined) if windows else (False, ["NO_WINDOWS"])

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_LONG_UNTOUCHED_HOLDOUT_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_id": STRATEGY_ID,
        "variant_id": "BASE",
        "window_contract": {
            "start": pd.Timestamp(start_ms, unit="ms", tz="UTC").isoformat(),
            "end": pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
            "window_bars": WINDOW_BARS,
            "window_count": WINDOW_COUNT,
            "warmup_bars": WARMUP_BARS,
            "history_bars": HISTORY_BARS,
            "cost_bps_per_side": COST_BPS_PER_SIDE,
            "untouched_before_run": True,
        },
        "windows": windows,
        "combined": combined,
        "long_holdout_pass": passed,
        "failure_reasons": reasons,
        "fetch_results": fetch_results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "shadow_allowed": False,
        "next": "THIRD_OOS_CONFIRMATION" if passed else "REJECT_VOL_SPIKE_AND_CONTINUE_OTHER_FAMILY",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"],
        "COMBINED": combined,
        "POSITIVE_WINDOWS": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows),
        "POSITIVE_SYMBOL_WINDOWS": sum(int(row["positive_symbols"]) for row in windows),
        "PASS": passed,
        "REASONS": reasons,
        "NEXT": report["next"],
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
