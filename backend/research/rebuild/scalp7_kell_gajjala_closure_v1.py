"""Two declared Kell/Gajjala research closures; no economic execution authority.

Reuse sealed structure producers and the existing detail/account engine. Source
grammar, numeric translations, stock-to-crypto differences and incomplete data
admission remain separate. The only executable caller is bounded synthetic QA.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from backend.research.rebuild import scalp7_exact25_structure_v1 as source
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
    account_snapshots_from_ledger,
)
from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    inspect_entry_bar,
    validate_rules,
)
from backend.research.rebuild.scalp7_volume_contract_v1 import admit_observed_base_frame

VERSION = "KELL_GAJJALA_SOURCE_CLOSURE_V1"
KELL = "KELL_BASE_BREAK_HTF15_PARTIAL_PIVOT_V1"
GAJJALA = "GAJJALA_FLAG15_CRYPTO_PARTIAL_PIVOT_V1"
MODEL_IDS = (KELL, GAJJALA)
ALIASES = {
    "ema_ribbon_scalp": KELL,
    "break_and_continue": GAJJALA,
    "scalp_snap": GAJJALA,
}
MINUTE, TF, HOUR = 60_000, 900_000, 3_600_000
PRODUCER_SHA = "bd55ba07eb92d7ee47ed573738b3be470b2d2b43be29ab1c531531cc0662c7b6"
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}
QUANTITY = {"risk_fraction": 0.0025, "notional_fraction": 0.10, "unit": "BASE/USDT"}
PROFILE = {
    KELL: {
        "strategy_id": "ema_ribbon_scalp",
        "source_ids": ["S305", "S306"],
        "source_mode": "KELL_BASE_BREAK_DECLARED",
        "geometry": {
            "ema_length": 20,
            "pivot_left_bars": 1,
            "pivot_right_bars": 1,
            "base_bars": 3,
            "base_range_ratio": 0.5,
            "watch_extension_fraction": 0.05,
            "setup_expiry_bars": 8,
        },
        "entry": "RESTING_STOP_MARKET_AFTER_CONFIRMED_BASE_PIVOT",
    },
    GAJJALA: {
        "strategy_id": "break_and_continue",
        "source_ids": ["S301"],
        "source_mode": "GAJJALA_FLAG_15M_DECLARED",
        "geometry": {
            "impulse_lookback_bars": 20,
            "impulse_range_multiple": 2.0,
            "flag_max_retracement_fraction": 0.5,
            "flag_min_bars": 2,
            "flag_max_bars": 6,
            "pullback_volume_ratio": 0.7,
        },
        "entry": "COMPLETED_15M_RESUMPTION_THEN_NEXT_MINUTE_OPEN_VARIANT",
    },
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("NUMERIC_VALUE_REQUIRED:" + name)
    result = float(value)
    if not math.isfinite(result) or result < 0 or (result == 0 and not zero):
        raise ValueError("FINITE_POSITIVE_VALUE_REQUIRED:" + name)
    return result


def stamp(value, name):
    number = positive(value, name, zero=True)
    if int(number) != number:
        raise ValueError("INTEGER_TIMESTAMP_REQUIRED:" + name)
    return int(number)


def catalog():
    return {
        model: {
            **copy.deepcopy(PROFILE[model]),
            "model_id": model,
            "timeframe_min": 15,
            "context_timeframe_min": 60,
            "aliases": [key for key, value in ALIASES.items() if value == model],
            "independent_lineage_count": 1,
            "complete_configured_research_lifecycle": True,
            "source_exact": False,
            "fixture_caller": "run_fixture",
            "execution_mode": "DETAIL_CONDITIONAL_PARTIAL_RECEIPTS",
            "decision_availability_policy": "BAR_CLOSE_ONLY_DELAYED_FEATURE_CLOCK_REJECTED",
            "price_basis": "LAST_PRICE",
            "genuine_economic_readiness": "BLOCKED_DATA_TICK_COST_FREEZE_AND_AUTHORIZED_CALLER_REQUIRED",
            "historical_probe_or_full_runs": 0,
            "authority": dict(AUTHORITY),
        }
        for model in MODEL_IDS
    }


def rules(model_id):
    if model_id not in MODEL_IDS:
        raise ValueError("UNKNOWN_KELL_GAJJALA_MODEL")
    if hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest() != PRODUCER_SHA:
        raise ValueError("SEALED_STRUCTURE_PRODUCER_CHANGED")
    profile = PROFILE[model_id]
    rows = [
        {
            "rule_id": "source_ordered_grammar",
            "origin": "SOURCE_DIRECT",
            "expression": "Selection precedes formation and later price confirmation; source watch is not automatic entry; structural failure and partial management are separate events.",
            "unit": "ordered_price_events",
            "version": VERSION,
            "source_id": ",".join(profile["source_ids"]),
            "source_mode": profile["source_mode"],
            "source_locator": "Final source package mode cards Q03 Kell ARM/watch-SWAV; Q01 Gajjala 5m/15m flag and discretionary management.",
        },
        {
            "rule_id": "preserved_component",
            "origin": "EXISTING_FROZEN",
            "expression": "Reuse structure_v1 actual watch/base/pivot or impulse/low-volume flag producer, without changing sealed source.",
            "unit": "completed_15m_OHLCV",
            "version": "PR1343",
            "code_path": "backend/research/rebuild/scalp7_exact25_structure_v1.py",
            "code_sha": PRODUCER_SHA,
        },
        {
            "rule_id": "declared_geometry",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": json.dumps(profile, sort_keys=True),
            "unit": "bars_price_ratios",
            "version": VERSION,
            "hypothesis_id": model_id,
            "rationale": "Fixed explicit numeric translation before economics; not source-original defaults. Kell watch_extension_fraction is a required producer parameter unused in non-reversal mode.",
            "exact_source_reproduction": False,
        },
        {
            "rule_id": "selection_completion",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": "At setup origin use only available contiguous four completed1h symbol and benchmark bars: close>4bar SMA-seeded EMA, close/first-close return>0 and >=benchmark return, setup low>=four-bar support. Context age<=1h. No future winner scanner.",
            "unit": "1h_bars_return_fraction_price_UTC_ms",
            "version": VERSION,
            "hypothesis_id": model_id + ":PIT_SELECTION",
            "rationale": "Minimal raw-data higher-timeframe support and relative-strength translation; crypto benchmark adaptation is not the source US-stock scanner.",
            "exact_source_reproduction": False,
        },
        {
            "rule_id": "management_completion",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": "Close below known formation floor exits at next detail open. Strict post-entry1L1R low ratchets stop one instrument tick below pivot, never loosens. First completed post-entry close above preceding3bar highs and actual entry with range>preceding3bar mean schedules30% of held quantity at next minute open once. No2R target, no forced terminal fill.",
            "unit": "bars_price_BASE_fraction_minutes",
            "version": VERSION,
            "hypothesis_id": model_id + ":PARTIAL_PIVOT",
            "rationale": "Public examples leave complete partial fractions and management discretion unspecified; thirty percent and three bars are declared mechanical choices, not author parameters or optimized values.",
            "exact_source_reproduction": False,
        },
        {
            "rule_id": "finite_execution",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": "q=min(available cash*.0025/known entry-stop distance, available cash*.10/known entry); adverse fill notional exceeding reservation cancels admission. First whole minute strictly after known features; Kell stop valid2decision bars, Gajjala next-open valid1minute. Missing detail retains unknown ownership. Funding unknown, fixture fees explicit.",
            "unit": "BASE_USDT_UTC_ms",
            "version": VERSION,
            "hypothesis_id": model_id + ":FINITE_EXECUTION",
            "rationale": "Finite small risk/notional normalization with explicit modeled delay; no leverage, guaranteed loss cap, source-original size, observed fill or actual funding claim.",
            "exact_source_reproduction": False,
        },
    ]
    validate_rules(rows)
    return rows


def _validated(frame, minutes, *, bar_close_only=False):
    for key, expected in (
        ("price_type", "last"),
        ("source_price_type", "last"),
        ("price_basis", "LAST_PRICE"),
    ):
        if frame.attrs.get(key) not in (None, expected):
            raise ValueError("SOURCE_PRICE_BASIS_CONFLICT:" + key)
        if key in frame.columns and not frame[key].eq(expected).all():
            raise ValueError("SOURCE_PRICE_BASIS_CONFLICT:" + key)
    segments = source._frame(frame, minutes)
    if bar_close_only and any(
        row["available_ts_ms"] != row["close_ts_ms"] for seg in segments for row in seg
    ):
        raise ValueError("BAR_CLOSE_MODEL_CLOCK_REQUIRED_DELAYED_CLOCK_UNSUPPORTED")
    if any(
        row["open_ts_ms"] % (minutes * MINUTE)
        or row["close_ts_ms"] != row["open_ts_ms"] + minutes * MINUTE
        for seg in segments
        for row in seg
    ):
        raise ValueError("EXCLUSIVE_ALIGNED_CANONICAL_BARS_REQUIRED")
    return segments


def _selection(symbol, origin, watch_low, config):
    contexts = config.get("context_frames", {})
    benchmark = config.get("benchmark_symbol")
    if (
        not isinstance(benchmark, str)
        or symbol not in contexts
        or benchmark not in contexts
    ):
        return {"selected": False, "reason": "RAW_1H_CONTEXT_OR_BENCHMARK_MISSING"}
    chosen = {}
    for name in (symbol, benchmark):
        eligible = [
            row
            for seg in _validated(contexts[name], 60)
            for row in seg
            if row["available_ts_ms"] <= origin and row["close_ts_ms"] <= origin
        ]
        rows = eligible[-4:]
        if (
            len(rows) < 4
            or len({r["segment_id"] for r in rows}) != 1
            or any(a["close_ts_ms"] != b["open_ts_ms"] for a, b in zip(rows, rows[1:]))
        ):
            return {
                "selected": False,
                "reason": "CONTEXT_NOT_FOUR_CONTIGUOUS_KNOWN_BARS",
            }
        if origin - rows[-1]["close_ts_ms"] > HOUR:
            return {"selected": False, "reason": "CONTEXT_TOO_OLD"}
        chosen[name] = rows
    own, ref = chosen[symbol], chosen[benchmark]
    if [r["close_ts_ms"] for r in own] != [r["close_ts_ms"] for r in ref]:
        return {"selected": False, "reason": "BENCHMARK_CONTEXT_CLOCK_MISMATCH"}
    closes = [r["close"] for r in own]
    ema = source._smooth(closes, 4, 2 / 5)[-1]
    momentum = closes[-1] / closes[0] - 1
    benchmark_momentum = ref[-1]["close"] / ref[0]["close"] - 1
    support = min(r["low"] for r in own)
    passed = (
        closes[-1] > ema
        and momentum > 0
        and momentum >= benchmark_momentum
        and watch_low >= support
    )
    return {
        "selected": passed,
        "reason": "SELECTED" if passed else "SUPPORT_OR_RELATIVE_STRENGTH_REJECTED",
        "selection_ts_ms": origin,
        "context_available_ts_ms": max(r["available_ts_ms"] for r in own + ref),
        "support_price": support,
        "ema4_1h_price": ema,
        "return_fraction": momentum,
        "benchmark_return_fraction": benchmark_momentum,
        "benchmark_symbol": benchmark,
        "source_exact_scanner": False,
    }


def _tick(config, symbol, known):
    receipt = config.get("tick_evidence", {}).get(symbol)
    if not isinstance(receipt, dict):
        return None
    required = {
        "tick_size",
        "unit",
        "available_ts_ms",
        "valid_from_ts_ms",
        "valid_to_ts_ms",
        "source_ref",
        "source_receipt_sha256",
    }
    if not required.issubset(receipt) or receipt["unit"] != "QUOTE_PRICE_INCREMENT":
        raise ValueError("PRICE_GRID_METADATA_CONTRACT_REQUIRED_NOT_TRADE_TICKS")
    value = positive(receipt["tick_size"], "tick_size")
    evidence_hash = receipt["source_receipt_sha256"]
    if (
        not isinstance(evidence_hash, str)
        or len(evidence_hash) != 64
        or any(x not in "0123456789abcdef" for x in evidence_hash)
    ):
        raise ValueError("TICK_METADATA_RECEIPT_HASH_REQUIRED")
    if not isinstance(receipt["source_ref"], str) or not receipt["source_ref"]:
        raise ValueError("TICK_METADATA_SOURCE_REQUIRED")
    if (
        not stamp(receipt["valid_from_ts_ms"], "tick_valid_from")
        <= known
        < stamp(receipt["valid_to_ts_ms"], "tick_valid_to")
        or stamp(receipt["available_ts_ms"], "tick_available") > known
    ):
        return None
    return value


def compile_model(model_id, frames, config):
    """Pure supplied-input compilation; never fetch data or allocate executions."""
    profile = catalog().get(model_id)
    if profile is None or not frames:
        raise ValueError("KNOWN_MODEL_AND_FRAMES_REQUIRED")
    if set(config) - {
        "tick_evidence",
        "context_frames",
        "benchmark_symbol",
        "volume_bindings",
    }:
        raise ValueError("UNREGISTERED_RESEARCH_PARAMETER")
    rows = rules(model_id)
    rule_digest = validate_rules(rows)
    events, plans, decisions = [], [], {}
    for symbol, original in sorted(frames.items()):
        _validated(original, 15, bar_close_only=True)
        frame = original.copy(deep=True)
        if model_id == GAJJALA:
            binding = config.get("volume_bindings", {}).get(symbol)
            if binding is None:
                events.append(
                    {
                        "symbol": symbol,
                        "kind": "BLOCKED_OBSERVED_BASE_VOLUME_BINDING_MISSING",
                    }
                )
                continue
            try:
                frame = admit_observed_base_frame(symbol, frame, binding)
            except ValueError as exc:
                events.append(
                    {
                        "symbol": symbol,
                        "kind": "BLOCKED_VOLUME_CONTRACT",
                        "reason": str(exc),
                    }
                )
                continue
            frame["volume_unit"] = "BASE"
            _validated(frame, 15, bar_close_only=True)
        decisions[symbol] = frame.assign(symbol=symbol)
        # The metadata value can be used by a producer only when every resulting
        # setup origin separately passes its PIT validity interval.
        receipt = config.get("tick_evidence", {}).get(symbol)
        if not isinstance(receipt, dict):
            events.append(
                {"symbol": symbol, "kind": "BLOCKED_TICK_GRID_METADATA_MISSING"}
            )
            continue
        tick = positive(receipt.get("tick_size"), "tick_size")
        strategy = "ema_ribbon_scalp" if model_id == KELL else "scalp_snap"
        source_config = {
            "mode_id": PROFILE[model_id]["source_mode"],
            "timeframe_min": 15,
            "hypothesis_id": model_id,
            "tick_size": tick,
            **PROFILE[model_id]["geometry"],
        }
        produced = source.evaluate(strategy, {symbol: frame}, source_config)
        events.extend(produced["events"])
        canonical = frame.to_dict("records")
        for intent in produced["intents"]:
            origin, known = intent["origin_ts_ms"], intent["feature_available_ts_ms"]
            if (
                _tick(config, symbol, origin) is None
                or _tick(config, symbol, known) is None
            ):
                events.append(
                    {
                        "symbol": symbol,
                        "kind": "BLOCKED_PIT_TICK_GRID",
                        "available_ts_ms": known,
                    }
                )
                continue
            watch = next((r for r in canonical if r["available_ts_ms"] == origin), None)
            if watch is None:
                raise ValueError("SOURCE_FORMATION_ORIGIN_MISSING")
            selection = _selection(symbol, origin, watch["low"], config)
            events.append(
                {
                    "symbol": symbol,
                    "kind": (
                        "SELECTION_ACCEPTED"
                        if selection["selected"]
                        else "SELECTION_REJECTED"
                    ),
                    "available_ts_ms": origin,
                    **selection,
                }
            )
            if not selection["selected"]:
                continue
            active = (known // MINUTE + 1) * MINUTE
            reference = positive(intent["trigger_price"], "reference_entry_price")
            plan = {
                "model_id": model_id,
                "strategy_id": profile["strategy_id"],
                "symbol": symbol,
                "side": 1,
                "decision_tf_min": 15,
                "setup_ts_ms": origin,
                "feature_available_ts_ms": known,
                "order_submit_ts_ms": known,
                "order_active_ts_ms": active,
                "expires_ts_ms": active + (2 * TF if model_id == KELL else MINUTE),
                "order_kind": intent["order_kind"],
                "trigger_price": reference if model_id == KELL else None,
                "protective_stop": intent["protective_stop"],
                "reference_entry_price": reference,
                "formation_floor_price": intent["protective_stop"] + tick,
                "tick_size": tick,
                "segment_id": intent["segment_id"],
                "selection": selection,
                "quantity_policy": dict(QUANTITY),
                "rule_digest": rule_digest,
                "timing_basis": "HISTORICAL_MODEL",
                "source_intent_sha256": digest(intent),
                "producer_rule_digest": produced["rule_digest"],
                "source_exact": False,
                "tick_receipt_sha256": receipt["source_receipt_sha256"],
                "entry_variant": profile["entry"],
                "partial_fraction": 0.30,
            }
            plans.append(plan)
    plans.sort(key=lambda r: (r["feature_available_ts_ms"], r["symbol"]))
    return {
        "model_id": model_id,
        "plans": plans,
        "events": events,
        "decisions": decisions,
        "rules": rows,
        "rule_digest": rule_digest,
        "complete": True,
        "execution_mode": "DETAIL_CONDITIONAL_PARTIAL_RECEIPTS",
        "timeframe_min": 15,
        "complete_configured_research_model": True,
        "genuine_execution_ready": False,
        "source_exact": False,
        "economics": "NOT_RUN",
        "new_full_runs": 0,
        "aliases": profile["aliases"],
        "independent_lineage_count": 1,
        "authority": dict(AUTHORITY),
    }


def create_order(plan, capital, identity, rule_digest):
    if plan.get("model_id") not in MODEL_IDS or plan.get("quantity_policy") != QUANTITY:
        raise ValueError("RESEARCH_MODEL_QUANTITY_BINDING_MISMATCH")
    if not identity or rule_digest != plan.get("rule_digest"):
        raise ValueError("IDENTITY_OR_RULE_DIGEST_MISMATCH")
    cash = positive(capital, "available_capital_usdt")
    reference, stop = positive(plan["reference_entry_price"], "entry"), positive(
        plan["protective_stop"], "stop"
    )
    if reference <= stop or plan["side"] != 1:
        raise ValueError("LONG_STRUCTURAL_RISK_REQUIRED")
    qty = min(
        cash * QUANTITY["risk_fraction"] / (reference - stop),
        cash * QUANTITY["notional_fraction"] / reference,
    )
    order = copy.deepcopy(plan)
    order.update(
        identity=identity,
        qty_base=qty,
        reserved_notional_usdt=cash * QUANTITY["notional_fraction"],
        position_episode_id=identity
        + ":"
        + plan["symbol"]
        + ":"
        + str(plan["setup_ts_ms"]),
    )
    order["signal"] = copy.deepcopy(plan)
    return order


def management_update(position, bar, history, state):
    """Causal one-episode state; queued partials become explicit model receipts."""
    signal = position.get("signal", {})
    if signal.get("model_id") not in MODEL_IDS or position.get("side") != 1:
        raise ValueError("MANAGEMENT_MODEL_BINDING_MISMATCH")
    rows = history.to_dict("records") if hasattr(history, "to_dict") else list(history)
    known, closed = stamp(bar["available_ts_ms"], "known"), stamp(
        bar["close_ts_ms"], "closed"
    )
    if any(r["available_ts_ms"] > known or r["close_ts_ms"] > closed for r in rows):
        raise ValueError("MANAGEMENT_FUTURE_HISTORY")
    if not rows or rows[-1] != bar:
        raise ValueError("MANAGEMENT_CURRENT_BAR_MISMATCH")
    post = [r for r in rows if r["open_ts_ms"] >= position["entry_ts_ms"]]
    if not post:
        return {"reason": "NO_COMPLETE_POST_ENTRY_BAR"}
    if any(
        a["close_ts_ms"] != b["open_ts_ms"] or a["segment_id"] != b["segment_id"]
        for a, b in zip(post, post[1:])
    ):
        raise ValueError("MANAGEMENT_DISCONTIGUOUS_HISTORY")
    if bar["close"] < signal["formation_floor_price"]:
        return {"exit_next_open": True, "reason": "FORMATION_FAILED_COMPLETED_CLOSE"}
    result = {"reason": "HOLD_STRUCTURAL_THESIS"}
    if len(post) >= 3:
        left, middle, right = post[-3:]
        if middle["low"] < min(left["low"], right["low"]):
            stop = middle["low"] - signal["tick_size"]
            if stop > position["stop_price"]:
                result.update(next_stop=stop, reason="CONFIRMED_POST_ENTRY_1L1R_PIVOT")
    if len(post) >= 4 and not state.get("partial_scheduled"):
        previous = post[-4:-1]
        strong = (
            bar["close"] > max(r["high"] for r in previous)
            and bar["close"] > position["entry_price"]
        )
        expanded = (
            bar["high"] - bar["low"] > sum(r["high"] - r["low"] for r in previous) / 3
        )
        if strong and expanded:
            result.update(
                partial_fraction=0.30,
                reason="DECLARED_FIRST_COMPLETED_STRENGTH_PARTIAL",
            )
    return result


def _fixture_guard(frames, details, config, manifest):
    if manifest.get("data_kind") != "SYNTHETIC_FIXTURE" or not manifest.get(
        "construction_reason"
    ):
        raise PermissionError("EXPLICIT_SYNTHETIC_FIXTURE_REQUIRED_NO_GENUINE_PROBE")
    all_frames = (
        list(frames.values())
        + list(details.values())
        + list(config.get("context_frames", {}).values())
    )
    if len(frames) != 1 or set(frames) != set(details):
        raise ValueError("SINGLE_SYMBOL_FINITE_FIXTURE_SLEEVE_REQUIRED")
    for frame in all_frames:
        if (
            frame.attrs.get("source_rows_are_genuine") is True
            or frame.attrs.get("data_kind") != "SYNTHETIC_FIXTURE"
        ):
            raise PermissionError(
                "GENUINE_OR_UNDECLARED_DATA_FORBIDDEN_IN_FIXTURE_CALLER"
            )
    if sum(len(frame) for frame in all_frames) > 10_000:
        raise PermissionError("BOUNDED_SYNTHETIC_LIFECYCLE_ONLY")


def _cash(ledger, initial):
    entries, cash = {}, Decimal(str(initial))
    for row in ledger:
        qty, price = Decimal(str(row["qty_base"])), Decimal(str(row["fill_price"]))
        episode = row["position_episode_id"]
        cash -= Decimal(str(row["fee_usdt"]))
        if row["effect"] == "OPEN":
            entries[episode] = price
        else:
            cash += qty * (price - entries[episode])
    return float(cash)


def _partial_at_open(adapter, pending, detail, fee):
    if pending is None or adapter.position is None:
        return None
    opened = detail["open_ts_ms"]
    prior = adapter.details[-1] if adapter.details else None
    if (
        prior is None
        or opened != prior["close_ts_ms"]
        or prior["segment_id"] != detail["segment_id"]
    ):
        return pending  # Existing engine marks the gap; no management fill first.
    if opened < pending["effective_ts_ms"]:
        return pending
    update = adapter.pending_update or {}
    stop = update.get("next_stop", adapter.stop)
    if update.get("exit_next_open") or detail["open"] <= stop:
        return None  # Full protective/failure exit owns this opening.
    held = Decimal(adapter.position["remaining_qty_base"])
    quantity = held * Decimal(str(pending["fraction"]))
    price = Decimal(str(detail["open"]))
    adapter.record_fill(
        {
            "fill_id": "partial:" + adapter.episode_id + ":" + str(opened),
            "ts_ms": opened,
            "available_ts_ms": detail["available_ts_ms"],
            "symbol": adapter.order["symbol"],
            "effect": "CLOSE",
            "qty_base": str(quantity),
            "fill_price": str(price),
            "fee_usdt": str(quantity * price * Decimal(str(fee))),
            "maker_taker": "TAKER",
            "source_ref": "DECLARED_NEXT_MINUTE_OPEN_PARTIAL_MODEL",
            "execution_evidence": "MODEL_NOT_OBSERVED",
            "time_precision": "OPEN",
            "quantity_unit": "BASE",
            "cash_unit": "USDT",
        }
    )
    return None


def run_fixture(
    model_id,
    frames,
    detail_frames,
    config,
    *,
    fixture_manifest,
    initial_cash_usdt=10_000.0,
    fee_rate=0.001,
):
    """Actual producer -> engine -> partial receipts -> saved account valuation.

    Single-symbol finite sleeve only, deliberately no genuine-history gateway.
    Exact source/native portfolio equivalence and economic readiness stay blocked.
    """
    _fixture_guard(frames, detail_frames, config, fixture_manifest)
    initial = positive(initial_cash_usdt, "initial_cash")
    fee = positive(fee_rate, "fee_rate", zero=True)
    compiled = compile_model(model_id, frames, config)
    symbol = next(iter(frames))
    details = [
        {**r, "symbol": symbol}
        for seg in _validated(detail_frames[symbol], 1, bar_close_only=True)
        for r in seg
    ]
    if not details:
        raise ValueError("FIXTURE_DETAIL_REQUIRED")
    ledger, executions, statuses = [], [], []
    ownership_until, first_unknown = -1, None
    decision_rows = (
        compiled["decisions"]
        .get(symbol, frames[symbol].assign(symbol=symbol))
        .to_dict("records")
    )
    for plan in compiled["plans"]:
        if plan["order_submit_ts_ms"] < ownership_until:
            statuses.append(
                {
                    "setup_ts_ms": plan["setup_ts_ms"],
                    "status": "BLOCKED_EXISTING_OR_UNKNOWN_OWNERSHIP",
                }
            )
            continue
        cash = _cash(ledger, initial)
        if cash <= 0:
            statuses.append(
                {
                    "setup_ts_ms": plan["setup_ts_ms"],
                    "status": "BLOCKED_NONPOSITIVE_CAPITAL",
                }
            )
            continue
        order = create_order(
            plan, cash, "SYNTHETIC:" + model_id, compiled["rule_digest"]
        )
        state, pending = {}, None
        management_events = []

        def callback(position, bar, history):
            nonlocal pending
            update = management_update(position, bar, history, state)
            management_events.append(
                {"available_ts_ms": bar["available_ts_ms"], **update}
            )
            if update.get("partial_fraction") is not None:
                state["partial_scheduled"] = True
                pending = {
                    "fraction": update.pop("partial_fraction"),
                    "effective_ts_ms": bar["available_ts_ms"],
                }
            return update

        adapter = DetailExecutionAdapter(
            order, fill_model=MODEL, fee_rate=fee, exit_update=callback
        )
        observed_unknown = None
        for detail in details:
            if detail["close_ts_ms"] <= order["order_active_ts_ms"]:
                continue
            pending = _partial_at_open(adapter, pending, detail, fee)
            if adapter.order_state in {"PENDING", "PARTIAL"}:
                witness = inspect_entry_bar(order, detail)
                if witness["status"].startswith("MODEL_") and Decimal(
                    str(witness["candidate_price"])
                ) * Decimal(str(order["qty_base"])) > Decimal(
                    str(order["reserved_notional_usdt"])
                ):
                    adapter.cancel(
                        detail["open_ts_ms"],
                        "ENTRY_GAP_EXCEEDS_FINITE_NOTIONAL_RESERVATION",
                    )
                    break
            adapter.process_detail_bar(detail)
            if adapter.state == "UNRESOLVED":
                observed_unknown = detail["open_ts_ms"]
            if adapter.state in {"CLOSED", "CANCELLED", "EXPIRED", "UNRESOLVED"}:
                break
            for decision in decision_rows:
                if (
                    decision["close_ts_ms"] == detail["close_ts_ms"]
                    and decision["available_ts_ms"] == detail["available_ts_ms"]
                    and decision["open_ts_ms"] >= order["order_active_ts_ms"]
                ):
                    history = [
                        r
                        for r in decision_rows
                        if r["available_ts_ms"] <= decision["available_ts_ms"]
                        and r["close_ts_ms"] <= decision["close_ts_ms"]
                    ]
                    adapter.process_decision_bar(decision, history)
        executed = adapter.finish()
        if executed["state"] == "UNRESOLVED":
            cutoff = (
                observed_unknown
                if observed_unknown is not None
                else adapter.last_available + 1
            )
            first_unknown = (
                cutoff if first_unknown is None else min(first_unknown, cutoff)
            )
            ownership_until = 2**63 - 1
        else:
            ownership_until = adapter.last_available
        executed.update(
            management_events=management_events,
            pending_management=copy.deepcopy(pending),
        )
        executions.append(executed)
        ledger.extend(executed["ledger"])
        statuses.append(
            {"setup_ts_ms": plan["setup_ts_ms"], "status": executed["state"]}
        )
    ledger.sort(key=lambda row: (row["ts_ms"], row["available_ts_ms"]))
    snapshots = [
        {
            "ts_ms": details[0]["open_ts_ms"],
            "prices": {
                symbol: {
                    "price": details[0]["open"],
                    "price_basis": "LAST_PRICE",
                    "ts_ms": details[0]["open_ts_ms"],
                    "source_ref": "SYNTHETIC_DETAIL_OPEN",
                }
            },
        }
    ]
    for row in details:
        if first_unknown is not None and row["close_ts_ms"] >= first_unknown:
            break
        snapshots.append(
            {
                "ts_ms": row["close_ts_ms"],
                "prices": {
                    symbol: {
                        "price": row["close"],
                        "price_basis": "LAST_PRICE",
                        "ts_ms": row["close_ts_ms"],
                        "source_ref": "SYNTHETIC_DETAIL_CLOSE",
                    }
                },
            }
        )
    end = snapshots[-1]["ts_ms"]
    account = account_snapshots_from_ledger(
        [row for row in ledger if row["ts_ms"] <= end],
        snapshots,
        initial_cash_usdt=initial,
        start_ts_ms=snapshots[0]["ts_ms"],
        price_basis="LAST_PRICE",
    )
    return {
        "model_id": model_id,
        "compiled": compiled,
        "ledger": ledger,
        "executions": executions,
        "statuses": statuses,
        "account": account,
        "account_prefix_only": first_unknown is not None,
        "first_unknown_ts_ms": first_unknown,
        "complete_account_claim": first_unknown is None,
        "fixture_manifest": copy.deepcopy(fixture_manifest),
        "data_kind": "SYNTHETIC_FIXTURE",
        "full_execution_performed": False,
        "new_full_runs": 0,
        "economics": "NOT_MEASURED_SYNTHETIC_ONLY",
        "funding_status": "UNKNOWN_NOT_ZERO",
        "authority": dict(AUTHORITY),
    }
