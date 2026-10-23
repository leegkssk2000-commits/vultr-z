"""Stage4 conditional runner tests on finite synthetic bars only.

No Stage1--3 evaluator, historical replay, market source, or economics runs here.
The reference class is AST-extracted from the hash-pinned native Expr source;
its network imports and data-fetch functions are never imported or executed.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import subprocess
import unittest
from unittest import mock

import policy_adapter as adapter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BAR = 14_400_000
BOUNDARY = 1_788_048_000_000
PARENT = "supertrend_replacement_highvol_mom_long_4h_h12_v2"
SYMBOLS = ("1000PEPE-USDT", "BCH-USDT", "BTC-USDT", "ETH-USDT", "HYPE-USDT", "LINK-USDT", "SOL-USDT")
EXPR_SHA = "d86a61ed25f8d6f74a8c56e834db13a6ba61daa370731a590bbbab514f5ae736"


def reference_expr_class():
    path = ROOT / "backend/research/architecture_factory/a1_gen2_generic_dev_econ_v1.py"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPR_SHA:
        raise AssertionError("EXACT_NATIVE_EXPR_SOURCE_CHANGED")
    parsed = ast.parse(raw)
    node = next(node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == "Expr")
    only_class = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(only_class)
    scope = {"ast": ast, "math": math, "re": re, "datetime": datetime, "timezone": timezone}
    exec(compile(only_class, "<pinned-native-Expr-class-only>", "exec"), scope)
    return scope["Expr"]


def bind_snapshot(snapshot):
    snapshot["raw_sha256"] = adapter.digest(snapshot["bars"])
    receipt = {"source_identity_sha256": adapter.digest({"fixture": "SYNTHETIC_ONLY_NO_MARKET"}),
               "raw_sha256": snapshot["raw_sha256"], "observed_at_ms": snapshot["as_of_ms"]}
    snapshot["source_receipt"] = receipt
    snapshot["source_receipt_sha256"] = adapter.digest(receipt)
    occupancy = {key: value for key, value in snapshot["occupancy"].items() if key != "receipt_sha256"}
    snapshot["occupancy"]["receipt_sha256"] = adapter.digest(occupancy)
    return snapshot


def synthetic_case(held=12, *, symbol="BTC-USDT", final_trend=True, censored=False):
    rows = []
    start = BOUNDARY - 240 * BAR
    for index in range(241 + held):
        price = 100.0 + index * 0.1 if index < 240 else 150.0 + (index - 240)
        if index > 240 and not final_trend:
            price = 1.0
        opened = start + index * BAR
        rows.append({"ts": opened, "open": price, "high": price + 0.5,
                     "low": max(0.01, price - 0.5), "close": price,
                     "volume": 0.0, "available_at_ms": opened + BAR, "received_at_ms": opened + BAR})
    asof = rows[-1]["ts"] + BAR
    snapshot = bind_snapshot({
        "as_of_ms": asof, "symbol": symbol, "timeframe": "4h", "bars": rows,
        "last_decision_close_ms": asof - BAR, "censor_at_end": censored,
        "occupancy": {"reservation_id": "synthetic-owner-reservation", "symbol": symbol,
                      "state": "OPEN", "as_of_ms": asof, "receipt_id": "synthetic-account-context"},
    })
    position = {"parent_id": PARENT, "symbol": symbol, "side": "long",
                "signal_ts": BOUNDARY, "entry_ts": BOUNDARY + BAR,
                "original_timeout_close_ms": BOUNDARY + 13 * BAR,
                "reservation_id": "synthetic-owner-reservation"}
    position["origin_prefix_sha256"] = adapter.digest(rows[:241])
    position["origin_signal_sha256"] = adapter.digest({key: position[key] for key in
        ("parent_id", "symbol", "side", "signal_ts", "entry_ts", "original_timeout_close_ms")})
    snapshot["occupancy"]["origin_signal_sha256"] = position["origin_signal_sha256"]
    bind_snapshot(snapshot)
    return snapshot, position


def synthetic_separate_dev_case():
    """Shift only synthetic clocks; this does not select any real DEV window."""
    snapshot, position = synthetic_case()
    shift = -100 * BAR
    for row in snapshot["bars"]:
        for key in ("ts", "available_at_ms", "received_at_ms"):
            row[key] += shift
    for key in ("as_of_ms", "last_decision_close_ms"):
        snapshot[key] += shift
    snapshot["occupancy"]["as_of_ms"] += shift
    for key in ("signal_ts", "entry_ts", "original_timeout_close_ms"):
        position[key] += shift
    position["origin_prefix_sha256"] = adapter.digest(snapshot["bars"][:241])
    position["origin_signal_sha256"] = adapter.digest({key: position[key] for key in adapter.PROOF_KEYS})
    snapshot["occupancy"]["origin_signal_sha256"] = position["origin_signal_sha256"]
    bind_snapshot(snapshot)
    snapshot["source_receipt"].update(
        history_role="SEPARATE_DEV", boundary_ms=BOUNDARY + shift, end_ms=BOUNDARY,
        native_prefix_start_ms=BOUNDARY + shift - 240 * BAR,
        dev_contract_sha256=adapter.digest({"fixture": "SYNTHETIC_DEV_CLOCK_CONTRACT_ONLY"}))
    snapshot["source_receipt_sha256"] = adapter.digest(snapshot["source_receipt"])
    return snapshot, position


class Stage4PolicyTests(unittest.TestCase):
    def assert_no_economic_action(self, result):
        self.assertFalse(result["executable"])
        self.assertFalse(result["source_ready"])
        self.assertFalse(result["economic_eligible"])
        self.assertFalse(result["position_release_authorized"])
        self.assertFalse(result["reservation_changed"])
        self.assertEqual(result["fresh_T"], 0)
        self.assertEqual(result["fills"], [])
        self.assertIsNone(result["PnL"])
        self.assertEqual(result["economic_runs"], 0)
        self.assertEqual(result["order_calls"], 0)

    def assert_rejected(self, snapshot, position, reason=None):
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "HOLD_UNRESOLVED", result)
        self.assert_no_economic_action(result)
        if reason:
            self.assertIn(reason, result["reason"])
        return result

    def test_native_reference_is_class_only_and_preserves_4n_seed(self):
        reference = reference_expr_class()
        snapshot, _ = synthetic_case()
        engine = reference(snapshot["bars"], {})
        native, _, _ = adapter._native_features(snapshot["bars"])
        for length in (20, 50):
            for index in (0, 19, 79, 199, len(snapshot["bars"]) - 1):
                actual = engine.eval("ema(close," + str(length) + ")", index)
                values = [row["close"] for row in snapshot["bars"][max(0, index - 4 * length + 1):index + 1]]
                seeded = values[0]
                alpha = 2.0 / (length + 1.0)
                for value in values[1:]:
                    seeded = alpha * value + (1 - alpha) * seeded
                self.assertEqual(actual, seeded)
                self.assertEqual(native["ema" + str(length)][index], actual)

    def test_default_off_never_calls_native_features(self):
        with mock.patch.object(adapter, "_native_features", side_effect=AssertionError("default OFF called native")) as native:
            for enabled in (False, "true", 1):
                result = adapter.prepare_extension({}, {}, enabled=enabled)
                self.assertEqual(result["state"], "DISABLED")
                self.assert_no_economic_action(result)
            native.assert_not_called()

    def test_actual_frozen_entry_and_false_ema_before_h12_do_not_exit_early(self):
        snapshot, position = synthetic_case(held=11, final_trend=False)
        features, engine, spec = adapter._native_features(snapshot["bars"])
        self.assertTrue(engine.eval(spec["entry_rule"], 240))
        self.assertLess(features["ema20"][-1], features["ema50"][-1])
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "NO_CHILD_ACTION_BEFORE_TIMEOUT", result)
        self.assert_no_economic_action(result)
        self.assertNotIn("REQUEST_EXIT_WITNESS", result.values())

    def test_h12_intact_trend_continues_without_changing_inputs_or_claiming_fills(self):
        snapshot, position = synthetic_case()
        before = copy.deepcopy((snapshot, position))
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "CONTINUE_INTENT_PENDING_OWNER", result)
        self.assertEqual(result["policy_intent"], "CONTINUE")
        self.assertTrue(result["trend_persists"])
        self.assertEqual(result["original_timeout_close_ms"], snapshot["as_of_ms"])
        self.assertEqual(result["required_fill_witness_at_or_after_ms"], snapshot["as_of_ms"])
        self.assertFalse(result["same_close_or_next_open_fill_claimed"])
        self.assertIsNone(result["additional_hold_cap"])
        self.assert_no_economic_action(result)
        self.assertEqual((snapshot, position), before)

    def test_h12_false_requests_a_witness_and_cannot_fabricate_original_close(self):
        snapshot, position = synthetic_case(final_trend=False)
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "EXIT_INTENT_REQUIRES_WITNESSED_FILL", result)
        self.assertEqual(result["policy_intent"], "REQUEST_EXIT_WITNESS")
        self.assertFalse(result["trend_persists"])
        self.assertFalse(result["same_close_or_next_open_fill_claimed"])
        self.assertNotIn("exit_price", result)
        self.assertNotIn("exit_px", result)
        self.assert_no_economic_action(result)

    def test_intact_trend_after_24_bars_does_not_invent_an_additional_timeout(self):
        snapshot, position = synthetic_case(held=25)
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "CONTINUE_INTENT_PENDING_OWNER", result)
        self.assertIsNone(result["additional_hold_cap"])
        self.assertGreater(result["decision_bar_close_ms"], position["entry_ts"] + 24 * BAR)
        self.assert_no_economic_action(result)

    def test_first_trend_loss_after_extension_is_intent_only_and_keeps_reservation(self):
        snapshot, position = synthetic_case(held=13)
        for row in snapshot["bars"][241:]:
            price = 125.0 if row is not snapshot["bars"][-1] else 1.0
            row.update(open=price, high=price + 0.5, low=price - 0.5, close=price)
        bind_snapshot(snapshot)
        features, _, _ = adapter._native_features(snapshot["bars"])
        self.assertGreater(features["ema20"][-2], features["ema50"][-2])
        self.assertLess(features["ema20"][-1], features["ema50"][-1])
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "EXIT_INTENT_REQUIRES_WITNESSED_FILL", result)
        self.assertEqual(result["reservation_id"], position["reservation_id"])
        self.assert_no_economic_action(result)

    def test_previously_failed_trend_cannot_resume_extension_or_backfill_exit(self):
        snapshot, position = synthetic_case(held=14, final_trend=False)
        last = snapshot["bars"][-1]
        last.update(open=1000.0, high=1001.0, low=999.0, close=1000.0)
        bind_snapshot(snapshot)
        self.assert_rejected(snapshot, position, "EARLIER_EXIT_UNRESOLVED_NO_EXTENSION_RESUME")

    def test_censored_positions_are_never_closed_or_released(self):
        for held in (5, 12, 13):
            with self.subTest(held=held):
                snapshot, position = synthetic_case(held=held, censored=True)
                result = adapter.prepare_extension(snapshot, position, enabled=True)
                self.assertEqual(result["state"], "CENSORED_NO_SYNTHETIC_CLOSE", result)
                self.assertEqual(result["reservation_id"], position["reservation_id"])
                self.assert_no_economic_action(result)

    def test_future_unclosed_and_not_yet_received_candles_are_rejected(self):
        for mutation in ("future_row", "before_close_available", "receipt_in_future"):
            with self.subTest(mutation=mutation):
                snapshot, position = synthetic_case()
                if mutation == "future_row":
                    future = copy.deepcopy(snapshot["bars"][-1])
                    for key in ("ts", "available_at_ms", "received_at_ms"):
                        future[key] += BAR
                    snapshot["bars"].append(future)
                elif mutation == "before_close_available":
                    snapshot["bars"][-1]["available_at_ms"] -= 1
                else:
                    snapshot["bars"][-1]["received_at_ms"] += 1
                bind_snapshot(snapshot)
                self.assert_rejected(snapshot, position, "UNFINISHED_FUTURE_OR_UNAVAILABLE_BAR")

    def test_observed_late_receipt_keeps_actual_clock_and_never_backdates_fill(self):
        snapshot, position = synthetic_case(final_trend=False)
        original_close = snapshot["as_of_ms"]
        snapshot["as_of_ms"] += 10
        snapshot["bars"][-1]["available_at_ms"] += 5
        snapshot["bars"][-1]["received_at_ms"] += 10
        snapshot["occupancy"]["as_of_ms"] += 10
        bind_snapshot(snapshot)
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "EXIT_INTENT_REQUIRES_WITNESSED_FILL", result)
        self.assertEqual(result["decision_bar_close_ms"], original_close)
        self.assertEqual(result["decision_as_of_ms"], original_close + 10)
        self.assertEqual(result["required_fill_witness_at_or_after_ms"], original_close + 10)
        self.assertFalse(result["same_close_or_next_open_fill_claimed"])
        self.assert_no_economic_action(result)

    def test_missing_receipts_hash_tamper_and_unfinished_source_identity_rejected(self):
        for mutation in ("missing_receipt", "missing_received", "raw_hash", "receipt_hash", "source_identity"):
            with self.subTest(mutation=mutation):
                snapshot, position = synthetic_case()
                if mutation == "missing_receipt":
                    del snapshot["source_receipt"]
                elif mutation == "missing_received":
                    del snapshot["bars"][-1]["received_at_ms"]
                    bind_snapshot(snapshot)
                elif mutation == "raw_hash":
                    snapshot["raw_sha256"] = "0" * 64
                elif mutation == "receipt_hash":
                    snapshot["source_receipt_sha256"] = "0" * 64
                else:
                    snapshot["source_receipt"]["source_identity_sha256"] = "not-an-immutable-source"
                    snapshot["source_receipt_sha256"] = adapter.digest(snapshot["source_receipt"])
                self.assert_rejected(snapshot, position)

    def test_gap_duplicate_candle_bad_geometry_and_prefix_seed_change_rejected(self):
        for mutation in ("gap", "duplicate", "bad_candle", "seed_change"):
            with self.subTest(mutation=mutation):
                snapshot, position = synthetic_case()
                if mutation == "gap":
                    del snapshot["bars"][100]
                elif mutation == "duplicate":
                    snapshot["bars"].insert(101, copy.deepcopy(snapshot["bars"][100]))
                elif mutation == "bad_candle":
                    snapshot["bars"][-1]["high"] = snapshot["bars"][-1]["close"] - 1
                else:
                    del snapshot["bars"][0]
                bind_snapshot(snapshot)
                result = self.assert_rejected(snapshot, position)
                self.assertEqual(result["reservation_id"], position["reservation_id"])

    def test_owner_reservation_mismatch_and_origin_proof_tamper_fail_closed(self):
        for mutation in ("reservation", "source_prefix", "signal_proof", "timeframe", "stop"):
            with self.subTest(mutation=mutation):
                snapshot, position = synthetic_case()
                if mutation == "reservation":
                    snapshot["occupancy"]["reservation_id"] = "different-owner-reservation"
                    bind_snapshot(snapshot)
                elif mutation == "source_prefix":
                    position["origin_prefix_sha256"] = "0" * 64
                elif mutation == "signal_proof":
                    position["origin_signal_sha256"] = "0" * 64
                elif mutation == "timeframe":
                    snapshot["timeframe"] = "1h"
                else:
                    position["stop_price"] = 90.0
                self.assert_rejected(snapshot, position)

    def test_rehashed_open_reservation_for_another_original_signal_is_rejected(self):
        snapshot, position = synthetic_case()
        other_origin = {key: position[key] for key in adapter.PROOF_KEYS}
        for key in ("signal_ts", "entry_ts", "original_timeout_close_ms"):
            other_origin[key] += BAR
        snapshot["occupancy"]["origin_signal_sha256"] = adapter.digest(other_origin)
        bind_snapshot(snapshot)
        body = {key: value for key, value in snapshot["occupancy"].items() if key != "receipt_sha256"}
        self.assertEqual(snapshot["occupancy"]["receipt_sha256"], adapter.digest(body))
        self.assert_rejected(snapshot, position, "EXISTING_OPEN_RESERVATION_UNBOUND")

    def test_cached_native_dependency_path_and_helper_identity_must_stay_bound(self):
        snapshot, position = synthetic_case()
        adapter._native_features(snapshot["bars"])
        dependency = importlib.import_module("backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1")
        native = importlib.import_module("backend.research.rebuild.a1_top5_replacement_child_prospective_v1")
        with mock.patch.object(dependency, "__file__", "/unbound/synthetic-foreign-native.py"):
            self.assert_rejected(snapshot, position, "NATIVE_DEPENDENCY_MODULE_PATH_CHANGED")
        for name in ("Expr", "_feature_formula"):
            with self.subTest(helper=name), mock.patch.object(native, name, object()):
                self.assert_rejected(snapshot, position, "NATIVE_DEPENDENCY_OBJECT_CHANGED")

    def test_all_seven_original_symbols_including_bch_and_pepe_are_neutral(self):
        states, emas = [], []
        for symbol in SYMBOLS:
            snapshot, position = synthetic_case(symbol=symbol)
            result = adapter.prepare_extension(snapshot, position, enabled=True)
            states.append(result["state"])
            emas.append((result.get("ema20"), result.get("ema50")))
            self.assert_no_economic_action(result)
        self.assertEqual(states, ["CONTINUE_INTENT_PENDING_OWNER"] * 7)
        self.assertEqual(len(set(emas)), 1)
        self.assertEqual(tuple(adapter.SYMBOLS), SYMBOLS)

    def test_outcomes_mfe_month_or_winner_keys_cannot_be_runtime_filters(self):
        for label in ("Net_bps", "future_exit_price", "MFE", "winner_trade_key", "month", "outcome"):
            with self.subTest(label=label):
                snapshot, position = synthetic_case()
                snapshot["diagnostic"] = {label: "forbidden-in-runtime-only"}
                self.assert_rejected(snapshot, position, "OUTCOME_OR_FUTURE_RUNTIME_FIELD_FORBIDDEN")

    def test_missing_certified_full_input_never_becomes_economic_eligible(self):
        snapshot, position = synthetic_case()
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "CONTINUE_INTENT_PENDING_OWNER", result)
        self.assertFalse(result["real_sources_verified"])
        self.assertFalse(result["source_ready"])
        self.assertFalse(result["economic_eligible"])
        self.assertNotIn("economic_command", result)
        self.assert_no_economic_action(result)

    def test_separate_dev_role_needs_bound_seed_and_nonoverlapping_window(self):
        snapshot, position = synthetic_separate_dev_case()
        result = adapter.prepare_extension(snapshot, position, enabled=True)
        self.assertEqual(result["state"], "CONTINUE_INTENT_PENDING_OWNER", result)
        self.assertEqual(result["history_role"], "SEPARATE_DEV")
        self.assert_no_economic_action(result)
        for mutation in ("overlap", "wrong_seed", "missing_contract"):
            with self.subTest(mutation=mutation):
                snapshot, position = synthetic_separate_dev_case()
                receipt = snapshot["source_receipt"]
                if mutation == "overlap":
                    receipt["end_ms"] = BOUNDARY + BAR
                elif mutation == "wrong_seed":
                    receipt["native_prefix_start_ms"] += BAR
                else:
                    del receipt["dev_contract_sha256"]
                snapshot["source_receipt_sha256"] = adapter.digest(receipt)
                self.assert_rejected(snapshot, position)

    def test_preserved_six_cohort_rows_are_exact_original_subset_not_runtime_features(self):
        # Read-only object verification, not a Stage3 evaluator or metric rerun.
        packet = json.loads((HERE / "OBSERVED_COHORT.json").read_bytes())
        blob = "70f5f6829d860a67f7df8e4ff1994965218c042c"
        self.assertEqual(packet["original_git_blob"], blob)
        original_raw = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=ROOT)
        self.assertEqual(hashlib.sha256(original_raw).hexdigest(),
                         "32ef0f850d546dea909094bebdf4e4df0d0b5980a66ec2db912859e7503e4d4d")
        original = json.loads(original_raw)
        original_rows = original["lanes"]["supertrend_pullback_main"]["closed_trades"]
        cohort = packet["rows_copied_without_recalculation"]
        expected = [row for row in original_rows if row["entry_ts"] == 1789992000000]
        self.assertEqual(cohort, expected)
        self.assertEqual(len(cohort), 6)
        self.assertEqual({row["symbol"] for row in cohort},
                         {"1000PEPE-USDT", "BCH-USDT", "BTC-USDT", "ETH-USDT", "HYPE-USDT", "SOL-USDT"})
        # These three reported cost2 losing cohort members must remain present;
        # their economic results are retained as published, not recomputed here.
        preserved_ids = {row["closed_trade_id"] for row in cohort}
        self.assertTrue({
            "ec8579c016316df9a8413f5efd4b217a1517dba09d1798dad1639de3308849f6",
            "988715942d65d150aa7f7199fa2e94620eb479f0e3f05a647c837e67f57fb39b",
            "595af8f47482848c8ebe5f8b966e96f277be98d9ca6f874cedf1a6057e8c38c1",
        }.issubset(preserved_ids))
        self.assertEqual(packet["unchanged_stage3_cohort_result"]["T"], 6)
        self.assertEqual(packet["unchanged_stage3_cohort_result"]["win_count_cost2"], 3)
        self.assertFalse(packet["new_measurement"])
        self.assertIn("NOT_RUNTIME_INPUT_NOT_FRESH", packet["classification"])
        self.assertEqual(tuple(packet["frozen_universe_still_seven"]), SYMBOLS)


if __name__ == "__main__":
    unittest.main()
