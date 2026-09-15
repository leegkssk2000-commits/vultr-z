"""Frozen standalone C4 30m controls and one-axis round-one children.

These are new timeframe-bound controls, never legacy outcome credit. Signals
have closed-bar availability; all lifecycle changes take effect next bar.
There is no evaluator, source fetcher, host injection, or live order path here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

TIMEFRAME_MIN = 30
TF_MS = TIMEFRAME_MIN * 60_000
MATERIALS = ("rbreaker_like", "rsi_swing_fail", "trend_ma_macd", "turtle_trend")
IDENTITIES = tuple(
    f"{material}_30m_{version}_v2"
    for material in MATERIALS
    for version in ("control", "round1")
)
PARAMS: dict[str, dict[str, Any]] = {
    "rbreaker_like": dict(
        stop_atr=0.9,
        target_r=1.8,
        max_hold=12,
        scratch_bars=4,
        scratch_r=0.35,
        trail_r=None,
        trail_atr=None,
    ),
    "rsi_swing_fail": dict(
        stop_atr=0.9,
        target_r=1.6,
        max_hold=18,
        scratch_bars=5,
        scratch_r=0.4,
        trail_r=None,
        trail_atr=None,
    ),
    "trend_ma_macd": dict(
        stop_atr=1.1,
        target_r=None,
        max_hold=32,
        scratch_bars=8,
        scratch_r=0.45,
        trail_r=1.0,
        trail_atr=1.8,
    ),
    "turtle_trend": dict(
        stop_atr=1.5,
        target_r=None,
        max_hold=24,
        scratch_bars=8,
        scratch_r=0.45,
        trail_r=1.0,
        trail_atr=2.0,
    ),
}
AXES = {
    "rbreaker_like": "EXIT_COMPLETED_CLOSE_INVALIDATES_FROZEN_RANGE_REFERENCE",
    "rsi_swing_fail": "EXIT_OPPOSITE_SWEEP_RECLAIM_WITH_RSI_TURN",
    "trend_ma_macd": "ENTRY_RESET_CANDLE_PRICE_BREAK_REPLACES_HISTOGRAM_ZERO_CROSS",
    "turtle_trend": "EXIT_DONCHIAN10_CLOSE_REPLACES_ATR_RUNNER_TRAIL",
}


def _identity(identity: str) -> tuple[str, bool]:
    if identity not in IDENTITIES:
        raise ValueError("UNKNOWN_FROZEN_MATERIAL_IDENTITY")
    return next(
        (m, "_round1_" in identity) for m in MATERIALS if identity.startswith(m + "_")
    )


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute price features per actual contiguous segment; never trust future features."""
    x = frame.copy().reset_index(drop=True)
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    }
    if not required.issubset(x):
        raise ValueError("MATERIAL_REQUIRED_CANONICAL_SCHEMA_MISSING")
    if x.empty:
        return x
    for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        values = pd.to_numeric(x[column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values != np.floor(values)).any():
            raise ValueError("MATERIAL_TIMESTAMP_INTEGER_REQUIRED")
    t = x["open_ts_ms"].astype("int64")
    if t.duplicated().any() or not t.is_monotonic_increasing or (t % TF_MS != 0).any():
        raise ValueError("MATERIAL_NONCANONICAL_TIME")
    prices = x[["open", "high", "low", "close"]].astype(float)
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError("MATERIAL_PRICE_INTEGRITY")
    if (
        (prices.high < prices[["open", "close", "low"]].max(axis=1))
        | (prices.low > prices[["open", "close", "high"]].min(axis=1))
    ).any():
        raise ValueError("MATERIAL_OHLC_GEOMETRY")
    close_ts = t + TF_MS
    if (x["close_ts_ms"] != close_ts).any() or (x["available_ts_ms"] < close_ts).any():
        raise ValueError("MATERIAL_CANDLE_CLOSE_OR_AVAILABILITY_INVALID")
    if x["segment_id"].isna().any():
        raise ValueError("MATERIAL_SEGMENT_REQUIRED")
    for alias, canonical in (
        ("ts_ms", "open_ts_ms"),
        ("available_at_ms", "available_ts_ms"),
    ):
        if alias in x and (x[alias] != x[canonical]).any():
            raise ValueError("MATERIAL_TIMESTAMP_ALIAS_MISMATCH")
    x["_feature_available_ts_ms"] = x["available_ts_ms"].astype("int64")
    reset = t.diff().ne(TF_MS) | x["segment_id"].ne(x["segment_id"].shift())
    x["_local_segment"] = reset.cumsum().astype(int)
    outputs: list[pd.DataFrame] = []
    for _, group in x.groupby("_local_segment", sort=False):
        g = group.copy()
        g["_feature_available_ts_ms"] = g["_feature_available_ts_ms"].cummax()
        c = g["close"].astype(float)
        prev = c.shift()
        tr = pd.concat(
            [g.high - g.low, (g.high - prev).abs(), (g.low - prev).abs()], axis=1
        ).max(axis=1)
        g["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
        for n in (21, 55, 100):
            g[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
        macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
        g["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
        delta = c.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        g["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        g.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
        g.loc[(loss == 0) & (gain == 0), "rsi"] = 50.0
        for n in (10, 20):
            g[f"hi{n}"] = g.high.shift().rolling(n).max()
            g[f"lo{n}"] = g.low.shift().rolling(n).min()
        outputs.append(g)
    result = pd.concat(outputs).sort_index()
    result.attrs["scalp7_material_causal_features_v2"] = True
    return result


def prepare_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Precompute once for chronological engine callbacks; sliced prefixes retain attrs."""
    return {symbol: _prepare(frame) for symbol, frame in frames.items()}


@dataclass
class _State:
    stage: int = 0
    side: int = 0
    since: int = -1
    reference: float = math.nan
    extreme: float = math.nan
    mode: str = ""
    trigger: float = math.nan


def _step(
    material: str,
    child: bool,
    state: _State,
    row: Mapping[str, Any],
    prev: Mapping[str, Any],
    i: int,
) -> _State | None:
    """C4 donor grammar with one explicitly declared child substitution."""
    if i < 101:
        return None
    if state.stage and i - state.since > 8:
        state.__dict__.update(_State().__dict__)
    c, p, h, low, a = (
        float(row[k]) for k in ("close", "previous_close", "high", "low", "atr")
    )
    e21, e55, e100 = (float(row[f"ema{n}"]) for n in (21, 55, 100))
    trend = 1 if c > e21 > e55 > e100 else -1 if c < e21 < e55 < e100 else 0
    hi, lo = float(row["hi20"]), float(row["lo20"])
    if not all(_finite(v) for v in (c, p, h, low, a, hi, lo)) or a <= 0:
        state.__dict__.update(_State().__dict__)
        return None
    emitted = False
    if material == "turtle_trend":
        if state.stage == 0:
            state.stage, state.since = 1, i
        elif c > hi or c < lo:
            state.side = 1 if c > hi else -1
            state.reference = hi if state.side == 1 else lo
            state.mode = "DONCHIAN_BREAKOUT"
            emitted = True
    elif material == "rbreaker_like":
        if state.stage == 0:
            state.stage, state.since = 1, i
        elif state.stage == 1:
            side = (
                1
                if c > hi
                else -1 if c < lo else 1 if low < lo < c else -1 if h > hi > c else 0
            )
            if side:
                state.side, state.stage, state.since = side, 2, i
                state.mode = "BREAKOUT" if c > hi or c < lo else "FAILED_BREAK_REVERSAL"
                state.reference = (
                    (hi if side == 1 else lo)
                    if state.mode == "BREAKOUT"
                    else (lo if side == 1 else hi)
                )
        elif state.side * (c - p) > 0:
            emitted = True
    elif material == "rsi_swing_fail":
        if state.stage == 0:
            if low < lo or h > hi:
                state.side = 1 if low < lo else -1
                state.reference = lo if state.side == 1 else hi
                state.extreme = low if state.side == 1 else h
                state.stage, state.since, state.mode = 1, i, "FAILED_SWING"
        elif state.stage == 1 and state.side * (c - state.reference) > 0:
            state.stage, state.since = 2, i
        elif (
            state.stage == 2
            and state.side * (float(row["rsi"]) - float(prev["rsi"])) > 0
        ):
            state.stage, state.since = 3, i
        elif state.stage == 3 and abs(e21 - e55) / a <= 1.2:
            emitted = True
    else:
        hist, hp = float(row["macd_hist"]), float(prev["macd_hist"])
        if state.stage == 0 and trend:
            state.side, state.stage, state.since = trend, 1, i
            state.reference, state.mode = e21, "GMMA_TREND"
        elif state.stage == 1 and state.side * hist <= 0:
            state.stage, state.since = 2, i
            state.trigger = h if state.side == 1 else low
        elif state.stage == 2:
            if child:
                # The only substituted trigger is price crossing the reset candle.
                if state.side * (c - state.trigger) > 0 and abs(c - e21) / a <= 1.25:
                    emitted = True
            elif state.side * hist > 0 >= state.side * hp and abs(c - e21) / a <= 1.25:
                emitted = True
    if emitted:
        result = _State(**state.__dict__)
        state.__dict__.update(_State().__dict__)
        return result
    return None


def generate_signals(
    frames: dict[str, pd.DataFrame],
    identity: str | None = None,
) -> list[dict[str, Any]]:
    """Generate 8 frozen standalone identities on already closed canonical 30m bars."""
    identities = (identity,) if identity else IDENTITIES
    for item in identities:
        _identity(item)
    events: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        x = _prepare(frame)
        if x.empty:
            continue
        for _, group in x.groupby("_local_segment", sort=False):
            rows = group.to_dict("records")
            for item in identities:
                material, child = _identity(item)
                state = _State()
                p = PARAMS[material]
                for i in range(1, len(rows)):
                    row = dict(rows[i], previous_close=rows[i - 1]["close"])
                    event = _step(material, child, state, row, rows[i - 1], i)
                    if event is None:
                        continue
                    side, close, a = event.side, float(row["close"]), float(row["atr"])
                    stop = close - side * float(p["stop_atr"]) * a
                    if stop <= 0:
                        continue
                    frozen_features = {
                        k: row[k]
                        for k in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "atr",
                            "ema21",
                            "ema55",
                            "ema100",
                            "rsi",
                            "macd_hist",
                            "hi20",
                            "lo20",
                        )
                    }
                    evidence = json.dumps(
                        frozen_features, sort_keys=True, allow_nan=False
                    )
                    events.append(
                        {
                            "identity": item,
                            "lane": "MATERIAL:" + material,
                            "timeframe_min": TIMEFRAME_MIN,
                            "symbol": symbol,
                            "side": side,
                            "signal_open_ts_ms": int(row["open_ts_ms"]),
                            "signal_ts_ms": int(row["_feature_available_ts_ms"]),
                            "segment_id": row["segment_id"],
                            "stop_price": stop,
                            "max_hold_bars": int(p["max_hold"]),
                            "take_profit_r": p["target_r"],
                            "invalidation_price": float(event.reference),
                            "exit_policy": "MATERIAL_LIFECYCLE_V2",
                            "meta": {
                                "material": material,
                                "round": 1 if child else 0,
                                "mode": event.mode,
                                "entry_atr": a,
                                "axis": (
                                    AXES[material]
                                    if child
                                    else "FROZEN_NEW_30M_CONTROL"
                                ),
                                "feature_sha256": hashlib.sha256(
                                    evidence.encode()
                                ).hexdigest(),
                                "features": frozen_features,
                                "authority": "RESEARCH_ONLY",
                                "order": "BLOCKED",
                            },
                        }
                    )
    return sorted(events, key=lambda e: (e["signal_ts_ms"], e["identity"], e["symbol"]))


def exit_update(
    position: Mapping[str, Any],
    bar: Mapping[str, Any],
    history: pd.DataFrame,
) -> dict[str, Any]:
    """Inspect current completed bar; caller fills exits/stop updates on next bar."""
    signal = position["signal"]
    material, child = _identity(str(signal["identity"]))
    side = int(position["side"])
    if side not in (-1, 1):
        raise ValueError("MATERIAL_POSITION_SIDE")
    out: dict[str, Any] = {"exit_next_open": False, "reason": None, "next_stop": None}
    c = float(bar["close"])
    p = PARAMS[material]
    hold = int(position["hold_bars"])
    mfe = float(position["mfe_R"])
    if hold >= int(p["scratch_bars"]) and mfe < float(p["scratch_r"]):
        return dict(out, exit_next_open=True, reason="PRESERVED_DONOR_NO_PROGRESS")
    reference = signal.get("invalidation_price")
    if child and material == "rbreaker_like" and _finite(reference):
        if side * (c - float(reference)) <= 0:
            return dict(out, exit_next_open=True, reason="RANGE_THESIS_INVALIDATED")
    if child and material in ("rsi_swing_fail", "turtle_trend"):
        x = (
            history
            if history.attrs.get("scalp7_material_causal_features_v2")
            else _prepare(history)
        )
        if len(x) >= 2:
            r, prev = x.iloc[-1], x.iloc[-2]
            # Caller must provide the completed prefix, never a future history tail.
            current_ts = int(bar.get("open_ts_ms", bar.get("ts_ms", -1)))
            if int(r["open_ts_ms"]) != current_ts:
                raise ValueError("MATERIAL_HISTORY_NOT_CURRENT_CLOSED_PREFIX")
            decision_ts = int(
                bar.get(
                    "available_at_ms", bar.get("available_ts_ms", current_ts + TF_MS)
                )
            )
            if int(r["_feature_available_ts_ms"]) > decision_ts:
                return dict(out, reason="MATERIAL_HISTORY_NOT_YET_AVAILABLE")
            if material == "rsi_swing_fail":
                opposite = (
                    side == 1
                    and float(r.high) > float(r.hi20) > c
                    and float(r.rsi) < float(prev.rsi)
                ) or (
                    side == -1
                    and float(r.low) < float(r.lo20) < c
                    and float(r.rsi) > float(prev.rsi)
                )
                if opposite:
                    return dict(
                        out, exit_next_open=True, reason="OPPOSITE_SWING_FAILURE"
                    )
            elif (side == 1 and c < float(r.lo10)) or (
                side == -1 and c > float(r.hi10)
            ):
                return dict(out, exit_next_open=True, reason="DONCHIAN10_CLOSE_EXIT")
    # Turtle round1 replaces only the runner exit; its initial stop/scratch remain.
    if (
        p["trail_r"] is not None
        and mfe >= float(p["trail_r"])
        and not (child and material == "turtle_trend")
    ):
        a = float(signal["meta"]["entry_atr"])
        next_stop = c - side * float(p["trail_atr"]) * a
        old = float(position["stop_price"])
        if side * (next_stop - old) > 0:
            out["next_stop"] = next_stop
    return out


def behavior_cosine(
    left: Mapping[str, float], right: Mapping[str, float]
) -> float | None:
    """Sparse signed exposure on the same symbol/30m decision grid; missing means flat."""
    keys = sorted(set(left) | set(right))
    a = np.array([left.get(k, 0.0) for k in keys], dtype=float)
    b = np.array([right.get(k, 0.0) for k in keys], dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("BEHAVIOR_NONFINITE")
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return None if denom == 0 else float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def assess_b_grade(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
    fresh: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Require hashed preregistration, exact comparison/rule binding, and genuine fresh."""
    reasons: list[str] = []
    minimum = contract.get("minimum_trades")
    minimum_fresh = contract.get("minimum_fresh_trades")
    if any(
        not isinstance(v, int) or isinstance(v, bool) or v <= 0
        for v in (minimum, minimum_fresh)
    ) or not _sha(contract.get("source_sha256")):
        reasons.append("SAMPLE_GATE_UNBOUND")
    for label, row in (("PARENT", parent), ("CHILD", child), ("FRESH", fresh)):
        if (
            row.get("source_integrity") is not True
            or row.get("cost_bound") is not True
            or not _sha(row.get("receipt_sha256"))
        ):
            reasons.append(label + "_SOURCE_OR_COST_UNBOUND")
        threshold = minimum_fresh if label == "FRESH" else minimum
        trades = row.get("T")
        if (
            not isinstance(trades, int)
            or isinstance(trades, bool)
            or trades <= 0
            or (isinstance(threshold, int) and trades < threshold)
        ):
            reasons.append(label + "_INSUFFICIENT_SAMPLE")
        if not all(_finite(row.get(k)) for k in ("Net", "PF", "DD", "loss_tail")):
            reasons.append(label + "_ECONOMICS_UNBOUND")
        elif label != "PARENT" and (float(row["Net"]) <= 0 or float(row["PF"]) <= 1):
            reasons.append(label + "_NEGATIVE_AFTER_COST")
        if _finite(row.get("DD")) and float(row["DD"]) < 0:
            reasons.append(label + "_NEGATIVE_DD_INVALID")
        if _finite(row.get("loss_tail")) and float(row["loss_tail"]) < 0:
            reasons.append(label + "_LOSS_TAIL_MUST_BE_POSITIVE_MAGNITUDE")
    rule = contract.get("rule_sha256")
    if (
        not _sha(rule)
        or rule != child.get("rule_sha256")
        or rule != fresh.get("rule_sha256")
    ):
        reasons.append("FRESH_RULE_BINDING_MISMATCH")
    frozen, start = contract.get("frozen_at_ms"), fresh.get("start_ts_ms")
    if (
        fresh.get("evidence_kind") != "GENUINE_FRESH_FROZEN"
        or not isinstance(frozen, int)
        or not isinstance(start, int)
        or start < frozen
    ):
        reasons.append("FRESH_BOUNDARY_UNBOUND")
    if not parent.get("comparison_id") or parent.get("comparison_id") != child.get(
        "comparison_id"
    ):
        reasons.append("PARENT_CHILD_OPPORTUNITY_OR_COST_DOMAIN_MISMATCH")
    if not all(
        _finite(parent.get(k)) and _finite(child.get(k))
        for k in ("Net", "DD", "loss_tail")
    ):
        reasons.append("PARENT_MARGINAL_UNBOUND")
    elif not (
        float(child["Net"]) > float(parent["Net"])
        and float(child["DD"]) <= float(parent["DD"])
        and float(child["loss_tail"]) <= float(parent["loss_tail"])
    ):
        reasons.append("PARENT_MARGINAL_OR_RISK_NONIMPROVEMENT")
    return {
        "grade": "C" if reasons else "B",
        "reasons": reasons,
        "B_eligible": not reasons,
        "fresh_verified": not reasons,
        "promotion_authority": False,
        "host_touch": False,
        "order": "BLOCKED",
    }


def fusion_eligible(
    left: Mapping[str, Any], right: Mapping[str, Any], cosine: float | None
) -> bool:
    return bool(
        left.get("grade") == right.get("grade") == "B"
        and left.get("B_eligible") is True
        and right.get("B_eligible") is True
        and left.get("fresh_verified") is True
        and right.get("fresh_verified") is True
        and left.get("identity")
        and right.get("identity")
        and left["identity"] != right["identity"]
        and cosine is not None
        and _finite(cosine)
        and -1.0 <= cosine < 0.85
    )
