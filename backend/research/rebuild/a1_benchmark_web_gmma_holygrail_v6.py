from __future__ import annotations

import argparse
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)

SHORT_GMMA = (3, 5, 8, 10, 12, 15)
LONG_GMMA = (30, 35, 40, 45, 50, 60)
CASES = (
    ("keltner_trend", 900_000, 5.8),
    ("keltner_trend", 1_800_000, 5.8),
    ("keltner_trend", 3_600_000, 5.8),
    ("trend_ma_macd", 900_000, 3.8),
    ("trend_ma_macd", 1_800_000, 3.8),
)


def wilder_adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / length, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / length, adjust=False).mean()


def enrich_web(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for n in sorted(set(SHORT_GMMA + LONG_GMMA + (20,))):
        x[f"g{n}"] = x["close"].ewm(span=n, adjust=False).mean()
    x["adx14"] = wilder_adx(x, 14)
    x["short_spread_atr"] = (
        x[[f"g{n}" for n in SHORT_GMMA]].max(axis=1)
        - x[[f"g{n}" for n in SHORT_GMMA]].min(axis=1)
    ) / x["atr"].replace(0, np.nan)
    x["long_spread_atr"] = (
        x[[f"g{n}" for n in LONG_GMMA]].max(axis=1)
        - x[[f"g{n}" for n in LONG_GMMA]].min(axis=1)
    ) / x["atr"].replace(0, np.nan)
    x["short_q35"] = x["short_spread_atr"].shift(1).rolling(20).quantile(0.35)
    return x


def ordered(row: pd.Series, periods: tuple[int, ...], side: str) -> bool:
    vals = [float(row[f"g{n}"]) for n in periods]
    return (
        all(a > b for a, b in zip(vals, vals[1:]))
        if side == "long"
        else all(a < b for a, b in zip(vals, vals[1:]))
    )


def gmma_long_side(row: pd.Series, prev: pd.Series) -> str:
    if ordered(row, LONG_GMMA, "long") and float(row["g60"]) > float(prev["g60"]):
        return "long"
    if ordered(row, LONG_GMMA, "short") and float(row["g60"]) < float(prev["g60"]):
        return "short"
    return "flat"


def atr_cost(row: pd.Series, entry: float, cost_bps: float) -> float:
    return float(row["atr"]) / max(entry, 1e-12) * 10_000.0 / max(cost_bps, 1e-9)


def make_signal(
    sid: str,
    spec: Mapping[str, Any],
    side: str,
    i: int,
    row: pd.Series,
    invalidation: float,
    extreme: float,
    trace: tuple[str, ...],
) -> Any:
    return sm.EntrySignal(
        strategy_id=sid,
        child_id=f"{sid}__web_donor_v6",
        side=side,
        index=i,
        signal_ts=int(row["ts_ms"]),
        mode="WEB_DONOR_V6",
        invalidation_ref=float(invalidation),
        event_extreme=float(extreme),
        event_trace=trace,
        benchmark_ids=tuple(spec["benchmark_ids"]),
        transfer=tuple(spec["source_transfer"]),
    )


@dataclass
class WebState:
    regime_side: str = "flat"
    episode_traded: bool = False
    stage: int = 0
    pull_low: float | None = None
    pull_high: float | None = None
    armed_spread: float | None = None

    def reset_event(self) -> None:
        self.stage = 0
        self.pull_low = None
        self.pull_high = None
        self.armed_spread = None

    def reset_all(self) -> None:
        self.regime_side = "flat"
        self.episode_traded = False
        self.reset_event()


def keltner_signal(
    state: WebState, i: int, x: pd.DataFrame, spec: Mapping[str, Any], cost_bps: float
) -> Any | None:
    row, prev = x.iloc[i], x.iloc[i - 1]
    side = gmma_long_side(row, prev)
    strong = side != "flat" and float(row["adx14"]) >= 30.0
    ema20_slope = float(row["g20"]) - float(prev["g20"])
    strong = strong and (
        (side == "long" and ema20_slope > 0) or (side == "short" and ema20_slope < 0)
    )
    if not strong:
        if float(row["adx14"]) < 25.0 or side == "flat":
            state.reset_all()
        return None
    if state.regime_side != side:
        state.reset_all()
        state.regime_side = side
    if state.episode_traded:
        return None
    if state.stage == 0:
        touched = (
            float(row["low"]) <= float(row["g20"])
            if side == "long"
            else float(row["high"]) >= float(row["g20"])
        )
        if touched:
            state.stage = 1
            state.pull_low = float(row["low"])
            state.pull_high = float(row["high"])
        return None
    state.pull_low = (
        min(float(state.pull_low), float(row["low"]))
        if state.pull_low is not None
        else float(row["low"])
    )
    state.pull_high = (
        max(float(state.pull_high), float(row["high"]))
        if state.pull_high is not None
        else float(row["high"])
    )
    turn = (
        float(row["close"]) > float(prev["high"])
        and float(row["close"]) > float(row["g20"])
        if side == "long"
        else float(row["close"]) < float(prev["low"])
        and float(row["close"]) < float(row["g20"])
    )
    entry = float(x.iloc[i + 1]["open"])
    if turn and atr_cost(row, entry, cost_bps) >= 5.8:
        state.episode_traded = True
        invalid = float(state.pull_low if side == "long" else state.pull_high)
        return make_signal(
            "keltner_trend",
            spec,
            side,
            i,
            row,
            invalid,
            invalid,
            (
                "ADX_GT_30",
                "GMMA_LONG_GROUP_AGREEMENT",
                "FIRST_PULLBACK_20EMA",
                "TURN_TRIGGER",
                "ATR_COST_5P8",
            ),
        )
    return None


def trend_signal(
    state: WebState, i: int, x: pd.DataFrame, spec: Mapping[str, Any], cost_bps: float
) -> Any | None:
    row, prev = x.iloc[i], x.iloc[i - 1]
    side = gmma_long_side(row, prev)
    if side == "flat":
        state.reset_all()
        return None
    if state.regime_side != side:
        state.reset_all()
        state.regime_side = side
    short_q = (
        float(row["short_q35"]) if np.isfinite(float(row["short_q35"])) else np.nan
    )
    spread = float(row["short_spread_atr"])
    long_top = max(float(row[f"g{n}"]) for n in LONG_GMMA)
    long_bottom = min(float(row[f"g{n}"]) for n in LONG_GMMA)
    atr = max(float(row["atr"]), 1e-12)
    close = float(row["close"])
    weak_near_long = (
        (close >= long_bottom - 0.25 * atr and close <= long_top + 0.75 * atr)
        if side == "long"
        else (close <= long_top + 0.25 * atr and close >= long_bottom - 0.75 * atr)
    )
    if state.stage == 0:
        if np.isfinite(short_q) and spread <= short_q and weak_near_long:
            state.stage = 1
            state.armed_spread = spread
            state.pull_low = float(row["low"])
            state.pull_high = float(row["high"])
        return None
    state.pull_low = (
        min(float(state.pull_low), float(row["low"]))
        if state.pull_low is not None
        else float(row["low"])
    )
    state.pull_high = (
        max(float(state.pull_high), float(row["high"]))
        if state.pull_high is not None
        else float(row["high"])
    )
    directional = ordered(row, SHORT_GMMA, side)
    expanded = state.armed_spread is not None and spread >= max(
        float(state.armed_spread) * 1.25, float(prev["short_spread_atr"]) * 1.05
    )
    turn = (
        float(row["close"]) > float(prev["high"])
        if side == "long"
        else float(row["close"]) < float(prev["low"])
    )
    entry = float(x.iloc[i + 1]["open"])
    if directional and expanded and turn and atr_cost(row, entry, cost_bps) >= 3.8:
        invalid = float(state.pull_low if side == "long" else state.pull_high)
        signal = make_signal(
            "trend_ma_macd",
            spec,
            side,
            i,
            row,
            invalid,
            invalid,
            (
                "GMMA_LONG_GROUP_TREND",
                "SHORT_GROUP_COMPRESSION",
                "PRICE_WEAKNESS",
                "SHORT_GROUP_REEXPANSION",
                "TURN_TRIGGER",
                "ATR_COST_3P8",
            ),
        )
        state.reset_event()
        return signal
    if i % 12 == 0 and state.stage == 1:
        state.reset_event()
    return None


def build_case_spec(all_spec: Mapping[str, Any], sid: str, tf: int) -> dict[str, Any]:
    spec_all: dict[str, Any] = json.loads(json.dumps(all_spec))
    child = spec_all["children"][sid]
    child["timeframe_ms"] = tf
    child["timeframe"] = {900_000: "15m", 1_800_000: "30m", 3_600_000: "1h"}[tf]
    child["risk"]["stop_mode"] = "reference_failure_plus_atr_buffer"
    if sid == "keltner_trend":
        child["child_id"] = "keltner_trend__raschke_holygrail_gmma_v6"
        child["lifecycle"]["target_mode"] = "fixed_r_or_trailing"
        child["lifecycle"]["target_r"] = 2.0
        child["lifecycle"]["timeout_bars"] = 20
    else:
        child["child_id"] = f"trend_ma_macd__true_gmma_v6__{child['timeframe']}"
    spec_all["children"] = {sid: child}
    return spec_all


def replay_case(
    sid: str,
    tf: int,
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    signals = 0
    for sym in v2.SYMS6:
        x = enrich_web(frames[sym])
        state = WebState()
        i = 121
        while i < len(x) - 1:
            sig = (
                keltner_signal(state, i, x, spec, costs[sym])
                if sid == "keltner_trend"
                else trend_signal(state, i, x, spec, costs[sym])
            )
            if sig is None:
                i += 1
                continue
            signals += 1
            trade, exit_j = v2.simulate_trade(sid, sig, x, float(costs[sym]), spec)
            if trade is not None:
                trade["symbol"] = sym
                trade["entry_source"] = "WEB_DONOR_V6_NOT_PARENT"
                trades.append(trade)
            i = max(i + 1, exit_j + 1)
    full = v2.metrics(trades)
    split = v2.split_metrics(trades)
    return {
        "strategy_id": sid,
        "timeframe": {900_000: "15m", 1_800_000: "30m", 3_600_000: "1h"}[tf],
        "signals": signals,
        "metrics": full,
        "split": split,
        "trades": trades,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sm.validate_coverage()
    all_spec = sm.load_spec()
    authority = v2.read_json(v2.COST_PATH)
    snapshots: dict[str, dict[str, Any]] = {}

    def cost(sym: str) -> float:
        if sym not in snapshots:
            snapshots[sym] = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        return float(snapshots[sym]["pretrade_verified_cost_bps"])

    costs = {s: cost(s) for s in v2.SYMS6}
    rows = []
    for sid, tf, frozen_gate in CASES:
        spec_all = build_case_spec(all_spec, sid, tf)
        frames_by_tf, _ = v2.prepare_frames(spec_all)
        spec = spec_all["children"][sid]
        result = replay_case(sid, tf, frames_by_tf[tf], costs, spec)
        result["frozen_cost_scale_gate"] = frozen_gate
        rows.append(result)
        m = result["metrics"]
        h = result["split"]["holdout40"]
        print(
            "WEBV6_ROW="
            + json.dumps(
                {
                    "strategy_id": sid,
                    "timeframe": result["timeframe"],
                    "T": m["T"],
                    "WR": m["WR"],
                    "GrossExp_bps_T": m["GrossExp_bps_T"],
                    "NetExp_bps_T": m["Exp_bps_T"],
                    "PF": m["PF"],
                    "HoldT": h["T"],
                    "HoldGrossExp_bps_T": h["GrossExp_bps_T"],
                    "HoldNetExp_bps_T": h["Exp_bps_T"],
                    "HoldPF": h["PF"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    receipt = {
        "schema": "zel.a1.benchmark_web.gmma_holygrail.v6",
        "state": "DEV_WEB_DONOR_REPLAY_COMPLETE",
        "selection_note": "development window; prior cost-scale gates already selected on overlapping history, not fresh OOS",
        "sources": ["RASCHKE_PRIMARY_INTERVIEW", "GUPPY_OFFICIAL"],
        "parent_reuse": False,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "cases": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
