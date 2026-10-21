"""Synthetic-only admission tests. Values below are fixtures, never SSOT settings.

No strategy, saved-price chronology, economic comparison or order is executed.
"""
from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("work_d_risk_admission", HERE / "risk_admission.py")
risk_admission = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(risk_admission)
evaluate_batch = risk_admission.evaluate_batch
NOW = 1_000_000


def fixture_contract(total="120", directional="60"):
    return {
        "binding_status": "SYNTHETIC_ONLY",
        "source_ref": "fixture://work_d/test_risk_admission",
        "source_sha256": "f" * 64,
        "quote_currency": "USDT",
        "total_risk_limit_quote": total,
        "directional_risk_limit_quote": {"1": directional, "-1": directional},
        "risk_unit": "quote_currency_stop_distance_plus_reserve",
        "quantity_contract": "EXPLICIT_REQUESTED_QUANTITY",
        "same_time_policy": "STRICTLY_EARLIER_KNOWN_OUTCOMES",
        "max_mark_age_ms": 10_000,
        "available_ts_ms": NOW - 100,
    }


def proposal(request="new-1", symbol="AAA-USDT", side=1, quantity="2"):
    return {
        "request_id": request, "symbol": symbol, "side": side,
        "requested_quantity": quantity,
        "quantity_unit": "BASE_ASSET", "base_units_per_contract": "1",
        "quote_currency": "USDT", "entry_price": "100",
        "entry_available_ts_ms": NOW,
        "stop_price": "90" if side == 1 else "110",
        "stop_available_ts_ms": NOW - 100,
        "stop_effective_ts_ms": NOW - 100,
        "cost_reserve_quote_per_base_unit": "2",
        "cost_available_ts_ms": NOW - 100,
        "quantity_step": "0.1", "minimum_quantity": "0.1",
        "setup_id": "setup:" + request, "reentry_authorized": True,
    }


def position(position_id="open-1", symbol="OLD-USDT", side=1, quantity="1"):
    return {
        "position_id": position_id, "symbol": symbol, "side": side,
        "quantity": quantity,
        "quantity_unit": "BASE_ASSET", "base_units_per_contract": "1",
        "quote_currency": "USDT", "mark_price": "100",
        "mark_available_ts_ms": NOW - 1,
        "stop_price": "90" if side == 1 else "110",
        "stop_available_ts_ms": NOW - 100,
        "stop_effective_ts_ms": NOW - 100,
        "cost_reserve_quote_per_base_unit": "2",
        "cost_available_ts_ms": NOW - 100,
        "setup_id": "setup:" + position_id,
    }


def outcome(position_id="closed-1", available=NOW - 1, net="-25"):
    return {
        "position_id": position_id, "symbol": "AAA-USDT", "side": 1,
        "setup_id": "setup:" + position_id,
        "outcome_available_ts_ms": available,
        "net_quote": net, "quote_currency": "USDT",
    }


def batch(proposals=None, positions=None, outcomes=None):
    return {
        "batch_id": "SYNTHETIC_ONLY:batch-1", "decision_ts_ms": NOW,
        "simultaneous_batch_complete": True,
        "exposure_snapshot_id": "SYNTHETIC_ONLY:snapshot-1",
        "exposure_available_ts_ms": NOW - 1,
        "positions": positions or [],
        "proposals": [proposal()] if proposals is None else proposals,
        "outcomes": outcomes or [],
    }


def by_request(result):
    return {row["request_id"]: row for row in result["allocations"]}


def allocation_values(result):
    return {key: (Decimal(row["admitted_quantity"]), Decimal(row["reserved_risk_quote"]), row["admission"])
            for key, row in by_request(result).items()}


