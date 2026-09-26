"""Complete declared research models over frozen reference producers.

No source-exact certification, data loader, economic run, live order, or
promotion. The prior SR economic pair remains an immutable failed experiment.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_exact25_reference_v1 as source
from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

DAY = 86_400_000
SR = "sr_levels_30m_prior_utc_day_box_intraday_v1"
SR_CONTROL = "sr_levels_30m_prior_utc_day_box_breakout_control_v1"
SOUP = "liquidity_sweep_15m_daily_soup_intraday_v1"
MODEL_IDS = (SR_CONTROL, SR, SOUP)
PRODUCER_SHA256 = "2becff8f57c25ca724a5d1bbabe352c45950d89d3996c70bb03cc61f951b3974"
QTY_POLICY: dict[str, Any] = {
    "risk_fraction": 0.0025,
    "notional_fraction": 0.10,
    "capital_unit": "USDT",
    "quantity_unit": "BASE",
    "gap_notional_policy": "REJECT_ABOVE_RESERVED_NOTIONAL",
}
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def _finite(value: Any, name: str, *, positive: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + name)
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return result


def _hypothesis(key: str, expression: str) -> dict[str, Any]:
    return {
        "rule_id": key,
        "origin": "DECLARED_HYPOTHESIS",
        "expression": expression,
        "unit": "UTC_ms/price/base_quantity/USDT",
        "version": "reference-models-v1",
        "hypothesis_id": "EXACT25_REFERENCE_INTRADAY_COMPLETION_V1",
        "rationale": (
            "Make a finite executable research model with causal references, "
            "pattern invalidation and explicit intraday capital allocation; "
            "these choices are not source-original defaults or fitted thresholds."
        ),
        "exact_source_reproduction": False,
    }


def catalog() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {
        SR: {
            "strategy_id": "sr_levels",
            "timeframe_min": 30,
            "source_mode": "BOX_RETEST_RECLAIM",
            "complete_configured_model": True,
            "source_exact": False,
            "data_requirements": ["complete prior UTC day", "real 1m detail"],
            "duplicate_status": "NEW_ARCHITECTURE_NOT_PR1340_ROLLING50_SR_PAIR",
        },
        SOUP: {
            "strategy_id": "liquidity_sweep",
            "timeframe_min": 15,
            "source_mode": "TURTLE_SOUP_DAILY_LONG",
            "complete_configured_model": True,
            "source_exact": False,
            "data_requirements": [
                "20 complete prior UTC daily sessions",
                "point-in-time verified tick receipt",
                "real 1m detail",
            ],
            "duplicate_status": "NO_COMPLETED_MATCHING_FULL_RECOVERED",
        },
    }
    result[SR]["comparison_role"] = "RETEST_CHILD"
    result[SR_CONTROL] = {**result[SR], "comparison_role": "BREAKOUT_CONTROL"}
    return result


def dispositions() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {
        "anchor_vwap_trend": {
            "status": "MATERIAL_DATA_AND_ANCHOR_BLOCKED",
            "reason": "Canonical volume units UNKNOWN; no actual quote/base numerator or causal automatic anchor contract.",
        },
        "fvg_revert": {
            "status": "MATERIAL_LIMIT_EXECUTION_BLOCKED",
            "reason": "Resting limit requires actual fill receipts or separately approved fill model; OHLC touch is not a fill.",
        },
        "vwap_revert": {
            "status": "MATERIAL_DATA_AND_SELECTION_BLOCKED",
            "reason": "No genuine quote/base VWAP or bound parabolic selection/anchor; no synthetic VWAP substitution.",
        },
        "alpha_combo": {
            "status": "FUSION_BLOCKED",
            "reason": "No two independently fresh-validated B materials; capital allocation component is not an approved composite.",
        },
        "grid_rebalance": {
            "status": "NATIVE_SPOT_AND_DGT_SOURCE_BLOCKED",
            "reason": "Frozen DGT runner/callee and cash/reset contracts unresolved; perpetual bars cannot certify native spot inventory fills.",
        },
    }
    for model_id, row in catalog().items():
        result[row["strategy_id"]] = {
            "status": "CONFIGURED_MODEL_IMPLEMENTED_ECONOMICS_NOT_RUN",
            "model_id": model_id,
            "source_exact": False,
        }
    result["sr_levels"]["model_id"] = SR
    result["sr_levels"]["control_model_id"] = SR_CONTROL
    return result


def rules(model_id: str) -> list[dict[str, Any]]:
    profile = catalog()[model_id]
    if (
        hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest()
        != PRODUCER_SHA256
    ):
        raise ValueError("FROZEN_REFERENCE_PRODUCER_CHANGED")
    rows = [
        {
            "rule_id": "frozen_reference_producer",
            "origin": "EXISTING_FROZEN",
            "expression": "Call reference.evaluate using its actual configured event grammar.",
            "unit": "completed 15m/30m bars",
            "version": "PR1343",
            "code_path": "backend/research/rebuild/scalp7_exact25_reference_v1.py",
            "code_sha": PRODUCER_SHA256,
        }
    ]
    if model_id in (SR, SR_CONTROL):
        rows.append(
            _hypothesis(
                "fixed_reference_selection",
                "Every UTC day uses the immediately preceding complete UTC-day high/low; "
                "Completed breakout reference and opposite box-edge stop are common to both arms. "
                "No rolling50, relative-volume filter or inherited ATR/2R scratch.",
            )
        )
        rows.append(
            _hypothesis(
                "entry_confirmation_axis",
                (
                    "First completed breakout close produces next-open entry."
                    if model_id == SR_CONTROL
                    else "A separate later retest and reclaim of the fixed breakout edge produces next-open entry."
                ),
            )
        )
        rows.append(
            _hypothesis(
                "box_failure_exit",
                "After fill, a completed close strictly back through the breakout edge exits next open; "
                "no profit target or automatically inherited trailing stop.",
            )
        )
    else:
        rows.append(
            _hypothesis(
                "daily_soup_execution_transfer",
                "Preserve source prior20 DAILY low, latest-tie age>=4 DAILY sessions, "
                "5-tick recovery trigger and 1-tick stop buffer; recognize on completed 15m "
                "UTC crypto bars, long-only. Point-in-time tick evidence required.",
            )
        )
        rows.append(
            _hypothesis(
                "soup_intraday_management",
                "Initial stop is the session low at recognition minus one tick; after entry, "
                "a completed close below the old20-day low exits next open; on a close above "
                "actual entry, trail to that completed bar low minus one tick, effective later. "
                "This is a declared Soup adaptation, not PlusOne or original full management.",
            )
        )
    rows.append(
        _hypothesis(
            "finite_session_lifecycle",
            f"tf={profile['timeframe_min']}m. Entry expiry is min(source expiry, "
            "UTC-day end minus 2 decision bars). No new activation at/after that cutoff. "
            "Exit at the first minute open after the completed bar ending UTC-day end minus "
            "1 decision bar; reserve the last decision bar for liquidation. Missing detail "
            "or tail remains unresolved; no synthetic boundary fill.",
        )
    )
    rows.append(
        _hypothesis(
            "preentry_quantity",
            "At admission q=min(available capital*0.0025/abs(known reference entry-stop), "
            "available capital*0.10/known reference entry). One unlevered reserved sleeve; "
            "actual fill gap may exceed planned stop risk, never claimed a guaranteed risk cap. "
            "A fill exceeding reserved notional is rejected by caller without resizing or leverage.",
        )
    )
    validate_rules(rows)
    return rows


def _daily_groups(
    frame: pd.DataFrame, minutes: int
) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    rows = source._bars(frame, minutes)
    groups: dict[int, list[dict[str, Any]]] = {}
    step = minutes * 60_000
    for row in rows:
        if row["open_ts_ms"] % step:
            raise ValueError("UTC_DECISION_ALIGNMENT_REQUIRED")
        day = row["open_ts_ms"] // DAY * DAY
        groups.setdefault(day, []).append(row)
    daily = []
    for day, own in groups.items():
        complete = (
            len(own) == DAY // step
            and [r["open_ts_ms"] for r in own] == list(range(day, day + DAY, step))
            and len({r["segment_id"] for r in own}) == 1
        )
        if complete:
            daily.append(
                {
                    "open_ts_ms": day,
                    "close_ts_ms": day + DAY,
                    "available_ts_ms": max(r["available_ts_ms"] for r in own),
                    "segment_id": own[0]["segment_id"],
                    "session_index": day // DAY,
                    "open": own[0]["open"],
                    "high": max(r["high"] for r in own),
                    "low": min(r["low"] for r in own),
                    "close": own[-1]["close"],
                }
            )
    columns = [
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "session_index",
        "open",
        "high",
        "low",
        "close",
    ]
    return {k: pd.DataFrame(v) for k, v in groups.items()}, pd.DataFrame(
        daily, columns=columns
    )


def _tick(config: dict[str, Any], symbol: str, day: int) -> dict[str, Any] | None:
    evidence = config.get("tick_evidence", {}).get(symbol)
    if evidence is None:
        return None
    stamp = evidence.get("available_ts_ms")
    valid = evidence.get("valid_from_ms")
    if (
        isinstance(stamp, bool)
        or not isinstance(stamp, int)
        or isinstance(valid, bool)
        or not isinstance(valid, int)
        or min(stamp, valid) < 0
        or max(stamp, valid) > day
    ):
        return None
    digest = evidence.get("source_receipt_sha256", "")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        or not isinstance(evidence.get("source_ref"), str)
        or not evidence["source_ref"].strip()
    ):
        raise ValueError("TICK_SOURCE_RECEIPT_REQUIRED")
    return {**evidence, "tick_size": _finite(evidence.get("tick_size"), "tick_size")}


def compile_model(
    model_id: str, frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> dict[str, Any]:
    """Compile actual source events; complete means specified, never economics passed."""
    if model_id not in MODEL_IDS:
        raise ValueError("UNKNOWN_REFERENCE_MODEL")
    if set(config) - {"tick_evidence"}:
        raise ValueError("UNREGISTERED_REFERENCE_MODEL_CONFIG")
    profile = catalog()[model_id]
    tf = profile["timeframe_min"]
    step = tf * 60_000
    declared_rules = rules(model_id)
    plans: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    decisions: dict[str, pd.DataFrame] = {}
    for symbol, frame in sorted(frames.items()):
        own_frame = frame.copy()
        own_frame["symbol"] = symbol
        decisions[symbol] = own_frame
        groups, daily = _daily_groups(own_frame, tf)
        complete_days = set(daily.open_ts_ms)
        for day, current in groups.items():
            conf: dict[str, Any] = {
                "timeframe_min": tf,
                "symbol": symbol,
                "source_clock": "CANONICAL_COMPLETED_UTC_EXCLUSIVE_CLOSE",
                "hypothesis_id": "EXACT25_REFERENCE_INTRADAY_COMPLETION_V1",
                "rationale": "Declared crypto UTC intraday model, source full reproduction not claimed.",
                "mode_id": profile["source_mode"],
            }
            tick = None
            if model_id in (SR, SR_CONTROL):
                if day - DAY not in complete_days:
                    events.append(
                        {
                            "symbol": symbol,
                            "day_ms": day,
                            "status": "PRIOR_COMPLETE_UTC_DAY_MISSING",
                        }
                    )
                    continue
                prior = groups[day - DAY]
                if int(prior.available_ts_ms.max()) > day:
                    events.append(
                        {
                            "symbol": symbol,
                            "day_ms": day,
                            "status": "PRIOR_DAY_NOT_YET_AVAILABLE",
                        }
                    )
                    continue
                conf.update(
                    reference_start_ts_ms=day - DAY,
                    reference_end_ts_ms=day,
                    reference_known_ts_ms=day,
                    reference_id=f"{symbol}:{day-DAY}",
                    reference_type="DECLARED_PRIOR_SESSION",
                    intent_ttl_bars=1,
                )
                inputs = {"decision": pd.concat([prior, current], ignore_index=True)}
            else:
                tick = _tick(config, symbol, day)
                if tick is None:
                    events.append(
                        {
                            "symbol": symbol,
                            "day_ms": day,
                            "status": "PIT_TICK_EVIDENCE_MISSING",
                        }
                    )
                    continue
                conf.update(
                    source_timeframe="1d",
                    daily_calendar="EXPLICIT_SESSIONS",
                    session_bounds=[
                        {
                            "open_ts_ms": day,
                            "close_ts_ms": day + DAY,
                            "session_id": f"{symbol}:{day}",
                        }
                    ],
                    tick_size=tick["tick_size"],
                    entry_offset_ticks=5,
                    stop_buffer_ticks=1,
                )
                inputs = {"decision": current, "1d": daily}
            produced = source.evaluate(profile["strategy_id"], inputs, conf)
            if produced["status"].startswith("BLOCKED"):
                events.append(
                    {
                        "symbol": symbol,
                        "day_ms": day,
                        "status": produced["status"],
                        "reason": produced.get("error"),
                    }
                )
                continue
            events.extend({**e, "symbol": symbol} for e in produced["events"])
            intents = (
                _box_control_intents(produced, symbol, tf)
                if model_id == SR_CONTROL
                else produced["intents"]
            )
            for intent in intents:
                active = int(intent["order_active_ts_ms"])
                expiry = min(int(intent["expires_ts_ms"]), day + DAY - 2 * step)
                if active >= expiry or active % 60_000:
                    events.append(
                        {
                            "symbol": symbol,
                            "status": "SESSION_CUTOFF_OR_INTRAMINUTE_ACTIVATION",
                            "available_ts_ms": active,
                        }
                    )
                    continue
                signal_row = current[current.close_ts_ms == intent["setup_ts_ms"]].iloc[
                    -1
                ]
                if model_id in (SR, SR_CONTROL):
                    reference = produced["components"][0]
                    edge = reference["upper" if intent["side"] == 1 else "lower"]
                    price = float(signal_row.close)
                else:
                    reference = produced["components"][0]
                    edge = reference["value"]
                    price = float(intent["trigger_price"])
                if intent["side"] * (price - intent["protective_stop"]) <= 0:
                    events.append(
                        {"symbol": symbol, "status": "NONPOSITIVE_DECLARED_ENTRY_RISK"}
                    )
                    continue
                plan = {
                    **intent,
                    "model_id": model_id,
                    "expires_ts_ms": expiry,
                    "reference_entry_price": price,
                    "reference_edge": edge,
                    "session_end_ms": day + DAY,
                    "liquidation_decision_close_ms": day + DAY - step,
                    "qty_policy": copy.deepcopy(QTY_POLICY),
                    "producer_rule_digest": produced["rule_digest"],
                    "timing_basis": "HISTORICAL_MODEL",
                    "lifecycle_gap": None,
                    "complete_configured_model": True,
                    "source_exact": False,
                    "tick_evidence": tick,
                }
                plans.append(plan)
    return {
        "model_id": model_id,
        "plans": sorted(plans, key=lambda p: (p["order_active_ts_ms"], p["symbol"])),
        "decisions": decisions,
        "events": events,
        "rules": declared_rules,
        "rule_digest": validate_rules(declared_rules),
        "complete": True,
        "execution_mode": "DETAIL_CONDITIONAL",
        "authority": dict(AUTHORITY),
        "economics": "NOT_RUN",
        "source_exact": False,
        "tick_receipt_authenticity_verified_by_this_module": False,
    }


def create_order(
    plan: dict[str, Any], capital: float, identity: str, rule_digest: str
) -> dict[str, Any]:
    if plan.get("model_id") not in MODEL_IDS or plan.get("qty_policy") != QTY_POLICY:
        raise ValueError("FROZEN_MODEL_AND_QUANTITY_POLICY_REQUIRED")
    cash = _finite(capital, "available_capital_usdt")
    entry = _finite(plan.get("reference_entry_price"), "reference_entry_price")
    stop = _finite(plan.get("protective_stop"), "protective_stop")
    risk = plan["side"] * (entry - stop)
    if risk <= 0:
        raise ValueError("NONPOSITIVE_PLANNED_RISK")
    quantity = min(
        cash * QTY_POLICY["risk_fraction"] / risk,
        cash * QTY_POLICY["notional_fraction"] / entry,
    )
    if not identity or not rule_digest:
        raise ValueError("FROZEN_IDENTITY_AND_RULE_DIGEST_REQUIRED")
    return {
        **copy.deepcopy(plan),
        "identity": identity,
        "rule_digest": rule_digest,
        "qty_base": quantity,
        "signal": copy.deepcopy(plan),
        "reserved_notional_usdt": cash * QTY_POLICY["notional_fraction"],
        "planned_stop_risk_usdt": quantity * risk,
        "position_episode_id": f"{identity}:{plan['symbol']}:{plan['order_active_ts_ms']}",
    }


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: Any
) -> dict[str, Any]:
    del history
    plan = position["signal"]
    model_id = plan["model_id"]
    if model_id not in MODEL_IDS:
        raise ValueError("UNKNOWN_REFERENCE_MODEL")
    if bar["available_ts_ms"] < bar["close_ts_ms"]:
        raise ValueError("COMPLETED_DECISION_REQUIRED")
    if bar["close_ts_ms"] >= plan["liquidation_decision_close_ms"]:
        return {"exit_next_open": True, "reason": "DECLARED_UTC_SESSION_LIQUIDATION"}
    side = position["side"]
    if side * (float(bar["close"]) - plan["reference_edge"]) < 0:
        return {"exit_next_open": True, "reason": "REFERENCE_RECOVERY_THESIS_FAILED"}
    if model_id == SOUP and float(bar["close"]) > position["entry_price"]:
        return {
            "next_stop": float(bar["low"]) - plan["tick_evidence"]["tick_size"],
            "exit_next_open": False,
            "reason": "DECLARED_COMPLETED_BAR_SOUP_TRAIL",
        }
    return {"exit_next_open": False, "reason": "REFERENCE_THESIS_INTACT"}


def _box_control_intents(
    produced: dict[str, Any], symbol: str, tf: int
) -> list[dict[str, Any]]:
    """Use the actual frozen producer's earlier breakout event as sole axis."""
    reference = produced["components"][0]
    intents = []
    for event in produced["events"]:
        if event["event"] != "FIXED_REFERENCE_BREAKOUT":
            continue
        known, side = event["available_ts_ms"], event["side"]
        intents.append(
            {
                "strategy_id": "sr_levels",
                "mode_id": "BOX_FIRST_BREAKOUT_CONTROL",
                "symbol": symbol,
                "side": side,
                "setup_ts_ms": event["event_ts_ms"],
                "feature_available_ts_ms": known,
                "order_submit_ts_ms": known,
                "order_active_ts_ms": known,
                "decision_tf_min": tf,
                "order_kind": "NEXT_OPEN",
                "trigger_price": None,
                "protective_stop": reference["lower" if side == 1 else "upper"],
                "expires_ts_ms": known + tf * 60_000,
                "reference_id": reference["reference_id"],
                "execution_evidence": "INTENT_ONLY_NOT_FILL",
            }
        )
    return intents
