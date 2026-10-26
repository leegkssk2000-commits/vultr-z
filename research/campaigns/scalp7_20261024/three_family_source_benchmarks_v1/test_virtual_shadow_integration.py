"""Deterministic native-signal -> actual-clock quote -> durable virtual ledger tests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

import rr_orderless_observer as r
import virtual_shadow_ledger as ledger

ANCHOR = r.FOUR * 100


def event(rule=r.TSMOM, *, symbol="BTC-USDT", decision=None):
    decision = ANCHOR + 10 if decision is None else decision
    row = {"symbol": symbol, "decision_ts_ms": decision}
    if rule == r.K117:
        row.update(status="SIGNAL", close_ts_ms=ANCHOR, signal={"side": 1, "stop_price": 99})
    else:
        row.update(rule_id=rule, state="SIGNAL_ONLY_NO_ORDER_NO_FILL", closed_native_4h_ts_ms=ANCHOR,
                   native_safety_stop_distance_price=1, native_signal_close_reference_price=100)
    return row


def sources(rows):
    a = {"order_calls": 0, "virtual_fills": 0, "formal_shadow": False, "signals": [], "decisions": []}
    b = {"order_calls": 0, "virtual_fills": 0, "signals": [], "decisions": []}
    for row in rows:
        (b if row.get("status") == "SIGNAL" else a)["signals"].append(row)
    return a, b


def quote(ts, *, bid=100., ask=100., read=None):
    return {"state": "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL", "best_bid": bid, "best_ask": ask,
            "source_bucket_start_ms": ts - 5, "source_quote_ts_ms": ts, "observed_at_ms": ts + 2 if read is None else read,
            "source_quote_clock_kind": "BUCKET_END", "source_quote_received_at_ms": None,
            "source_quote_sha256": r.digest({"ts": ts, "bid": bid, "ask": ask})}


def reader(q):
    return lambda *a, **kw: q if kw["decision_ts_ms"] < q["source_bucket_start_ms"] else {"state": "HOLD_NO_POST_DECISION_QUOTE"}


class VirtualIntegration(unittest.TestCase):
    def test_ready_requires_living_producer_and_current_poll_contract(self):
        state={"pid":os.getpid(),"updated_at_ms":ANCHOR,"producer_poll_seconds":60}
        self.assertTrue(r.producer_alive(state,ANCHOR+1000))
        self.assertFalse(r.producer_alive(state,ANCHOR+136000))
        self.assertFalse(r.producer_alive({**state,"pid":0},ANCHOR))
        self.assertFalse(r.producer_alive({**state,"stopped":True},ANCHOR))

    def test_unsupported_k117_short_gets_durable_rejection_ack(self):
        row=event(r.K117);row["signal"]["side"]=-1
        state=r.new_state(ANCHOR)
        r.poll_once(state,*sources([row]),ANCHOR+22,quote_reader=lambda *a,**k:self.fail("short quote"))
        self.assertEqual(state["virtual_entry_T"],0)
        self.assertFalse(state["admission_acks"][0]["accepted"])
        self.assertEqual(state["admission_acks"][0]["reason"],"UNSUPPORTED_K117_SIDE_LONG_ONLY")

    def test_known_quote_stop_precedes_new_completed_bar_censor(self):
        state,src=self.opened()
        src[0]["decisions"]=[{"symbol":"BTC-USDT","rule_id":r.TSMOM,"closed_native_4h_ts_ms":ANCHOR+r.FOUR}]
        def wrong_priority(*a,**k):self.fail("already witnessed stop must close before native ambiguity")
        r.poll_once(state,*src,ANCHOR+42,quote_reader=reader(quote(ANCHOR+40,bid=98.,ask=98.1)),native_exit_fn=wrong_priority)
        self.assertEqual(state["virtual_closed_T"],1)
        self.assertEqual(state["virtual_censored_T"],0)

    def opened(self, rule=r.TSMOM):
        state = r.new_state(ANCHOR)
        src = sources([event(rule)])
        r.poll_once(state, *src, ANCHOR+22, quote_reader=reader(quote(ANCHOR+20)))
        self.assertEqual(state["virtual_entry_T"], 1)
        self.assertEqual(state["virtual_open_T"], 1)
        return state, src

    def test_three_native_types_enter_close_restart_exact_once(self):
        for rule in r.RULES:
            with self.subTest(rule=rule), tempfile.TemporaryDirectory() as td:
                state, src = self.opened(rule)
                with ledger.Store(Path(td)/"VIRTUAL_LEDGER.sqlite3") as store:
                    r.persist(Path(td), state, store)
                with ledger.Store(Path(td)/"VIRTUAL_LEDGER.sqlite3") as store:
                    state = r.resume_state(store.load(), ANCHOR+25)
                    r.poll_once(state, *src, ANCHOR+42, quote_reader=reader(quote(ANCHOR+40, bid=98.9, ask=99.)))
                    r.persist(Path(td), state, store)
                    self.assertEqual(state["virtual_entry_T"], 1)
                    self.assertEqual(state["virtual_closed_T"], 1)
                    self.assertEqual(state["runner_closed_T"], 1)
                    self.assertAlmostEqual(state["virtual_net_trade_bps_sum"], -150)
                    self.assertAlmostEqual(state["virtual_net_R_sum"], -1.5)
                    self.assertEqual(state["virtual_entries"][0]["virtual_entry_observed_at_ms"], ANCHOR+22)
                    r.poll_once(state, *src, ANCHOR+52, quote_reader=reader(quote(ANCHOR+50)))
                    self.assertEqual(state["virtual_entry_T"], 1)

    def test_restart_accepts_unconsumed_signal_before_new_process_start(self):
        state = r.resume_state(r.new_state(ANCHOR), ANCHOR+15)
        r.poll_once(state, *sources([event()]), ANCHOR+22, quote_reader=reader(quote(ANCHOR+20)))
        self.assertEqual(state["virtual_entry_T"], 1)

    def test_same_symbol_three_rules_have_one_shared_entry(self):
        state = r.new_state(ANCHOR)
        r.poll_once(state, *sources([event(x) for x in r.RULES]), ANCHOR+22, quote_reader=reader(quote(ANCHOR+20)))
        self.assertEqual(state["virtual_entry_T"], 1)
        self.assertEqual(len(state["blocked"]), 2)
        self.assertEqual(state["symbol_exposure_open_T"], 1)

    def test_runner_floor_is_separate_from_native(self):
        state, src = self.opened()
        r.poll_once(state, *src, ANCHOR+42, quote_reader=reader(quote(ANCHOR+40, bid=102.2, ask=102.3)))
        self.assertEqual(state["runner_closed_T"], 0)
        r.poll_once(state, *src, ANCHOR+62, quote_reader=reader(quote(ANCHOR+60, bid=100.4, ask=100.5)))
        self.assertEqual(state["runner_closed_T"], 1)
        self.assertEqual(state["virtual_closed_T"], 0)
        self.assertEqual(state["virtual_open_T"], 1)
        self.assertAlmostEqual(state["runner_net_trade_bps_sum"], 0)

    def test_native_exit_waits_for_decision_later_bucket_and_read(self):
        state, src = self.opened()
        for item in state["positions"]["BTC-USDT"]["tracks"].values():
            item["native_pending"]["exit_event"] = {"decision_ts_ms": ANCHOR+100, "reason": "NATIVE_CLOSE"}
        r.poll_once(state, *src, ANCHOR+102, quote_reader=reader(quote(ANCHOR+101)))
        self.assertEqual(state["virtual_closed_T"], 0)
        r.poll_once(state, *src, ANCHOR+122, quote_reader=reader(quote(ANCHOR+120, bid=101, ask=101.1)))
        self.assertEqual(state["virtual_closed_T"], 1)
        self.assertEqual(state["virtual_exits"][0]["virtual_exit_observed_at_ms"], ANCHOR+122)

    def test_k117_partial_then_remaining_stop_has_one_40bp_charge(self):
        state, src = self.opened(r.K117)
        for item in state["positions"]["BTC-USDT"]["tracks"].values():
            item["native_pending"]["partial_event"] = {"decision_ts_ms": ANCHOR+25, "partial_fraction": .1, "reason": "NATIVE_2R_PARTIAL"}
        r.poll_once(state, *src, ANCHOR+42, quote_reader=reader(quote(ANCHOR+40, bid=102, ask=102.1)))
        self.assertEqual(state["virtual_closed_T"], 0)
        self.assertAlmostEqual(state["positions"]["BTC-USDT"]["tracks"]["native"]["remaining_fraction"], .9)
        r.poll_once(state, *src, ANCHOR+62, quote_reader=reader(quote(ANCHOR+60, bid=98, ask=98.1)))
        self.assertEqual(state["virtual_closed_T"], 1)
        self.assertAlmostEqual(state["virtual_net_trade_bps_sum"], .1*200 + .9*(-200) - 40)

    def test_running_gap_censors_without_made_up_close(self):
        state, src = self.opened()
        r.poll_once(state, *src, ANCHOR+30023, quote_reader=reader(quote(ANCHOR+30021)))
        self.assertEqual(state["virtual_censored_T"], 1)
        self.assertEqual(state["virtual_closed_T"], 0)
        self.assertEqual(state["virtual_net_trade_bps_sum"], 0)

    def test_restart_gap_censors_and_keeps_admission_consumed(self):
        state, src = self.opened()
        state = r.resume_state(state, ANCHOR+30023)
        r.poll_once(state, *src, ANCHOR+30042, quote_reader=reader(quote(ANCHOR+30040)))
        self.assertEqual(state["virtual_entry_T"], 1)
        self.assertEqual(state["virtual_censored_T"], 1)

    def test_prestart_signal_is_not_fresh(self):
        state = r.new_state(ANCHOR+11)
        r.poll_once(state, *sources([event()]), ANCHOR+22, quote_reader=reader(quote(ANCHOR+20)))
        self.assertEqual(state["virtual_entry_T"], 0)
        self.assertEqual(state["blocked"][0]["reason"], "PRE_VIRTUAL_START_NOT_FRESH")

    def test_sol_xrp_hold_without_fabricated_quotes(self):
        for sym in ("SOL-USDT", "XRP-USDT"):
            state = r.new_state(ANCHOR)
            r.poll_once(state, *sources([event(symbol=sym)]), ANCHOR+22, quote_reader=lambda *a, **k: self.fail("unapproved book requested"))
            self.assertEqual(state["virtual_entry_T"], 0)
            self.assertEqual(state["blocked"][0]["reason"], "HOLD_NO_EXISTING_WS_QUOTE_FOR_SYMBOL")

    def test_old_k117_signal_uses_own_clock_not_latest_checkpoint(self):
        src = sources([event(r.K117)])
        src[1].update(last_complete_30m_close_ms=ANCHOR+r.HALF_HOUR, last_native_decision_ms=ANCHOR+r.HALF_HOUR+100)
        self.assertEqual(r.native_events(*src)[0]["decision_ms"], ANCHOR+10)
        del src[1]["signals"][0]["decision_ts_ms"]
        rejected=[]
        self.assertEqual(r.native_events(*src, rejected), [])
        self.assertEqual(rejected[0]["reason"], "SOURCE_EVENT_DECISION_CLOCK_UNVERIFIED")

    def test_no_bbo_window_extension_to_force_entry(self):
        state = r.new_state(ANCHOR)
        r.poll_once(state, *sources([event()]), ANCHOR+120011, quote_reader=lambda *a, **k: self.fail("expired quote requested"))
        self.assertEqual(state["virtual_entry_T"], 0)
        self.assertEqual(state["blocked"][0]["reason"], "NO_TIMELY_POST_SIGNAL_QUOTE")

    def test_predecision_bucket_cannot_be_used_despite_later_end(self):
        e=r.native_events(*sources([event()]))[0]
        q=quote(ANCHOR+20);q["source_bucket_start_ms"]=ANCHOR
        self.assertIsNone(r.quote_entry(e,q))

    def test_nonfinite_crossed_or_future_quote_rejected(self):
        e=r.native_events(*sources([event()]))[0]
        for changes in ({"best_ask":float("inf")},{"best_bid":101},{"observed_at_ms":ANCHOR+19}):
            self.assertIsNone(r.quote_entry(e,{**quote(ANCHOR+20),**changes}))

    def test_native_absolute_atr_distance_not_rescaled_to_ask(self):
        e=r.native_events(*sources([event()]))[0]
        p=r.quote_entry(e,quote(ANCHOR+20,bid=104.9,ask=105))
        self.assertEqual(p["initial_risk_price"],1)
        self.assertEqual(p["base_stop_price"],104)

    def test_checkpoint_retains_source_evidence_and_real_read_clock(self):
        state,_=self.opened()
        with tempfile.TemporaryDirectory() as td:
            with ledger.Store(Path(td)/"VIRTUAL_LEDGER.sqlite3") as store:
                r.persist(Path(td),state,store)
                (Path(td)/"STATUS.json").write_text("damaged cache")
                recovered=store.load()
                self.assertEqual(recovered["virtual_entries"],state["virtual_entries"])
                self.assertIsNone(recovered["virtual_entries"][0]["quote_received_at_ms"])
                self.assertEqual(recovered["virtual_entries"][0]["source_quote_clock_kind"],"BUCKET_END")
                self.assertEqual(recovered["order_calls"],0)


class ReadinessTests(unittest.TestCase):
    def test_code_upgrade_requires_explicit_pin_and_empty_ledger(self):
        old, new, native = {"code": "old"}, {"code": "new"}, {"native": "fixed"}
        state = r.new_state(ANCHOR)
        r.pin_contract(state, old, native)
        with self.assertRaises(RuntimeError):
            r.pin_contract(state, new, native)
        r.pin_contract(state, new, native, r.digest(old))
        self.assertEqual(state["empty_code_migrations"][0]["previous"], old)
        state["virtual_entry_T"] = 1
        with self.assertRaises(RuntimeError):
            r.pin_contract(state, old, native, r.digest(new))
        with self.assertRaises(RuntimeError):
            r.pin_contract(state, new, {"native": "changed"}, r.digest(new))

    def test_k117_requires_verified_ack_health_and_no_causal_hold(self):
        import os
        status = {"pid": os.getpid(), "updated_at_ms": ANCHOR, "producer_poll_seconds": 60,
                  "phase": "VIRTUAL_SOURCE_ONLY_NATIVE_PENDING_OR_CAUSAL_HOLD",
                  "virtual_signal_export": {"native_causal_hold": None}}
        self.assertFalse(r.k117_ready(status, ANCHOR))
        status["virtual_ack_health"] = "VERIFIED_READ_ONLY_SQLITE_SNAPSHOT"
        self.assertTrue(r.k117_ready(status, ANCHOR))
        status["virtual_signal_export"]["native_causal_hold"] = "EXPIRED"
        self.assertFalse(r.k117_ready(status, ANCHOR))

if __name__ == "__main__":
    unittest.main()
