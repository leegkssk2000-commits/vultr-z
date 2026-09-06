"""Synthetic clock, fill/accounting, boundary and restart proofs for M."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch

from backend.research.rebuild import keltner_opportunity_reservation_adapter_v1 as m
from backend.research.rebuild import keltner_cumulative_entry_adapter_v1 as n
from backend.research.rebuild import parallel_exit_keltner_v1 as d
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle


def replay(rows, b, **kwargs):
    return m.replay(rows, b, eval_start_ms=0,
                    eval_end_ms=rows[-1]["bar_close_ts"], **kwargs)


def clock(rows, b, **kwargs):
    return m.causal_clock(rows, b, eval_start_ms=0,
                          eval_end_ms=rows[-1]["bar_close_ts"], **kwargs)


class KeltnerOpportunityReservationTests(unittest.TestCase):
    def test_rejected_opportunity_blocks_replacement_restores_following_D_origin(self):
        rows = bars(45); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 12, 13, 14, 18, 27, 30, 42])
        actual = replay(rows, b)
        prior_n = n.replay(rows, b, eval_start_ms=0, eval_end_ms=45 * d.BAR)
        self.assertEqual([t["signal_index"] for t in prior_n["trades"]], [3, 18])
        self.assertEqual([t["signal_index"] for t in actual["trades"]], [13, 27])
        self.assertEqual([t["signal_index"] for t in actual["open_positions"]], [42])
        events = {e["signal_index"]: e for e in actual["events"]}
        self.assertEqual(events[0]["exclusion_reason"], n.VETO_REASON)
        self.assertTrue(events[0]["reservation_created"])
        self.assertEqual(events[3]["exclusion_reason"], m.REFERENCE_VETO_REASON)
        self.assertEqual(events[3]["blocking_reference_signal_index"], 0)
        self.assertFalse(events[3]["blocking_reference_model_selected"])
        self.assertEqual(events[12]["exclusion_reason"], m.EXIT_BAR_VETO_REASON)
        self.assertEqual(events[18]["blocking_reference_signal_index"], 13)
        self.assertEqual(actual["audit"]["reference_reservation_count"], 4)

    def test_reference_releases_without_an_actual_position(self):
        rows = bars(30); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 4, 13])
        result = replay(rows, b)
        first = result["reference_opportunities"][0]
        self.assertFalse(first["model_selected"])
        self.assertEqual(first["release_reason"], "ORIGINAL_TIME_STOP_CLOSE")
        self.assertEqual((first["release_index"], first["release_ts"]), (12, 13 * d.BAR))
        self.assertEqual([t["signal_index"] for t in result["trades"]], [13])

    def test_ema_release_is_decided_at_close_and_executed_next_open_only(self):
        rows = bars(30); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 5, 6, 7]); b["ema20"][5] = 100.0
        before = clock(rows, b, stop_after_index=4)
        self.assertIsNone(before["reference_opportunities"][0]["release_index"])
        self.assertIsNone(before["reference_opportunities"][0]["pending_exit_signal_index"])
        trigger = clock(rows, b, stop_after_index=5)
        active = trigger["reference_opportunities"][0]
        self.assertEqual(active["phase"], "PENDING_EMA_EXIT_NEXT_OPEN")
        self.assertIsNone(active["release_index"])
        self.assertEqual(active["pending_exit_signal_ts"], 6 * d.BAR)
        released = clock(rows, b, stop_after_index=6)
        active = released["reference_opportunities"][0]
        self.assertEqual((active["release_index"], active["release_ts"]), (6, 6 * d.BAR))
        self.assertEqual(released["opportunity_events"][-1]["exclusion_reason"], m.EXIT_BAR_VETO_REASON)
        result = replay(rows, b)
        self.assertEqual([t["signal_index"] for t in result["trades"]], [7])

    def test_signal_bar_itself_cannot_invalidate_a_not_yet_entered_reference(self):
        rows = bars(20); b = bundle(rows, [0]); b["ema20"][0] = 99.0
        result = replay(rows, b)
        self.assertEqual(result["reference_opportunities"][0]["release_index"], 12)
        self.assertEqual(result["trades"][0]["exit_index"], 12)

    def test_timeout_precedes_same_close_ema_and_owns_exit_bar(self):
        rows = bars(30); b = bundle(rows, [0, 12, 13]); b["ema20"][12] = 99.0
        result = replay(rows, b)
        self.assertEqual(result["reference_opportunities"][0]["release_reason"],
                         "ORIGINAL_TIME_STOP_CLOSE")
        self.assertFalse(any(e["kind"] == "REFERENCE_EMA_INVALIDATION_CLOSE"
                             for e in result["reference_events"]))
        self.assertEqual([t["signal_index"] for t in result["trades"]], [0, 13])
        self.assertEqual(result["events"][1]["exclusion_reason"], m.EXIT_BAR_VETO_REASON)

    def test_previous_close_trigger_exits_at_timeout_bar_open(self):
        rows = bars(20); b = bundle(rows, [0, 12, 13]); b["ema20"][11] = 99.0
        result = replay(rows, b)
        first = result["reference_opportunities"][0]
        self.assertEqual((first["release_index"], first["release_ts"]), (12, 12 * d.BAR))
        self.assertEqual(first["release_reason"], "EMA20_NOT_ABOVE_EMA50_NEXT_OPEN")
        self.assertEqual(result["events"][1]["exclusion_reason"], m.EXIT_BAR_VETO_REASON)

    def test_strict_terminal_timeout_keeps_reference_and_actual_open(self):
        rows = bars(13); b = bundle(rows, [0]); b["ema20"][-1] = 99.0
        result = replay(rows, b)
        reference = result["reference_opportunities"][0]
        self.assertIsNone(reference["release_ts"])
        self.assertTrue(reference["strict_end_timeout_pending"])
        self.assertIsNone(reference["pending_exit_signal_ts"])
        self.assertEqual(result["trades"], [])
        self.assertEqual(len(result["open_positions"]), 1)
        self.assertFalse(result["open_positions"][0]["terminal_liquidation"])
        self.assertEqual(result["open_positions"][0]["censor_reason"],
                         "ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY")

    def test_pending_terminal_ema_does_not_invent_next_open_or_money(self):
        for selected in (True, False):
            rows = bars(6)
            if not selected:
                rows[0]["close"] = 99.0
            b = bundle(rows, [0, 3]); b["ema20"][-1] = 100.0
            result = replay(rows, b)
            reference = result["reference_opportunities"][0]
            self.assertEqual(reference["phase"], "PENDING_EMA_EXIT_NEXT_OPEN")
            self.assertEqual(reference["pending_exit_signal_ts"], 6 * d.BAR)
            self.assertIsNone(reference["release_ts"])
            self.assertEqual(result["trades"], [])
            self.assertEqual(len(result["open_positions"]), int(selected))
            self.assertEqual(result["audit"]["reference_open_count"], 1)
            self.assertEqual(result["audit"]["modeled_entry_count"], int(selected))

    def test_midpoint_tie_uses_unchanged_N_primitive(self):
        for value, expected in ((99.0, False), (100.0, True), (101.0, True)):
            rows = bars(20); rows[0]["close"] = value
            result = replay(rows, bundle(rows, [0]))
            self.assertEqual(result["events"][0]["admission"], expected)
            self.assertEqual(result["audit"]["reference_reservation_count"], 1)
            self.assertEqual(result["events"][0]["entry_observation"], n.entry_observation(rows[0]))

    def test_original_raw_denominator_and_exclusion_partition(self):
        rows = bars(30); rows[0]["close"] = 99.0; rows[3]["close"] = 99.0
        b = bundle(rows, [0, 3, 4, 12, 13, 18, 26])
        result = replay(rows, b); audit = result["audit"]
        self.assertEqual(audit["raw_signals"], 7)
        self.assertEqual(audit["original_signal_count"], 7)
        self.assertEqual(audit["raw_below_half_signal_count"], 2)
        self.assertEqual(audit["entry_veto_count"], 1)
        self.assertEqual(audit["reference_reservation_count"], 3)
        self.assertEqual(audit["completed"] + audit["open"] + audit["excluded"], 7)
        self.assertEqual(audit["entry_veto_count"] + audit["reference_occupancy_exclusion_count"]
                         + audit["reference_exit_bar_exclusion_count"], audit["excluded"])

    def test_disabled_is_entire_raw_N_including_cost_input_tail_and_denominators(self):
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16, 35]); b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        expected = n.replay(rows, b, eval_start_ms=0, eval_end_ms=43 * d.BAR)
        actual = replay(rows, b, enabled=False)
        self.assertEqual(actual, expected)
        from backend.research.rebuild import parallel_exit_dev_v1 as accounting
        from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy
        p = policy(); p["development_interval_ms"] = [0, 43 * d.BAR]
        self.assertEqual(accounting.charge_result(actual, "TEST", d.LANE, "CHECK", p, COSTS, rows),
                         accounting.charge_result(expected, "TEST", d.LANE, "CHECK", p, COSTS, rows))

    def test_reference_never_adds_trade_fee_funding_or_exposure(self):
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16, 35]); b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        actual = replay(rows, b)
        from backend.research.rebuild import parallel_exit_dev_v1 as accounting
        from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy
        p = policy(); p["development_interval_ms"] = [0, 43 * d.BAR]
        charged = accounting.charge_result(actual, "TEST", d.LANE, "CHECK", p, COSTS, rows)
        check_only = d.replay(rows, b, eval_start_ms=0, eval_end_ms=43 * d.BAR,
                              fixed_signal_indices=[16, 35])
        expected = accounting.charge_result(check_only, "TEST", d.LANE, "CHECK", p, COSTS, rows)
        self.assertEqual(charged["trades"], expected["trades"])
        self.assertEqual(charged["open_observations"], expected["open_observations"])
        stage = accounting.metrics.build_stage(charged["trades"], charged["open_observations"],
                                                charged["events"], {"TEST": rows}, COSTS, p,
                                                ["TEST"], 0, 43 * d.BAR)
        expected_stage = accounting.metrics.build_stage(expected["trades"], expected["open_observations"],
                                                         expected["events"], {"TEST": rows}, COSTS, p,
                                                         ["TEST"], 0, 43 * d.BAR)
        self.assertEqual(stage["daily"], expected_stage["daily"])
        self.assertEqual(stage["metrics"]["total_exposure_symbol_days"],
                         expected_stage["metrics"]["total_exposure_symbol_days"])
        self.assertEqual(actual["audit"]["reference_reservation_count"], 3)
        self.assertEqual(actual["audit"]["modeled_entry_count"], 2)
        for key in ("reference_virtual_quantity", "reference_virtual_notional",
                    "reference_virtual_trade_count", "reference_virtual_fee_bps",
                    "reference_virtual_funding_bps", "reference_virtual_exposure_ms"):
            self.assertEqual(actual["audit"][key], 0)

    def test_clock_is_independent_of_batch_path_and_historical_D_outputs(self):
        rows = bars(30); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 13])
        with patch.object(d, "_path", side_effect=AssertionError("FUTURE_PATH_READ")):
            result = clock(rows, b)
        self.assertEqual(result["admitted_signal_indices"], [13])
        self.assertEqual(result["reference_opportunities"][0]["release_index"], 12)
        # Neither a historical ID nor an injected exit index is accepted as a
        # signal attribute by the direct streaming gate.
        poisoned = deepcopy(b); poisoned["signals"][0]["exit_index"] = 1
        with self.assertRaisesRegex(RuntimeError, "REFERENCE_SIGNAL_INVALID_OR_FUTURE"):
            clock(rows, poisoned)

    def test_checkpoint_resume_and_whole_input_reprocessing_are_idempotent(self):
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 7, 16, 35]); b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        expected = clock(rows, b)
        for end_index in (0, 1, 4, 5, 6, 16, 42):
            with self.subTest(index=end_index):
                prefix = clock(rows, b, stop_after_index=end_index)
                checkpoint = json.loads(json.dumps(prefix))
                resumed = clock(rows, b, checkpoint=checkpoint)
                self.assertEqual(resumed, expected)
                self.assertEqual(checkpoint, prefix)
                self.assertEqual(clock(rows, b, checkpoint=resumed), expected)
                self.assertEqual(len(set(resumed["modeled_entry_signal_indices"])),
                                 len(resumed["modeled_entry_signal_indices"]))

    def test_checkpoint_resume_produces_identical_full_actual_M_ledger(self):
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 7, 16, 35]); b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        expected = replay(rows, b)
        stopped = json.loads(json.dumps(clock(rows, b, stop_after_index=5)))
        resumed = replay(rows, b, reference_checkpoint=stopped)
        self.assertEqual(resumed, expected)
        self.assertEqual(replay(rows, b, reference_checkpoint=resumed["reference_checkpoint"]), expected)
        self.assertEqual(len({t["signal_index"] for t in resumed["trades"]}), len(resumed["trades"]))

    def test_new_runner_cost_stage_and_reference_field_integration(self):
        from backend.research.rebuild import keltner_opportunity_reservation_v1 as runner
        from backend.research.rebuild.test_break_channel_source_v1 import COSTS, policy
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 16, 35]); b["ema20"][5] = 100.0; b["ema20"][-1] = 100.0
        p = policy(); p["development_interval_ms"] = [0, 43 * d.BAR]
        values, features = {"TEST": rows}, {"TEST": b}
        actual = runner.replay(values, features, COSTS, p, 0, 43 * d.BAR)
        disabled = runner.replay(values, features, COSTS, p, 0, 43 * d.BAR, enabled=False)
        expected_N = runner.prior.replay(values, features, COSTS, p, 0, 43 * d.BAR, "N_FULL")
        runner.prior.assert_D_parity(disabled, expected_N)
        self.assertEqual(actual["admission"]["TEST"]["reference_reservation_count"], 3)
        self.assertEqual([t["signal_index"] for t in actual["trades"]], [16])
        self.assertEqual(actual["trades"][0]["candidate_id"], m.RULE_ID)
        self.assertEqual(actual["trades"][0]["evidence_type"], "REUSED_DEV_CAUSAL_RESERVATION")
        self.assertEqual([t["signal_index"] for t in actual["open_observations"]], [35])
        self.assertTrue(all(e["symbol"] == "TEST" for e in actual["reference_events"]))
        self.assertEqual(actual["reference_states"]["TEST"]["modeled_entry_signal_indices"], [16, 35])
        check_only = runner.prior.replay(values, features, COSTS, p, 0, 43 * d.BAR,
                                        "N_COMMON_D", common={"TEST": [0, 16, 35]})
        self.assertEqual(runner.comparison_only_common_parity(actual, check_only)["status"], "MATCH")
        stage = runner.prior.previous.metrics.build_stage(actual["trades"], actual["open_observations"],
            actual["events"], values, COSTS, p, ["TEST"], 0, 43 * d.BAR)
        check_stage = runner.prior.previous.metrics.build_stage(check_only["trades"], check_only["open_observations"],
            check_only["events"], values, COSTS, p, ["TEST"], 0, 43 * d.BAR)
        self.assertEqual(stage["daily"], check_stage["daily"])
        self.assertEqual(stage["metrics"]["total_exposure_symbol_days"],
                         check_stage["metrics"]["total_exposure_symbol_days"])

    def test_changed_duplicate_gap_and_checkpoint_calendar_fail_closed(self):
        rows = bars(20); b = bundle(rows, [0, 3, 13])
        prefix = clock(rows, b, stop_after_index=4)
        corrupted = deepcopy(rows); corrupted[2]["close"] = 99.5
        with self.assertRaisesRegex(RuntimeError, "REPROCESSED_INPUT_CHANGED"):
            clock(corrupted, b, checkpoint=prefix)
        fresh = m.initial_clock(eval_start_ms=0, eval_end_ms=20 * d.BAR)
        with self.assertRaisesRegex(RuntimeError, "INDEX_GAP_OR_ORDER"):
            m.advance_clock(fresh, rows[1], index=1, ema20=101.0, ema50=100.0)
        self.assertEqual(fresh["last_index"], -1)
        bad = deepcopy(prefix); bad["eval_end_ms"] += d.BAR
        with self.assertRaisesRegex(RuntimeError, "CHECKPOINT_CALENDAR_OR_LENGTH"):
            clock(rows, b, checkpoint=bad)

    def test_cross_symbol_reservations_have_no_shared_state(self):
        rows_a, rows_b = bars(30), bars(30)
        rows_a[0]["close"] = 99.0
        b_a, b_b = bundle(rows_a, [0, 3, 13]), bundle(rows_b, [3, 16])
        independent_b = replay(rows_b, b_b)
        first_a = replay(rows_a, b_a)
        self.assertEqual(replay(rows_b, b_b), independent_b)
        self.assertEqual(replay(rows_a, b_a), first_a)
        self.assertEqual([t["signal_index"] for t in independent_b["trades"]], [3, 16])

    def test_future_suffix_cannot_change_prior_reservations_admissions_or_entries(self):
        rows = bars(43); rows[0]["close"] = 99.0
        b = bundle(rows, [0, 3, 7, 16, 25, 35]); b["ema20"][5] = 100.0
        other_rows, other_b = deepcopy(rows), deepcopy(b)
        for i in range(20, len(rows)):
            other_rows[i].update(open=200.0, high=203.0, low=197.0, close=199.0)
            other_b["ema20"][i] = 99.0
        a, c = clock(rows, b, stop_after_index=19), clock(other_rows, other_b, stop_after_index=19)
        self.assertEqual(a, c)
        aa, cc = replay(rows, b), replay(other_rows, other_b)
        cutoff = rows[19]["bar_close_ts"]
        self.assertEqual([e for e in aa["reference_events"] if e["ts"] <= cutoff],
                         [e for e in cc["reference_events"] if e["ts"] <= cutoff])
        self.assertEqual([e for e in aa["reference_checkpoint"]["opportunity_events"]
                          if e["signal_ts"] <= cutoff],
                         [e for e in cc["reference_checkpoint"]["opportunity_events"]
                          if e["signal_ts"] <= cutoff])

    def test_real_original_signal_and_clock_prefix_invariance(self):
        rows = bars(310)
        for i, row in enumerate(rows):
            px = 100.0 + 8.0 * math.sin(i / 7.0) + i / 100.0
            row.update(open=px, close=px, high=px + 1.5, low=px - 1.0)
        full = m.build_bundle(rows, d.PARENT_SPEC, eval_start_ms=0, eval_end_ms=310 * d.BAR)
        short = m.build_bundle(rows[:280], d.PARENT_SPEC, eval_start_ms=0, eval_end_ms=280 * d.BAR)
        self.assertEqual(short["signals"], [s for s in full["signals"] if s["signal_ts"] < 280 * d.BAR])
        a, c = clock(rows, full), clock(rows[:280], short)
        cutoff = 279 * d.BAR
        self.assertEqual([e for e in a["reference_events"] if e["ts"] < cutoff],
                         [e for e in c["reference_events"] if e["ts"] < cutoff])
        self.assertEqual([e for e in a["opportunity_events"] if e["signal_ts"] < cutoff],
                         [e for e in c["opportunity_events"] if e["signal_ts"] < cutoff])

    def test_fresh_flat_start_and_final_signal_boundary_unchanged(self):
        rows = bars(30); b = bundle(rows, [9, 20])
        result = m.replay(rows, b, eval_start_ms=10 * d.BAR, eval_end_ms=30 * d.BAR)
        self.assertEqual(result["trades"][0]["entry_ts"], 10 * d.BAR)
        self.assertEqual(result["reference_opportunities"][0]["reference_signal_index"], 9)
        for bad in ([8, 9], [9, 29]):
            with self.assertRaisesRegex(RuntimeError, "SIGNAL_INVALID_OR_FUTURE"):
                m.replay(rows, bundle(rows, bad), eval_start_ms=10 * d.BAR, eval_end_ms=30 * d.BAR)

    def test_missing_duplicate_reversed_timestamps_and_future_rows_fail_closed(self):
        rows = bars(20)
        for changed in (rows[:4] + rows[5:], rows[:5] + [rows[4]] + rows[5:],
                        rows[:4] + [rows[5], rows[4]] + rows[6:]):
            with self.assertRaisesRegex(RuntimeError, "GAP_DUPLICATE_OR_ORDER"):
                replay(changed, bundle(changed, [0]))
        with self.assertRaisesRegex(RuntimeError, "PARTITION_ROW_FORBIDDEN"):
            m.replay(rows, bundle(rows, [0]), eval_start_ms=0, eval_end_ms=19 * d.BAR)

    def test_nonfinite_and_bad_OHLC_stream_inputs_fail_before_state_change(self):
        for key, value in (("close", None), ("high", math.inf), ("open", 103.0),
                           ("volume", -1), ("bar_close_ts", d.BAR + 1)):
            state = m.initial_clock(eval_start_ms=0, eval_end_ms=20 * d.BAR)
            before = deepcopy(state); row = bars(1)[0]; row[key] = value
            with self.assertRaises(RuntimeError):
                m.advance_clock(state, row, index=0, ema20=101.0, ema50=100.0,
                                 signal={"signal_index": 0, "signal_ts": d.BAR})
            self.assertEqual(state, before)

    def test_unmodified_input_and_boolean_switch(self):
        rows = bars(20); b = bundle(rows, [0, 3, 13]); before = deepcopy((rows, b))
        replay(rows, b)
        self.assertEqual((rows, b), before)
        with self.assertRaisesRegex(RuntimeError, "ENABLE_BOOL_REQUIRED"):
            replay(rows, b, enabled=1)


if __name__ == "__main__":
    unittest.main()
