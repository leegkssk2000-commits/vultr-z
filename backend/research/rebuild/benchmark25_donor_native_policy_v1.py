# mypy: follow_imports=skip

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

_overlay: Any = importlib.import_module(
    "backend.research.rebuild." + "benchmark25_transfer_overlay_v1"
)
context = _overlay.context
_micro_align = _overlay._micro_align
_micro_available = _overlay._micro_available
_kernel: Any = importlib.import_module("backend.research.rebuild." + "policy_kernel_v1")
ema = _kernel.ema
rsi = _kernel.rsi

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "backend/research/rebuild/benchmark25_donor_native_spec_v1.json"


@dataclass(frozen=True)
class NativeDecision:
    strategy_id: str
    child_id: str
    no_trade: bool
    side: str
    signal_ts: int
    entry_rule: str
    mode: str
    atr: float
    stop_atr_mult: float
    target_r: float | None
    timeout_bars: int
    scratch_after_bars: int
    scratch_mfe_below_r: float
    trail_activate_r: float | None
    trail_atr_mult: float | None
    benchmark_ids: tuple[str, ...]
    transfer: tuple[str, ...]
    reason_codes: tuple[str, ...]


def load_spec() -> dict[str, Any]:
    value = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if value.get("state") != "FROZEN_25_DONOR_NATIVE_ARCHITECTURES":
        raise RuntimeError("DONOR_NATIVE_SPEC_INVALID")
    if len(value.get("children") or {}) != 25:
        raise RuntimeError("DONOR_NATIVE_SPEC_COUNT_INVALID")
    return value


def _flat(sid: str, spec: Mapping[str, Any], ts: int, reason: str) -> NativeDecision:
    return NativeDecision(
        sid,
        str(spec["child_id"]),
        True,
        "flat",
        ts,
        str(spec["entry_handler"]),
        "NO_TRADE",
        0.0,
        float(spec["stop_atr_mult"]),
        spec.get("target_r"),
        int(spec["timeout_bars"]),
        int(spec["scratch_after_bars"]),
        float(spec["scratch_if_mfe_below_r"]),
        spec.get("trail_activate_r"),
        spec.get("trail_atr_mult"),
        tuple(spec["benchmark_ids"]),
        tuple(spec["transfer"]),
        (reason,),
    )


def _micro_side(side: str, micro: Mapping[str, Any] | None) -> bool:
    return bool(_micro_available(micro) and _micro_align(side, micro or {}))


def _mfi(bars: Sequence[Mapping[str, Any]], length: int = 14) -> float:
    xs = bars[-(length + 1) :]
    pos = 0.0
    neg = 0.0
    prev_tp = None
    for bar in xs:
        tp = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0
        flow = tp * max(0.0, float(bar.get("volume") or 0.0))
        if prev_tp is not None:
            if tp > prev_tp:
                pos += flow
            elif tp < prev_tp:
                neg += flow
        prev_tp = tp
    if neg <= 1e-12:
        return 100.0
    return 100.0 - 100.0 / (1.0 + pos / neg)


def _obv_delta(bars: Sequence[Mapping[str, Any]], length: int = 34) -> float:
    xs = bars[-(length + 1) :]
    out = 0.0
    for a, b in zip(xs[:-1], xs[1:]):
        d = float(b["close"]) - float(a["close"])
        v = max(0.0, float(b.get("volume") or 0.0))
        out += v if d > 0 else -v if d < 0 else 0.0
    return out


def _finish(
    sid: str, spec: Mapping[str, Any], c: Mapping[str, Any], side: str, mode: str
) -> NativeDecision:
    return NativeDecision(
        sid,
        str(spec["child_id"]),
        False,
        side,
        int(c["ts"]),
        str(spec["entry_handler"]),
        mode,
        float(c["a"]),
        float(spec["stop_atr_mult"]),
        spec.get("target_r"),
        int(spec["timeout_bars"]),
        int(spec["scratch_after_bars"]),
        float(spec["scratch_if_mfe_below_r"]),
        spec.get("trail_activate_r"),
        spec.get("trail_atr_mult"),
        tuple(spec["benchmark_ids"]),
        tuple(spec["transfer"]),
        ("DONOR_NATIVE_ENTRY", mode),
    )


