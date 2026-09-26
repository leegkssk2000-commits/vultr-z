"""Price-only declared Supertrend model; other indicator roles stay explicit.

This is a complete research policy, not the author's original trading system.
No loader, budget allocation, genuine-history probe, live API, or promotion.
The two profiles share entries/size and differ only in post-entry band trailing.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Integral
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from backend.research.rebuild import scalp7_exact25_indicators_v1 as source
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

VERSION = "EXACT25_INDICATOR_MODEL_CLOSURE_V1"
CONTROL = "ST30_STRUCTURAL_CONTROL_V1"
TRAIL = "ST30_COMPLETED_BAND_TRAIL_V1"
MODELS = (CONTROL, TRAIL)
TF = 30 * 60_000
DAY = 24 * 60 * 60_000
MINUTE = 60_000
CONFIG = {"timeframe_min": 30, "price_type": "last"}
QUANTITY = {
    "kind": "AVAILABLE_CAPITAL_STRUCTURAL_RISK_CAPPED_NOTIONAL_V1",
    "price_risk_fraction": 0.0025,
    "max_notional_fraction": 0.25,
    "costs_in_price_risk": False,
    "no_leverage_multiplier": True,
}
DISPOSITIONS = {
    "bb_revert": {
        "status": "DATA_AND_POLICY_BLOCKED",
        "reason": "BBIII needs evidenced volume units and a separate declared full management policy; neither is silently filled.",
        "economic_runs": 0,
    },
    "mfi_rsi_div": {
        "status": "OBSERVATION_MATERIAL_ONLY",
        "reason": "Same-price-pivot warning is not an entry; MFI volume provenance and a selected host action remain unbound.",
        "economic_runs": 0,
    },
    "obv_trend": {
        "status": "OBSERVATION_MATERIAL_ONLY",
        "reason": "OBV signed volume is not an independent trade. Unknown historical volume units block source-volume claims.",
        "economic_runs": 0,
    },
    "rsi_swing_fail": {
        "status": "COMPLETED_FAILURE_PRESERVED",
        "reason": "PR1340 oscillator entry result retained; no duplicate entry/exit run or R2 substitution.",
        "economic_runs": 0,
    },
    "supertrend_pullback": {
        "status": "COMPLETE_DECLARED_RESEARCH_PAIR",
        "reason": "One new price sequence, two matched lifecycle profiles; economic authority remains separately required.",
        "model_ids": list(MODELS),
        "economic_runs": 0,
    },
    "trend_ma_macd": {
        "status": "OBSERVATION_MATERIAL_ONLY",
        "reason": "Raschke SMA, GMMA and EMA-MACD stay separate. No arbitrary host vote or PR1341 entry repeat.",
        "economic_runs": 0,
    },
}


def catalog() -> dict[str, Any]:
    return copy.deepcopy(DISPOSITIONS)


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return value


def _stamp(value: Any, name: str) -> int:
    answer = _number(value, name)
    if answer < 0 or answer != int(answer):
        raise ValueError("INVALID_TIMESTAMP:" + name)
    return int(answer)


def _choice(rule_id: str, expression: str, rationale: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "origin": "DECLARED_HYPOTHESIS",
        "expression": expression,
        "unit": "declared research policy",
        "version": VERSION,
        "hypothesis_id": rule_id,
        "rationale": rationale,
        "exact_source_reproduction": False,
    }


def candidate_spec(model_id: str) -> dict[str, Any]:
    if model_id not in MODELS:
        raise ValueError("UNKNOWN_MODEL")
    rules = [
        {
            "rule_id": "ST_OFFICIAL_BAND_RECURRENCE",
            "origin": "SOURCE_DIRECT",
            "expression": "HL2 plus/minus ATR multiple; previous close/final bands retain or replace bands; strict close crossings change direction.",
            "unit": "last price",
            "version": VERSION,
            "source_id": "R20",
            "source_locator": source.SOURCES["R20"],
            "source_mode": "official indicator formula only",
        },
        _choice(
            "ST30_INPUT_AND_SEED",
            "Completed exclusive-close 30m last prices; ATR10 arithmetic seed then Wilder recursion, factor3; reset at physical/declared gaps. Volume is never accessed.",
            "One explicit intraday indicator setting fixed before any market-feature or economic scan; not an optimized threshold.",
        ),
        _choice(
            "ST30_ENTRY_SEQUENCE",
            "Observed direction flip; later favorable close and new directional extreme beyond flip; first later bar with both high/low counter-direction; later close beyond previous bar directional extreme while direction persists. One consumed setup per flip.",
            "Distinguish direction observation, expansion, pullback and price resumption. This entire entry is our hypothesis, not the indicator author's strategy.",
        ),
        _choice(
            "ST30_INVALIDATION",
            "A new flip replaces the pending setup; physical gaps or UTC day change erase pending setup; no reuse after entry. Stop is adverse pullback extreme including confirmation bar.",
            "A completed setup's price structure defines failure without a generic ATR stop or reward multiple.",
        ),
        _choice(
            "ST30_ORDER",
            "NEXT_OPEN at first whole minute not before cumulative feature availability; expires after one30m bar or UTC23:00, whichever first. No entry at/after23:00; reserve a complete30m exit decision and following detail.",
            "Explicit model latency and finite order life; no inferred same-bar or observed fill.",
        ),
        _choice(
            "ST30_SIZE",
            "At admission qty=min(available capital*0.0025/structural stop distance,available capital*0.25/confirmation close); no leverage. Reject actual fill breaching reserved price-risk or notional.",
            "Finite research risk and concentration policy, not source size or guaranteed loss cap. Fees/gaps are separately reported.",
        ),
        _choice(
            "ST30_EXIT_COMMON",
            "Existing protective stop; completed opposite direction or UTC23:30 decision exits at next open; no entry at/after23:00. No TP, partial exit, or generic hold cutoff. Incomplete detail retains unresolved ownership.",
            "Explicit intraday adaptation and adverse structure exit shared identically by control and child.",
        ),
        _choice(
            "ST30_EXIT_AXIS",
            (
                "Keep initial structural stop."
                if model_id == CONTROL
                else "After each completed bar in position direction, monotonically tighten to its observed Supertrend line for future detail only."
            ),
            "The only changed axis is post-entry band trailing. Existing recurrence is reused, not claimed as a newly invented indicator.",
        ),
    ]
    return {
        "strategy_id": "supertrend_pullback",
        "model_id": model_id,
        "config": dict(CONFIG),
        "rules": rules,
        "rule_digest": validate_rules(rules),
        "complete": True,
        "source_original": False,
        "research_model": True,
        "quantity_policy": copy.deepcopy(QUANTITY),
        "execution_mode": "DETAIL_CONDITIONAL",
        "required_data": [
            "genuine last OHLC30m",
            "contiguous detail1m",
            "available timestamps",
            "segment identifiers",
        ],
        "volume_required": False,
        "orders": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "new_full_authority": False,
    }


def _segments(frame: pd.DataFrame) -> list[list[dict[str, Any]]]:
    columns = (
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    )
    if not set(columns).issubset(frame.columns):
        raise ValueError("MISSING_PRICE_CLOCK_COLUMNS")
    if "price_type" in frame.columns and any(
        value != "last" for value in frame["price_type"]
    ):
        raise ValueError("ROW_PRICE_TYPE_MISMATCH")
    groups: list[list[dict[str, Any]]] = []
    previous: dict[str, Any] | None = None
    for raw in frame[list(columns)].to_dict("records"):
        row = dict(raw)
        for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            row[key] = _stamp(row[key], key)
        for key in ("open", "high", "low", "close"):
            row[key] = _number(row[key], key, positive=True)
        if row["open_ts_ms"] % TF or row["close_ts_ms"] != row["open_ts_ms"] + TF:
            raise ValueError("EXCLUSIVE_30M_CLOCK_REQUIRED")
        if row["available_ts_ms"] < row["close_ts_ms"]:
            raise ValueError("UNAVAILABLE_PRICE")
        segment = row["segment_id"]
        valid_segment = (isinstance(segment, str) and bool(segment.strip())) or (
            isinstance(segment, Integral)
            and not isinstance(segment, bool)
            and int(segment) >= 0
        )
        if not valid_segment:
            raise ValueError("INVALID_SEGMENT")
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(
            row["open"], row["close"]
        ):
            raise ValueError("INVALID_PRICE_RANGE")
        if previous is not None and row["open_ts_ms"] < previous["close_ts_ms"]:
            raise ValueError("NON_CHRONOLOGICAL_OR_OVERLAPPING_PRICES")
        reset = (
            previous is None
            or row["open_ts_ms"] != previous["close_ts_ms"]
            or row["segment_id"] != previous["segment_id"]
        )
        if reset:
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


def _produce(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, Any] = {"components": [], "events": []}
    # Direct existing recurrence, with price fields only. No fake volume adapter.
    source._supertrend(symbol, rows, {"atr_length": 10, "multiplier": 3.0}, output)
    by_open = {r["bar_open_ts_ms"]: r for r in output["components"]}
    result = []
    for raw in rows:
        row = dict(raw)
        component = by_open.get(row["open_ts_ms"])
        row.update(
            symbol=symbol,
            st_direction=component["direction"] if component else None,
            st_line=component["line"] if component else None,
            st_available_ts_ms=row["feature_available_ts_ms"],
        )
        result.append(row)
    return result


def _plans(
    symbol: str, rows: list[dict[str, Any]], model_id: str
) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    setup: dict[str, Any] | None = None
    prior: dict[str, Any] | None = None
    for row in rows:
        if prior is None:
            prior = row
            continue
        day_end = (row["open_ts_ms"] // DAY + 1) * DAY
        if row["open_ts_ms"] // DAY != prior["open_ts_ms"] // DAY:
            setup = None
        direction = row["st_direction"]
        if direction is None or prior["st_direction"] is None:
            prior = row
            continue
        if direction != prior["st_direction"]:
            setup = {"side": direction, "phase": "EXTENSION", "flip": dict(row)}
            prior = row
            continue
        if setup is None:
            prior = row
            continue
        side = setup["side"]
        favorable, adverse = ("high", "low") if side == 1 else ("low", "high")
        if setup["phase"] == "EXTENSION":
            if (
                side * (row["close"] - prior["close"]) > 0
                and side * (row[favorable] - setup["flip"][favorable]) > 0
            ):
                setup["phase"] = "PULLBACK"
        elif setup["phase"] == "PULLBACK":
            if (
                side * (row["high"] - prior["high"]) < 0
                and side * (row["low"] - prior["low"]) < 0
            ):
                setup.update(
                    phase="RECLAIM", stop=row[adverse], pullback_ts_ms=row["open_ts_ms"]
                )
        else:
            setup["stop"] = (
                min(setup["stop"], row[adverse])
                if side == 1
                else max(setup["stop"], row[adverse])
            )
            if side * (row["close"] - prior[favorable]) > 0:
                known = row["feature_available_ts_ms"]
                active = (known + MINUTE - 1) // MINUTE * MINUTE
                if (
                    active < day_end - 2 * TF
                    and side * (row["close"] - setup["stop"]) > 0
                ):
                    plans.append(
                        {
                            "symbol": symbol,
                            "side": side,
                            "model_id": model_id,
                            "decision_tf_min": 30,
                            "order_kind": "NEXT_OPEN",
                            "timing_basis": "HISTORICAL_MODEL",
                            "setup_ts_ms": setup["flip"]["open_ts_ms"],
                            "signal_open_ts_ms": row["open_ts_ms"],
                            "feature_available_ts_ms": known,
                            "order_submit_ts_ms": known,
                            "order_active_ts_ms": active,
                            "expires_ts_ms": min(active + TF, day_end - 2 * TF),
                            "protective_stop": setup["stop"],
                            "reference_entry_price": row["close"],
                            "quantity_policy": copy.deepcopy(QUANTITY),
                            "signal": {
                                "model_id": model_id,
                                "side": side,
                                "session_end_ts_ms": day_end,
                                "scheduled_exit_ts_ms": day_end - TF,
                                "st_direction": direction,
                                "structural_stop": setup["stop"],
                                "flip_ts_ms": setup["flip"]["open_ts_ms"],
                                "pullback_ts_ms": setup["pullback_ts_ms"],
                                "confirmation_ts_ms": row["close_ts_ms"],
                            },
                        }
                    )
                setup = None
        prior = row
    return plans


def compile_model(
    model_id: str, frames: dict[str, pd.DataFrame], config: Mapping[str, Any]
) -> dict[str, Any]:
    spec = candidate_spec(model_id)
    if dict(config) != CONFIG:
        raise ValueError("FROZEN_CONFIG_MISMATCH")
    plans = []
    decisions = {}
    for symbol, frame in sorted(frames.items()):
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("INVALID_SYMBOL")
        all_rows = []
        for segment in _segments(frame):
            rows = _produce(symbol, segment)
            plans.extend(_plans(symbol, rows, model_id))
            all_rows.extend(rows)
        decisions[symbol] = pd.DataFrame(all_rows)
    return {**spec, "plans": plans, "decisions": decisions, "economic_runs": 0}


def create_order(
    plan: Mapping[str, Any], capital: Any, identity: str, rule_digest: str
) -> dict[str, Any]:
    candidate_spec(str(plan.get("model_id")))
    if (
        not isinstance(identity, str)
        or not identity
        or not isinstance(rule_digest, str)
        or not rule_digest
    ):
        raise ValueError("IDENTITY_AND_RULE_DIGEST_REQUIRED")
    if plan.get("quantity_policy") != QUANTITY:
        raise ValueError("FROZEN_QUANTITY_POLICY_MISMATCH")
    equity = _number(capital, "available_capital", positive=True)
    reference = _number(plan.get("reference_entry_price"), "reference", positive=True)
    stop = _number(plan.get("protective_stop"), "stop", positive=True)
    side = plan.get("side")
    if side not in (-1, 1) or isinstance(side, bool):
        raise ValueError("INVALID_SIDE")
    risk = side * (reference - stop)
    if risk <= 0:
        raise ValueError("STOP_NOT_ADVERSE")
    risk_budget, notional_budget = equity * 0.0025, equity * 0.25
    quantity = min(risk_budget / risk, notional_budget / reference)
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("INVALID_QUANTITY")
    order = copy.deepcopy(dict(plan))
    order.update(identity=identity, rule_digest=rule_digest, qty_base=str(quantity))
    order["signal"].update(
        qty_base=quantity,
        reserved_price_risk_usdt=risk_budget,
        reserved_notional_usdt=notional_budget,
    )
    return order


def entry_update(signal: Mapping[str, Any], actual_entry_price: Any) -> dict[str, Any]:
    price = _number(actual_entry_price, "entry_price", positive=True)
    qty = _number(signal.get("qty_base"), "qty_base", positive=True)
    stop = _number(signal.get("structural_stop"), "stop", positive=True)
    side = signal.get("side")
    if side not in (-1, 1) or isinstance(side, bool):
        raise ValueError("INVALID_SIDE")
    risk = qty * side * (price - stop)
    risk_cap = _number(
        signal.get("reserved_price_risk_usdt"), "reserved_risk", positive=True
    )
    notional_cap = _number(
        signal.get("reserved_notional_usdt"), "reserved_notional", positive=True
    )
    if (
        risk <= 0
        or risk > risk_cap * (1 + 1e-12)
        or qty * price > notional_cap * (1 + 1e-12)
    ):
        return {
            "reject": True,
            "reason": "ACTUAL_ENTRY_EXCEEDS_RESERVED_RISK_OR_NOTIONAL",
        }
    return {"stop_price": stop}


def exit_update(
    position: Mapping[str, Any], bar: Mapping[str, Any], history: Any
) -> dict[str, Any]:
    del history
    signal = position["signal"]
    model_id = signal["model_id"]
    if model_id not in MODELS:
        raise ValueError("UNKNOWN_MODEL")
    known = _stamp(bar.get("available_ts_ms"), "bar_available")
    if _stamp(bar.get("st_available_ts_ms"), "st_available") > known:
        raise ValueError("FUTURE_BAND")
    closed = _stamp(bar.get("close_ts_ms"), "bar_close")
    if closed >= _stamp(signal["scheduled_exit_ts_ms"], "scheduled_exit"):
        return {"exit_next_open": True, "reason": "DECLARED_UTC_2330_FLATTEN"}
    side = position["side"]
    direction = bar.get("st_direction")
    if direction not in (-1, 1) or isinstance(direction, bool):
        raise ValueError("UNAVAILABLE_ST_DIRECTION")
    if direction != side:
        return {"exit_next_open": True, "reason": "COMPLETED_DIRECTION_INVALIDATION"}
    if model_id == CONTROL:
        return {}
    line = _number(bar.get("st_line"), "st_line")
    old_stop = _number(position["stop_price"], "stop_price", positive=True)
    return {
        "next_stop": max(old_stop, line) if side == 1 else min(old_stop, line),
        "reason": "COMPLETED_ST_BAND_FUTURE_ONLY",
    }
