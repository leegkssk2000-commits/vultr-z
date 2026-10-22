"""Default-OFF, caller-supplied MR30m forward observation preparation.

No source fetch, collector, economic replay, position opening, fill, PnL, state
writer, account allocation or execution authority exists in this module. Hashes
bind caller-supplied evidence; they do not authenticate its external origin.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
IDENTITY = "mr_reexpansion_bar4_30m_causal_control_v2"
TF_MS = 1_800_000
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
PINS = {
    "backend/research/rebuild/scalp7_mr_formation_v2.py": "1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5",
    "backend/research/rebuild/scalp7_observed_paper_v3.py": "368b3e516438ab82222117d0200e9a71af578e7674c1aebb936d736c16590308",
    "backend/research/rebuild/scalp7_source_clock_v3.py": "a42e6484d321f82c37fe815c3631cef30a9a124864d69404ec995319ff929814",
}


class PreparationError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def opportunity_key(signal: Mapping[str, Any]) -> str:
    """Exact existing fresh_forward opportunity key, including JSON newline."""
    value = {"identity": signal["identity"], "symbol": signal["symbol"],
             "opened": signal["signal_open_ts_ms"], "side": signal.get("side"),
             "legs": signal.get("legs")}
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False) + "\n").encode()).hexdigest()


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise PreparationError(reason)


def _integer(value: Any, name: str) -> int:
    _require(type(value) is int and value >= 0, "INVALID_INTEGER:" + name)
    return value


def _positive(value: Any, name: str) -> float:
    _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
             "UNKNOWN_OR_INVALID_NUMBER:" + name)
    return float(value)


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _modules() -> tuple[Any, Any]:
    # Verify trusted bytes before importing native code. Imports below have no
    # collector/writer effects; no runtime initialize/poll/main is called.
    for relative, expected in PINS.items():
        path = ROOT / relative
        _require(path.is_file() and not path.is_symlink(), "SOURCE_PIN_MISSING:" + relative)
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 "SOURCE_PIN_CHANGED:" + relative)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    native = importlib.import_module("backend.research.rebuild.scalp7_mr_formation_v2")
    quotes = importlib.import_module("backend.research.rebuild.scalp7_observed_paper_v3")
    _require(native.REEXPANSION_IDENTITY == IDENTITY and tuple(native.PARENT_SYMBOLS) == SYMBOLS,
             "NATIVE_IDENTITY_OR_UNIVERSE_CHANGED")
    return native, quotes


def _result(state: str, reason: str | None, snapshot: Any, *, intents: list | None = None,
            costs: dict | None = None) -> dict:
    occupancy = snapshot.get("occupancy", {}) if isinstance(snapshot, Mapping) else {}
    if not isinstance(occupancy, Mapping):
        occupancy = {}
    return {"schema": "zel.mr_fresh_preparation.v1", "identity": IDENTITY,
            "state": state, "reason": reason, "intents": deepcopy(intents or []),
            "reservation": deepcopy(occupancy.get("reservation")),
            "reservation_changed": False, "capital_allocated": False,
            "costs": costs, "executable": False, "real_sources_verified": False,
            "source_evidence": "CALLER_SUPPLIED_HASH_BOUND_NOT_EXTERNAL_AUTHENTICATION",
            "fresh_T": 0, "economic_full_runs": 0, "order_calls": 0,
            "fills": [], "PnL": None, "shadow_active": False,
            "historical_economics_inherited": False}


def _reference(snapshot: Mapping[str, Any]) -> tuple[int, int]:
    now = _integer(snapshot["as_of_ms"], "as_of_ms")
    clock = snapshot["reference_clock"]
    _require(_integer(clock["wall_ms"], "wall_ms") == now, "REFERENCE_CLOCK_MISMATCH")
    mono = _integer(clock["monotonic_ns"], "monotonic_ns")
    _require(_integer(clock["previous_wall_ms"], "previous_wall_ms") <= now and
             _integer(clock["previous_monotonic_ns"], "previous_monotonic_ns") <= mono,
             "REFERENCE_CLOCK_REVERSED")
    boundary = _integer(snapshot["forward_boundary_ms"], "forward_boundary_ms")
    _require(boundary % TF_MS == 0 and boundary <= now, "PROSPECTIVE_BOUNDARY_INVALID")
    last = _integer(snapshot["last_decision_close_ms"], "last_decision_close_ms")
    _require(last <= now and last % TF_MS == 0, "DECISION_BARRIER_INVALID")
    return now, now // TF_MS * TF_MS


def _validate_snapshot(snapshot: Mapping[str, Any]) -> tuple[dict, int, int, Any]:
    _require(isinstance(snapshot, Mapping), "SNAPSHOT_REQUIRED")
    now, current_close = _reference(snapshot)
    raw = snapshot["frames"]
    _require(isinstance(raw, Mapping) and set(raw) == set(SYMBOLS),
             "EXACT_SIX_UNIQUE_SYMBOLS_REQUIRED")
    receipts = snapshot["source_receipts"]
    _require(isinstance(receipts, Mapping) and set(receipts) == set(SYMBOLS),
             "EXACT_SIX_SOURCE_RECEIPTS_REQUIRED")
    native, quotes = _modules()
    import pandas as pd
    frames = {}
    expected_recent = list(range(current_close - 21 * TF_MS, current_close, TF_MS))
    for symbol in SYMBOLS:
        rows = raw[symbol]
        _require(isinstance(rows, list) and len(rows) >= 21, "NATIVE_20BAR_WARMUP_UNBOUND:" + symbol)
        previous = -1
        for bar in rows:
            _require(isinstance(bar, Mapping), "BAR_SCHEMA_INVALID")
            opened = _integer(bar["open_ts_ms"], "open_ts_ms")
            closed = _integer(bar["close_ts_ms"], "close_ts_ms")
            available = _integer(bar["available_ts_ms"], "available_ts_ms")
            _require(opened > previous and opened % TF_MS == 0, "DUPLICATE_UNSORTED_OR_UNALIGNED_BAR")
            _require(closed == opened + TF_MS, "UNFINISHED_OR_WRONG_30M_BAR")
            _require(closed <= available <= now, "FUTURE_OR_PREMATURE_BAR")
            segment = bar["segment_id"]
            _require(type(segment) in (str, int) and str(segment) != "", "MISSING_SEGMENT_ID")
            o, h, low, c = [_positive(bar[key], key) for key in ("open", "high", "low", "close")]
            _require(low <= min(o, c) <= max(o, c) <= h, "INVALID_OHLC_GEOMETRY")
            previous = opened
        _require(rows[-1]["close_ts_ms"] == current_close, "STALE_OR_MISSING_COMMON_CLOSE:" + symbol)
        recent = rows[-21:]
        _require([r["open_ts_ms"] for r in recent] == expected_recent and
                 len({str(r["segment_id"]) for r in recent}) == 1,
                 "DATA_GAP_OR_6H_HISTORY_UNBOUND:" + symbol)
        wrapped = receipts[symbol]
        receipt = wrapped["receipt"]
        _require(digest(receipt) == wrapped["receipt_sha256"], "SOURCE_RECEIPT_HASH_MISMATCH")
        _require(receipt["symbol"] == symbol and receipt["frame_sha256"] == digest(rows),
                 "SOURCE_FRAME_BINDING_MISMATCH")
        _require(_hash(receipt["source_identity_sha256"]) and _hash(receipt["source_cursor_sha256"]),
                 "SOURCE_IDENTITY_OR_CURSOR_UNBOUND")
        latest_available = max(r["available_ts_ms"] for r in rows)
        _require(receipt["available_ts_ms"] == latest_available and
                 receipt["received_at_ms"] == latest_available and
                 receipt["source_ts_ms"] == current_close,
                 "SOURCE_CLOCK_FRAME_BINDING_MISMATCH")
        observed = _integer(receipt["observed_at_ms"], "observed_at_ms")
        usable = quotes._usable(receipt)
        _require(current_close <= latest_available <= usable <= observed <= now,
                 "SOURCE_CLOCK_NOT_AVAILABLE_ASOF")
        frames[symbol] = pd.DataFrame(rows)
    return frames, now, current_close, native


def _costs(snapshot: Mapping[str, Any], signal: Mapping[str, Any]) -> dict:
    costs = snapshot.get("costs_bps")
    _require(isinstance(costs, Mapping) and set(costs) == set(SYMBOLS), "COST_UNKNOWN")
    verified = {s: _positive(costs[s], "cost_bps:" + s) for s in SYMBOLS}
    legs = signal["legs"]
    value = sum(float(leg["weight"]) * verified[leg["symbol"]] for leg in legs)
    return {"weighted_cost1x_bps": value, "weighted_cost2x_bps": value * 2,
            "cost_kind": "CALLER_SUPPLIED_NUMERIC_SCENARIO_NOT_VERIFIED_FEE_AUTHORITY",
            "strategy_geometry_changed": False, "actual_funding_verified": False}


def _native_current(snapshot: Mapping[str, Any], frames: dict, close: int, native: Any) -> list[dict]:
    signals = native.generate_signals(frames, identity=IDENTITY)
    current = [s for s in signals if int(s["signal_open_ts_ms"]) + TF_MS == close]
    _require(len(current) <= 1, "MULTIPLE_CURRENT_PAIR_SIGNALS")
    for signal in current:
        _require(int(signal["signal_open_ts_ms"]) >= snapshot["forward_boundary_ms"],
                 "HISTORICAL_CONTEXT_NOT_FORWARD_SIGNAL")
        _require(signal["stop_price"] is None and not signal.get("take_profit_r") and
                 not signal.get("partial_take_profit_r"), "FROZEN_NO_STOP_POLICY_CHANGED")
        legs = signal["legs"]
        _require(len(legs) == 2 and len({x["symbol"] for x in legs}) == 2 and
                 [x["side"] for x in legs] == [1, -1] and
                 all(x["weight"] == 0.5 for x in legs), "FROZEN_PAIR_GEOMETRY_CHANGED")
    return current


def _reservation(snapshot: Mapping[str, Any], signal: Mapping[str, Any], *, exiting: bool = False) -> bool:
    occupancy = snapshot.get("occupancy")
    _require(isinstance(occupancy, Mapping), "EXTERNAL_CAPITAL_CONTEXT_UNBOUND")
    body = {k: v for k, v in occupancy.items() if k != "receipt_sha256"}
    _require(digest(body) == occupancy.get("receipt_sha256") and
             isinstance(occupancy.get("receipt_id"), str) and bool(occupancy["receipt_id"]),
             "CAPITAL_RECEIPT_UNBOUND")
    _require(occupancy["as_of_ms"] == snapshot["as_of_ms"] and
             type(occupancy["capital_available"]) is bool and
             type(occupancy["account_reservation_busy"]) is bool, "CAPITAL_CLOCK_OR_STATUS_UNBOUND")
    occupied = occupancy["occupied_symbols"]
    _require(isinstance(occupied, list) and len(occupied) == len(set(occupied)) and
             set(occupied).issubset(SYMBOLS), "OCCUPIED_SYMBOLS_INVALID")
    wanted = sorted(x["symbol"] for x in signal["legs"])
    reservation = occupancy.get("reservation")
    if reservation is None:
        _require(not exiting, "ORIGINAL_RESERVATION_MISSING")
        _require(occupancy["capital_available"] and not occupancy["account_reservation_busy"] and
                 not set(wanted).intersection(occupied), "CAPITAL_OCCUPIED")
        return False
    _require(isinstance(reservation, Mapping) and isinstance(reservation.get("reservation_id"), str)
             and bool(reservation["reservation_id"]), "RESERVATION_ID_UNBOUND")
    _require(reservation["identity"] == IDENTITY and
             reservation["signal_ts_ms"] == signal["signal_ts_ms"] and
             sorted(reservation["symbols"]) == wanted and len(reservation["symbols"]) == 2 and
             reservation["as_of_ms"] == snapshot["as_of_ms"], "EXACT_PAIR_RESERVATION_MISMATCH")
    if not exiting:
        _require(occupancy["capital_available"] and not occupancy["account_reservation_busy"] and
                 not set(wanted).intersection(occupied), "CAPITAL_OCCUPIED")
    return True


def prepare_signals(snapshot: Mapping[str, Any], *, enabled: bool = False) -> dict:
    if enabled is not True:
        return _result("DISABLED", "DEFAULT_OFF", snapshot)
    try:
        snapshot = deepcopy(snapshot)
        frames, now, closed, native = _validate_snapshot(snapshot)
        _require(snapshot["last_decision_close_ms"] < closed, "DUPLICATE_DECISION")
        seen = snapshot["seen_opportunity_keys"]
        _require(isinstance(seen, list) and len(seen) == len(set(seen)) and
                 all(_hash(key) for key in seen), "EXISTING_OPPORTUNITY_PROJECTION_UNBOUND")
        signals = _native_current(snapshot, frames, closed, native)
        # Unknown costs remain unknown even when this snapshot has no signal.
        check_signal = signals[0] if signals else {"legs": [
            {"symbol": SYMBOLS[0], "weight": 0.5}, {"symbol": SYMBOLS[1], "weight": 0.5}]}
        costs = _costs(snapshot, check_signal)
        if not signals:
            return _result("NO_SIGNAL", None, snapshot)
        signal = signals[0]
        key = opportunity_key(signal)
        _require(key not in seen, "DUPLICATE_EXISTING_FORWARD_OPPORTUNITY")
        intent = {"operation": "ENTRY_SIGNAL_OBSERVATION", "signal": signal,
                  "signal_sha256": digest(signal), "origin_sha256": digest(snapshot),
                  "opportunity_key": key,
                  "decision_as_of_ms": now, "feature_available_ts_ms": signal["signal_ts_ms"],
                  "entry_reference_ts_ms": int(signal["signal_open_ts_ms"]) + TF_MS,
                  "entry_reference_is_not_fill": True,
                  "earliest_new_observation_ms": now + 1,
                  "required_common_open_strictly_after_ms": max(now, int(signal["signal_ts_ms"])),
                  "reservation_required_from_existing_account_arbiter": True}
        if max(now, int(signal["signal_ts_ms"])) > closed:
            return _result("HOLD", "LATE_MODEL_ENTRY_NO_RETROACTIVE_FILL", snapshot, intents=[intent], costs=costs)
        reserved = _reservation(snapshot, signal)
        return _result("SOURCE_CODE_READY_SIGNAL_ONLY" if reserved else "PENDING_EXTERNAL_CAPITAL_RESERVATION",
                       None if reserved else "NO_BOUND_ATOMIC_ACCOUNT_RESERVATION", snapshot,
                       intents=[intent], costs=costs)
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        return _result("HOLD", str(exc), snapshot)


def prepare_exit(snapshot: Mapping[str, Any], position: Mapping[str, Any], *, enabled: bool = False) -> dict:
    if enabled is not True:
        return _result("DISABLED", "DEFAULT_OFF", snapshot)
    try:
        snapshot, position = deepcopy(snapshot), deepcopy(position)
        frames, now, closed, native = _validate_snapshot(snapshot)
        _require(snapshot["last_decision_close_ms"] < closed, "DUPLICATE_DECISION")
        _require(snapshot["last_decision_close_ms"] == closed - TF_MS,
                 "MISSED_LIFECYCLE_DECISION_NO_BACKFILL")
        origin = position["origin_snapshot"]
        _require(digest(origin) == position["origin_sha256"], "ORIGIN_SNAPSHOT_HASH_MISMATCH")
        admitted = prepare_signals(origin, enabled=True)
        _require(admitted["state"] == "SOURCE_CODE_READY_SIGNAL_ONLY",
                 "ORIGIN_ENTRY_ADMISSION_DENIED:" + str(admitted.get("reason")))
        _require(len(admitted["intents"]) == 1 and
                 admitted["intents"][0]["signal"] == position["signal"] and
                 admitted["intents"][0]["origin_sha256"] == position["origin_sha256"] and
                 admitted["reservation"] == origin["occupancy"]["reservation"],
                 "ORIGIN_ENTRY_ADMISSION_BINDING_MISMATCH")
        origin_frames, origin_now, origin_closed, _ = _validate_snapshot(origin)
        _require(origin_now <= now and origin_closed < closed, "FUTURE_OR_UNHELD_POSITION")
        _require(origin["forward_boundary_ms"] == snapshot["forward_boundary_ms"],
                 "PROSPECTIVE_BOUNDARY_CHANGED")
        candidates = _native_current(origin, origin_frames, origin_closed, native)
        _require(len(candidates) == 1, "ORIGINAL_NATIVE_SIGNAL_NOT_FOUND")
        signal = position["signal"]
        _require(digest(signal) == position["signal_sha256"] and signal == candidates[0],
                 "ORIGINAL_SIGNAL_GEOMETRY_MISMATCH")
        _require(signal.get("stop_price") is None and position.get("stop_price") is None and
                 position.get("initial_stop") is None and position.get("take_profit_r") is None,
                 "FROZEN_NO_STOP_POLICY_CHANGED")
        _require(max(origin_now, int(signal["signal_ts_ms"])) == origin_closed,
                 "LATE_MODEL_ENTRY_NO_RETROACTIVE_FILL")
        _require(_reservation(origin, signal), "ORIGINAL_RESERVATION_MISSING")
        _require(position["reservation_id"] == origin["occupancy"]["reservation"]["reservation_id"],
                 "ORIGINAL_RESERVATION_CHANGED")
        # A later snapshot may extend history, never silently rewrite the origin.
        for symbol in SYMBOLS:
            current = {r["open_ts_ms"]: r for r in snapshot["frames"][symbol]}
            for row in origin["frames"][symbol]:
                _require(current.get(row["open_ts_ms"]) == row, "ORIGINAL_SOURCE_PREFIX_CHANGED")
        reference = _integer(position["entry_reference_ts_ms"], "entry_reference_ts_ms")
        _require(reference == origin_closed, "ENTRY_REFERENCE_CHANGED")
        held = (closed - reference) // TF_MS
        _require(held <= 8, "MISSED_8BAR_MAX_HOLD_NO_BACKFILL")
        _require(_integer(position["hold_bars"], "hold_bars") == held and held >= 1,
                 "HELD_BAR_CLOCK_MISMATCH")
        _require(_reservation(snapshot, signal, exiting=True), "ORIGINAL_RESERVATION_MISSING")
        _require(position["reservation_id"] == snapshot["occupancy"]["reservation"]["reservation_id"],
                 "ORIGINAL_RESERVATION_CHANGED")
        costs = _costs(snapshot, signal)
        symbols = [leg["symbol"] for leg in signal["legs"]]
        histories = {symbol: frames[symbol] for symbol in symbols}
        # Validate the supplied held reference against earlier native decisions.
        # This produces no historical intents, fills, or synthetic lifecycle.
        for prior_held in range(1, held):
            prior_close = reference + prior_held * TF_MS
            prior_histories = {symbol: history[history["close_ts_ms"] <= prior_close]
                               for symbol, history in histories.items()}
            prior_bars = {symbol: history.iloc[-1].to_dict()
                          for symbol, history in prior_histories.items()}
            _require(all(int(bar["close_ts_ms"]) == prior_close and
                         int(bar["available_ts_ms"]) <= prior_close
                         for bar in prior_bars.values()),
                     "EARLIER_LIFECYCLE_SOURCE_UNRESOLVED_NO_BACKFILL")
            prior_update = native.exit_update({"signal": signal, "hold_bars": prior_held},
                                              prior_bars, prior_histories)
            _require(not prior_update["exit_next_open"],
                     "EARLIER_NATIVE_EXIT_UNRESOLVED_NO_BACKFILL:" + str(prior_close) +
                     ":" + str(prior_update.get("reason")))
        bars = {symbol: histories[symbol].iloc[-1].to_dict() for symbol in symbols}
        update = native.exit_update({"signal": signal, "hold_bars": held}, bars, histories)
        intent = {"operation": "EXIT_CALLBACK_OBSERVATION", "signal_sha256": digest(signal),
                  "decision_as_of_ms": now, "decision_bar_close_ms": closed,
                  "source_available_ts_ms": max(int(b["available_ts_ms"]) for b in bars.values()),
                  "hold_bars": held, **update,
                  "exit_reference_ts_ms": closed if update["exit_next_open"] else None,
                  "exit_reference_is_not_fill": True, "earliest_new_observation_ms": now + 1,
                  "required_common_open_strictly_after_ms": max(now, max(int(b["available_ts_ms"]) for b in bars.values()))}
        if update["exit_next_open"] and max(now, intent["source_available_ts_ms"]) > closed:
            return _result("HOLD", "LATE_MODEL_EXIT_NO_RETROACTIVE_FILL", snapshot, intents=[intent], costs=costs)
        return _result("SOURCE_CODE_READY_EXIT_ONLY" if update["exit_next_open"] else "HOLD_POSITION",
                       update.get("reason"), snapshot, intents=[intent], costs=costs)
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        result = _result("HOLD", str(exc), snapshot)
        result["position_status"] = "HOLD_UNRESOLVED_REFERENCE_NO_RELEASE"
        return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreparationError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="caller-supplied JSON; never a network source")
    parser.add_argument("--position", type=Path, help="optional original observation position reference")
    parser.add_argument("--enable-preparation", action="store_true")
    args = parser.parse_args(argv)
    if not args.enable_preparation:
        print(json.dumps(_result("DISABLED", "DEFAULT_OFF", {}), sort_keys=True))
        return 0
    if args.snapshot is None:
        parser.error("--snapshot required for explicitly enabled preparation")
    snapshot = json.loads(args.snapshot.read_text(), object_pairs_hook=_unique_object)
    if args.position:
        position = json.loads(args.position.read_text(), object_pairs_hook=_unique_object)
        result = prepare_exit(snapshot, position, enabled=True)
    else:
        result = prepare_signals(snapshot, enabled=True)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