def build_native_decision(
    strategy_id: str,
    bars: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    micro: Mapping[str, Any] | None = None,
) -> NativeDecision:
    if len(bars) < 120:
        ts = int(bars[-1]["ts_ms"]) if bars else 0
        return _flat(strategy_id, spec, ts, "WARMUP_120")
    c = dict(context(bars))
    c["ts"] = int(bars[-1]["ts_ms"])
    if spec.get("microstructure_required") and not _micro_available(micro):
        return _flat(strategy_id, spec, int(c["ts"]), "REAL_MICROSTRUCTURE_REQUIRED")
    sid = strategy_id
    a = float(c["a"])
    close = float(c["close"])
    prev = float(c["prev"])
    long = False
    short = False
    mode = str(spec["entry_handler"])
    if sid == "turtle_trend":
        long = close > float(c["hi20"])
        short = close < float(c["lo20"])
    elif sid == "bb_revert":
        range_ok = abs(float(c["e21"]) - float(c["e55"])) / a <= 0.65
        long = (
            range_ok
            and float(c["prev_low"])
            < float(c["mean20"]) - 0.45 * float(c["bb_width_atr"]) * a
            and close > float(c["mean20"]) - 0.45 * float(c["bb_width_atr"]) * a
        )
        short = (
            range_ok
            and float(c["prev_high"])
            > float(c["mean20"]) + 0.45 * float(c["bb_width_atr"]) * a
            and close < float(c["mean20"]) + 0.45 * float(c["bb_width_atr"]) * a
        )
    elif sid == "anchor_vwap_trend":
        long = (
            float(c["e21"]) > float(c["e55"])
            and prev <= float(c["avwap_long"])
            and close > float(c["avwap_long"])
            and float(c["rel_vol20"]) >= 0.8
        )
        short = (
            float(c["e21"]) < float(c["e55"])
            and prev >= float(c["avwap_short"])
            and close < float(c["avwap_short"])
            and float(c["rel_vol20"]) >= 0.8
        )
    elif sid == "vwap_revert":
        long = (
            prev < float(c["vwap20"]) - 0.7 * a
            and close > prev
            and _micro_side("long", micro)
        )
        short = (
            prev > float(c["vwap20"]) + 0.7 * a
            and close < prev
            and _micro_side("short", micro)
        )
    elif sid == "break_and_continue":
        compression = float(c["bb_prev_width_atr"]) <= 3.0
        long = (
            compression
            and float(c["prev_high"]) > float(c["hi_pre"])
            and float(c["low"]) <= float(c["hi_pre"]) + 0.35 * a
            and close > float(c["hi_pre"])
            and float(c["dist21_atr"]) <= 1.5
        )
        short = (
            compression
            and float(c["prev_low"]) < float(c["lo_pre"])
            and float(c["high"]) >= float(c["lo_pre"]) - 0.35 * a
            and close < float(c["lo_pre"])
            and float(c["dist21_atr"]) <= 1.5
        )
    elif sid == "keltner_trend":
        long = (
            bool(c["trend_long"])
            and close > float(c["e21"]) + 1.2 * a
            and float(c["range_atr"]) >= 0.8
            and float(c["dist21_atr"]) <= 1.6
        )
        short = (
            bool(c["trend_short"])
            and close < float(c["e21"]) - 1.2 * a
            and float(c["range_atr"]) >= 0.8
            and float(c["dist21_atr"]) <= 1.6
        )
    elif sid == "squeeze_break":
        compression = float(c["bb_prev_width_atr"]) <= 2.2
        long = (
            compression
            and float(c["range_atr"]) >= 0.9
            and close > float(c["hi20"])
            and close > float(c["e21"])
            and float(c["dist21_atr"]) <= 1.5
        )
        short = (
            compression
            and float(c["range_atr"]) >= 0.9
            and close < float(c["lo20"])
            and close < float(c["e21"])
            and float(c["dist21_atr"]) <= 1.5
        )
    elif sid == "supertrend_pullback":
        long = (
            bool(c["trend_long"])
            and prev <= float(c["e21"]) + 0.6 * a
            and close > prev
            and close > float(c["e21"])
        )
        short = (
            bool(c["trend_short"])
            and prev >= float(c["e21"]) - 0.6 * a
            and close < prev
            and close < float(c["e21"])
        )
    elif sid == "trend_ma_macd":
        closes = [float(x["close"]) for x in bars]
        macd = [x - y for x, y in zip(ema(closes, 12), ema(closes, 26))]
        signal = ema(macd, 9)
        hist = [x - y for x, y in zip(macd, signal)]
        long = (
            bool(c["trend_long"])
            and hist[-1] > 0 >= hist[-2]
            and float(c["dist21_atr"]) <= 1.25
        )
        short = (
            bool(c["trend_short"])
            and hist[-1] < 0 <= hist[-2]
            and float(c["dist21_atr"]) <= 1.25
        )
    elif sid == "trend_rider":
        long = (
            bool(c["trend_long"])
            and float(c["e50"]) >= float(c["p50"])
            and prev <= float(c["e21"]) + 0.8 * a
            and close > prev
            and float(c["dist21_atr"]) <= 1.6
        )
        short = (
            bool(c["trend_short"])
            and float(c["e50"]) <= float(c["p50"])
            and prev >= float(c["e21"]) - 0.8 * a
            and close < prev
            and float(c["dist21_atr"]) <= 1.6
        )
    elif sid == "liquidity_sweep":
        long = (
            float(c["low"]) < float(c["lo20"])
            and close > float(c["lo20"])
            and _micro_side("long", micro)
        )
        short = (
            float(c["high"]) > float(c["hi20"])
            and close < float(c["hi20"])
            and _micro_side("short", micro)
        )
    elif sid == "scalp_snap":
        c3 = float(bars[-3]["close"])
        long = (
            prev - c3 <= -0.9 * a
            and close - prev >= 0.4 * a
            and _micro_side("long", micro)
        )
        short = (
            prev - c3 >= 0.9 * a
            and close - prev <= -0.4 * a
            and _micro_side("short", micro)
        )
    elif sid == "vol_spike_fade":
        vm = sum(float(x.get("volume") or 0.0) for x in bars[-22:-2]) / 20.0
        prev_vol = float(bars[-2].get("volume") or 0.0)
        prev_range = float(c["prev_high"]) - float(c["prev_low"])
        ti = float((micro or {}).get("trade_imbalance") or 0.0)
        im = float((micro or {}).get("imbalance_delta") or 0.0)
        prev_open = float(bars[-2]["open"])
        long = (
            prev_vol >= 1.8 * vm
            and prev_range >= 1.2 * a
            and prev < prev_open
            and close > prev
            and ti >= -0.05
            and im > 0
        )
        short = (
            prev_vol >= 1.8 * vm
            and prev_range >= 1.2 * a
            and prev > prev_open
            and close < prev
            and ti <= 0.05
            and im < 0
        )
    elif sid == "range_fade":
        range_ok = abs(float(c["e21"]) - float(c["e55"])) / a <= 0.7
        long = (
            range_ok and float(c["low"]) < float(c["lo20"]) and close > float(c["lo20"])
        )
        short = (
            range_ok
            and float(c["high"]) > float(c["hi20"])
            and close < float(c["hi20"])
        )
    elif sid == "fvg_revert":
        prev_range = float(c["prev_high"]) - float(c["prev_low"])
        mid = (float(c["prev_high"]) + float(c["prev_low"])) / 2.0
        prev_open = float(bars[-2]["open"])
        long = prev_range >= 1.3 * a and prev < prev_open and close > mid
        short = prev_range >= 1.3 * a and prev > prev_open and close < mid
    elif sid == "pivot_reversal":
        long = (
            float(c["low"]) < float(c["lo20"])
            and close > float(c["lo20"])
            and close >= float(c["vwap20"])
        )
        short = (
            float(c["high"]) > float(c["hi20"])
            and close < float(c["hi20"])
            and close <= float(c["vwap20"])
        )
    elif sid == "rsi_swing_fail":
        closes = [float(x["close"]) for x in bars]
        rsi_prev = rsi(closes[:-1], 14)
        range_ok = abs(float(c["e21"]) - float(c["e55"])) / a <= 1.2
        long = (
            range_ok
            and float(c["low"]) < float(c["lo20"])
            and close > float(c["lo20"])
            and float(c["rsi"]) > rsi_prev
        )
        short = (
            range_ok
            and float(c["high"]) > float(c["hi20"])
            and close < float(c["hi20"])
            and float(c["rsi"]) < rsi_prev
        )
    elif sid == "alpha_combo":
        gap = abs(float(c["e21"]) - float(c["e55"])) / a
        if gap >= 0.7:
            long = (
                bool(c["trend_long"])
                and close > float(c["hi20"])
                and float(c["rel_vol20"]) >= 1.0
            )
            short = (
                bool(c["trend_short"])
                and close < float(c["lo20"])
                and float(c["rel_vol20"]) >= 1.0
            )
            mode = "MOMENTUM_REGIME"
        else:
            long = prev < float(c["vwap20"]) - 0.6 * a and close > prev
            short = prev > float(c["vwap20"]) + 0.6 * a and close < prev
            mode = "MEAN_REVERSION_REGIME"
    elif sid == "ema_ribbon_scalp":
        ribbon_long = close > float(c["e8"]) > float(c["e21"]) > float(c["e55"])
        ribbon_short = close < float(c["e8"]) < float(c["e21"]) < float(c["e55"])
        long = (
            ribbon_long
            and float(c["ribbon_sep_atr"]) >= 0.2
            and prev <= float(c["e8"]) + 0.4 * a
            and close > prev
            and float(c["dist21_atr"]) <= 0.85
        )
        short = (
            ribbon_short
            and float(c["ribbon_sep_atr"]) >= 0.2
            and prev >= float(c["e8"]) - 0.4 * a
            and close < prev
            and float(c["dist21_atr"]) <= 0.85
        )
    elif sid == "mfi_rsi_div":
        closes = [float(x["close"]) for x in bars]
        rv_prev = rsi(closes[:-1], 14)
        mfi_now = _mfi(bars, 14)
        mfi_prev = _mfi(bars[:-1], 14)
        long = (
            float(c["low"]) <= float(c["lo50"])
            and close > prev
            and float(c["rsi"]) > rv_prev
            and mfi_now > mfi_prev
        )
        short = (
            float(c["high"]) >= float(c["hi50"])
            and close < prev
            and float(c["rsi"]) < rv_prev
            and mfi_now < mfi_prev
        )
    elif sid == "obv_trend":
        obv_delta = _obv_delta(bars, 34)
        long = (
            bool(c["trend_long"])
            and close > float(c["hi20"])
            and float(c["rel_vol20"]) >= 1.15
            and obv_delta > 0
        )
        short = (
            bool(c["trend_short"])
            and close < float(c["lo20"])
            and float(c["rel_vol20"]) >= 1.15
            and obv_delta < 0
        )
    elif sid == "grid_rebalance":
        range_ok = abs(float(c["e21"]) - float(c["e55"])) / a <= 0.7
        ext = (close - float(c["vwap50"])) / a
        long = range_ok and ext <= -0.9 and close > prev
        short = range_ok and ext >= 0.9 and close < prev
    elif sid == "rbreaker_like":
        breakout_l = close > float(c["hi20"]) and float(c["rel_vol20"]) >= 1.0
        breakout_s = close < float(c["lo20"]) and float(c["rel_vol20"]) >= 1.0
        fail_l = float(c["low"]) < float(c["lo20"]) and close > float(c["lo20"])
        fail_s = float(c["high"]) > float(c["hi20"]) and close < float(c["hi20"])
        long = breakout_l or fail_l
        short = breakout_s or fail_s
        mode = "BREAKOUT" if breakout_l or breakout_s else "FAILED_BREAK_REVERSAL"
    elif sid == "session_bias":
        liquid = (
            float(c["rel_vol20"]) >= 1.05
            and float(c["range_atr"]) >= 0.8
            and int(c["hour"]) not in (21, 22, 23)
        )
        long = liquid and close > float(c["hi20"])
        short = liquid and close < float(c["lo20"])
    elif sid == "sr_levels":
        cont_l = close > float(c["hi50"]) and float(c["rel_vol50"]) >= 1.25
        cont_s = close < float(c["lo50"]) and float(c["rel_vol50"]) >= 1.25
        rec_l = (
            float(c["prev_high"]) > float(c["hi50"])
            and float(c["low"]) <= float(c["hi50"])
            and close > float(c["hi50"])
            and float(c["rel_vol50"]) >= 1.0
        )
        rec_s = (
            float(c["prev_low"]) < float(c["lo50"])
            and float(c["high"]) >= float(c["lo50"])
            and close < float(c["lo50"])
            and float(c["rel_vol50"]) >= 1.0
        )
        long = cont_l or rec_l
        short = cont_s or rec_s
        mode = "CONTINUATION" if cont_l or cont_s else "BREAK_RECLAIM"
    else:
        return _flat(sid, spec, int(c["ts"]), "UNMAPPED_DONOR_NATIVE_CHILD")

    if long == short:
        return _flat(sid, spec, int(c["ts"]), "NO_UNAMBIGUOUS_DONOR_NATIVE_ENTRY")
    side = "long" if long else "short"
    return _finish(sid, spec, c, side, mode)


def self_test() -> int:
    spec = load_spec()
    if set(spec["children"]) != {
        "turtle_trend",
        "bb_revert",
        "anchor_vwap_trend",
        "vwap_revert",
        "break_and_continue",
        "keltner_trend",
        "squeeze_break",
        "supertrend_pullback",
        "trend_ma_macd",
        "trend_rider",
        "liquidity_sweep",
        "scalp_snap",
        "vol_spike_fade",
        "range_fade",
        "fvg_revert",
        "pivot_reversal",
        "rsi_swing_fail",
        "alpha_combo",
        "ema_ribbon_scalp",
        "mfi_rsi_div",
        "obv_trend",
        "grid_rebalance",
        "rbreaker_like",
        "session_bias",
        "sr_levels",
    }:
        raise RuntimeError("DONOR_NATIVE_25_COVERAGE_FAIL")
    print("PASS_DONOR_NATIVE_POLICY_25_OF_25")
    return 0
