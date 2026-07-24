from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from strategies.authentic.integrated_supertrend_pullback_v1 import (  # noqa: E402
    BLOCK,
    FLAT,
    STRATEGY_ID,
    evaluate_latest,
    load_contract,
)
from tools.r7a4d_integrated_supertrend_pullback_replay import run_replay  # noqa: E402

FORBIDDEN_SOURCE_STRATEGY_IDS = {
    "manual_pullback_confluence_v1",
    "manual_pullback_confluence_rsi_v1",
    "tradinglab_dema200_supertrend12x3_video_v1",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def _fixture() -> pd.DataFrame:
    count = 320
    closes = []
    price = 100.0
    for position in range(count):
        if position < 210:
            price += 0.03
        elif position < 235:
            price -= 0.45
        elif position < 270:
            price += 0.70
        elif position < 295:
            price -= 0.65
        else:
            price += 0.75
        closes.append(price)

    close = np.asarray(closes, dtype=float)
    open_ = np.concatenate(([close[0]], close[:-1]))
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.20,
            "low": np.minimum(open_, close) - 0.20,
            "close": close,
            "timestamp": pd.date_range("2025-01-01", periods=count, freq="15min", tz="UTC"),
        }
    )
    frame["structure_long"] = False
    frame["structure_short"] = False
    frame.loc[235:269, "structure_long"] = True
    frame.loc[295:319, "structure_long"] = True
    frame.loc[210:234, "structure_short"] = True
    frame.loc[270:294, "structure_short"] = True
    frame["sr_touch"] = False
    frame["trendline_touch"] = False
    frame["ma50_touch"] = False
    frame.loc[210:319, "sr_touch"] = True
    frame.loc[210:319, "trendline_touch"] = True
    frame["counter_trend_break_up"] = False
    frame["counter_trend_break_down"] = False
    frame.loc[[238, 299], "counter_trend_break_up"] = True
    frame.loc[[212, 275], "counter_trend_break_down"] = True
    return frame


def main() -> int:
    contract = load_contract()
    _require(contract["strategy_id"] == STRATEGY_ID, "CONTRACT_CHILD_ID_MISMATCH")
    _require(contract["registration_invariants"]["canonical_strategy_count"] == 1, "CANONICAL_COUNT_NOT_ONE")

    incomplete = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})
    fail_closed = evaluate_latest(incomplete)
    _require(fail_closed["intent"] == BLOCK, "MISSING_GEOMETRY_NOT_BLOCKED")
    _require("OBJECTIVE_GEOMETRY_MISSING" in fail_closed["reason"], "MISSING_GEOMETRY_REASON_INVALID")

    replay = run_replay(
        _fixture(),
        symbol="SYNTHETIC",
        timeframe="15m",
        replay_fold_id="CONTRACT_CHECK",
        cost_bps_per_side=0.0,
    )
    _require(replay["strategy_id"] == STRATEGY_ID, "REPLAY_STRATEGY_ID_MISMATCH")
    _require(replay["canonical_strategy_count"] == 1, "REPLAY_CANONICAL_COUNT_NOT_ONE")
    _require(replay["signal_time"] == "CONFIRMED_BAR_CLOSE", "SIGNAL_TIME_INVALID")
    _require(replay["fill_time"] == "NEXT_BAR_OPEN", "FILL_TIME_INVALID")
    _require(replay["terminal_force_close"] is False, "TERMINAL_FORCE_CLOSE_NOT_BLOCKED")
    _require(replay["performance_claim_allowed"] is False, "PERFORMANCE_CLAIM_NOT_BLOCKED")
    _require(replay["trade_count"] >= 1, "SYNTHETIC_REPLAY_NO_CLOSED_TRADE")
    _require(
        replay["trade_count"] >= 1 or replay["open_position"]["side"] != FLAT,
        "SYNTHETIC_REPLAY_NO_POSITION_LIFECYCLE",
    )
    emitted_ids = {trade["strategy_id"] for trade in replay["trades"]}
    _require(emitted_ids <= {STRATEGY_ID}, "NONCANONICAL_STRATEGY_ID_EMITTED")
    _require(not emitted_ids.intersection(FORBIDDEN_SOURCE_STRATEGY_IDS), "SOURCE_MODULE_REGISTERED_AS_STRATEGY")

    print("STATE=PASS_INTEGRATED_SUPERTREND_PULLBACK_ONE_CHILD_ONE_REPLAY_RUNNER")
    print(f"STRATEGY_ID={STRATEGY_ID}")
    print("CANONICAL_STRATEGY_COUNT=1")
    print("CHILD_MODULE_COUNT=1")
    print("REPLAY_RUNNER_COUNT=1")
    print("OBJECTIVE_GEOMETRY_FAIL_CLOSED=true")
    print("SOURCE_MODULE_STRATEGY_REGISTRATION_ALLOWED=false")
    print(f"SYNTHETIC_CLOSED_TRADE_COUNT={replay['trade_count']}")
    print(f"SYNTHETIC_OPEN_POSITION_SIDE={replay['open_position']['side']}")
    print("NEXT_STAGE=LOCK_OBJECTIVE_SR_TRENDLINE_GEOMETRY_THEN_RUN_REAL_OOS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
