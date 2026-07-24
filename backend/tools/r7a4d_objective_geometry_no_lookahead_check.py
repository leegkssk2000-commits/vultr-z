from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from strategies.authentic.objective_pullback_geometry_v1 import (  # noqa: E402
    GEOMETRY_ID,
    ObjectivePullbackGeometryConfig,
    REQUIRED_OUTPUT_COLUMNS,
    attach_objective_geometry,
    compute_objective_geometry,
)
from tools.r7a4d_integrated_supertrend_pullback_replay import run_replay  # noqa: E402

NUMERIC_PROOF_COLUMNS = (
    "geometry_atr",
    "geometry_ma50",
    "confirmed_pivot_high",
    "confirmed_pivot_low",
    "trendline_support",
    "trendline_resistance",
)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _synthetic_frame(rows: int = 360, seed: int = 7342) -> pd.DataFrame:
    rng = random.Random(seed)
    records: List[Dict[str, Any]] = []
    close = 100.0
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    for i in range(rows):
        regime = (i // 60) % 4
        drift = (0.18, -0.14, 0.08, -0.05)[regime]
        impulse = 1.1 if i % 47 == 0 else (-1.0 if i % 53 == 0 else 0.0)
        next_close = max(1.0, close + drift + impulse + rng.uniform(-0.95, 0.95))
        open_price = close + rng.uniform(-0.35, 0.35)
        high = max(open_price, next_close) + rng.uniform(0.08, 0.75)
        low = min(open_price, next_close) - rng.uniform(0.08, 0.75)
        records.append(
            {
                "timestamp": start + pd.Timedelta(minutes=15 * i),
                "open": open_price,
                "high": high,
                "low": low,
                "close": next_close,
            }
        )
        close = next_close
    return pd.DataFrame(records)


def _values_equal(left: Any, right: Any) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if isinstance(left, (bool,)) or isinstance(right, (bool,)):
        return bool(left) == bool(right)
    if _finite(left) and _finite(right):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
    return left == right


def _assert_prefix_invariance(frame: pd.DataFrame, cfg: ObjectivePullbackGeometryConfig) -> int:
    full = compute_objective_geometry(frame, cfg)
    checked = 0
    start = max(cfg.ma_length + 5, cfg.pivot_left + cfg.pivot_right + 5)
    proof_columns: Iterable[str] = (*REQUIRED_OUTPUT_COLUMNS, *NUMERIC_PROOF_COLUMNS)
    for end in range(start, len(frame)):
        prefix = compute_objective_geometry(frame.iloc[: end + 1].copy(), cfg)
        for column in proof_columns:
            if not _values_equal(prefix[column].iloc[-1], full[column].iloc[end]):
                raise AssertionError(f"PREFIX_INVARIANCE_FAILED:end={end}:column={column}")
        checked += 1
    return checked


def _assert_future_append_invariance(frame: pd.DataFrame, cfg: ObjectivePullbackGeometryConfig) -> int:
    cutoff = 240
    base = frame.iloc[:cutoff].copy()
    future = frame.iloc[cutoff:].copy()
    future["open"] = future["open"] * 1.7
    future["high"] = future[["open", "close"]].max(axis=1) + 8.0
    future["low"] = (future[["open", "close"]].min(axis=1) - 8.0).clip(lower=0.01)
    future["close"] = future["close"] * 1.6
    future["high"] = future[["open", "close", "high"]].max(axis=1)
    future["low"] = future[["open", "close", "low"]].min(axis=1)

    base_geometry = compute_objective_geometry(base, cfg)
    extended_geometry = compute_objective_geometry(pd.concat([base, future], ignore_index=True), cfg).iloc[:cutoff]
    proof_columns: Iterable[str] = (*REQUIRED_OUTPUT_COLUMNS, *NUMERIC_PROOF_COLUMNS)
    for column in proof_columns:
        for position in range(cutoff):
            if not _values_equal(base_geometry[column].iloc[position], extended_geometry[column].iloc[position]):
                raise AssertionError(f"FUTURE_APPEND_CHANGED_HISTORY:position={position}:column={column}")
    return cutoff


def _validate_real_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    timestamp_column = next(
        (column for column in ("timestamp", "bar_open_ts", "open_ts", "ts", "time") if column in frame.columns),
        None,
    )
    if timestamp_column is None:
        raise ValueError("REAL_OOS_TIMESTAMP_COLUMN_MISSING")
    timestamps = pd.to_datetime(frame[timestamp_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError("REAL_OOS_TIMESTAMP_INVALID")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("REAL_OOS_TIMESTAMP_NOT_MONOTONIC")
    if timestamps.duplicated().any():
        raise ValueError("REAL_OOS_TIMESTAMP_DUPLICATE")
    if len(frame) < 250:
        raise ValueError("REAL_OOS_ROWS_LT_250")
    frame[timestamp_column] = timestamps
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove objective pullback geometry is causal and optionally run real OOS")
    parser.add_argument("--csv")
    parser.add_argument("--symbol", default="UNKNOWN")
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    cfg = ObjectivePullbackGeometryConfig()
    cfg.validate()
    synthetic = _synthetic_frame()
    prefix_checks = _assert_prefix_invariance(synthetic, cfg)
    append_checks = _assert_future_append_invariance(synthetic, cfg)

    attached = attach_objective_geometry(synthetic, cfg)
    missing = [column for column in REQUIRED_OUTPUT_COLUMNS if column not in attached.columns]
    if missing:
        raise AssertionError("GEOMETRY_SCHEMA_MISSING:" + ",".join(missing))

    synthetic_replay = run_replay(
        synthetic,
        symbol="SYNTHETIC",
        timeframe="15m",
        replay_fold_id="NO_LOOKAHEAD_PROOF",
        cost_bps_per_side=args.cost_bps_per_side,
    )
    if synthetic_replay.get("canonical_strategy_count") != 1:
        raise AssertionError("CANONICAL_STRATEGY_COUNT_INVALID")
    if synthetic_replay.get("geometry_id") != GEOMETRY_ID:
        raise AssertionError("GEOMETRY_NOT_BOUND_TO_REPLAY")
    if synthetic_replay.get("geometry_attached") is not True:
        raise AssertionError("RAW_OHLC_GEOMETRY_ATTACH_NOT_PROVEN")

    real_oos_ready = bool(args.csv)
    real_oos_result = None
    if args.csv:
        real_frame = _validate_real_csv(Path(args.csv))
        real_oos_result = run_replay(
            real_frame,
            symbol=args.symbol,
            timeframe="15m",
            replay_fold_id="REAL_OOS",
            cost_bps_per_side=args.cost_bps_per_side,
        )

    result = {
        "state": "PASS_OBJECTIVE_PULLBACK_GEOMETRY_NO_LOOKAHEAD",
        "geometry_id": GEOMETRY_ID,
        "canonical_strategy_count": 1,
        "prefix_invariance_checks": prefix_checks,
        "future_append_history_checks": append_checks,
        "geometry_columns": list(REQUIRED_OUTPUT_COLUMNS),
        "geometry_assumptions": {
            "pivot_confirmation": "3_LEFT_3_RIGHT_EMITTED_ONLY_ON_CONFIRMATION_BAR",
            "support_resistance": "LAST_6_CONFIRMED_PIVOT_LEVELS",
            "touch_tolerance": "0.25_ATR14",
            "trendline": "LAST_2_CONFIRMED_PIVOTS_PROJECTED_FORWARD",
            "ma50": "SMA50",
            "counter_trendline": "8_PRIOR_BARS_LINEAR_PROJECTION_WITH_0.05_ATR_BREAK_BUFFER",
        },
        "source_1_to_1_claim_allowed": False,
        "performance_claim_allowed": False,
        "synthetic_replay_trade_count": synthetic_replay.get("trade_count"),
        "real_oos_data_ready": real_oos_ready,
        "real_oos_result": real_oos_result,
        "next_stage": (
            "REVIEW_REAL_OOS_RESULT_WITHOUT_PARAMETER_OPTIMIZATION"
            if real_oos_ready
            else "PROVIDE_TIMESTAMPED_15M_OHLC_CSV_AND_RUN_REAL_OOS"
        ),
        "blockers": [] if real_oos_ready else ["NO_LOCAL_TIMESTAMPED_OHLC_DATASET"],
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
