"""Default-OFF H12 EMA-persistence policy preparation; no execution authority.

The original H12 scheduled-close control remains a separate frozen control.
This child suspends that timeout while awaiting the completed H12 receipt.
Even a false EMA condition therefore needs a later, independently witnessed
fill. Neither the original close nor the next open is fabricated here.
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

ROOT = Path(__file__).resolve().parents[4]
BAR = 14_400_000
BOUNDARY = 1_788_048_000_000
PREFIX_START = BOUNDARY - 240 * BAR
FROZEN_ID = "supertrend_replacement_highvol_mom_long_4h_h12_v2"
POLICY_ID = "supertrend_momentum_h12_ema_persistence_intent_v1"
SYMBOLS = ("1000PEPE-USDT", "BCH-USDT", "BTC-USDT", "ETH-USDT", "HYPE-USDT", "LINK-USDT", "SOL-USDT")
PINS = {
    "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json": "686a8839bf9de0ef0baf719511910c10982656a20d723c2f997b58cc618576ce",
    "backend/research/rebuild/a1_top5_replacement_child_prospective_v1.py": "d509b69cc80c773d4678613b21259e5d25b1a21407bb41e02bd7077e39bd96d3",
    "backend/research/architecture_factory/a1_gen2_generic_dev_econ_v1.py": "d86a61ed25f8d6f74a8c56e834db13a6ba61daa370731a590bbbab514f5ae736",
}
PROOF_KEYS = ("parent_id", "symbol", "side", "signal_ts", "entry_ts", "original_timeout_close_ms")
FORBIDDEN = ("mfe", "mae", "outcome", "winner", "month", "pnl", "profit", "net_bps", "gross_bps", "net1x", "net2x", "future")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _integer(value: Any, name: str) -> int:
    _require(type(value) is int and value >= 0, "INVALID_INTEGER:" + name)
    return value


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reject_labels(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _require(isinstance(key, str) and not any(word in key.lower() for word in FORBIDDEN),
                     "OUTCOME_OR_FUTURE_RUNTIME_FIELD_FORBIDDEN:" + str(key))
            _reject_labels(child)
    elif isinstance(value, list):
        for child in value:
            _reject_labels(child)


def _native_features(bars: list[dict]) -> tuple[dict, Any, dict]:
    for relative, expected in PINS.items():
        path = ROOT / relative
        _require(path.is_file() and not path.is_symlink() and
                 hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 "FROZEN_SOURCE_CHANGED:" + relative)
    contract = json.loads((ROOT / next(iter(PINS))).read_text())
    _require(tuple(contract["frozen_symbol_universe"]) == SYMBOLS and
             contract["prospective_boundary"]["ms"] == BOUNDARY, "FROZEN_POPULATION_CHANGED")
    child = next(row for row in contract["children"] if row["child_id"] == FROZEN_ID)
    spec = child["executable_spec"]
    _require(spec["max_hold_bars"] == 12 and spec["exit_rule"] == "time_stop" and
             spec["entry_timing"] == "next_bar_open", "FROZEN_PARENT_CHANGED")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    dependency = importlib.import_module("backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1")
    _require(Path(dependency.__file__).resolve() ==
             (ROOT / "backend/research/architecture_factory/a1_gen2_generic_dev_econ_v1.py").resolve(),
             "NATIVE_DEPENDENCY_MODULE_PATH_CHANGED")
    native = importlib.import_module("backend.research.rebuild.a1_top5_replacement_child_prospective_v1")
    _require(Path(native.__file__).resolve() ==
             (ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v1.py").resolve(),
             "NATIVE_MODULE_PATH_CHANGED")
    _require(native.Expr is dependency.Expr and native._feature_formula is dependency._feature_formula,
             "NATIVE_DEPENDENCY_OBJECT_CHANGED")
    # Expr eagerly builds a volume environment value, although this frozen DSL
    # never consumes volume. This constant is not a market-volume observation.
    projected = [{**bar, "volume": 0.0} for bar in bars]
    features, engine = native._features(projected, spec)
    return features, engine, spec


def _result(state: str, reason: str | None, snapshot: Any, **extra: Any) -> dict:
    occupancy = snapshot.get("occupancy", {}) if isinstance(snapshot, Mapping) else {}
    if not isinstance(occupancy, Mapping):
        occupancy = {}
    return {"schema": "zel.supertrend_momentum.extension_preparation.v1", "policy_id": POLICY_ID,
            "state": state, "reason": reason, "executable": False, "source_ready": False,
            "real_sources_verified": False, "economic_eligible": False,
            "source_evidence": "CALLER_SUPPLIED_HASH_BINDING_NOT_EXTERNAL_AUTHENTICATION",
            "reservation_id": occupancy.get("reservation_id"), "reservation_changed": False,
            "position_release_authorized": False, "fresh_T": 0, "fills": [], "PnL": None,
            "economic_runs": 0, "order_calls": 0, "new_entry_authorized": False,
            "original_control_unchanged": True, "historical_economics_inherited": False,
            "timing": "H12_TIMEOUT_SUSPENDED_PENDING_RECEIPT; EXIT_REQUIRES_LATER_WITNESSED_FILL",
            **deepcopy(extra)}


def _validate(snapshot: Mapping, position: Mapping) -> tuple[list[dict], int, int, int, int, str]:
    _require(isinstance(snapshot, Mapping) and isinstance(position, Mapping), "INPUT_OBJECT_REQUIRED")
    _reject_labels(snapshot)
    _reject_labels(position)
    now = _integer(snapshot["as_of_ms"], "as_of_ms")
    symbol = snapshot["symbol"]
    _require(symbol in SYMBOLS and snapshot["timeframe"] == "4h", "ORIGINAL_SYMBOL_OR_TIMEFRAME_REQUIRED")
    _require(type(snapshot["censor_at_end"]) is bool, "CENSOR_FLAG_REQUIRED")
    bars = snapshot["bars"]
    _require(isinstance(bars, list) and len(bars) >= 60, "NATIVE_PREFIX_REQUIRED")
    _require(snapshot["raw_sha256"] == digest(bars), "RAW_HASH_MISMATCH")
    receipt = snapshot["source_receipt"]
    _require(isinstance(receipt, Mapping) and snapshot["source_receipt_sha256"] == digest(receipt),
             "SOURCE_RECEIPT_HASH_MISMATCH")
    role = receipt.get("history_role", "ORIGINAL_REVIEWED_DIAGNOSTIC")
    _require(role in ("ORIGINAL_REVIEWED_DIAGNOSTIC", "SEPARATE_DEV"), "HISTORY_ROLE_UNBOUND")
    boundary, prefix_start, window_end = BOUNDARY, PREFIX_START, None
    if role == "SEPARATE_DEV":
        boundary = _integer(receipt["boundary_ms"], "boundary_ms")
        window_end = _integer(receipt["end_ms"], "end_ms")
        prefix_start = _integer(receipt["native_prefix_start_ms"], "native_prefix_start_ms")
        _require(boundary % BAR == 0 and window_end % BAR == 0 and boundary < window_end and
                 prefix_start == boundary - 240 * BAR, "DEV_WINDOW_OR_NATIVE_SEED_INVALID")
        _require(window_end <= BOUNDARY, "DEV_OVERLAPS_PROTECTED_ORIGINAL_PERIOD")
        _require(_hash(receipt["dev_contract_sha256"]), "DEV_CONTRACT_UNBOUND")
    for index, bar in enumerate(bars):
        _require(isinstance(bar, Mapping), "BAR_OBJECT_REQUIRED")
        opened = _integer(bar["ts"], "ts")
        available = _integer(bar["available_at_ms"], "available_at_ms")
        received = _integer(bar["received_at_ms"], "received_at_ms")
        _require(opened == prefix_start + index * BAR, "ORIGINAL_PREFIX_SEED_OR_GAP_CHANGED")
        _require(opened + BAR <= available <= received <= now, "UNFINISHED_FUTURE_OR_UNAVAILABLE_BAR")
        for field in ("open", "high", "low", "close"):
            value = bar[field]
            _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                     "INVALID_OHLC:" + field)
        _require(bar["low"] <= min(bar["open"], bar["close"]) <=
                 max(bar["open"], bar["close"]) <= bar["high"], "INVALID_OHLC_GEOMETRY")
    closed = bars[-1]["ts"] + BAR
    _require(window_end is None or closed <= window_end, "DEV_WINDOW_END_EXCEEDED")
    _require(snapshot["censor_at_end"] or closed == now // BAR * BAR, "STALE_COMPLETED_PREFIX")
    last = _integer(snapshot["last_decision_close_ms"], "last_decision_close_ms")
    _require(last % BAR == 0 and last < closed, "DUPLICATE_OR_INVALID_DECISION_BARRIER")
    _require(_hash(receipt["source_identity_sha256"]) and receipt["raw_sha256"] == snapshot["raw_sha256"],
             "SOURCE_IDENTITY_OR_PREFIX_UNBOUND")
    observed = _integer(receipt["observed_at_ms"], "observed_at_ms")
    _require(max(bar["received_at_ms"] for bar in bars) <= observed <= now, "RECEIPT_NOT_AVAILABLE_ASOF")
    _require(position["parent_id"] == FROZEN_ID and position["symbol"] == symbol and
             position["side"] == "long", "ORIGINAL_POSITION_LINEAGE_CHANGED")
    signal = _integer(position["signal_ts"], "signal_ts")
    entry = _integer(position["entry_ts"], "entry_ts")
    timeout = _integer(position["original_timeout_close_ms"], "original_timeout_close_ms")
    _require(signal >= boundary and signal % BAR == 0 and entry == signal + BAR and
             timeout == entry + 12 * BAR and closed > entry, "ORIGINAL_ENTRY_OR_H12_CLOCK_CHANGED")
    signal_index = (signal - prefix_start) // BAR
    _require(50 <= signal_index < len(bars), "ORIGINAL_SIGNAL_PREFIX_MISSING")
    _require(position["origin_prefix_sha256"] == digest(bars[:signal_index + 1]) and
             position["origin_signal_sha256"] == digest({key: position[key] for key in PROOF_KEYS}),
             "ORIGIN_PROOF_HASH_MISMATCH")
    _require(position.get("stop_price") is None and position.get("take_profit") is None,
             "UNFROZEN_STOP_OR_TARGET_FORBIDDEN")
    occupancy = snapshot["occupancy"]
    _require(isinstance(occupancy, Mapping), "OWNER_OCCUPANCY_REQUIRED")
    body = {key: value for key, value in occupancy.items() if key != "receipt_sha256"}
    _require(occupancy["receipt_sha256"] == digest(body), "OWNER_OCCUPANCY_HASH_MISMATCH")
    _require(isinstance(occupancy["receipt_id"], str) and bool(occupancy["receipt_id"]) and
             isinstance(position["reservation_id"], str) and bool(position["reservation_id"]) and
             occupancy["reservation_id"] == position["reservation_id"] and
             occupancy["origin_signal_sha256"] == position["origin_signal_sha256"] and
             occupancy["symbol"] == symbol and occupancy["state"] == "OPEN" and
             occupancy["as_of_ms"] == now, "EXISTING_OPEN_RESERVATION_UNBOUND")
    return bars, now, closed, signal_index, prefix_start, role


def prepare_extension(snapshot: Mapping, position: Mapping, *, enabled: bool = False) -> dict:
    """Prepare one held-reference intent; caller retains all source/fill authority."""
    if enabled is not True:
        return _result("DISABLED", "DEFAULT_OFF", snapshot)
    try:
        snapshot, position = deepcopy(snapshot), deepcopy(position)
        bars, now, closed, signal_index, prefix_start, role = _validate(snapshot, position)
        features, engine, spec = _native_features(bars)
        _require(bool(engine.eval(spec["entry_rule"], signal_index)), "ORIGINAL_NATIVE_ENTRY_NOT_REPRODUCED")
        timeout = position["original_timeout_close_ms"]
        common = {"decision_as_of_ms": now, "decision_bar_close_ms": closed,
                  "history_role": role, "native_prefix_start_ms": prefix_start,
                  "source_available_ms": bars[-1]["received_at_ms"],
                  "original_timeout_close_ms": timeout,
                  "signal_hash": position["origin_signal_sha256"],
                  "required_fill_witness_at_or_after_ms": now,
                  "same_close_or_next_open_fill_claimed": False}
        if closed < timeout:
            if snapshot["censor_at_end"]:
                return _result("CENSORED_NO_SYNTHETIC_CLOSE", "END_BEFORE_ORIGINAL_TIMEOUT", snapshot,
                               policy_intent="NO_CHILD_ACTION_BEFORE_TIMEOUT", **common)
            return _result("NO_CHILD_ACTION_BEFORE_TIMEOUT", None, snapshot, **common)
        first_timeout_index = (timeout - prefix_start) // BAR - 1
        for index in range(first_timeout_index, len(bars)):
            fast, slow = features["ema20"][index], features["ema50"][index]
            _require(type(fast) in (int, float) and type(slow) in (int, float) and
                     math.isfinite(fast) and math.isfinite(slow), "NATIVE_EMA_UNBOUND")
            if index < len(bars) - 1:
                _require(fast > slow, "EARLIER_EXIT_UNRESOLVED_NO_EXTENSION_RESUME")
        fast, slow = features["ema20"][-1], features["ema50"][-1]
        persists = fast > slow
        common.update({"ema20": fast, "ema50": slow, "trend_persists": persists,
                       "policy_intent": "CONTINUE" if persists else "REQUEST_EXIT_WITNESS",
                       "additional_hold_cap": None})
        if snapshot["censor_at_end"]:
            return _result("CENSORED_NO_SYNTHETIC_CLOSE", "END_OF_SUPPLIED_WINDOW", snapshot, **common)
        return _result("CONTINUE_INTENT_PENDING_OWNER" if persists else "EXIT_INTENT_REQUIRES_WITNESSED_FILL",
                       None if persists else "EMA20_NOT_GREATER_THAN_EMA50", snapshot, **common)
    except (KeyError, TypeError, ValueError, RuntimeError, OSError, StopIteration) as exc:
        return _result("HOLD_UNRESOLVED", str(exc), snapshot)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--position", type=Path)
    parser.add_argument("--enable-preparation", action="store_true")
    args = parser.parse_args(argv)
    if not args.enable_preparation:
        result = prepare_extension({}, {})
    else:
        if args.snapshot is None or args.position is None:
            parser.error("--snapshot and --position required for enabled preparation")
        snapshot = json.loads(args.snapshot.read_text(), object_pairs_hook=_unique_object)
        position = json.loads(args.position.read_text(), object_pairs_hook=_unique_object)
        result = prepare_extension(snapshot, position, enabled=True)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
