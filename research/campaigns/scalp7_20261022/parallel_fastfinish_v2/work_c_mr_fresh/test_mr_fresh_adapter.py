"""Finite synthetic supplied-frame tests; no source fetch, fill, or economic replay.

The 21+ bar fixtures run the exact native six-symbol formation. They are not
old 61T execution-parity fixtures or claims about future profitability.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

import pandas as pd

import mr_fresh_adapter as adapter


HERE = Path(__file__).resolve().parent
TF = 1_800_000
START = 1_000_000 * TF
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
NATIVE_SHA = "1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5"
IDENTITY = "mr_reexpansion_bar4_30m_causal_control_v2"


def native_module():
    path = HERE.parents[4] / "backend/research/rebuild/scalp7_mr_formation_v2.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != NATIVE_SHA:
        raise AssertionError("NATIVE_SOURCE_CHANGED")
    name = "mr_fresh_test_exact_native"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def refresh_receipts(snapshot):
    """Self-consistent synthetic delivery receipts; no market provenance claim."""
    receipts = {}
    for symbol, rows in snapshot["frames"].items():
        closed = rows[-1]["close_ts_ms"]
        received = max(row["available_ts_ms"] for row in rows)
        usable = max(closed, received, snapshot["as_of_ms"])
        proof = {
            "schema": "scalp7.actual_source_clock_barrier.v3",
            "state": "USABLE_AFTER_ACTUAL_CLOCK_BARRIER",
            "native_ts_ms": closed, "received_at_ms": received,
            "started_at_ms": usable, "usable_at_ms": usable,
            "started_monotonic_ns": 1_000_000_000, "usable_monotonic_ns": 1_000_000_000,
            "waited_ms": 0.0, "max_wait_ms": 5000, "quarantined": False,
            "clock_samples": [{"wall_ms": usable, "monotonic_ns": 1_000_000_000}],
            "native_timestamp_rewritten": False, "receipt_timestamp_rewritten": False,
            "clock_offset_or_tolerance_applied": False,
        }
        receipt = {
            "symbol": symbol,
            "frame_sha256": adapter.digest(rows),
            "source_identity_sha256": adapter.digest({"fixture": "SYNTHETIC_ONLY", "symbol": symbol}),
            "source_cursor_sha256": adapter.digest({"symbol": symbol, "last_open": rows[-1]["open_ts_ms"]}),
            "available_ts_ms": received,
            "observed_at_ms": snapshot["as_of_ms"],
            "source_ts_ms": closed, "received_at_ms": received, "usable_at_ms": usable,
            "clock_proof": proof,
        }
        receipts[symbol] = {"receipt": receipt, "receipt_sha256": adapter.digest(receipt)}
    snapshot["source_receipts"] = receipts
    return snapshot


def refresh_occupancy(snapshot):
    body = {key: value for key, value in snapshot["occupancy"].items() if key != "receipt_sha256"}
    snapshot["occupancy"]["receipt_sha256"] = adapter.digest(body)
    return snapshot


def synthetic_snapshot(extra_bars=0, *, reexpand=True):
    """Actual native entry at index20: spread .16 contracts from .20."""
    asof = START + (21 + extra_bars) * TF
    frames = {}
    for symbol in SYMBOLS:
        rows = []
        for index in range(21 + extra_bars):
            price = 100.0
            if symbol in SYMBOLS[:2] and index >= 19:
                direction = 1 if symbol == SYMBOLS[0] else -1
                amount = 10.0 if index == 19 else 8.0 if index == 20 else 10.0 if reexpand else 6.0
                price += direction * amount
            opened = START + index * TF
            rows.append({"open_ts_ms": opened, "close_ts_ms": opened + TF,
                         "available_ts_ms": opened + TF, "segment_id": "synthetic-contiguous",
                         "open": price, "high": price + 1, "low": price - 1, "close": price,
                         "volume": None})
        frames[symbol] = rows
    return refresh_occupancy(refresh_receipts({
        "as_of_ms": asof,
        "reference_clock": {"wall_ms": asof, "monotonic_ns": (extra_bars + 2) * TF * 1_000_000,
                            "previous_wall_ms": asof - TF,
                            "previous_monotonic_ns": (extra_bars + 1) * TF * 1_000_000},
        "forward_boundary_ms": START + 20 * TF,
        "last_decision_close_ms": asof - TF,
        "seen_opportunity_keys": [],
        "frames": frames, "costs_bps": {symbol: 10.0 for symbol in SYMBOLS},
        "occupancy": {
            "receipt_id": "synthetic-global-capital-receipt", "as_of_ms": asof,
            "capital_available": True, "account_reservation_busy": False, "occupied_symbols": [],
            "reservation": {"reservation_id": "synthetic-owner-reservation", "identity": IDENTITY,
                            "signal_ts_ms": START + 21 * TF, "symbols": ["ETH-USDT", "BTC-USDT"],
                            "as_of_ms": asof},
        },
    }))


def native_signals(snapshot):
    return native_module().generate_signals(
        {symbol: pd.DataFrame(rows) for symbol, rows in snapshot["frames"].items()}, identity=IDENTITY)


def synthetic_position(extra_bars):
    origin = synthetic_snapshot()
    signal = native_signals(origin)[0]
    return {"signal": signal, "signal_sha256": adapter.digest(signal),
            "origin_snapshot": origin, "origin_sha256": adapter.digest(origin),
            "entry_reference_ts_ms": signal["signal_open_ts_ms"] + TF,
            "hold_bars": extra_bars, "reservation_id": "synthetic-owner-reservation"}


class MRFreshAdapterTests(unittest.TestCase):
    def assert_no_signal(self, result):
        self.assertEqual(result["intents"], [], result)
        self.assertFalse(result["executable"], result)
        self.assertEqual(result["fresh_T"], 0, result)

    def test_fixture_uses_actual_native_six_symbol_pair_formation(self):
        snapshot = synthetic_snapshot()
        signals = native_signals(snapshot)
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal["identity"], IDENTITY)
        self.assertEqual(signal["meta"]["leader"], "BTC-USDT")
        self.assertEqual(signal["meta"]["laggard"], "ETH-USDT")
        self.assertAlmostEqual(signal["meta"]["signal_spread6h"], 0.16)
        self.assertAlmostEqual(signal["meta"]["previous_spread6h"], 0.20)
        self.assertEqual(signal["signal_ts_ms"], snapshot["as_of_ms"])
        self.assertIsNone(signal["stop_price"])
        self.assertEqual(signal["max_hold_bars"], 8)

    def test_adapter_entry_is_exact_native_signal_and_does_not_mutate_snapshot(self):
        snapshot = synthetic_snapshot()
        before = copy.deepcopy(snapshot)
        result = adapter.prepare_signals(snapshot, enabled=True)
        self.assertEqual(len(result["intents"]), 1, result)
        self.assertEqual(result["intents"][0]["signal"], native_signals(snapshot)[0])
        self.assertEqual(result["state"], "SOURCE_CODE_READY_SIGNAL_ONLY")
        self.assertFalse(result["executable"])
        self.assertFalse(result["real_sources_verified"])
        self.assertEqual(result["fresh_T"], 0)
        self.assertEqual(snapshot, before)

    def test_future_and_unclosed_bars_cannot_emit(self):
        for mode in ("future_closed", "unclosed"):
            with self.subTest(mode=mode):
                snapshot = synthetic_snapshot()
                for rows in snapshot["frames"].values():
                    row = copy.deepcopy(rows[-1])
                    row["open_ts_ms"] += TF
                    row["close_ts_ms"] += TF
                    row["available_ts_ms"] = row["close_ts_ms"] if mode == "future_closed" else snapshot["as_of_ms"]
                    rows.append(row)
                refresh_receipts(snapshot)
                self.assert_no_signal(adapter.prepare_signals(snapshot, enabled=True))

    def test_missing_pair_stale_six_hour_feed_and_history_gap_cannot_emit(self):
        missing = synthetic_snapshot()
        del missing["frames"]["ETH-USDT"]
        refresh_receipts(missing)
        self.assert_no_signal(adapter.prepare_signals(missing, enabled=True))
        stale = synthetic_snapshot()
        stale["as_of_ms"] += 12 * TF
        stale["reference_clock"]["wall_ms"] = stale["as_of_ms"]
        stale["reference_clock"]["previous_wall_ms"] = stale["as_of_ms"] - TF
        stale["occupancy"]["as_of_ms"] = stale["as_of_ms"]
        stale["occupancy"]["reservation"]["as_of_ms"] = stale["as_of_ms"]
        refresh_receipts(stale)
        refresh_occupancy(stale)
        self.assert_no_signal(adapter.prepare_signals(stale, enabled=True))
        gap = synthetic_snapshot()
        del gap["frames"]["BTC-USDT"][10]
        refresh_receipts(gap)
        self.assert_no_signal(adapter.prepare_signals(gap, enabled=True))

    def test_duplicate_symbol_alias_and_duplicate_bar_are_rejected(self):
        alias = synthetic_snapshot()
        alias["frames"]["BTC-USDT_DUPLICATE"] = copy.deepcopy(alias["frames"]["BTC-USDT"])
        refresh_receipts(alias)
        self.assert_no_signal(adapter.prepare_signals(alias, enabled=True))
        duplicate = synthetic_snapshot()
        duplicate["frames"]["BTC-USDT"].append(copy.deepcopy(duplicate["frames"]["BTC-USDT"][-1]))
        refresh_receipts(duplicate)
        self.assert_no_signal(adapter.prepare_signals(duplicate, enabled=True))

    def test_bad_price_geometry_and_missing_cost_are_rejected(self):
        geometry = synthetic_snapshot()
        geometry["frames"]["BTC-USDT"][-1]["high"] = 1.0
        refresh_receipts(geometry)
        self.assert_no_signal(adapter.prepare_signals(geometry, enabled=True))
        for unknown in (None, -1.0, float("nan")):
            cost = synthetic_snapshot()
            cost["costs_bps"]["ETH-USDT"] = unknown
            self.assert_no_signal(adapter.prepare_signals(cost, enabled=True))
        cost = synthetic_snapshot()
        del cost["costs_bps"]["ETH-USDT"]
        self.assert_no_signal(adapter.prepare_signals(cost, enabled=True))

    def test_unknown_volume_is_ignored_by_exact_native_formation(self):
        unknown = synthetic_snapshot()
        arbitrary = copy.deepcopy(unknown)
        for rows in arbitrary["frames"].values():
            for row in rows:
                row["volume"] = "SOURCE_VOLUME_UNAVAILABLE"
        refresh_receipts(arbitrary)
        first = adapter.prepare_signals(unknown, enabled=True)
        second = adapter.prepare_signals(arbitrary, enabled=True)
        self.assertEqual(len(first["intents"]), 1, first)
        self.assertEqual(len(second["intents"]), 1, second)
        self.assertEqual(first["intents"][0]["signal"], second["intents"][0]["signal"])

    def test_reference_clock_receipt_and_future_boundary_fail_closed(self):
        for key, value in (("wall_ms", 0), ("monotonic_ns", 0)):
            snapshot = synthetic_snapshot()
            snapshot["reference_clock"][key] = value
            self.assert_no_signal(adapter.prepare_signals(snapshot, enabled=True))
        proof = synthetic_snapshot()
        receipt = proof["source_receipts"]["BTC-USDT"]["receipt"]
        receipt["clock_proof"]["clock_offset_or_tolerance_applied"] = True
        proof["source_receipts"]["BTC-USDT"]["receipt_sha256"] = adapter.digest(receipt)
        self.assert_no_signal(adapter.prepare_signals(proof, enabled=True))
        snapshot = synthetic_snapshot()
        snapshot["forward_boundary_ms"] = snapshot["as_of_ms"] + TF
        self.assert_no_signal(adapter.prepare_signals(snapshot, enabled=True))

    def test_global_capital_busy_blocks_even_disjoint_symbols_and_missing_reservation(self):
        for field, value in (("capital_available", False), ("account_reservation_busy", True)):
            snapshot = synthetic_snapshot()
            snapshot["occupancy"][field] = value
            snapshot["occupancy"]["occupied_symbols"] = ["SOL-USDT", "LINK-USDT"]
            refresh_occupancy(snapshot)
            result = adapter.prepare_signals(snapshot, enabled=True)
            self.assert_no_signal(result)
            self.assertEqual(result["state"], "HOLD")
            self.assertIn("CAPITAL_OCCUPIED", result["reason"])
        pending = synthetic_snapshot()
        pending["occupancy"]["reservation"] = None
        refresh_occupancy(pending)
        result = adapter.prepare_signals(pending, enabled=True)
        self.assertEqual(result["state"], "PENDING_EXTERNAL_CAPITAL_RESERVATION")
        self.assertFalse(result["executable"])
        self.assertFalse(result["capital_allocated"])
        self.assertIsNone(result["reservation"])

    def test_default_off_calls_no_native_loader_or_signal_callback(self):
        with mock.patch.object(adapter, "_modules", side_effect=AssertionError("native must not run")) as loader:
            self.assert_no_signal(adapter.prepare_signals({}))
            self.assert_no_signal(adapter.prepare_exit({}, {}))
            self.assert_no_signal(adapter.prepare_signals({}, enabled="true"))
            loader.assert_not_called()

    def test_fee_2x_changes_only_reference_cost_arithmetic(self):
        snapshot = synthetic_snapshot()
        snapshot["costs_bps"]["BTC-USDT"] = 12.0
        snapshot["costs_bps"]["ETH-USDT"] = 8.0
        result = adapter.prepare_signals(snapshot, enabled=True)
        self.assertEqual(len(result["intents"]), 1, result)
        self.assertEqual(result["intents"][0]["signal"], native_signals(snapshot)[0])
        self.assertEqual(result["costs"]["weighted_cost1x_bps"], 10.0)
        self.assertEqual(result["costs"]["weighted_cost2x_bps"], 20.0)
        self.assertFalse(result["costs"]["strategy_geometry_changed"])
        self.assertIsNone(result["PnL"])
        self.assertEqual(result["fills"], [])

    def test_native_exit_parity_bar3_bar4_and_frozen_bar8_timeout(self):
        for held, reexpand, reason in ((3, True, None), (4, True, "THESIS_REEXPAND_FAIL_BAR4"),
                                       (7, False, None), (8, False, "TIME_8BAR")):
            with self.subTest(held=held, reexpand=reexpand):
                snapshot = synthetic_snapshot(held, reexpand=reexpand)
                position = synthetic_position(held)
                before_snapshot, before_position = copy.deepcopy(snapshot), copy.deepcopy(position)
                pair = [leg["symbol"] for leg in position["signal"]["legs"]]
                histories = {symbol: pd.DataFrame(snapshot["frames"][symbol]) for symbol in pair}
                bars = {symbol: snapshot["frames"][symbol][-1] for symbol in pair}
                expected = native_module().exit_update(
                    {"signal": position["signal"], "hold_bars": held}, bars, histories)
                result = adapter.prepare_exit(snapshot, position, enabled=True)
                self.assertEqual(len(result["intents"]), 1, result)
                actual = result["intents"][0]
                for key in ("exit_next_open", "reason", "current_spread6h"):
                    self.assertEqual(actual[key], expected[key])
                self.assertEqual(actual["reason"], reason)
                self.assertEqual(actual["exit_reference_ts_ms"], snapshot["as_of_ms"] if reason else None)
                self.assertEqual(result["reservation"], snapshot["occupancy"]["reservation"])
                self.assertFalse(result["reservation_changed"])
                self.assertFalse(result["executable"])
                self.assertEqual((snapshot, position), (before_snapshot, before_position))

    def test_frozen_mr_has_no_stop_and_cannot_invent_stop_first_behavior(self):
        snapshot = synthetic_snapshot(3)
        position = synthetic_position(3)
        for rows in snapshot["frames"].values():
            rows[-1]["low"] = 0.01  # Adverse range alone is not a native MR stop.
        refresh_receipts(snapshot)
        result = adapter.prepare_exit(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "HOLD_POSITION", result)
        self.assertIsNone(result["intents"][0]["reason"])
        self.assertFalse(result["intents"][0]["exit_next_open"])
        position["stop_price"] = 95.0
        result = adapter.prepare_exit(snapshot, position, enabled=True)
        self.assert_no_signal(result)
        self.assertIn("FROZEN_NO_STOP_POLICY_CHANGED", result["reason"])

    def test_bad_spread_duplicate_legs_and_reference_hold_clock_are_rejected(self):
        snapshot = synthetic_snapshot(4)
        for mutation in ("bad_spread", "duplicate_leg", "wrong_held", "wrong_entry_clock"):
            with self.subTest(mutation=mutation):
                position = synthetic_position(4)
                if mutation == "bad_spread":
                    position["signal"]["meta"]["signal_spread6h"] = -0.16
                elif mutation == "duplicate_leg":
                    position["signal"]["legs"][1]["symbol"] = position["signal"]["legs"][0]["symbol"]
                elif mutation == "wrong_held":
                    position["hold_bars"] = 3
                else:
                    position["entry_reference_ts_ms"] += TF
                position["signal_sha256"] = adapter.digest(position["signal"])
                self.assert_no_signal(adapter.prepare_exit(snapshot, position, enabled=True))

    def test_exit_gap_is_unresolved_and_does_not_release_pair_capital(self):
        for gap in ("missing_pair", "history_gap"):
            with self.subTest(gap=gap):
                snapshot = synthetic_snapshot(4)
                position = synthetic_position(4)
                if gap == "missing_pair":
                    del snapshot["frames"]["ETH-USDT"]
                else:
                    del snapshot["frames"]["BTC-USDT"][-3]
                refresh_receipts(snapshot)
                result = adapter.prepare_exit(snapshot, position, enabled=True)
                self.assert_no_signal(result)
                self.assertEqual(result["position_status"], "HOLD_UNRESOLVED_REFERENCE_NO_RELEASE", result)
                self.assertEqual(result["reservation"], snapshot["occupancy"]["reservation"])
                self.assertFalse(result["reservation_changed"])
                self.assertEqual(result["fills"], [])

    def test_late_delivery_never_claims_reference_open_fill(self):
        for exiting in (False, True):
            with self.subTest(exiting=exiting):
                snapshot = synthetic_snapshot(4 if exiting else 0)
                snapshot["as_of_ms"] += 1
                snapshot["reference_clock"]["wall_ms"] += 1
                snapshot["occupancy"]["as_of_ms"] += 1
                snapshot["occupancy"]["reservation"]["as_of_ms"] += 1
                for rows in snapshot["frames"].values():
                    rows[-1]["available_ts_ms"] += 1
                refresh_receipts(snapshot)
                refresh_occupancy(snapshot)
                result = (adapter.prepare_exit(snapshot, synthetic_position(4), enabled=True) if exiting
                          else adapter.prepare_signals(snapshot, enabled=True))
                self.assertEqual(result["state"], "HOLD", result)
                self.assertIn("LATE_MODEL_", result["reason"])
                self.assertEqual(result["fills"], [])
                self.assertFalse(result["executable"])
                self.assertEqual(result["fresh_T"], 0)

    def test_same_opportunity_from_another_producer_is_not_reemitted(self):
        snapshot = synthetic_snapshot()
        signal = native_signals(snapshot)[0]
        snapshot["seen_opportunity_keys"] = [adapter.opportunity_key(signal)]
        result = adapter.prepare_signals(snapshot, enabled=True)
        self.assert_no_signal(result)
        self.assertIn("OPPORTUNITY", result["reason"])

    def test_actual_decision_after_model_close_cannot_use_on_time_rows_as_a_fill(self):
        for exiting in (False, True):
            with self.subTest(exiting=exiting):
                snapshot = synthetic_snapshot(4 if exiting else 0)
                original_receipts = copy.deepcopy(snapshot["source_receipts"])
                snapshot["as_of_ms"] += 1
                snapshot["reference_clock"]["wall_ms"] += 1
                snapshot["occupancy"]["as_of_ms"] += 1
                snapshot["occupancy"]["reservation"]["as_of_ms"] += 1
                refresh_occupancy(snapshot)
                result = (adapter.prepare_exit(snapshot, synthetic_position(4), enabled=True) if exiting
                          else adapter.prepare_signals(snapshot, enabled=True))
                self.assertEqual(result["state"], "HOLD", result)
                self.assertIn("LATE_MODEL_", result["reason"])
                self.assertFalse(result["executable"])
                self.assertEqual(result["fills"], [])
                self.assertEqual(snapshot["source_receipts"], original_receipts)

    def test_position_origin_must_have_passed_all_original_entry_admission_gates(self):
        for mutation in ("seen_opportunity", "decision_already_seen", "unknown_cost", "late_origin"):
            with self.subTest(mutation=mutation):
                snapshot = synthetic_snapshot(4)
                position = synthetic_position(4)
                origin = position["origin_snapshot"]
                if mutation == "seen_opportunity":
                    origin["seen_opportunity_keys"] = [adapter.opportunity_key(position["signal"])]
                elif mutation == "decision_already_seen":
                    origin["last_decision_close_ms"] = origin["as_of_ms"]
                elif mutation == "unknown_cost":
                    origin["costs_bps"]["ETH-USDT"] = None
                else:
                    origin["as_of_ms"] += 1
                    origin["reference_clock"]["wall_ms"] += 1
                    origin["occupancy"]["as_of_ms"] += 1
                    origin["occupancy"]["reservation"]["as_of_ms"] += 1
                    refresh_occupancy(origin)
                position["origin_sha256"] = adapter.digest(origin)
                self.assertEqual(adapter.prepare_signals(origin, enabled=True)["state"], "HOLD")
                result = adapter.prepare_exit(snapshot, position, enabled=True)
                self.assert_no_signal(result)
                self.assertEqual(result["state"], "HOLD")
                self.assertIn("ORIGIN_ENTRY_ADMISSION_DENIED", result["reason"])
                self.assertEqual(result["reservation"], snapshot["occupancy"]["reservation"])

    def test_previously_due_bar4_exit_cannot_be_backfilled_at_bar7(self):
        snapshot = synthetic_snapshot(7, reexpand=True)
        result = adapter.prepare_exit(snapshot, synthetic_position(7), enabled=True)
        self.assert_no_signal(result)
        self.assertEqual(result["state"], "HOLD")
        self.assertIn("EARLIER_NATIVE_EXIT_UNRESOLVED_NO_BACKFILL", result["reason"])
        self.assertIn("THESIS_REEXPAND_FAIL_BAR4", result["reason"])
        self.assertEqual(result["position_status"], "HOLD_UNRESOLVED_REFERENCE_NO_RELEASE")
        self.assertEqual(result["reservation"], snapshot["occupancy"]["reservation"])
        self.assertFalse(result["reservation_changed"])


if __name__ == "__main__":
    unittest.main()
