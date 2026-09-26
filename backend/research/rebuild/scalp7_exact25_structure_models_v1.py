"""One fully specified Anti research model; no source-original certification.

The unchanged producer supplies causal impulse/flag/resumption events. This
module declares one numeric translation, finite sizing and structural lifecycle
before economics. Its five other structural rows remain explicitly unselected.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any
from pathlib import Path

import pandas as pd

from backend.research.rebuild import scalp7_exact25_structure_v1 as source
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

MODEL_ID = "ANTI30_CAUSAL_FLAG_PIVOT_V1"
LIFECYCLE_ID = "ANTI_POST_ENTRY_CONFIRMED_COUNTER_PIVOT_1L1R_V1"
VERSION = "exact25.structure_models.v1"
MINUTE = 60_000
TF = 30 * MINUTE
RISK_FRACTION = 0.0025
NOTIONAL_FRACTION = 0.25
QUANTITY_POLICY = {
    "risk_fraction": 0.0025,
    "max_notional_fraction": 0.25,
    "sizing_price_basis": "KNOWN_SIGNAL_CLOSE",
    "origin": "DECLARED_HYPOTHESIS",
}
DISPOSITIONS = {
    "ema_ribbon_scalp": {
        "status": "MATERIAL_ONLY_UNSELECTED",
        "reason": "Kell six-phase/higher-timeframe and partial-management selection remains unbound; a generic exit would manufacture a different model.",
    },
    "keltner_trend": {
        "status": "PARENT_PRESERVED_NO_NEW_PROFILE",
        "reason": "Positive parent and preregistered TD+0.75R BE remain distinct; HG first-touch source repair and failed historical exit experiments are not repeated.",
    },
    "pivot_reversal": {
        "status": "MATERIAL_ONLY_UNSELECTED",
        "reason": "Confirmed support/pivot observation remains a material; source discretionary target/partial management is not complete.",
    },
    "range_fade": {
        "status": "COMPLETE_DECLARED_MODEL_NOT_ECONOMICALLY_RUN",
        "model_id": MODEL_ID,
        "reason": "Corrected Anti continuation grammar plus a separately declared causal counter-swing lifecycle; not a range-boundary fade.",
    },
    "scalp_snap": {
        "status": "MATERIAL_ONLY_LINEAGE_DUPLICATE",
        "reason": "Gajjala flag is shared with break_and_continue; completed flag/Rider work is preserved and native Short Skirt cannot be represented by 15m.",
    },
    "vol_spike_fade": {
        "status": "MATERIAL_ONLY_UNSELECTED",
        "reason": "Price-retest short component lacks selected stock/crypto role and original borrow/scale-out management; no synthetic source equivalence.",
    },
}


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("POSITIVE_NUMBER_REQUIRED:" + label)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("POSITIVE_NUMBER_REQUIRED:" + label)
    return number


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def catalog() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DISPOSITIONS)


def profile(model_id: str = MODEL_ID, tick_size: float | None = None) -> dict[str, Any]:
    """All research thresholds are fixed; only measured instrument tick varies."""
    if model_id != MODEL_ID:
        raise ValueError("UNKNOWN_COMPLETE_STRUCTURE_MODEL")
    tick = _positive(tick_size, "instrument_tick_size")
    return {
        "model_id": MODEL_ID,
        "strategy_id": "range_fade",
        "decision_tf_min": 30,
        "source_config": {
            "mode_id": "ANTI_IMPULSE_CONTINUATION_DECLARED",
            "timeframe_min": 30,
            "hypothesis_id": "ANTI30_GEOMETRY_FIXED_BEFORE_ECONOMICS_V1",
            "impulse_lookback_bars": 10,
            "impulse_range_multiple": 2.0,
            "flag_max_retracement_fraction": 0.5,
            "flag_min_bars": 1,
            "flag_max_bars": 5,
            "tick_size": tick,
        },
        "lifecycle_id": LIFECYCLE_ID,
        "quantity_policy": copy.deepcopy(QUANTITY_POLICY),
        "activation_policy": "FIRST_MINUTE_OPEN_STRICTLY_AFTER_FEATURE_AVAILABILITY",
        "pending_expiry_policy": "ONE_ACTIVATION_MINUTE_NO_RETRY",
        "initial_stop_policy": "KNOWN_FLAG_EXTREME_PLUS_ONE_INSTRUMENT_TICK",
        "exit_policy": "MONOTONIC_POST_ENTRY_STRICT_1L1R_COUNTER_PIVOT_STOP",
        "terminal_policy": "NO_FORCED_WINDOW_CLOSE_UNRESOLVED_OWNERSHIP_RETAINED",
        "complete_configured_research_model": True,
        "exact_source_reproduction": False,
        "economic_status": "NOT_RUN",
        "gap_risk_policy": "PLANNED_PRICE_RISK_NOT_GUARANTEED_NO_FUTURE_RESIZING",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }


def _rules(profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "anti_grammar_lineage",
            "origin": "EXISTING_FROZEN",
            "expression": "Call unchanged structure_v1 range_fade Anti producer; do not reinterpret as boundary fade.",
            "unit": "completed_30m_price_events",
            "version": VERSION,
            "code_path": "backend/research/rebuild/scalp7_exact25_structure_v1.py",
            "code_sha": hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest(),
        },
        {
            "rule_id": "anti_complete_geometry_and_lifecycle",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": json.dumps(profiles, sort_keys=True),
            "unit": "bars_price_base_quantity_USDT",
            "version": VERSION,
            "hypothesis_id": MODEL_ID,
            "rationale": "Ten-bar range context matches the slow oscillator scale; double-range impulse and half-impulse maximum retracement separate impulse from small flag. One-to-five flag bars specify setup persistence, not outcome selection. A new confirmed counter-swing after entry invalidates continuation; no fixed profit or holding target is invented.",
            "exact_source_reproduction": False,
        },
        {
            "rule_id": "anti_finite_allocation",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": "qty=min(capital*0.0025/abs(known_close-flag_stop),capital*0.25/known_close); runner enforces finite shared capital, known reservations, actual cost/slippage/funding evidence. Adverse entry/stop gaps may exceed planned price risk; no future resize or guaranteed loss cap.",
            "unit": "base_quantity_USDT",
            "version": VERSION,
            "hypothesis_id": "ANTI_CAUSAL_FIXED_RISK_NOTIONAL_CAP_V1",
            "rationale": "Explicit small risk and finite notional normalization permit account comparison; neither is claimed to be Raschke's original sizing nor optimized on economic outcomes.",
            "exact_source_reproduction": False,
        },
    ]


def evaluate(
    model_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Invoke actual frozen producer; convert only its witnessed partial intents."""
    if model_id != MODEL_ID or not frames:
        raise ValueError("COMPLETE_STRUCTURE_MODEL_AND_FRAMES_REQUIRED")
    if set(config) - {"tick_size", "tick_sizes"}:
        raise ValueError("FROZEN_PROFILE_PARAMETERS_CANNOT_BE_RETUNED")
    if ("tick_size" in config) == ("tick_sizes" in config):
        raise ValueError("ONE_EXPLICIT_TICK_SOURCE_REQUIRED")
    if "tick_sizes" in config and set(config["tick_sizes"]) != set(frames):
        raise ValueError("TICK_SYMBOL_BINDING_REQUIRED")
    profiles = {
        symbol: profile(
            model_id,
            (
                config["tick_sizes"][symbol]
                if "tick_sizes" in config
                else config["tick_size"]
            ),
        )
        for symbol in sorted(frames)
    }
    rules = _rules(profiles)
    digest = validate_rules(rules)
    plans, events = [], []
    for symbol, frame in sorted(frames.items()):
        # Canonical execution bars use exclusive close; no hidden 1ms repair.
        for row in frame.to_dict("records"):
            if row["open_ts_ms"] % TF or row["close_ts_ms"] != row["open_ts_ms"] + TF:
                raise ValueError("EXCLUSIVE_CANONICAL_30M_CLOSE_REQUIRED")
        chosen = profiles[symbol]
        produced = source.evaluate(
            "range_fade", {symbol: frame}, chosen["source_config"]
        )
        events.extend(produced["events"])
        for intent in produced["intents"]:
            known = int(intent["feature_available_ts_ms"])
            active = (known // MINUTE + 1) * MINUTE
            reference = _positive(intent["trigger_price"], "known_signal_close")
            signal = {
                **copy.deepcopy(intent),
                "model_id": model_id,
                "lifecycle_id": LIFECYCLE_ID,
                "tick_size": chosen["source_config"]["tick_size"],
                "profile_sha256": _digest(chosen),
            }
            plans.append(
                {
                    "model_id": model_id,
                    "strategy_id": "range_fade",
                    "symbol": symbol,
                    "side": intent["side"],
                    "decision_tf_min": 30,
                    "feature_available_ts_ms": known,
                    "order_submit_ts_ms": known,
                    "order_active_ts_ms": active,
                    "expires_ts_ms": active + MINUTE,
                    "order_kind": "NEXT_OPEN",
                    "trigger_price": None,
                    "protective_stop": intent["protective_stop"],
                    "reference_entry_price": reference,
                    "quantity_policy": copy.deepcopy(QUANTITY_POLICY),
                    "lifecycle_id": LIFECYCLE_ID,
                    "rule_digest": digest,
                    "timing_basis": "HISTORICAL_MODEL",
                    "signal": signal,
                    "source_provenance": {
                        "producer": "scalp7_exact25_structure_v1.evaluate",
                        "source_rule_digest": produced["rule_digest"],
                        "source_intent_sha256": _digest(intent),
                        "profile_sha256": _digest(chosen),
                        "source_claim": "DECLARED_ANTI_TRANSLATION_NOT_FULL_ORIGINAL",
                    },
                }
            )
    plans.sort(key=lambda item: (item["feature_available_ts_ms"], item["symbol"]))
    return {
        "model_id": model_id,
        "profile": profiles,
        "plans": plans,
        "events": events,
        "rules": rules,
        "rule_digest": digest,
        "limitations": [
            "Numeric geometry, trailing, clock and sizing are declared hypotheses.",
            "No source-original certification; archived FAQ lineage does not certify omitted management.",
            "All OHLC fills are model assumptions; gaps and open terminal positions remain unresolved.",
            "No result measured; no original range-fade failure or grade is reversed.",
        ],
        "complete_configured_research_model": True,
        "exact_source_reproduction": False,
        "economic_execution_performed": False,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }


def create_order(
    plan: dict[str, Any], capital: float, identity: str, rule_digest: str
) -> dict[str, Any]:
    """Size at pre-entry signal close, never at a future favorable fill."""
    if plan.get("model_id") != MODEL_ID or plan.get("lifecycle_id") != LIFECYCLE_ID:
        raise ValueError("MODEL_LIFECYCLE_BINDING_MISMATCH")
    if plan.get("quantity_policy") != QUANTITY_POLICY:
        raise ValueError("FROZEN_QUANTITY_POLICY_MISMATCH")
    if rule_digest != plan.get("rule_digest") or not rule_digest:
        raise ValueError("RULE_DIGEST_MISMATCH")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("IDENTITY_REQUIRED")
    cash = _positive(capital, "capital_usdt")
    reference = _positive(plan.get("reference_entry_price"), "reference_entry_price")
    stop = _positive(plan.get("protective_stop"), "protective_stop")
    side = plan.get("side")
    if isinstance(side, bool) or side not in (-1, 1) or side * (reference - stop) <= 0:
        raise ValueError("INVALID_KNOWN_STRUCTURAL_RISK")
    qty = min(
        cash * RISK_FRACTION / abs(reference - stop),
        cash * NOTIONAL_FRACTION / reference,
    )
    _positive(qty, "qty_base")
    order = copy.deepcopy(plan)
    order.update(identity=identity, rule_digest=rule_digest, qty_base=qty)
    order["position_episode_id"] = (
        identity + ":" + plan["symbol"] + ":" + str(plan["order_active_ts_ms"])
    )
    order["signal"].update(
        reference_entry_price=reference,
        known_risk_cash_usdt=qty * abs(reference - stop),
        known_notional_usdt=qty * reference,
    )
    return order


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: Any
) -> dict[str, Any]:
    """A pivot becomes usable only after its right-hand 30m bar completes."""
    signal = position.get("signal", {})
    if signal.get("model_id") != MODEL_ID or signal.get("lifecycle_id") != LIFECYCLE_ID:
        raise ValueError("EXIT_MODEL_BINDING_MISMATCH")
    tick = _positive(signal.get("tick_size"), "tick_size")
    side = position.get("side")
    if isinstance(side, bool) or side not in (-1, 1):
        raise ValueError("INVALID_SIDE")
    rows = history.to_dict("records") if hasattr(history, "to_dict") else list(history)
    known, closed = int(bar["available_ts_ms"]), int(bar["close_ts_ms"])
    if any(r["available_ts_ms"] > known or r["close_ts_ms"] > closed for r in rows):
        raise ValueError("EXIT_HISTORY_CONTAINS_FUTURE")
    if not rows or any(
        rows[-1].get(k) != bar.get(k)
        for k in (
            "open_ts_ms",
            "close_ts_ms",
            "available_ts_ms",
            "segment_id",
            "high",
            "low",
            "close",
        )
    ):
        raise ValueError("EXIT_HISTORY_CURRENT_BAR_MISMATCH")
    post_entry = [r for r in rows if r["open_ts_ms"] >= position["entry_ts_ms"]]
    if len(post_entry) < 3:
        return {"reason": "NO_POST_ENTRY_CONFIRMED_COUNTER_PIVOT"}
    left, center, right = post_entry[-3:]
    if any(r["close_ts_ms"] != r["open_ts_ms"] + TF for r in (left, center, right)):
        raise ValueError("EXIT_CANONICAL_30M_REQUIRED")
    if (
        center["open_ts_ms"] != left["close_ts_ms"]
        or right["open_ts_ms"] != center["close_ts_ms"]
        or len({r["segment_id"] for r in (left, center, right)}) != 1
    ):
        raise ValueError("EXIT_DETAIL_GAP_UNRESOLVED")
    key = "low" if side == 1 else "high"
    levels = [_positive(r[key], key) for r in (left, center, right)]
    pivot = (
        levels[1] < min(levels[0], levels[2])
        if side == 1
        else levels[1] > max(levels[0], levels[2])
    )
    if not pivot:
        return {"reason": "NO_NEW_STRICT_COUNTER_PIVOT"}
    candidate = levels[1] - side * tick
    current = _positive(position["stop_price"], "current_stop")
    if candidate <= 0 or side * (candidate - current) <= 0:
        return {"reason": "COUNTER_PIVOT_DOES_NOT_TIGHTEN"}
    return {"next_stop": candidate, "reason": "POST_ENTRY_CONFIRMED_COUNTER_PIVOT"}


def compile_model(
    model_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Common chronological-runner envelope; completeness is policy, not readiness."""
    result = evaluate(model_id, frames, config)
    decisions = {}
    for symbol, frame in frames.items():
        own = frame.copy(deep=True)
        own["symbol"] = symbol
        decisions[symbol] = own
    return {
        **result,
        "complete": True,
        "timeframe_min": 30,
        "execution_mode": "DETAIL_CONDITIONAL",
        "decisions": decisions,
        "genuine_tick_receipt_verified": False,
        "genuine_economic_readiness": "CONDITIONAL_DATA_BLOCKED",
    }
