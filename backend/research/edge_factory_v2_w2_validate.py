from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
W1_PATH = HERE / "edge_factory_v2_w1_effect_map.py"
W2_START_MS = 1774828800000
W2_END_MS = 1778630400000
WARMUP_START_MS = 1771027200000


def load_w1_module() -> Any:
    spec = importlib.util.spec_from_file_location("edge_factory_v2_w1_parent", W1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("W1_MODULE_SPEC")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


w1 = load_w1_module()


def load_frames(root: Path, start_ms: int, end_ms: int) -> dict[str, pd.DataFrame]:
    manifest, post = w1.load_manifest(root)
    if manifest.get("dataset_sha256") != w1.DATASET_SHA256:
        raise RuntimeError("DATASET_SHA")
    out: dict[str, pd.DataFrame] = {}
    for symbol in w1.SYMBOLS:
        row = post[symbol]
        path = root / "data" / str(row["file"])
        if w1.file_sha(path) != str(row["file_sha256"]):
            raise RuntimeError(f"MARKET_SHA:{symbol}")
        df = pd.read_csv(path, usecols=["timestamp_ms", "open", "high", "low", "close", "volume"])
        df = df[(df["timestamp_ms"] >= start_ms) & (df["timestamp_ms"] < end_ms)].copy()
        expected = (end_ms - start_ms) // 60_000
        if len(df) != expected:
            raise RuntimeError(f"WINDOW_ROWS:{symbol}:{len(df)}:{expected}")
        ts = df["timestamp_ms"].astype("int64")
        if int(ts.iloc[0]) != start_ms or int(ts.iloc[-1]) != end_ms - 60_000:
            raise RuntimeError(f"WINDOW_RANGE:{symbol}")
        if not bool((ts.diff().dropna() == 60_000).all()):
            raise RuntimeError(f"WINDOW_GAP:{symbol}")
        df["ts"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        out[symbol] = df.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def score_mask(index: pd.DatetimeIndex, start_ms: int, end_ms: int) -> np.ndarray:
    start = pd.to_datetime(start_ms, unit="ms", utc=True)
    end = pd.to_datetime(end_ms, unit="ms", utc=True)
    return (index >= start) & (index < end)


def regime_mean_reversion_events(frames: Mapping[str, pd.DataFrame], score_start_ms: int, score_end_ms: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    lookback = 24
    regime_history = 24 * 20
    horizon = 4
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
        future = w1.forward_next_open_return(frame, horizon)
        mask = (
            (zscore <= -1.5)
            & (directional_efficiency < median_efficiency)
            & w1.decision_grid(frame.index)
            & score_mask(frame.index, score_start_ms, score_end_ms)
            & future.notna()
        )
        for ts in frame.index[mask]:
            rows.append({"ts": ts, "symbol": symbol, "raw_return": float(future.loc[ts])})
    if not rows:
        return pd.DataFrame(columns=["symbol", "raw_return"])
    return pd.DataFrame(rows).set_index("ts")


def vol_expansion_events(frames: Mapping[str, pd.DataFrame], score_start_ms: int, score_end_ms: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ret_lookback = 4
    history = 24 * 20
    horizon = 4
    for symbol, frame in frames.items():
        prev_close = frame["close"].shift(1)
        true_range = pd.concat(
            [(frame["high"] - frame["low"]), (frame["high"] - prev_close).abs(), (frame["low"] - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        normalized = true_range / frame["close"]
        q90 = normalized.shift(1).rolling(history, min_periods=max(30, history // 2)).quantile(0.90)
        trailing_return = frame["close"] / frame["close"].shift(ret_lookback) - 1.0
        future = w1.forward_next_open_return(frame, horizon)
        mask = (
            (normalized > q90)
            & (trailing_return > 0.0)
            & w1.decision_grid(frame.index)
            & score_mask(frame.index, score_start_ms, score_end_ms)
            & future.notna()
        )
        for ts in frame.index[mask]:
            rows.append({"ts": ts, "symbol": symbol, "raw_return": float(future.loc[ts])})
    if not rows:
        return pd.DataFrame(columns=["symbol", "raw_return"])
    return pd.DataFrame(rows).set_index("ts")


def summarize(family: str, events: pd.DataFrame) -> dict[str, Any]:
    base = w1.summarize_events(events)
    translate = {
        "PASS_W1_EFFECT_DISCOVERY": "PASS_W2_EFFECT",
        "HOLD_W1_POSITIVE_NOT_ROBUST": "HOLD_W2_POSITIVE_NOT_ROBUST",
        "REJECT_W1_NONPOSITIVE_OR_NARROW": "REJECT_W2_NONPOSITIVE_OR_NARROW",
        "HOLD_W1_LOW_SAMPLE": "HOLD_W2_LOW_SAMPLE",
        "REJECT_W1_NO_EVENTS": "REJECT_W2_NO_EVENTS",
    }
    base["state"] = translate.get(str(base.get("state")), str(base.get("state")))
    base["family"] = family
    base["timeframe"] = "1h"
    base["w2_gate_pass"] = base["state"] == "PASS_W2_EFFECT"
    return base


def assert_w1_reproduction(frames: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]) -> dict[str, Any]:
    expected = {str(row["family"]): row for row in contract["candidates"]}
    actual = {
        "REGIME_MEAN_REVERSION_LONG": w1.summarize_events(
            regime_mean_reversion_events(frames, w1.W1_START_MS, w1.W1_END_MS)
        ),
        "VOL_EXPANSION_CONTINUATION_LONG": w1.summarize_events(
            vol_expansion_events(frames, w1.W1_START_MS, w1.W1_END_MS)
        ),
    }
    checks: dict[str, Any] = {}
    for family, row in actual.items():
        exp = expected[family]
        if int(row["event_count"]) != int(exp["w1_event_count"]):
            raise RuntimeError(f"W1_EVENT_PARITY:{family}")
        if abs(float(row["mean_net_bps_after_cost_floor"]) - float(exp["w1_mean_net_bps"])) > 1e-9:
            raise RuntimeError(f"W1_NET_PARITY:{family}")
        ci = row["daily_block_bootstrap95_net_bps"]
        exp_ci = exp["w1_daily_bootstrap95_net_bps"]
        if max(abs(float(ci[i]) - float(exp_ci[i])) for i in (0, 1)) > 1e-9:
            raise RuntimeError(f"W1_CI_PARITY:{family}")
        if int(row["positive_symbol_count"]) != int(exp["w1_positive_symbol_count"]):
            raise RuntimeError(f"W1_BREADTH_PARITY:{family}")
        checks[family] = "PASS"
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-root", type=Path, required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    contract = json.loads(ns.contract.read_text(encoding="utf-8"))
    if contract.get("state") != "FROZEN_BEFORE_W2_REPLAY":
        raise RuntimeError("CONTRACT_STATE")
    if contract.get("parent_w1_receipt_sha256") != "aab36b521c5ac9e2002d4dc04d34dfdac855653986f01efb761fe4cd43968fcf":
        raise RuntimeError("PARENT_W1_SHA")
    if int(contract.get("parameter_changes_after_w1", -1)) != 0 or int(contract.get("feature_changes_after_w1", -1)) != 0:
        raise RuntimeError("W1_RULE_MUTATION")

    raw = load_frames(ns.dataset_root.resolve(), WARMUP_START_MS, W2_END_MS)
    frames = w1.resample_frames(raw, "1h")
    for symbol, frame in frames.items():
        if int(frame.index[-1].timestamp() * 1000) >= W2_END_MS:
            raise RuntimeError(f"W3_LEAK:{symbol}")

    w1_parity = assert_w1_reproduction(frames, contract)
    results = {
        "REGIME_MEAN_REVERSION_LONG": summarize(
            "REGIME_MEAN_REVERSION_LONG",
            regime_mean_reversion_events(frames, W2_START_MS, W2_END_MS),
        ),
        "VOL_EXPANSION_CONTINUATION_LONG": summarize(
            "VOL_EXPANSION_CONTINUATION_LONG",
            vol_expansion_events(frames, W2_START_MS, W2_END_MS),
        ),
    }
    passes = [family for family, row in results.items() if row["w2_gate_pass"]]
    state = "PASS_W2_EFFECT_WITH_CANDIDATE" if passes else "FAIL_W2_NO_EFFECT_SURVIVOR"
    receipt: dict[str, Any] = {
        "schema_version": "zel.edge_factory_v2.w2_validate.v1",
        "state": state,
        "parent_w1_receipt_sha256": contract["parent_w1_receipt_sha256"],
        "dataset_sha256": contract["dataset_sha256"],
        "warmup_start_ms": WARMUP_START_MS,
        "w2_start_ms": W2_START_MS,
        "w2_end_exclusive_ms": W2_END_MS,
        "w1_semantic_parity": w1_parity,
        "results": results,
        "w2_pass_count": len(passes),
        "w2_pass_families": passes,
        "next": "AI_RED_TEAM_THEN_FREEZE_W3" if passes else "ROUTE_NEW_ECONOMIC_FAMILY_OR_SOURCE",
        "action": "hold" if passes else "route_change",
        "research_only": True,
        "ai_used_before_w2": False,
        "w3_metrics_inspected": False,
        "survivor_declared": False,
        "selection_authority": False,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    receipt["receipt_sha256"] = w1.stable_sha(receipt)
    w1.write_json(ns.out.resolve(), receipt)
    print(json.dumps({
        "state": state,
        "w2_pass_count": len(passes),
        "w2_pass_families": passes,
        "results": results,
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
