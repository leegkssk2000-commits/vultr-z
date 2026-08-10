from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

VERSION = "ZEL_EDGE_FACTORY_V2_W1_EFFECT_MAP_V1"
DATASET_STATE = "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED"
DATASET_SHA256 = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
W1_START_MS = 1771027200000
W1_END_MS = 1774828800000
SYMBOLS = ("BTC-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT")
TIMEFRAMES = {"15m": "15min", "1h": "1h"}
PRIMARY_HORIZON_HOURS = 4
COST_BPS_PER_SIDE = 4.0
ROUNDTRIP_COST_BPS = 2.0 * COST_BPS_PER_SIDE
MIN_EVENTS = 30
BOOTSTRAP_REPS = 4000
BOOTSTRAP_SEED = 42

SAFETY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "survivor_declared": False,
    "canonical_mutated": False,
    "registry_mutated": False,
    "runtime_mutated": False,
    "shadow_mutated": False,
    "paper_mutated": False,
    "live_mutated": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "ai_used_for_discovery": False,
    "w2_metrics_inspected": False,
    "w3_metrics_inspected": False,
}


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def load_manifest(root: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") != DATASET_STATE:
        raise RuntimeError(f"DATASET_STATE:{manifest.get('state')}")
    if manifest.get("dataset_sha256") != DATASET_SHA256:
        raise RuntimeError(f"DATASET_SHA:{manifest.get('dataset_sha256')}")
    post: dict[str, Mapping[str, Any]] = {}
    for row in manifest.get("results") or []:
        if not isinstance(row, Mapping) or row.get("segment_id") != "POST_GAP":
            continue
        symbol = str(row.get("symbol"))
        if symbol in SYMBOLS:
            post[symbol] = row
    if set(post) != set(SYMBOLS):
        raise RuntimeError(f"SYMBOL_SET:{sorted(post)}")
    return manifest, post


def load_w1_frames(root: Path, post: Mapping[str, Mapping[str, Any]]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        row = post[symbol]
        path = root / "data" / str(row["file"])
        if not path.is_file():
            raise RuntimeError(f"MARKET_FILE_MISSING:{symbol}")
        if file_sha(path) != str(row["file_sha256"]):
            raise RuntimeError(f"MARKET_SHA:{symbol}")
        df = pd.read_csv(path, usecols=["timestamp_ms", "open", "high", "low", "close", "volume"])
        df = df[(df["timestamp_ms"] >= W1_START_MS) & (df["timestamp_ms"] < W1_END_MS)].copy()
        expected = (W1_END_MS - W1_START_MS) // 60_000
        if len(df) != expected:
            raise RuntimeError(f"W1_ROWS:{symbol}:{len(df)}:{expected}")
        ts = df["timestamp_ms"].astype("int64")
        if int(ts.iloc[0]) != W1_START_MS or int(ts.iloc[-1]) != W1_END_MS - 60_000:
            raise RuntimeError(f"W1_RANGE:{symbol}")
        if not bool((ts.diff().dropna() == 60_000).all()):
            raise RuntimeError(f"W1_GAP:{symbol}")
        df["ts"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        out[symbol] = df.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def resample_frames(raw: Mapping[str, pd.DataFrame], rule: str) -> dict[str, pd.DataFrame]:
    return {
        symbol: frame.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        for symbol, frame in raw.items()
    }


def horizon_bars(tf: str, hours: int) -> int:
    if tf == "15m":
        return hours * 4
    if tf == "1h":
        return hours
    raise ValueError(tf)


def lookback_bars(tf: str, hours: int) -> int:
    return horizon_bars(tf, hours)


def forward_next_open_return(frame: pd.DataFrame, bars: int) -> pd.Series:
    entry = frame["open"].shift(-1)
    exit_ = frame["open"].shift(-(1 + bars))
    return exit_ / entry - 1.0


def decision_grid(index: pd.DatetimeIndex) -> np.ndarray:
    return (index.minute == 0) & ((index.hour % PRIMARY_HORIZON_HOURS) == 0)


def daily_block_bootstrap(net_bps: pd.Series, reps: int = BOOTSTRAP_REPS) -> tuple[float, float, int]:
    frame = pd.DataFrame({"net_bps": net_bps}).dropna()
    if frame.empty:
        return float("nan"), float("nan"), 0
    frame["day"] = frame.index.date
    daily = frame.groupby("day")["net_bps"].mean().to_numpy(dtype=float)
    if len(daily) < 5:
        return float("nan"), float("nan"), int(len(daily))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(reps, dtype=float)
    for idx in range(reps):
        means[idx] = rng.choice(daily, size=len(daily), replace=True).mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high), int(len(daily))


def summarize_events(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {"event_count": 0, "state": "REJECT_W1_NO_EVENTS"}
    work = events.dropna(subset=["raw_return"]).copy()
    work["net_bps"] = work["raw_return"] * 10_000.0 - ROUNDTRIP_COST_BPS
    low, high, day_count = daily_block_bootstrap(work["net_bps"])
    by_symbol = work.groupby("symbol")["net_bps"].mean().sort_index()
    count = int(len(work))
    mean_net = float(work["net_bps"].mean())
    positive_symbols = int((by_symbol > 0.0).sum())
    if count < MIN_EVENTS:
        state = "HOLD_W1_LOW_SAMPLE"
    elif mean_net <= 0.0 or positive_symbols < 3:
        state = "REJECT_W1_NONPOSITIVE_OR_NARROW"
    elif math.isfinite(low) and low > 0.0:
        state = "PASS_W1_EFFECT_DISCOVERY"
    else:
        state = "HOLD_W1_POSITIVE_NOT_ROBUST"
    return {
        "state": state,
        "event_count": count,
        "independent_day_count": day_count,
        "mean_raw_bps": float(work["raw_return"].mean() * 10_000.0),
        "median_raw_bps": float(work["raw_return"].median() * 10_000.0),
        "mean_net_bps_after_cost_floor": mean_net,
        "net_hit_rate_pct": float((work["net_bps"] > 0.0).mean() * 100.0),
        "daily_block_bootstrap95_net_bps": [low, high],
        "symbol_breadth": int(by_symbol.size),
        "positive_symbol_count": positive_symbols,
        "symbol_mean_net_bps": {str(k): float(v) for k, v in by_symbol.items()},
    }


def xsec_relative_strength(frames: Mapping[str, pd.DataFrame], tf: str) -> dict[str, Any]:
    lookback = lookback_bars(tf, 24)
    horizon = horizon_bars(tf, PRIMARY_HORIZON_HOURS)
    closes = pd.concat({symbol: frame["close"] for symbol, frame in frames.items()}, axis=1).dropna()
    opens = pd.concat({symbol: frame["open"] for symbol, frame in frames.items()}, axis=1).dropna()
    momentum = closes / closes.shift(lookback) - 1.0
    future = opens.shift(-(1 + horizon)) / opens.shift(-1) - 1.0
    rows: list[dict[str, Any]] = []
    for ts in momentum.index[decision_grid(momentum.index)]:
        m = momentum.loc[ts].dropna()
        f = future.loc[ts].dropna()
        common = m.index.intersection(f.index)
        if len(common) != len(SYMBOLS):
            continue
        symbol = str(m[common].idxmax())
        raw = finite(f[symbol], float("nan"))
        if not math.isfinite(raw):
            continue
        rows.append({
            "ts": ts,
            "symbol": symbol,
            "raw_return": raw,
            "relative_alpha": raw - float(f[common].mean()),
        })
    events = pd.DataFrame(rows)
    if events.empty:
        return summarize_events(events)
    events = events.set_index("ts")
    result = summarize_events(events)
    result["mean_relative_alpha_bps"] = float(events["relative_alpha"].mean() * 10_000.0)
    result["contract"] = {
        "feature": "24H_CROSS_SECTIONAL_RETURN_RANK_TOP1",
        "entry": "NEXT_BAR_OPEN",
        "holding_hours": PRIMARY_HORIZON_HOURS,
        "decision_grid_hours": PRIMARY_HORIZON_HOURS,
    }
    return result


def vol_expansion_continuation(frames: Mapping[str, pd.DataFrame], tf: str) -> dict[str, Any]:
    ret_lookback = lookback_bars(tf, 4)
    history = lookback_bars(tf, 24 * 20)
    horizon = horizon_bars(tf, PRIMARY_HORIZON_HOURS)
    rows: list[dict[str, Any]] = []
    for symbol, frame in frames.items():
        prev_close = frame["close"].shift(1)
        true_range = pd.concat(
            [(frame["high"] - frame["low"]), (frame["high"] - prev_close).abs(), (frame["low"] - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        normalized = true_range / frame["close"]
        q90 = normalized.shift(1).rolling(history, min_periods=max(30, history // 2)).quantile(0.90)
        trailing_return = frame["close"] / frame["close"].shift(ret_lookback) - 1.0
        future = forward_next_open_return(frame, horizon)
        grid = decision_grid(frame.index)
        mask = (normalized > q90) & (trailing_return > 0.0) & grid & future.notna()
        for ts in frame.index[mask]:
            rows.append({"ts": ts, "symbol": symbol, "raw_return": float(future.loc[ts])})
    events = pd.DataFrame(rows)
    if events.empty:
        return summarize_events(events)
    result = summarize_events(events.set_index("ts"))
    result["contract"] = {
        "feature": "CURRENT_TRUE_RANGE_GT_TRAILING_20D_Q90_AND_4H_RETURN_POSITIVE",
        "quantile_history_excludes_current_bar": True,
        "entry": "NEXT_BAR_OPEN",
        "holding_hours": PRIMARY_HORIZON_HOURS,
        "decision_grid_hours": PRIMARY_HORIZON_HOURS,
    }
    return result


def regime_mean_reversion(frames: Mapping[str, pd.DataFrame], tf: str) -> dict[str, Any]:
    lookback = lookback_bars(tf, 24)
    regime_history = lookback_bars(tf, 24 * 20)
    horizon = horizon_bars(tf, PRIMARY_HORIZON_HOURS)
    rows: list[dict[str, Any]] = []
    for symbol, frame in frames.items():
        mean = frame["close"].rolling(lookback, min_periods=lookback).mean()
        std = frame["close"].rolling(lookback, min_periods=lookback).std(ddof=0).replace(0.0, np.nan)
        zscore = (frame["close"] - mean) / std
        one_bar_abs = frame["close"].pct_change().abs()
        directional_efficiency = (
            (frame["close"] / frame["close"].shift(lookback) - 1.0).abs()
            / one_bar_abs.rolling(lookback, min_periods=lookback).sum().replace(0.0, np.nan)
        )
        median_efficiency = directional_efficiency.shift(1).rolling(
            regime_history, min_periods=max(30, regime_history // 2)
        ).quantile(0.50)
        future = forward_next_open_return(frame, horizon)
        grid = decision_grid(frame.index)
        mask = (zscore <= -1.5) & (directional_efficiency < median_efficiency) & grid & future.notna()
        for ts in frame.index[mask]:
            rows.append({"ts": ts, "symbol": symbol, "raw_return": float(future.loc[ts])})
    events = pd.DataFrame(rows)
    if events.empty:
        return summarize_events(events)
    result = summarize_events(events.set_index("ts"))
    result["contract"] = {
        "feature": "24H_ZSCORE_LE_-1P5_IN_BELOW_TRAILING_20D_MEDIAN_DIRECTIONAL_EFFICIENCY",
        "regime_quantile_history_excludes_current_bar": True,
        "entry": "NEXT_BAR_OPEN",
        "holding_hours": PRIMARY_HORIZON_HOURS,
        "decision_grid_hours": PRIMARY_HORIZON_HOURS,
    }
    return result


def choose_w2_candidates(results: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    family_best: list[dict[str, Any]] = []
    for family in (
        "XSEC_RELATIVE_STRENGTH_LONG",
        "VOL_EXPANSION_CONTINUATION_LONG",
        "REGIME_MEAN_REVERSION_LONG",
    ):
        rows = []
        for tf in TIMEFRAMES:
            row = dict(results[tf][family])
            row.update({"family": family, "timeframe": tf})
            low = row.get("daily_block_bootstrap95_net_bps", [float("nan"), float("nan")])[0]
            row["ranking_key"] = [
                1 if row.get("state") == "PASS_W1_EFFECT_DISCOVERY" else 0,
                finite(low, -1e9),
                finite(row.get("mean_net_bps_after_cost_floor"), -1e9),
            ]
            rows.append(row)
        eligible = [
            row for row in rows
            if row.get("state") in {"PASS_W1_EFFECT_DISCOVERY", "HOLD_W1_POSITIVE_NOT_ROBUST"}
        ]
        if eligible:
            family_best.append(max(eligible, key=lambda row: tuple(row["ranking_key"])))
    family_best.sort(key=lambda row: tuple(row["ranking_key"]), reverse=True)
    return [
        {
            "family": row["family"],
            "timeframe": row["timeframe"],
            "w1_state": row["state"],
            "event_count": row["event_count"],
            "mean_net_bps_after_cost_floor": row["mean_net_bps_after_cost_floor"],
            "daily_block_bootstrap95_net_bps": row["daily_block_bootstrap95_net_bps"],
            "positive_symbol_count": row["positive_symbol_count"],
            "authority": "W2_HYPOTHESIS_ONLY_NOT_SURVIVOR",
        }
        for row in family_best[:2]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    manifest, post = load_manifest(root)
    raw = load_w1_frames(root, post)
    results: dict[str, dict[str, Any]] = {}
    for tf, rule in TIMEFRAMES.items():
        frames = resample_frames(raw, rule)
        for symbol, frame in frames.items():
            if frame.empty or int(frame.index[-1].timestamp() * 1000) >= W1_END_MS:
                raise RuntimeError(f"HOLDOUT_LEAK:{tf}:{symbol}")
        results[tf] = {
            "XSEC_RELATIVE_STRENGTH_LONG": xsec_relative_strength(frames, tf),
            "VOL_EXPANSION_CONTINUATION_LONG": vol_expansion_continuation(frames, tf),
            "REGIME_MEAN_REVERSION_LONG": regime_mean_reversion(frames, tf),
        }

    w2_candidates = choose_w2_candidates(results)
    strong_count = sum(
        1 for tf in results.values() for row in tf.values() if row.get("state") == "PASS_W1_EFFECT_DISCOVERY"
    )
    state = "PASS_W1_EFFECT_MAP_WITH_CANDIDATE" if w2_candidates else "HOLD_W1_NO_POSITIVE_EFFECT"
    receipt: dict[str, Any] = {
        "schema_version": "zel.edge_factory_v2.w1_effect_map.v1",
        "version": VERSION,
        "state": state,
        "dataset": {
            "state": manifest.get("state"),
            "dataset_sha256": manifest.get("dataset_sha256"),
            "w1_start_ms": W1_START_MS,
            "w1_end_exclusive_ms": W1_END_MS,
            "symbols": list(SYMBOLS),
        },
        "method": {
            "timeframes": list(TIMEFRAMES),
            "families": [
                "XSEC_RELATIVE_STRENGTH_LONG",
                "VOL_EXPANSION_CONTINUATION_LONG",
                "REGIME_MEAN_REVERSION_LONG",
            ],
            "primary_horizon_hours": PRIMARY_HORIZON_HOURS,
            "decision_grid_hours": PRIMARY_HORIZON_HOURS,
            "entry": "NEXT_BAR_OPEN",
            "roundtrip_cost_floor_bps": ROUNDTRIP_COST_BPS,
            "minimum_events": MIN_EVENTS,
            "bootstrap": "UTC_DAILY_CLUSTER_MEAN_95CI",
            "bootstrap_reps": BOOTSTRAP_REPS,
            "candidate_budget": 2,
            "tp_sl_trailing_skill_bot_used": False,
            "parameter_search_per_family": 0,
        },
        "results": results,
        "strong_effect_test_count": strong_count,
        "w2_candidate_count": len(w2_candidates),
        "w2_candidates": w2_candidates,
        "next": "FREEZE_CANDIDATE_RULES_AND_RUN_W2_ONLY" if w2_candidates else "ROUTE_NEW_ECONOMIC_FAMILY_OR_SOURCE",
        "action": "hold",
        **SAFETY,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    write_json(args.out.resolve(), receipt)
    print(json.dumps({
        "state": state,
        "strong_effect_test_count": strong_count,
        "w2_candidate_count": len(w2_candidates),
        "w2_candidates": w2_candidates,
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
