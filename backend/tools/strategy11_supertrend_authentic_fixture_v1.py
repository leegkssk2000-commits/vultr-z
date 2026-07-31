from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).with_name("strategy11_supertrend_authentic_child_v1.py")
spec = importlib.util.spec_from_file_location("s11_supertrend_authentic", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("MODULE_SPEC_FAILED")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def synthetic_frame() -> pd.DataFrame:
    closes: list[float] = []
    value = 100.0
    segments = [
        (1.1, 45),
        (-1.45, 55),
        (1.55, 60),
        (-1.25, 55),
        (1.35, 65),
        (-1.5, 60),
        (1.0, 60),
    ]
    for slope, count in segments:
        for index in range(count):
            value += slope + math.sin(index / 3.0) * 0.22
            closes.append(value)
    rows = []
    for index, close in enumerate(closes):
        open_ = closes[index - 1] if index else close - 0.25
        width = 0.65 + abs(math.sin(index / 5.0)) * 0.35
        rows.append({
            "timestamp_ms": 1_700_000_000_000 + index * 900_000,
            "open": open_,
            "high": max(open_, close) + width,
            "low": min(open_, close) - width,
            "close": close,
            "volume": 1000.0 + index,
        })
    return pd.DataFrame(rows)


def main() -> int:
    frame = synthetic_frame()
    st = module.authentic_supertrend(frame, length=10, multiplier=3.0)
    assert st["atr"].iloc[:9].isna().all()
    assert pd.notna(st["atr"].iloc[9])
    assert st["supertrend"].iloc[9:].notna().all()
    assert st["direction"].iloc[9:].isin([-1.0, 1.0]).all()
    for end in (80, 120, 180, 260, len(frame)):
        prefix = module.authentic_supertrend(frame.iloc[:end].copy(), length=10, multiplier=3.0)
        for column in ("atr", "final_upper", "final_lower", "direction", "supertrend"):
            left = float(prefix[column].iloc[-1])
            right = float(st[column].iloc[end - 1])
            assert abs(left - right) <= 1e-12, (column, end, left, right)
    kwargs = {
        "window_id": "FIXTURE",
        "symbol": "BTCUSDT",
        "warmup_bars": 30,
        "length": 10,
        "multiplier": 3.0,
        "cost_bps_per_side": 4.0,
    }
    first = module.replay_window(frame, **kwargs)
    second = module.replay_window(frame, **kwargs)
    assert module.stable_sha(first) == module.stable_sha(second)
    assert first["long_flip_count"] > 0 and first["short_flip_count"] > 0
    assert first["post_seed_nan_count"] == 0
    assert all(
        trade["exit_reason"] in {"OPPOSITE_CONFIRMED_FLIP", "WINDOW_END"}
        for trade in first["trades"]
    )
    assert all(trade["entry_ts"] > trade["signal_ts"] for trade in first["trades"])
    keys = [
        (trade["side"], trade["entry_ts"], trade["exit_ts"])
        for trade in first["trades"]
    ]
    assert len(keys) == len(set(keys))
    print(
        "PASS_SUPERTREND_AUTHENTIC_FORMULA_STATE_AND_BIDIRECTIONAL_FIXTURE",
        len(first["trades"]),
        first["long_flip_count"],
        first["short_flip_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
