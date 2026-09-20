"""Six raw-OHLCV indicator bindings; no fills, economics or complete strategy.

Source formula, existing frozen adaptation, and new engineering choices are
separate rules. Every observation is known only after all its dependencies.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from backend.research.rebuild import scalp7_fidelity_rsi_v1 as existing_rsi
from backend.research.rebuild.scalp7_economic_rider_v1 import LONG_GMMA, SHORT_GMMA
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

VERSION = "RAW_INDICATOR_BINDING_V1"
SOURCES = {
    "R17": "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI",
    "R18": "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/mfi",
    "R19": "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/obv",
    "R20": "https://www.tradingview.com/support/solutions/43000634738-supertrend/",
    "S317": "https://www.bollingerbands.com/_files/ugd/58be43_377f4254baa04a19aaadb1735b45b6f0.pdf",
    "S312": "https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf",
    "S314": "https://lindaraschke.net/faq/",
    "R14": "https://www.guppytraders.com/gmma-info",
}
MODES = {
    "bb_revert": ("BBIII_ALERT_CONFIRM_EXPLICIT_V1",),
    "mfi_rsi_div": ("RSI_MFI_SAME_PIVOT_COMPONENT_V1",),
    "obv_trend": ("OBV_SIGNED_VOLUME_COMPONENT_V1",),
    "rsi_swing_fail": ("RSI14_EXISTING_8BAR_FAILURE_COMPONENT_V1",),
    "supertrend_pullback": ("TV_SUPERTREND_RMA_SMA_SEED_COMPONENT_V1",),
    "trend_ma_macd": (
        "RASCHKE_SMA_3_10_16_COMPONENT_V1",
        "GMMA_EXISTING_PERIODS_FIRST_CLOSE_SEED_COMPONENT_V1",
        "EMA_MACD_EXPLICIT_COMPONENT_V1",
    ),
}
EXTRA_CONFIG = {
    "bb_revert": [
        "bb_length",
        "bb_multiplier",
        "ii_period",
        "ii_version",
        "confirmation",
        "alert_expiry_bars",
        "invalidation",
    ],
    "mfi_rsi_div": ["oscillator_period", "pivot_left", "pivot_right"],
    "obv_trend": [],
    "rsi_swing_fail": [],
    "supertrend_pullback": ["atr_length", "multiplier"],
    "trend_ma_macd": [],
}


LIMITATIONS = {
    "bb_revert": [
        "II accumulation, population SD and price confirmation are explicit interpretations, not certified TradeStation parity.",
        "MethodII MFI and ConnorsR2 remain separate; quantity, stop, exit and executable-order expiry unresolved.",
    ],
    "mfi_rsi_div": [
        "Pivot window is a declared mechanical choice; RSI and MFI warnings are separate, not independent votes.",
        "Subsequent price confirmation and host action/risk are unresolved.",
    ],
    "obv_trend": [
        "Raw participation is separate from signed cumulative volume; discretionary impulse/pullback phases are not inferred.",
        "No OBV-only entry or validated host contribution.",
    ],
    "rsi_swing_fail": [
        "Existing8bar oscillator state adaptation reused; this component uses separately declared arithmetic-seeded RSI.",
        "No old parent regime/risk inheritance, R2 substitution, or repeated economic run.",
    ],
    "supertrend_pullback": [
        "ATR seed and parameters are declared; direction/band observations do not define a pullback entry.",
        "Band usable only after availability; no intrabar retrospective stop or host mutation.",
    ],
    "trend_ma_macd": [
        "RaschkeSMA, GMMA and EMA-MACD are separate component modes, not combined confirmations.",
        "No repeated PR1341 entry architecture or inferred standalone economics.",
    ],
}


def catalog() -> dict[str, Any]:
    return {
        key: {
            "strategy_id": key,
            "mode_ids": list(modes),
            "required_config": ["timeframe_min", "mode_id", "volume_unit", "price_type"]
            + EXTRA_CONFIG[key],
            "complete_strategy": False,
            "status": "COMPONENT_IMPLEMENTED_ECONOMICS_NOT_RUN",
            "gaps": LIMITATIONS[key]
            + [
                "host role",
                "entry order policy",
                "quantity",
                "expiry",
                "risk",
                "exit",
                "fresh economic contribution",
            ],
        }
        for key, modes in MODES.items()
    }


def _number(value: Any, key: str) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + key)
    try:
        answer = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_NUMBER:" + key) from exc
    if not math.isfinite(answer):
        raise ValueError("INVALID_NUMBER:" + key)
    return answer


def _integer(value: Any, key: str, minimum: int = 1) -> int:
    n = _number(value, key)
    if n < minimum or n != int(n):
        raise ValueError("INVALID_INTEGER:" + key)
    return int(n)


def _segments(
    frame: pd.DataFrame, config: dict[str, Any]
) -> list[list[dict[str, Any]]]:
    """Reject invalid bars; split physical gaps without creating any replacement."""
    tf = _integer(config["timeframe_min"], "timeframe_min")
    if tf not in (15, 30):
        raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    if config.get("volume_unit") != "base" or config.get("price_type") != "last":
        raise ValueError("EXPLICIT_BASE_VOLUME_AND_LAST_PRICE_REQUIRED")
    columns = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not columns.issubset(frame.columns):
        raise ValueError("MISSING_CANONICAL_COLUMNS")
    groups: list[list[dict[str, Any]]] = []
    previous: dict[str, Any] | None = None
    for raw in frame.to_dict("records"):
        row = dict(raw)
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            row[key] = _integer(row[key], key, 0)
        for key in ("open", "high", "low", "close", "volume"):
            row[key] = _number(row[key], key)
        if not isinstance(row["segment_id"], (str, int)) or isinstance(
            row["segment_id"], bool
        ):
            raise ValueError("INVALID_SEGMENT")
        if row["close_ts_ms"] - row["open_ts_ms"] != tf * 60000:
            raise ValueError("TIMEFRAME_MISMATCH")
        if row["available_ts_ms"] < row["close_ts_ms"]:
            raise ValueError("UNAVAILABLE_BAR")
        if (
            row["low"] <= 0
            or row["low"] > min(row["open"], row["close"])
            or row["high"] < max(row["open"], row["close"])
            or row["volume"] < 0
        ):
            raise ValueError("INVALID_OHLCV")
        for key in ("volume_unit", "price_type"):
            if key in row and row[key] != config[key]:
                raise ValueError("ROW_UNIT_MISMATCH:" + key)
        if previous is not None and row["open_ts_ms"] <= previous["open_ts_ms"]:
            raise ValueError("NON_CHRONOLOGICAL_INPUT")
        if previous is not None and row["open_ts_ms"] < previous["close_ts_ms"]:
            raise ValueError("OVERLAPPING_BAR_INTERVALS")
        new = (
            previous is None
            or row["segment_id"] != previous["segment_id"]
            or row["open_ts_ms"] != previous["close_ts_ms"]
        )
        if new:
            groups.append([])
            row["feature_available_ts_ms"] = row["available_ts_ms"]
        else:
            assert previous is not None
            row["feature_available_ts_ms"] = max(
                row["available_ts_ms"], previous["feature_available_ts_ms"]
            )
        row["local_segment"] = len(groups) - 1
        groups[-1].append(row)
        previous = row
    return groups


def _sma(values: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        window = values[max(0, i + 1 - n) : i + 1]
        out.append(
            sum(v for v in window if v is not None) / n
            if len(window) == n and all(v is not None for v in window)
            else None
        )
    return out


def _rma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) >= n:
        value = sum(values[:n]) / n
        out[n - 1] = value
        for i in range(n, len(values)):
            value = (value * (n - 1) + values[i]) / n
            out[i] = value
    return out


def _ema(values: list[float], n: int) -> list[float]:
    out: list[float] = []
    for value in values:
        out.append(value if not out else out[-1] + 2 / (n + 1) * (value - out[-1]))
    return out


def rsi_values(close: list[float], n: int = 14) -> list[float | None]:
    """Arithmetic seed over n changes; flat seed50 is an explicit convention."""
    delta = [b - a for a, b in zip(close, close[1:])]
    gains = _rma([max(x, 0.0) for x in delta], n)
    losses = _rma([max(-x, 0.0) for x in delta], n)
    out: list[float | None] = [None] if close else []
    for up, down in zip(gains, losses):
        out.append(
            None
            if up is None or down is None
            else 50.0 if up + down == 0 else 100 * up / (up + down)
        )
    return out


def mfi_values(rows: list[dict[str, Any]], n: int) -> list[float | None]:
    typical = [(r["high"] + r["low"] + r["close"]) / 3 for r in rows]
    positive: list[float | None] = [None] if rows else []
    negative: list[float | None] = [None] if rows else []
    for i in range(1, len(rows)):
        flow = typical[i] * rows[i]["volume"]
        positive.append(flow if typical[i] > typical[i - 1] else 0.0)
        negative.append(flow if typical[i] < typical[i - 1] else 0.0)
    up, down = _sma(positive, n), _sma(negative, n)
    return [
        None if a is None or b is None or a + b == 0 else 100 * a / (a + b)
        for a, b in zip(up, down)
    ]


def _source(
    rule: str, expression: str, source: str, mode: str, unit: str
) -> dict[str, Any]:
    return {
        "rule_id": rule,
        "origin": "SOURCE_DIRECT",
        "expression": expression,
        "source_id": source,
        "source_locator": SOURCES[source],
        "source_mode": mode,
        "unit": unit,
        "version": VERSION,
    }


def _choice(
    rule: str, expression: str, unit: str = "declared configuration"
) -> dict[str, Any]:
    return {
        "rule_id": rule,
        "origin": "DECLARED_HYPOTHESIS",
        "expression": expression,
        "unit": unit,
        "version": VERSION,
        "hypothesis_id": rule,
        "rationale": "Explicit engineering choice; source does not fully fix this implementation detail.",
        "exact_source_reproduction": False,
    }


def _rules(strategy: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    common = [
        _choice(
            "INPUT_CLOCK",
            "15m/30m completed last-price OHLCV, base volume; exclusive close; cumulative availability; physical/declared gaps reset all state.",
        ),
        _choice("MODE_CONFIG", repr(sorted(config.items()))),
    ]
    definitions = {
        "bb_revert": [
            _source(
                "BBIII_ALERT",
                "Lower band tag with positive Intraday Intensity alerts long; upper tag with negative II alerts short. Later price confirmation required, no full-day ban.",
                "S317",
                "Method III",
                "price, signed volume",
            ),
            _source(
                "BB_MATH",
                "SMA close centre plus/minus multiplier times close standard deviation.",
                "S317",
                "Method III",
                "price",
            ),
            _choice(
                "BBIII_INTERPRETATION",
                "Population SD; rolling normalized II=sum((2C-H-L)/(H-L)*V)/sum(V); zero range undefined; close beyond alert high/low confirmation; alert-extreme or no invalidation; explicit bar expiry. Same-bar alert/confirmation never inferred.",
            ),
        ],
        "mfi_rsi_div": [
            _source(
                "MFI_MATH",
                "HLC3 times base volume, positive/negative classified by HLC3 change, rolling flow ratio mapped to0..100.",
                "R18",
                "MFI",
                "ratio points",
            ),
            _source(
                "RSI_MATH",
                "100*average_gain/(average_gain+average_loss)",
                "R17",
                "RSI",
                "ratio points",
            ),
            _source(
                "SAME_PIVOT_DIVERGENCE",
                "Price new extreme unconfirmed by oscillator at same two price events.",
                "R18",
                "divergence",
                "price and oscillator points",
            ),
            _choice(
                "PIVOT_CONFIRMATION",
                "Strict unique price extrema in declared left/right windows; usable only after right-bar availability; each oscillator evaluated independently at same price pivots. No later price-entry confirmation implemented.",
            ),
        ],
        "obv_trend": [
            _source(
                "OBV_MATH",
                "Add current base volume if close rises, subtract if falls, unchanged if flat.",
                "R19",
                "OBV",
                "base units",
            ),
            _choice(
                "OBV_ROLE",
                "Zero origin per contiguous segment. Raw close change, raw volume and previous-volume ratio remain separate; no inferred discretionary impulse phase or entry.",
            ),
        ],
        "rsi_swing_fail": [
            _source(
                "RSI_MATH",
                "100*average_gain/(average_gain+average_loss)",
                "R17",
                "RSI",
                "ratio points",
            ),
            {
                "rule_id": "RSI_EXISTING_SEQUENCE",
                "origin": "EXISTING_FROZEN",
                "expression": "Reuse oscillator_step only: ordered alternating pivots, strict middle break, consumption and8bar stage expiry. No inherited risk/entry-regime or old replay.",
                "unit": "RSI points; bars",
                "version": "PR1340_COMPONENT_ONLY",
                "code_path": "backend/research/rebuild/scalp7_fidelity_rsi_v1.py",
                "code_sha": "f8aeb4eb4eb664da35ef35e24bdb729501b671f23155371b4ae1fbc23de01093",
            },
        ],
        "supertrend_pullback": [
            _source(
                "SUPERTREND_RECURRENCE",
                "HL2 plus/minus multiplier ATR; final bands use previous final band/close; direction flips only on strict close through current final band.",
                "R20",
                "official indicator",
                "price",
            ),
            _choice(
                "ATR_SEED",
                "True range first bar H-L; SMA seed then Wilder1/n smoothing; initial direction down; length/multiplier explicit. A completed band is an observation, never applied to earlier intrabar prices.",
            ),
        ],
        "trend_ma_macd": [
            _source(
                "RASCHKE_MATH",
                "Oscillator=SMA(close,3)-SMA(close,10); signal=SMA(oscillator,16).",
                "S312",
                "3-10 oscillator",
                "price",
            ),
            {
                "rule_id": "GMMA_PERIODS",
                "origin": "EXISTING_FROZEN",
                "expression": "Reuse SHORT_GMMA and LONG_GMMA constants; first-close seeded EMA math. No PR1341 entry grammar or replay.",
                "unit": "bars",
                "version": "PR1341_COMPONENT_ONLY",
                "code_path": "backend/research/rebuild/scalp7_economic_rider_v1.py",
                "code_sha": "43dc17c4b1b3afaa7856ed4efa0e586c7e48fd63cd7d411f45df7ff10f100622",
            },
            _choice(
                "EMA_MACD",
                "Explicit fast/slow/signal periods; first-close EMA seed; signal starts only after slow warmup. Separate from Raschke SMA3-10 and GMMA.",
            ),
        ],
    }
    if strategy in ("rsi_swing_fail", "mfi_rsi_div"):
        common.append(
            _choice(
                "RSI_SEED",
                "RSI arithmetic seed over first n price changes, Wilder recursion; both zero=>50. MFI no positive or negative flow=>undefined. Not old parent pandas seed.",
            )
        )
    selected = definitions[strategy]
    if strategy == "trend_ma_macd":
        rule_id = dict(
            zip(MODES[strategy], ("RASCHKE_MATH", "GMMA_PERIODS", "EMA_MACD"))
        )[config["mode_id"]]
        selected = [rule for rule in selected if rule["rule_id"] == rule_id]
    return common + selected


def _event(
    symbol: str, row: dict[str, Any], kind: str, rule: str, **details: Any
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "kind": kind,
        "rule_id": rule,
        "bar_open_ts_ms": row["open_ts_ms"],
        "available_ts_ms": row["feature_available_ts_ms"],
        "local_segment": row["local_segment"],
        **details,
    }


def _partial(event: dict[str, Any]) -> dict[str, Any]:
    return {
        **event,
        "status": "BLOCKED_INCOMPLETE_STRATEGY",
        "order_kind": None,
        "quantity": None,
        "expiry_ts_ms": None,
        "initial_stop": None,
        "exit_policy": None,
        "earliest_submit_ts_ms": event["available_ts_ms"],
        "order": "BLOCKED",
        "live": "BLOCKED",
    }


def _bb(
    symbol: str, rows: list[dict[str, Any]], config: dict[str, Any], out: dict[str, Any]
) -> None:
    n, ii_n = _integer(config["bb_length"], "bb_length", 2), _integer(
        config["ii_period"], "ii_period"
    )
    multiplier = _number(config["bb_multiplier"], "bb_multiplier")
    expiry = _integer(config["alert_expiry_bars"], "alert_expiry_bars")
    if (
        multiplier <= 0
        or config["ii_version"] != "ROLLING_NORMALIZED_HLC_VOLUME_V1"
        or config["confirmation"] != "CLOSE_BEYOND_ALERT_EXTREME"
        or config["invalidation"] not in ("ALERT_EXTREME", "NONE_UNSPECIFIED")
    ):
        raise ValueError("UNSUPPORTED_BBIII_CONFIG")
    closes = [r["close"] for r in rows]
    means = _sma(closes, n)
    ii_raw = [
        (
            None
            if r["high"] == r["low"]
            else (2 * r["close"] - r["high"] - r["low"])
            / (r["high"] - r["low"])
            * r["volume"]
        )
        for r in rows
    ]
    ii_mean, volume_mean = _sma(ii_raw, ii_n), _sma([r["volume"] for r in rows], ii_n)
    pending: dict[str, Any] | None = None
    for i, row in enumerate(rows):
        if pending is not None:
            side = pending["side"]
            invalid = config["invalidation"] == "ALERT_EXTREME" and (
                row["low"] < pending["low"]
                if side == 1
                else row["high"] > pending["high"]
            )
            if i - pending["index"] > expiry or invalid:
                out["events"].append(
                    _event(
                        symbol,
                        row,
                        "ALERT_CANCELLED",
                        "BBIII_INTERPRETATION",
                        alert_ts_ms=pending["ts"],
                        reason="INVALIDATED" if invalid else "EXPIRED",
                    )
                )
                pending = None
            elif (
                row["close"] > pending["high"]
                if side == 1
                else row["close"] < pending["low"]
            ):
                event = _event(
                    symbol,
                    row,
                    "PRICE_CONFIRMED",
                    "BBIII_INTERPRETATION",
                    side=side,
                    alert_ts_ms=pending["ts"],
                    confirmation_price=row["close"],
                )
                out["events"].append(event)
                out["intents"].append(_partial(event))
                pending = None
        if means[i] is None or ii_mean[i] is None or not volume_mean[i]:
            continue
        middle = _number(means[i], "middle")
        sd = math.sqrt(sum((x - middle) ** 2 for x in closes[i + 1 - n : i + 1]) / n)
        lower, upper = middle - multiplier * sd, middle + multiplier * sd
        ii = 100 * _number(ii_mean[i], "ii") / _number(volume_mean[i], "volume_mean")
        out["components"].append(
            _event(
                symbol,
                row,
                "BBIII_NUMERIC",
                "BB_MATH",
                middle=middle,
                lower=lower,
                upper=upper,
                intraday_intensity=ii,
                ii_version=config["ii_version"],
            )
        )
        if pending is None:
            side = (
                1
                if row["low"] <= lower and ii > 0
                else -1 if row["high"] >= upper and ii < 0 else 0
            )
            if side:
                pending = {
                    "side": side,
                    "low": row["low"],
                    "high": row["high"],
                    "index": i,
                    "ts": row["open_ts_ms"],
                }
                out["events"].append(
                    _event(
                        symbol,
                        row,
                        "REVERSAL_ALERT",
                        "BBIII_ALERT",
                        side=side,
                        intraday_intensity=ii,
                    )
                )


def _divergence(
    symbol: str, rows: list[dict[str, Any]], config: dict[str, Any], out: dict[str, Any]
) -> None:
    n = _integer(config["oscillator_period"], "oscillator_period", 2)
    left, right = _integer(config["pivot_left"], "pivot_left"), _integer(
        config["pivot_right"], "pivot_right"
    )
    oscillators = {
        "rsi": rsi_values([r["close"] for r in rows], n),
        "mfi": mfi_values(rows, n),
    }
    previous: dict[str, int] = {}
    for i, row in enumerate(rows):
        out["components"].append(
            _event(
                symbol,
                row,
                "OSCILLATORS",
                "MFI_MATH",
                rsi=oscillators["rsi"][i],
                mfi=oscillators["mfi"][i],
            )
        )
        pivot = i - right
        if pivot < left:
            continue
        for field, side in (("low", 1), ("high", -1)):
            value = rows[pivot][field]
            neighbors = [
                rows[j][field] for j in range(pivot - left, i + 1) if j != pivot
            ]
            confirmed = (
                all(value < x for x in neighbors)
                if side == 1
                else all(value > x for x in neighbors)
            )
            if not confirmed:
                continue
            prior = previous.get(field)
            previous[field] = pivot
            out["events"].append(
                _event(
                    symbol,
                    row,
                    "PRICE_PIVOT_CONFIRMED",
                    "PIVOT_CONFIRMATION",
                    pivot_ts_ms=rows[pivot]["open_ts_ms"],
                    price=value,
                    side=side,
                )
            )
            if prior is None or not (
                value < rows[prior][field] if side == 1 else value > rows[prior][field]
            ):
                continue
            for name, values in oscillators.items():
                first, second = values[prior], values[pivot]
                if (
                    first is None
                    or second is None
                    or not (second > first if side == 1 else second < first)
                ):
                    continue
                out["events"].append(
                    _event(
                        symbol,
                        row,
                        "DIVERGENCE_WARNING",
                        "SAME_PIVOT_DIVERGENCE",
                        side=side,
                        oscillator=name,
                        first_pivot_ts_ms=rows[prior]["open_ts_ms"],
                        second_pivot_ts_ms=rows[pivot]["open_ts_ms"],
                        first_price=rows[prior][field],
                        second_price=value,
                        first_oscillator=first,
                        second_oscillator=second,
                        price_confirmation="UNRESOLVED",
                    )
                )


def _supertrend(
    symbol: str, rows: list[dict[str, Any]], config: dict[str, Any], out: dict[str, Any]
) -> None:
    n = _integer(config["atr_length"], "atr_length")
    multiplier = _number(config["multiplier"], "multiplier")
    if multiplier <= 0:
        raise ValueError("INVALID_MULTIPLIER")
    tr = [
        (
            max(
                r["high"] - r["low"],
                abs(r["high"] - rows[i - 1]["close"]),
                abs(r["low"] - rows[i - 1]["close"]),
            )
            if i
            else r["high"] - r["low"]
        )
        for i, r in enumerate(rows)
    ]
    atr = _rma(tr, n)
    upper: float | None = None
    lower: float | None = None
    direction = -1
    for i, row in enumerate(rows):
        if atr[i] is None:
            continue
        basic_upper = (row["high"] + row["low"]) / 2 + multiplier * _number(
            atr[i], "atr"
        )
        basic_lower = (row["high"] + row["low"]) / 2 - multiplier * _number(
            atr[i], "atr"
        )
        old_direction = direction
        if upper is None or lower is None:
            upper, lower = basic_upper, basic_lower
        else:
            upper = (
                basic_upper
                if basic_upper < upper or rows[i - 1]["close"] > upper
                else upper
            )
            lower = (
                basic_lower
                if basic_lower > lower or rows[i - 1]["close"] < lower
                else lower
            )
            direction = (
                (1 if row["close"] > upper else -1)
                if direction == -1
                else (-1 if row["close"] < lower else 1)
            )
        line = lower if direction == 1 else upper
        out["components"].append(
            _event(
                symbol,
                row,
                "SUPERTREND_BAND",
                "SUPERTREND_RECURRENCE",
                atr=atr[i],
                upper=upper,
                lower=lower,
                direction=direction,
                line=line,
                applicable_not_before_ts_ms=row["feature_available_ts_ms"],
            )
        )
        if direction != old_direction:
            out["events"].append(
                _event(
                    symbol,
                    row,
                    "DIRECTION_FLIP_COMPONENT",
                    "SUPERTREND_RECURRENCE",
                    side=direction,
                    entry="UNSPECIFIED",
                )
            )


def _trend(
    symbol: str, rows: list[dict[str, Any]], config: dict[str, Any], out: dict[str, Any]
) -> None:
    close = [r["close"] for r in rows]
    mode = config["mode_id"]
    if mode == MODES["trend_ma_macd"][0]:
        fast, slow = _sma(close, 3), _sma(close, 10)
        oscillator = [
            None if a is None or b is None else a - b for a, b in zip(fast, slow)
        ]
        signal = _sma(oscillator, 16)
        for i, row in enumerate(rows):
            out["components"].append(
                _event(
                    symbol,
                    row,
                    "RASCHKE_3_10_16",
                    "RASCHKE_MATH",
                    oscillator=oscillator[i],
                    signal=signal[i],
                )
            )
    elif mode == MODES["trend_ma_macd"][1]:
        values = {n: _ema(close, n) for n in SHORT_GMMA + LONG_GMMA}
        for i, row in enumerate(rows):
            out["components"].append(
                _event(
                    symbol,
                    row,
                    "GMMA_GROUPS",
                    "GMMA_PERIODS",
                    short={str(n): values[n][i] for n in SHORT_GMMA},
                    long={str(n): values[n][i] for n in LONG_GMMA},
                    ready=i + 1 >= max(LONG_GMMA),
                )
            )
    else:
        fast_n = _integer(config.get("fast_period"), "fast_period")
        slow_n = _integer(config.get("slow_period"), "slow_period")
        signal_n = _integer(config.get("signal_period"), "signal_period")
        if fast_n >= slow_n:
            raise ValueError("MACD_FAST_NOT_LESS_THAN_SLOW")
        ema_fast, ema_slow = _ema(close, fast_n), _ema(close, slow_n)
        macd = [a - b for a, b in zip(ema_fast, ema_slow)]
        ema_signal = _ema(macd[slow_n - 1 :], signal_n)
        for i, row in enumerate(rows):
            j = i - slow_n + 1
            value = ema_signal[j] if j >= signal_n - 1 else None
            out["components"].append(
                _event(
                    symbol,
                    row,
                    "EMA_MACD",
                    "EMA_MACD",
                    macd=macd[i] if i + 1 >= slow_n else None,
                    signal=value,
                )
            )


def evaluate(
    strategy_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Calculate causal components and blocked partial intents; never execute."""
    if strategy_id not in MODES:
        raise ValueError("UNKNOWN_STRATEGY")
    if config.get("mode_id") not in MODES[strategy_id]:
        raise ValueError("EXPLICIT_SUPPORTED_MODE_REQUIRED")
    missing = set(catalog()[strategy_id]["required_config"]) - config.keys()
    if missing:
        raise ValueError("MISSING_CONFIG:" + ",".join(sorted(missing)))
    tf = _integer(config["timeframe_min"], "timeframe_min")
    if tf not in (15, 30):
        raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    if config.get("volume_unit") != "base" or config.get("price_type") != "last":
        raise ValueError("EXPLICIT_BASE_VOLUME_AND_LAST_PRICE_REQUIRED")
    rules = _rules(strategy_id, config)
    out: dict[str, Any] = {
        "strategy_id": strategy_id,
        "mode_id": config["mode_id"],
        "events": [],
        "intents": [],
        "components": [],
        "rules": rules,
        "rule_digest": validate_rules(rules),
        "limitations": catalog()[strategy_id]["gaps"],
        "complete_strategy": False,
        "economic_runs": 0,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "classification": "SOURCE_BOUND_COMPONENT_WITH_DECLARED_CHOICES",
    }
    for symbol, frame in sorted(frames.items()):
        for rows in _segments(frame, config):
            if strategy_id == "bb_revert":
                _bb(symbol, rows, config, out)
            elif strategy_id == "mfi_rsi_div":
                _divergence(symbol, rows, config, out)
            elif strategy_id == "supertrend_pullback":
                _supertrend(symbol, rows, config, out)
            elif strategy_id == "trend_ma_macd":
                _trend(symbol, rows, config, out)
            elif strategy_id == "rsi_swing_fail":
                state = existing_rsi.OscillatorState()
                values = rsi_values([r["close"] for r in rows], 14)
                for i, row in enumerate(rows):
                    value = values[i]
                    out["components"].append(
                        _event(symbol, row, "RSI14", "RSI_MATH", rsi=value)
                    )
                    event = existing_rsi.oscillator_step(
                        state, float(value) if value is not None else math.nan, i
                    )
                    if event:
                        event = copy.deepcopy(event)
                        for pivot in event["pivots"]:
                            pivot["pivot_ts_ms"] = rows[pivot["index"]]["open_ts_ms"]
                            pivot["confirmed_available_ts_ms"] = rows[
                                pivot["confirmed_index"]
                            ]["feature_available_ts_ms"]
                        out["events"].append(
                            _event(
                                symbol,
                                row,
                                "RSI_FAILURE_SWING_COMPONENT",
                                "RSI_EXISTING_SEQUENCE",
                                **event,
                            )
                        )
            else:
                obv = 0.0
                for i, row in enumerate(rows):
                    change = row["close"] - rows[i - 1]["close"] if i else 0.0
                    obv += row["volume"] * (
                        1 if change > 0 else -1 if change < 0 else 0
                    )
                    out["components"].append(
                        _event(
                            symbol,
                            row,
                            "OBV",
                            "OBV_MATH",
                            obv=obv,
                            close_change=change,
                            base_volume=row["volume"],
                            volume_ratio_to_previous=(
                                row["volume"] / rows[i - 1]["volume"]
                                if i and rows[i - 1]["volume"]
                                else None
                            ),
                            discretionary_phase="UNRESOLVED",
                        )
                    )
    for intent in out["intents"]:
        intent.update(
            mode_id=config["mode_id"],
            setup_ts_ms=intent["alert_ts_ms"],
            feature_available_ts_ms=intent["available_ts_ms"],
            trigger_price=intent["confirmation_price"],
            protective_stop=None,
            expires_ts_ms=None,
            lifecycle_gap="SOURCE_ENTRY_ORDER_QTY_EXPIRY_RISK_EXIT_UNRESOLVED",
        )
    json.dumps(out, allow_nan=False)
    return out
