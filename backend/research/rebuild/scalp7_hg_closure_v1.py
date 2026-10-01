"""One 1997 HG sequence with declared research lifecycle; no economic authority.

Frozen raw-price HG grammar supplies ADX qualification and first EMA touch.
Expiry, rearm, latency, sizing and numerical trailing are separate hypotheses.
The existing minute execution engine owns fills and unresolved positions.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_exact25_structure_v1 as source
from backend.research.rebuild import scalp7_exact25_structure_models_v1 as mechanics
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
)
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

MODEL_ID = "HG1997_FIRST_PULLBACK_STOP_V1"
LIFECYCLE_ID = "HG1997_DECLARED_FIRST_TOUCH_EXPIRY_PIVOT_TRAIL_V1"
VERSION = "scalp7.hg_closure.v1"
MINUTE = 60_000
TF = 30 * MINUTE
QUANTITY_POLICY = copy.deepcopy(mechanics.QUANTITY_POLICY)
TERMINAL = {"CLOSED", "CANCELLED", "EXPIRED", "UNRESOLVED"}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def profile(model_id: str = MODEL_ID, tick_size: float | None = None) -> dict[str, Any]:
    if model_id != MODEL_ID:
        raise ValueError("HG_SINGLE_SELECTED_MODEL_REQUIRED")
    tick = mechanics._positive(tick_size, "instrument_price_tick")
    return {
        "model_id": MODEL_ID,
        "strategy_id": "keltner_trend",
        "decision_tf_min": 30,
        "decision_availability_policy": "BAR_CLOSE_ONLY; DELAYED_FEATURE_CLOCK_UNSUPPORTED_AND_REJECTED",
        "detail_availability_policy": "BAR_CLOSE_ONLY; DELAYED_MINUTE_DELIVERY_UNSUPPORTED_AND_REJECTED",
        "source_mode": "HG_1997_CONDITIONAL",
        "selection_basis": "1997 explicit qualification/touch/conditional-entry sequence, not economic outcomes",
        "source_config": {
            "mode_id": "HG_1997_CONDITIONAL",
            "timeframe_min": 30,
            "hypothesis_id": MODEL_ID,
            "qualification_expiry_bars": 20,
            "requalification_adx_below": 25,
            "tick_size": tick,
        },
        "lifecycle_id": LIFECYCLE_ID,
        "quantity_policy": copy.deepcopy(QUANTITY_POLICY),
        "activation_policy": "FIRST_MINUTE_OPEN_STRICTLY_AFTER_FEATURE_AVAILABILITY",
        "pending_expiry_minutes": 30,
        "pending_invalidation": "FIRST_CAUSALLY_OBSERVED_STOP_ONLY_MINUTE; BOTH_TRIGGER_AND_STOP_REMAIN_UNRESOLVED",
        "stop_policy": "FIXED_FIRST_TOUCH_EXTREME_PLUS_ONE_MEASURED_PRICE_TICK",
        "source_boundary": "REQUIRE_TOUCH_BAR_RANGE_CONTAINS_EMA; WHOLE_BAR_GAP_THROUGH_REJECTED",
        "direction_persistence": "INITIAL_DIRECTION_RETAINED_UNTIL_CONSUMPTION_OR_20BAR_EXPIRY_HYPOTHESIS",
        "trailing_policy": "POST_ENTRY_STRICT_1L1R_COUNTER_PIVOT; NEXT_DETAIL_BAR; TIGHTEN_ONLY",
        "terminal_policy": "NO_FORCED_CLOSE; UNKNOWN_OWNERSHIP_RETAINED; NO_AUTOMATIC_RETRY",
        "requalification_policy": "UNCHANGED_SOURCE_PRODUCER_REARM_ADX_LT25_THEN_LATER_NEW_GT30_RISING_QUALIFIER",
        "exact_source_reproduction": False,
        "economic_status": "NOT_RUN",
        "new_full_authorized": 0,
    }


def _rules(profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "hg_1997_ordered_sequence",
            "origin": "SOURCE_DIRECT",
            "expression": "ADX14 above 30 and rising; later first EMA20 retracement; conditional stop above previous completed bar high for long, reverse for short; structural protective stop and qualitative trailing. No 2004 oscillator case is merged.",
            "unit": "ADX_points_periods_and_ordered_price_events",
            "version": "AIQ_Opening_Bell_August_1997",
            "source_id": "R09",
            "source_mode": "HG_1997_CONDITIONAL",
            "source_locator": "source_package archive R1/R2 HG record; August1997 page2 Holy Grail",
        },
        {
            "rule_id": "hg_unchanged_raw_producer",
            "origin": "EXISTING_FROZEN",
            "expression": "Call structure_v1.evaluate keltner_trend HG_1997_CONDITIONAL; preserve positive parent and rejected ADX/exit variants unchanged.",
            "unit": "raw_completed_30m_OHLCV",
            "version": source.VERSION,
            "code_path": "backend/research/rebuild/scalp7_exact25_structure_v1.py",
            "code_sha": hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest(),
        },
        {
            "rule_id": "hg_declared_mechanical_closure",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": json.dumps(profiles, sort_keys=True),
            "unit": "30m_bars_minutes_ADX_points_price_tick_base_quantity_USDT",
            "version": VERSION,
            "hypothesis_id": MODEL_ID,
            "rationale": "One fixed pre-economic research closure: 20-bar qualification horizon matches EMA period; ADX below25 resets before a later fresh qualifier; one decision interval bounds resting order life. Crypto30m, strict one-bar rise, EMA seed, direction, tick buffer, 1L1R trail and risk0.25%/notional25% are not author defaults. Existing structural-pivot mechanics are reused without importing Anti entry semantics, parent GMMA/regimes or failed BE/scratch/partial variants.",
            "exact_source_reproduction": False,
        },
        {
            "rule_id": "hg_reused_structural_mechanics",
            "origin": "EXISTING_FROZEN",
            "expression": "Reuse finite causal size and post-entry strict1L1R counter-pivot implementation only; choice for HG is declared hypothesis above.",
            "unit": "base_quantity_price_completed_30m_bars",
            "version": mechanics.VERSION,
            "code_path": "backend/research/rebuild/scalp7_exact25_structure_models_v1.py",
            "code_sha": hashlib.sha256(
                Path(mechanics.__file__).read_bytes()
            ).hexdigest(),
        },
    ]


def evaluate(
    model_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    if model_id != MODEL_ID or not frames:
        raise ValueError("HG_MODEL_AND_FRAMES_REQUIRED")
    if set(config) - {"tick_size", "tick_sizes"}:
        raise ValueError("HG_FIXED_PROFILE_CANNOT_BE_RETUNED")
    if ("tick_size" in config) == ("tick_sizes" in config):
        raise ValueError("ONE_EXPLICIT_PRICE_TICK_SOURCE_REQUIRED")
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
        for row in frame.to_dict("records"):
            if row["open_ts_ms"] % TF or row["close_ts_ms"] != row["open_ts_ms"] + TF:
                raise ValueError("EXCLUSIVE_CANONICAL_30M_REQUIRED")
            if row["available_ts_ms"] != row["close_ts_ms"]:
                raise ValueError("HG_BAR_CLOSE_FEATURE_CLOCK_REQUIRED")
        chosen = profiles[symbol]
        produced = source.evaluate(
            "keltner_trend", {symbol: frame}, chosen["source_config"]
        )
        events.extend(produced["events"])
        for intent in produced["intents"]:
            touch = next(
                e
                for e in produced["events"]
                if e["kind"] == "FIRST_POST_QUALIFICATION_EMA_TOUCH"
                and e["available_ts_ms"] == intent["feature_available_ts_ms"]
            )
            candle = next(
                r
                for r in frame.to_dict("records")
                if r["available_ts_ms"] == intent["feature_available_ts_ms"]
            )
            if not candle["low"] <= touch["ema20"] <= candle["high"]:
                events.append(
                    {**touch, "kind": "HG_GAP_THROUGH_EMA_NO_OBSERVED_TOUCH_NO_ORDER"}
                )
                continue
            known = int(intent["feature_available_ts_ms"])
            active = (known // MINUTE + 1) * MINUTE
            signal = {
                **copy.deepcopy(intent),
                "model_id": MODEL_ID,
                "lifecycle_id": LIFECYCLE_ID,
                "tick_size": chosen["source_config"]["tick_size"],
                "profile_sha256": _hash(chosen),
            }
            plans.append(
                {
                    "model_id": MODEL_ID,
                    "strategy_id": "keltner_trend",
                    "symbol": symbol,
                    "side": intent["side"],
                    "decision_tf_min": 30,
                    "feature_available_ts_ms": known,
                    "order_submit_ts_ms": known,
                    "order_active_ts_ms": active,
                    "expires_ts_ms": active + TF,
                    "order_kind": "STOP_MARKET",
                    "trigger_price": intent["trigger_price"],
                    "protective_stop": intent["protective_stop"],
                    "reference_entry_price": intent["trigger_price"],
                    "quantity_policy": copy.deepcopy(QUANTITY_POLICY),
                    "lifecycle_id": LIFECYCLE_ID,
                    "rule_digest": digest,
                    "timing_basis": "HISTORICAL_MODEL",
                    "signal": signal,
                    "source_provenance": {
                        "producer": "scalp7_exact25_structure_v1.evaluate",
                        "source_rule_digest": produced["rule_digest"],
                        "source_intent_sha256": _hash(intent),
                        "profile_sha256": _hash(chosen),
                        "source_claim": "1997_SEQUENCE_WITH_DECLARED_CLOSURE_NOT_FULL_ORIGINAL",
                    },
                }
            )
    plans.sort(key=lambda p: (p["feature_available_ts_ms"], p["symbol"]))
    return {
        "model_id": MODEL_ID,
        "profile": profiles,
        "plans": plans,
        "events": events,
        "rules": rules,
        "rule_digest": digest,
        "complete_configured_research_model": True,
        "exact_source_reproduction": False,
        "economic_execution_performed": False,
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
        "limitations": [
            "Only one1997 grammar mode; 30m crypto and all numeric closure hypotheses are separate from source.",
            "Tick is measured instrument price grid, not historical trade/quote evidence.",
            "OHLC conditional entry is modeled, never observed; same-minute ambiguous paths stay unresolved.",
            "Unfilled/expired/invalidated order never becomes a trade; unresolved ownership blocks later entries.",
            "No economic measurement or original25/G4 completion; original source management remains partially unspecified.",
            "Decision features support BAR_CLOSE availability only; delayed source or management decisions are rejected before plan construction.",
        ],
    }


def _mechanical(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("model_id") != MODEL_ID or value.get("lifecycle_id") != LIFECYCLE_ID:
        raise ValueError("HG_MODEL_LIFECYCLE_BINDING_MISMATCH")
    return {
        **copy.deepcopy(value),
        "model_id": mechanics.MODEL_ID,
        "lifecycle_id": mechanics.LIFECYCLE_ID,
    }


def create_order(
    plan: dict[str, Any], capital: float, identity: str, rule_digest: str
) -> dict[str, Any]:
    translated = _mechanical(plan)
    translated["signal"] = _mechanical(plan["signal"])
    order = mechanics.create_order(translated, capital, identity, rule_digest)
    order.update(model_id=MODEL_ID, lifecycle_id=LIFECYCLE_ID)
    order["signal"].update(model_id=MODEL_ID, lifecycle_id=LIFECYCLE_ID)
    return order


def entry_update(signal: dict[str, Any], entry_price: float) -> dict[str, Any]:
    _mechanical(signal)
    price = mechanics._positive(entry_price, "entry_price")
    stop = mechanics._positive(signal.get("protective_stop"), "protective_stop")
    if signal.get("side") not in (-1, 1) or signal["side"] * (price - stop) <= 0:
        return {"reject": True, "reason": "HG_ENTRY_INVALIDATES_FROZEN_SWING"}
    return {"stop_price": stop}


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: Any
) -> dict[str, Any]:
    return mechanics.exit_update(
        {**position, "signal": _mechanical(position.get("signal", {}))}, bar, history
    )


class HGExecutionAdapter(DetailExecutionAdapter):
    """Existing engine plus causal unfilled swing invalidation; no fill override."""

    def process_detail_bar(self, bar: Mapping[str, Any]) -> dict[str, Any]:
        if bar["available_ts_ms"] != bar["close_ts_ms"]:
            raise ValueError("HG_BAR_CLOSE_DETAIL_CLOCK_REQUIRED")
        event = super().process_detail_bar(bar)
        if (
            self.state == "PENDING"
            and self.order_state == "PENDING"
            and event["status"] == "WAIT"
        ):
            invalid = (
                float(bar["low"]) <= self.stop
                if self.order["side"] == 1
                else float(bar["high"]) >= self.stop
            )
            if invalid:
                return self.cancel(
                    int(bar["available_ts_ms"]), "HG_PREENTRY_SWING_INVALIDATED"
                )
        return event


def create_adapter(order: dict[str, Any], *, fee_rate: float) -> HGExecutionAdapter:
    _mechanical(order)
    return HGExecutionAdapter(
        order,
        fill_model=MODEL,
        fee_rate=fee_rate,
        entry_update=entry_update,
        exit_update=exit_update,
    )


def compile_model(
    model_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    result = evaluate(model_id, frames, config)
    return {
        **result,
        "complete": True,
        "timeframe_min": 30,
        "execution_mode": "DETAIL_CONDITIONAL",
        "decisions": {s: f.assign(symbol=s) for s, f in frames.items()},
        "adapter_factory": "scalp7_hg_closure_v1.create_adapter",
        "genuine_tick_receipt_verified": False,
        "genuine_economic_readiness": "DATA_COST_FREEZE_AND_NEW_AUTHORIZATION_REQUIRED",
    }


def run_synthetic_fixture(
    frames: dict[str, pd.DataFrame],
    details: dict[str, pd.DataFrame],
    config: dict[str, Any],
    *,
    dataset_kind: str,
    capital: float = 10000,
    fee_rate: float = 0.001,
) -> dict[str, Any]:
    """Bounded declared fixtures only; one symbol owner retained after unknowns.

    The declaration is a caller assertion, not independent data authentication.
    Shared-portfolio allocation and economic authorization are not provided.
    """
    if dataset_kind != "SYNTHETIC_FIXTURE" or set(frames) != set(details):
        raise ValueError("MATCHED_DECLARED_SYNTHETIC_FIXTURE_REQUIRED")
    if (
        not 0 < len(frames) <= 3
        or sum(map(len, frames.values())) > 256
        or sum(map(len, details.values())) > 2048
    ):
        raise ValueError("HG_FIXTURE_CAP_EXCEEDED")
    for symbol, detail_frame in details.items():
        if "symbol" in detail_frame and any(detail_frame["symbol"] != symbol):
            raise ValueError("HG_DETAIL_SYMBOL_MISMATCH")
    compiled = compile_model(MODEL_ID, frames, config)
    executions, dispositions = [], []
    occupied: dict[str, int] = {}
    for plan in compiled["plans"]:
        symbol, active = plan["symbol"], plan["order_active_ts_ms"]
        if occupied.get(symbol, -1) >= plan["feature_available_ts_ms"]:
            dispositions.append(
                {
                    "symbol": symbol,
                    "active_ts_ms": active,
                    "status": "PRIOR_OWNERSHIP_RETAINED_NO_NEW_ORDER",
                }
            )
            continue
        adapter = create_adapter(
            create_order(plan, capital, MODEL_ID + ":FIXTURE", compiled["rule_digest"]),
            fee_rate=fee_rate,
        )
        decision_rows = compiled["decisions"][symbol].to_dict("records")
        for detail in details[symbol].to_dict("records"):
            if detail["close_ts_ms"] <= active:
                continue
            adapter.process_detail_bar({**detail, "symbol": symbol})
            if adapter.state in TERMINAL:
                break
            for decision in decision_rows:
                if (
                    decision["available_ts_ms"] == detail["available_ts_ms"]
                    and decision["close_ts_ms"] == detail["close_ts_ms"]
                    and decision["open_ts_ms"] >= active
                ):
                    history = pd.DataFrame(
                        [
                            r
                            for r in decision_rows
                            if r["available_ts_ms"] <= decision["available_ts_ms"]
                            and r["close_ts_ms"] <= decision["close_ts_ms"]
                        ]
                    )
                    adapter.process_decision_bar(decision, history)
        result = adapter.finish()
        executions.append(result)
        occupied[symbol] = (
            2**63 - 1 if result["state"] == "UNRESOLVED" else adapter.last_available
        )
    return {
        "model_id": MODEL_ID,
        "events": compiled["events"],
        "plans": compiled["plans"],
        "executions": executions,
        "dispositions": dispositions,
        "economic_execution_performed": False,
        "new_full_runs": 0,
        "dataset_kind": dataset_kind,
        "exact_source_reproduction": False,
    }