class AdmissionContractTests(unittest.TestCase):
    def run_case(self, value=None, contract=None):
        return evaluate_batch(value or batch(), contract or fixture_contract(), enabled=True)

    def assert_fails_closed(self, value, contract=None):
        try:
            result = self.run_case(value, contract)
        except ValueError:
            return
        self.assertEqual(result["status"], "REQUIRED_INPUT")
        self.assertFalse(result["allocations"])

    def test_disabled_does_not_claim_admission_or_change_inputs(self):
        value = batch()
        before = deepcopy(value)
        result = evaluate_batch(value)
        self.assertEqual(result["status"], "DISABLED")
        self.assertEqual(value, before)

    def test_four_open_losses_are_unknown_and_exposure_is_still_reserved(self):
        symbols = ["ETH-USDT", "SOL-USDT", "LINK-USDT", "XRP-USDT"]
        positions = [position("open-" + str(i), symbol=symbols[i], side=-1) for i in range(4)]
        future = [outcome("open-" + str(i), NOW + 1_000 + i, "-10") for i in range(4)]
        for i, value in enumerate(future):
            value.update(symbol=symbols[i], side=-1)
        result = self.run_case(batch([proposal(side=-1)], positions, future))
        self.assertEqual(result["audit"]["known_outcome_count"], 0)
        self.assertEqual(result["audit"]["known_loss_count"], 0)
        self.assertEqual(result["audit"]["excluded_not_yet_known_outcome_count"], 4)
        self.assertEqual(Decimal(result["audit"]["existing_risk_quote"]), Decimal("48"))
        self.assertEqual(Decimal(result["allocations"][0]["admitted_quantity"]), Decimal("1"))

    def test_earlier_known_loss_is_retained_without_inventing_cooldown(self):
        clean = self.run_case(batch())
        prior_loss = self.run_case(batch(outcomes=[outcome()]))
        self.assertEqual(prior_loss["audit"]["known_outcome_count"], 1)
        self.assertEqual(prior_loss["audit"]["known_loss_count"], 1)
        self.assertEqual(Decimal(prior_loss["audit"]["known_net_quote"]), Decimal("-25"))
        self.assertEqual(allocation_values(clean), allocation_values(prior_loss))

    def test_same_timestamp_mixed_outcomes_are_excluded_atomically(self):
        values = [outcome("loss", NOW, "-20"), outcome("win", NOW, "30")]
        result = self.run_case(batch(outcomes=values))
        self.assertEqual(result["audit"]["known_outcome_count"], 0)
        self.assertEqual(result["audit"]["excluded_not_yet_known_outcome_count"], 2)
        self.assertEqual(Decimal(result["audit"]["known_net_quote"]), Decimal("0"))
        later = batch(outcomes=values)
        later["decision_ts_ms"] += 1
        known = self.run_case(later)
        self.assertEqual(known["audit"]["known_outcome_count"], 2)
        self.assertEqual(known["audit"]["known_loss_count"], 1)
        self.assertEqual(known["audit"]["known_win_count"], 1)
        self.assertEqual(Decimal(known["audit"]["known_net_quote"]), Decimal("10"))
        self.assertEqual(len(known["audit"]["known_outcome_batches"]), 1)

    def test_same_time_signal_permutation_is_symmetric(self):
        proposals = [proposal("one", "ZZZ-USDT"), proposal("two", "AAA-USDT")]
        c = fixture_contract("24", "24")
        first = self.run_case(batch(proposals), c)
        second = self.run_case(batch(list(reversed(proposals))), c)
        self.assertEqual(allocation_values(first), allocation_values(second))
        self.assertEqual({v[0] for v in allocation_values(first).values()}, {Decimal("1")})

    def test_total_and_side_limits_hold_with_opposite_direction_signals(self):
        proposals = [proposal("long", side=1), proposal("short", side=-1)]
        result = self.run_case(batch(proposals), fixture_contract("24", "60"))
        self.assertEqual({v[0] for v in allocation_values(result).values()}, {Decimal("1")})
        self.assertEqual(sum(v[1] for v in allocation_values(result).values()), Decimal("24"))

    def test_existing_and_pending_exposure_consume_budget_once(self):
        positions = [position("open-1", quantity="2"), position("pending-reservation-2", quantity="2")]
        result = self.run_case(batch(positions=positions))
        self.assertEqual(Decimal(result["audit"]["existing_risk_quote"]), Decimal("48"))
        self.assertEqual(Decimal(result["allocations"][0]["admitted_quantity"]), Decimal("1"))
        duplicated = batch(positions=positions + [deepcopy(positions[0])])
        self.assert_fails_closed(duplicated)

    def test_future_or_same_time_stop_update_cannot_release_risk(self):
        old = position(quantity="4")
        control = self.run_case(batch(positions=[old]))
        for available, effective in [(NOW + 1, NOW + 1), (NOW, NOW), (NOW - 1, NOW + 1)]:
            with self.subTest(available=available, effective=effective):
                updated = deepcopy(old)
                updated["stop_updates"] = [{"stop_price": "99", "available_ts_ms": available, "effective_ts_ms": effective}]
                result = self.run_case(batch(positions=[updated]))
                self.assertEqual(allocation_values(result), allocation_values(control))
                self.assertEqual(Decimal(result["audit"]["existing_risk_quote"]), Decimal("48"))

    def test_available_effective_stop_update_releases_only_current_remaining_risk(self):
        old = position(quantity="4")
        old["stop_updates"] = [{"stop_price": "99", "available_ts_ms": NOW - 2, "effective_ts_ms": NOW - 1}]
        result = self.run_case(batch(positions=[old]))
        self.assertEqual(Decimal(result["audit"]["existing_risk_quote"]), Decimal("12"))
        self.assertEqual(Decimal(result["allocations"][0]["admitted_quantity"]), Decimal("2"))

    def test_contract_quantity_conversion_matches_base_asset_risk(self):
        base = self.run_case(batch())
        self.assertEqual(Decimal(base["allocations"][0]["reserved_risk_quote"]), Decimal("24"))
        converted = proposal()
        converted.update(quantity_unit="CONTRACTS", base_units_per_contract="0.1", requested_quantity="20", quantity_step="1", minimum_quantity="1")
        result = self.run_case(batch([converted]))
        self.assertEqual(Decimal(result["allocations"][0]["admitted_quantity"]), Decimal("20"))
        self.assertEqual(Decimal(result["allocations"][0]["reserved_risk_quote"]), Decimal(base["allocations"][0]["reserved_risk_quote"]))

    def test_unit_mismatch_and_unbound_bps_cost_fail_closed(self):
        for field, value in [("quote_currency", "USD"), ("quantity_unit", "quote_notional"), ("base_units_per_contract", "2")]:
            with self.subTest(field=field):
                bad = proposal()
                bad[field] = value
                self.assert_fails_closed(batch([bad]))
        bad = proposal()
        del bad["cost_reserve_quote_per_base_unit"]
        bad["cost_bps"] = "20"
        self.assert_fails_closed(batch([bad]))

    def test_future_winner_or_loser_labels_do_not_select_cluster_members(self):
        proposals = [proposal("one", "ZZZ-USDT"), proposal("two", "AAA-USDT")]
        wins = batch(proposals, outcomes=[outcome("future-one", NOW + 1, "1000"), outcome("future-two", NOW + 1, "1000")])
        losses = deepcopy(wins)
        for row in losses["outcomes"]:
            row["net_quote"] = "-1000"
        c = fixture_contract("24", "24")
        self.assertEqual(allocation_values(self.run_case(wins, c)), allocation_values(self.run_case(losses, c)))

    def test_missing_budget_setup_or_incomplete_batch_has_no_allocations(self):
        value = batch()
        result = evaluate_batch(value, enabled=True)
        self.assertEqual(result["status"], "REQUIRED_INPUT")
        self.assertFalse(result["allocations"])
        missing_setup = batch()
        del missing_setup["proposals"][0]["setup_id"]
        self.assert_fails_closed(missing_setup)
        incomplete = batch()
        incomplete["simultaneous_batch_complete"] = False
        self.assert_fails_closed(incomplete)
        missing_limit = fixture_contract()
        del missing_limit["directional_risk_limit_quote"]
        self.assert_fails_closed(batch(), missing_limit)

    def test_restart_exact_replay_idempotent_and_changed_input_rejected(self):
        value, contract = batch(), fixture_contract()
        receipt = self.run_case(value, contract)
        repeated = evaluate_batch(deepcopy(value), deepcopy(contract), enabled=True, receipt=deepcopy(receipt))
        self.assertEqual(receipt, repeated)
        changed = deepcopy(value)
        changed["proposals"][0]["requested_quantity"] = "3"
        with self.assertRaisesRegex(ValueError, "CONFLICTING_BATCH_REPLAY"):
            evaluate_batch(changed, contract, enabled=True, receipt=receipt)

    def test_restart_receipt_mutated_allocation_or_audit_fails_integrity(self):
        value, contract = batch(), fixture_contract()
        receipt = self.run_case(value, contract)
        for field in ("allocation", "audit"):
            with self.subTest(field=field):
                changed = deepcopy(receipt)
                if field == "allocation":
                    changed["allocations"][0]["admitted_quantity"] = "999"
                else:
                    changed["audit"]["known_net_quote"] = "999"
                with self.assertRaisesRegex(ValueError, "INTEGRITY"):
                    evaluate_batch(value, contract, enabled=True, receipt=changed)

    def test_restart_receipt_without_output_digest_fails_integrity(self):
        value, contract = batch(), fixture_contract()
        receipt = self.run_case(value, contract)
        self.assertIn("output_receipt_sha256", receipt)
        del receipt["output_receipt_sha256"]
        with self.assertRaisesRegex(ValueError, "INTEGRITY"):
            evaluate_batch(value, contract, enabled=True, receipt=receipt)

    def test_same_setup_reentry_needs_explicit_permission_not_symbol_proxy(self):
        old = outcome("prior", NOW - 1, "-25")
        request = proposal()
        request["setup_id"] = old["setup_id"]
        request["reentry_authorized"] = False
        blocked = self.run_case(batch([request], outcomes=[old]))
        self.assertEqual(blocked["allocations"][0]["admission"], "BLOCK")
        request["reentry_authorized"] = True
        permitted = self.run_case(batch([request], outcomes=[old]))
        self.assertEqual(Decimal(permitted["allocations"][0]["admitted_quantity"]), Decimal("2"))
        request["setup_id"] = "different-canonical-setup"
        request["reentry_authorized"] = False
        new_setup = self.run_case(batch([request], outcomes=[old]))
        self.assertEqual(Decimal(new_setup["allocations"][0]["admitted_quantity"]), Decimal("2"))

    def test_open_same_setup_cannot_receive_second_risk_reservation(self):
        old = position()
        request = proposal(symbol=old["symbol"])
        request["setup_id"] = old["setup_id"]
        result = self.run_case(batch([request], [old]))
        self.assertEqual(result["allocations"][0]["admission"], "BLOCK")
        self.assertEqual(Decimal(result["allocations"][0]["reserved_risk_quote"]), Decimal("0"))

    def test_nan_negative_boolean_or_stale_inputs_fail_closed(self):
        for field, value in [("requested_quantity", "NaN"), ("requested_quantity", "-1"), ("requested_quantity", True), ("cost_reserve_quote_per_base_unit", "-1")]:
            with self.subTest(field=field, value=value):
                bad = proposal()
                bad[field] = value
                self.assert_fails_closed(batch([bad]))
        bad_contract = fixture_contract(total="-1")
        self.assert_fails_closed(batch(), bad_contract)
        stale = position()
        stale["mark_available_ts_ms"] = NOW - 10_001
        self.assert_fails_closed(batch(positions=[stale]))

    def test_floor_rounding_does_not_exceed_budget_or_favor_first_symbol(self):
        proposals = [proposal("one", "ZZZ-USDT"), proposal("two", "AAA-USDT")]
        for value in proposals:
            value.update(quantity_step="0.3", minimum_quantity="0.3")
        c = fixture_contract("20", "20")
        result = self.run_case(batch(proposals), c)
        reversed_result = self.run_case(batch(list(reversed(proposals))), c)
        self.assertEqual(allocation_values(result), allocation_values(reversed_result))
        allocations = allocation_values(result)
        self.assertEqual({v[0] for v in allocations.values()}, {Decimal("0.6")})
        self.assertLessEqual(sum(v[1] for v in allocations.values()), Decimal("20"))


if __name__ == "__main__":
    unittest.main()
