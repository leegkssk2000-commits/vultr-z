"""Past-only 90-day context fits and nonoverlapping 30-day research windows."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

DAY = 86_400_000
HOUR = 3_600_000
HALF_HOUR = HOUR // 2
SYMBOLS = {"BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT"}


def windows(start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    if start_ms % DAY or end_ms % DAY or end_ms <= start_ms + 90 * DAY:
        raise ValueError("UTC_12M_CALENDAR_REQUIRED")
    result = []
    opened = start_ms + 90 * DAY
    index = 0
    while opened < end_ms:
        closed = min(opened + 30 * DAY, end_ms)
        result.append(
            {
                "label": "validation" if index == 0 else "rolling_" + str(index),
                "partition": "validation" if index == 0 else "rolling",
                "train_start_ms": opened - 90 * DAY,
                "train_end_ms": opened,
                "start_ms": opened,
                "end_ms": closed,
                "partial_window": closed - opened < 30 * DAY,
                "formation_inspection": "STRATEGY_FORMED_AFTER_HISTORY_OBSERVED",
                "oos_scope": "PAST_ONLY_PARAMETER_FIT_NOT_GENUINE_FRESH",
                "initial_position": "FLAT_INDEPENDENT_WINDOW",
                "boundary_trade_policy": "NO_SYNTHETIC_CLOSE_EXCLUDE_UNRESOLVED_AND_CROSS_BOUNDARY",
            }
        )
        opened = closed
        index += 1
    return result


def hourly(frames30: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result = {}
    for symbol, frame in frames30.items():
        work = frame.copy()
        required = {
            "open_ts_ms",
            "close_ts_ms",
            "available_ts_ms",
            "open",
            "high",
            "low",
            "close",
            "segment_id",
        }
        if not required.issubset(work):
            raise ValueError("CONTEXT_CANONICAL_BAR_SCHEMA_REQUIRED")
        stamps = work[["open_ts_ms", "close_ts_ms", "available_ts_ms"]].to_numpy(
            dtype=float
        )
        if (
            not np.isfinite(stamps).all()
            or not np.equal(stamps, np.floor(stamps)).all()
        ):
            raise ValueError("CONTEXT_INTEGER_TIMESTAMPS_REQUIRED")
        if (
            work["open_ts_ms"].duplicated().any()
            or not work["open_ts_ms"].is_monotonic_increasing
        ):
            raise ValueError("CONTEXT_DUPLICATE_OR_UNORDERED_BAR")
        if (work["open_ts_ms"] % HALF_HOUR != 0).any() or (
            work["close_ts_ms"] != work["open_ts_ms"] + HALF_HOUR
        ).any():
            raise ValueError("CONTEXT_EXACT_UTC_30M_REQUIRED")
        if (work["available_ts_ms"] < work["close_ts_ms"]).any() or work[
            "segment_id"
        ].isna().any():
            raise ValueError("CONTEXT_AVAILABILITY_OR_SEGMENT_INVALID")
        prices = work[["open", "high", "low", "close"]].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or not (prices > 0).all():
            raise ValueError("CONTEXT_INVALID_PRICE")
        if (
            (work["low"] > work[["open", "close"]].min(axis=1))
            | (work["high"] < work[["open", "close"]].max(axis=1))
        ).any():
            raise ValueError("CONTEXT_INVALID_CANDLE_GEOMETRY")
        work["bucket"] = (work["open_ts_ms"].astype("int64") // HOUR) * HOUR
        grouped = work.groupby("bucket", sort=True)
        out = (
            grouped.agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                count=("open", "size"),
                segment_id=("segment_id", "first"),
                segments=("segment_id", "nunique"),
                first=("open_ts_ms", "min"),
                last=("close_ts_ms", "max"),
                available_ts_ms=("available_ts_ms", "max"),
            )
            .reset_index()
            .rename(columns={"bucket": "open_ts_ms"})
        )
        out = out[
            (out["count"] == 2)
            & (out["segments"] == 1)
            & (out["first"] == out["open_ts_ms"])
            & (out["last"] == out["open_ts_ms"] + HOUR)
        ].copy()
        breaks = (out["open_ts_ms"].diff() != HOUR) | out["segment_id"].ne(
            out["segment_id"].shift()
        )
        out["context_segment"] = breaks.cumsum()
        pieces = []
        for _, segment in out.groupby("context_segment", sort=True):
            x = segment.copy()
            # EMA/ATR retain all earlier inputs in a segment, so availability does too.
            x["available_ts_ms"] = x["available_ts_ms"].cummax()
            close = x["close"]
            x["dir"] = np.sign(
                close.ewm(span=21, adjust=False).mean()
                - close.ewm(span=55, adjust=False).mean()
            )
            x["r24"] = close / close.shift(24) - 1
            prev = close.shift(1)
            tr = pd.concat(
                [
                    x["high"] - x["low"],
                    (x["high"] - prev).abs(),
                    (x["low"] - prev).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
            x["vr"] = atr / atr.rolling(72, min_periods=36).median()
            pieces.append(x)
        if pieces:
            result[symbol] = pd.concat(pieces).set_index("open_ts_ms").sort_index()
        else:
            result[symbol] = pd.DataFrame(
                columns=["open_ts_ms", "available_ts_ms", "dir", "r24", "vr"]
            ).set_index("open_ts_ms")
    return result


def cross_features(frames30: dict[str, pd.DataFrame]) -> pd.DataFrame:
    by = hourly(frames30)
    if set(by) != SYMBOLS:
        raise ValueError("EXACT_SIX_SYMBOL_CONTEXT_REQUIRED")
    common = sorted(set.intersection(*(set(x.index) for x in by.values())))
    if not common:
        return pd.DataFrame(
            columns=[
                "context_open_ts_ms",
                "regime_available_ts_ms",
                "dispersion24",
                "mean_abs24",
                "breadth",
                "vol_ratio",
            ]
        )
    r24 = np.column_stack([x.reindex(common)["r24"].to_numpy() for x in by.values()])
    dirs = np.column_stack([x.reindex(common)["dir"].to_numpy() for x in by.values()])
    vr = np.column_stack([x.reindex(common)["vr"].to_numpy() for x in by.values()])
    available = np.column_stack(
        [x.reindex(common)["available_ts_ms"].to_numpy() for x in by.values()]
    )
    valid = (
        np.isfinite(r24).all(axis=1)
        & np.isfinite(dirs).all(axis=1)
        & np.isfinite(vr).all(axis=1)
    )
    return (
        pd.DataFrame(
            {
                "context_open_ts_ms": np.array(common)[valid],
                "regime_available_ts_ms": available.max(axis=1)[valid].astype("int64"),
                "dispersion24": np.std(r24, axis=1)[valid],
                "mean_abs24": np.mean(np.abs(r24), axis=1)[valid],
                "breadth": dirs.sum(axis=1)[valid],
                "vol_ratio": np.median(vr, axis=1)[valid],
            }
        )
        .sort_values(["regime_available_ts_ms", "context_open_ts_ms"])
        .reset_index(drop=True)
    )


def fit_context(features: pd.DataFrame, window: dict[str, Any]) -> dict[str, Any]:
    if (
        int(window["train_end_ms"]) != int(window["start_ms"])
        or int(window["train_start_ms"]) != int(window["start_ms"]) - 90 * DAY
        or int(window["end_ms"]) <= int(window["start_ms"])
        or int(window["end_ms"]) - int(window["start_ms"]) > 30 * DAY
        or any(
            int(window[key]) % DAY
            for key in ("train_start_ms", "train_end_ms", "start_ms", "end_ms")
        )
    ):
        raise ValueError("CONTEXT_90D_TRAIN_30D_WINDOW_REQUIRED")
    cols = [
        "context_open_ts_ms",
        "regime_available_ts_ms",
        "dispersion24",
        "mean_abs24",
        "breadth",
        "vol_ratio",
    ]
    if (
        not set(cols).issubset(features)
        or not np.isfinite(features[cols].to_numpy(dtype=float)).all()
    ):
        raise ValueError("CONTEXT_FEATURE_INTEGRITY")
    if features["context_open_ts_ms"].duplicated().any():
        raise ValueError("CONTEXT_DUPLICATE_FEATURE_HOUR")
    train = features[
        (features["regime_available_ts_ms"] >= window["train_start_ms"])
        & (features["regime_available_ts_ms"] < window["train_end_ms"])
        & (features["context_open_ts_ms"] + HOUR >= window["train_start_ms"])
        & (features["regime_available_ts_ms"] >= features["context_open_ts_ms"] + HOUR)
        & (
            features["regime_available_ts_ms"]
            <= features["context_open_ts_ms"] + 2 * HOUR
        )
    ]
    if len(train) < 72:
        raise ValueError("INSUFFICIENT_PAST_CONTEXT")
    train = train.sort_values(["regime_available_ts_ms", "context_open_ts_ms"])
    training_feature_sha256 = hashlib.sha256(
        train[cols].to_json(orient="split", index=False, double_precision=15).encode()
    ).hexdigest()
    result = {
        "training_feature_sha256": training_feature_sha256,
        "disp_q67": float(train["dispersion24"].quantile(0.67)),
        "meanabs_q85": float(train["mean_abs24"].quantile(0.85)),
        "vol_q25": float(train["vol_ratio"].quantile(0.25)),
        "vol_q67": float(train["vol_ratio"].quantile(0.67)),
        "train_start_ms": int(window["train_start_ms"]),
        "train_end_ms": int(window["train_end_ms"]),
        "last_fit_observation_ms": int(train["regime_available_ts_ms"].max()),
        "train_rows": len(train),
    }
    result["sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def classify(row: dict[str, Any], fit: dict[str, Any]) -> str:
    if (
        row["mean_abs24"] >= fit["meanabs_q85"]
        and row["dispersion24"] >= fit["disp_q67"]
    ):
        return "PANIC_DISPERSION"
    if abs(row["breadth"]) >= 4:
        return (
            "TREND_DISPERSED"
            if row["dispersion24"] >= fit["disp_q67"]
            else "TREND_COHERENT"
        )
    if row["vol_ratio"] <= fit["vol_q25"]:
        return "COMPRESSION"
    if row["vol_ratio"] >= fit["vol_q67"]:
        return "VOL_EXPANSION_MIXED"
    return "RANGE_MIXED"


def bind_context(
    frames: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    window_list: list[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    if any(
        window_list[i]["start_ms"] != window_list[i - 1]["end_ms"]
        for i in range(1, len(window_list))
    ):
        raise ValueError("CONTEXT_WINDOWS_MUST_BE_CONTIGUOUS_NONOVERLAPPING")
    fits = [fit_context(features, window) for window in window_list]
    features = features.sort_values(["regime_available_ts_ms", "context_open_ts_ms"])
    result = {}
    for symbol, frame in frames.items():
        x = pd.merge_asof(
            frame.sort_values("available_ts_ms"),
            features,
            left_on="available_ts_ms",
            right_on="regime_available_ts_ms",
            direction="backward",
            tolerance=HOUR,
        )
        x["regime"] = "NO_CONTEXT"
        x["regime_fit_end_ts_ms"] = -1
        x["regime_spec_sha256"] = ""
        records = x.to_dict("records")
        for record in records:
            decision = int(record["available_ts_ms"])
            if not np.isfinite(record.get("dispersion24", np.nan)):
                continue
            context_close = int(record["context_open_ts_ms"]) + HOUR
            if not context_close <= decision <= context_close + HOUR:
                continue
            for window, fit in zip(window_list, fits):
                if window["start_ms"] <= decision < window["end_ms"]:
                    if fit["last_fit_observation_ms"] >= decision:
                        raise ValueError("FUTURE_TRAINING_FORBIDDEN")
                    record["regime"] = classify(record, fit)
                    record["regime_fit_end_ts_ms"] = fit["last_fit_observation_ms"]
                    record["regime_spec_sha256"] = fit["sha256"]
                    break
        enriched = (
            pd.DataFrame(records).sort_values("open_ts_ms").reset_index(drop=True)
        )
        enriched.attrs = frame.attrs.copy()
        result[symbol] = enriched
    return result, fits
