"""Synthetic clock, atomic-batch and exact-checkpoint restart tests; no market replay."""
from copy import deepcopy
import csv
import gzip
import importlib
import io
import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

obs = importlib.import_module("k117_price_only_source_observer_v1")
k = obs.k
j = obs.journal
H = obs.HALF_HOUR
START = 1_793_040_010_000
CLOSE = (START // H + 1) * H
LABELS = ["BTC-USDT", "ETH-USDT"]
ORIGIN_SHA = "b" * 64
CURRENT_SHA = "c" * 64
CONTRACT_SHA = "a" * 64


def bar(close=CLOSE):
    return {"open_ts_ms": close-H, "close_ts_ms": close, "available_ts_ms": close+100,
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0}


def source_snapshot_fixture(close=CLOSE):
    return {"schema": "k117.price_only.six_context_receipts.v1", "snapshot_asof_ms": close+100,
            "close_ts_ms": close, "symbols": {sym: {"synthetic_test_only": True} for sym in LABELS}}


def event(state, kind, body):
    result = {"seq": len(state["events"]), "kind": kind, "body": deepcopy(body),
              "previous": state["events"][-1]["event_sha256"] if state["events"] else None}
    result["event_sha256"] = k.digest(result)
    state["events"].append(result)
    return result


class FakeNativeAdapter:
    """Only a deterministic stateful test double, never claimed to be native output."""
    def __init__(self, state=None, outcomes=None):
        self.state = deepcopy(state) if state is not None else {
            "fresh_start_ms": START, "signals": {}, "pending": {}, "positions": {}, "trades": [],
            "events": [], "order_calls": 0, "formal_fresh_credit": False,
        }
        self.outcomes = outcomes or {}

    def log(self, kind, body):
        event(self.state, kind, body)

    def on_bar(self, *, symbol, frame, asof_ms, **unused):
        last = frame.iloc[-1]
        result_status = self.outcomes.get(symbol, "NO_SIGNAL")
        if result_status == "RAISE":
            raise OSError("synthetic interruption")
        if result_status == "HOLD":
            event(self.state, "HOLD", {"symbol": symbol, "asof_ms": asof_ms, "reason": "synthetic guard"})
            return {"status": "UNKNOWN", "signal": None, "reason": "synthetic guard"}
        cursor = self.state["signals"].get(symbol)
        if cursor and cursor["last_open"] == int(last.open_ts_ms):
            return {"status": "DUPLICATE", "signal": None}
        signal = None
        if result_status == "SIGNAL":
            signal = {"symbol": symbol, "side": 1, "signal_ts_ms": int(last.available_ts_ms),
                      "signal_open_ts_ms": int(last.open_ts_ms), "invalidation_price": 95.0,
                      "meta": {"synthetic_test_only": True}}
            self.state["pending"][symbol] = {"signal": deepcopy(signal), "decision_ts_ms": asof_ms}
        event(self.state, "BAR", {"symbol": symbol, "close_ts_ms": int(last.close_ts_ms),
                                  "available_ts_ms": int(last.available_ts_ms), "decision_ts_ms": asof_ms,
                                  "status": result_status, "signal": signal})
        hg = (self.state["signals"].get(symbol) or {}).get("hg")
        self.state["signals"][symbol] = {"last_open": int(last.open_ts_ms), "last_asof": asof_ms}
        if hg is not None:
            self.state["signals"][symbol]["hg"] = deepcopy(hg)
        return {"status": result_status, "signal": signal, "reason": "SYNTHETIC_TEST_ONLY"}


def status():
    return {"schema": obs.SCHEMA, "started_at_ms": START, "contract_sha256": CONTRACT_SHA,
            "first_context_open_ms": CLOSE-obs.BARS*H, "next_expected_complete_close_ms": CLOSE,
            "decisions": [], "signals": [], "next_open_entry_holds": [],
            "formal_shadow_active": False, "formal_fresh_credit": False, "virtual_fills": 0, "order_calls": 0}


def run_batch(adapter, close=CLOSE, quote=None, times=None):
    clock = iter(times or range(close+1000, close+1100, 10))
    return obs.observe_batch(adapter, bound={sym: pd.DataFrame([bar(close)]) for sym in LABELS}, labels=LABELS,
                             guard={}, fit={}, costs={sym: 20.0 for sym in LABELS}, target_close=close,
                             source_receipt_digest=k.digest(source_snapshot_fixture(close)), clock_ms=lambda: next(clock),
                             quote_observer=quote or (lambda *args, **kwargs: {"synthetic_test_only": True, **kwargs}))


def append_batch(s, rows):
    s["decisions"].extend(rows)
    s["signals"].extend(row for row in rows if row["status"] == "SIGNAL")
    s["last_complete_30m_close_ms"] = rows[0]["close_ts_ms"]
    s["next_expected_complete_close_ms"] = rows[0]["close_ts_ms"]+H
    s["last_native_decision_ms"] = max(row["decision_ts_ms"] for row in rows)
    if s.get('virtual_signal_export') is not None:
        virtual = s['virtual_signal_export']
        virtual['source_only_next_close_ms'] = max(virtual['source_only_next_close_ms'], s['next_expected_complete_close_ms'])
    source = source_snapshot_fixture(rows[0]["close_ts_ms"])
    s.setdefault("source_receipt_snapshots", []).append({**source, "source_receipt_digest": k.digest(source)})


class ActualEventClockTests(unittest.TestCase):
    def test_per_symbol_clock_is_sampled_after_native_not_reused_batch_time(self):
        rows = run_batch(FakeNativeAdapter())
        self.assertEqual([row["native_asof_ts_ms"] for row in rows], [CLOSE+1000, CLOSE+1020])
        self.assertEqual([row["decision_ts_ms"] for row in rows], [CLOSE+1010, CLOSE+1030])
        self.assertTrue(all(row["decision_ts_ms"] > row["native_asof_ts_ms"] for row in rows))

    def test_signal_clock_full_signal_and_native_receipt_are_exact(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[0]: "SIGNAL"})
        row = run_batch(adapter)[0]
        self.assertEqual(row["native_signal_ts_ms"], CLOSE+100)
        self.assertEqual(row["native_signal_open_ts_ms"], CLOSE-H)
        self.assertEqual(row["native_signal_sha256"], k.digest(row["signal"]))
        self.assertEqual(row["native_receipt_sha256"], adapter.state["events"][0]["event_sha256"])
        self.assertEqual(row["signal"]["invalidation_price"], 95)
        self.assertEqual(row["post_decision_existing_ws_quote"]["decision_ts_ms"], row["decision_ts_ms"])
        self.assertGreater(row["post_decision_existing_ws_quote"]["read_at_ms"], row["decision_ts_ms"])

    def test_all_results_supply_completed_source_bar_without_native_exit_or_fill(self):
        rows = run_batch(FakeNativeAdapter(outcomes={LABELS[1]: "UNKNOWN"}))
        for row in rows:
            self.assertEqual(row["native_exit_input"]["bar"], bar())
            self.assertEqual(row["native_exit_input"]["source_bar_sha256"], k.digest(bar()))
            self.assertEqual(row["native_exit_input"]["source_receipt_digest"], k.digest(source_snapshot_fixture()))
            self.assertIsNone(row["native_exit"])
            self.assertEqual(row["native_exit_status"], "INPUT_ONLY_NO_POSITION_STATE")
            self.assertIsNone(row["native_signal_ts_ms"])
            self.assertFalse(row["virtual_fill"])
            self.assertEqual(row["actual_order_calls"], 0)

    def test_clock_reversal_rolls_back_entire_native_batch(self):
        adapter = FakeNativeAdapter()
        before = deepcopy(adapter.state)
        with self.assertRaisesRegex(ValueError, "CLOCK_REVERSED"):
            run_batch(adapter, times=[CLOSE+200, CLOSE+199])
        self.assertEqual(adapter.state, before)

    def test_unavailable_source_cannot_be_labeled_decided(self):
        adapter = FakeNativeAdapter()
        with self.assertRaisesRegex(ValueError, "SOURCE_UNAVAILABLE"):
            run_batch(adapter, times=[CLOSE+99, CLOSE+101])
        self.assertEqual(adapter.state["events"], [])


class AtomicBatchTests(unittest.TestCase):
    def test_second_symbol_exception_leaves_no_partial_bar_or_signal(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[0]: "SIGNAL", LABELS[1]: "RAISE"})
        before = deepcopy(adapter.state)
        with self.assertRaisesRegex(OSError, "interruption"):
            run_batch(adapter)
        self.assertEqual(adapter.state, before)

    def test_quote_exception_rolls_back_native_signal_and_pending(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[1]: "SIGNAL"})
        before = deepcopy(adapter.state)
        def failing_quote(*args, **kwargs):
            raise OSError("synthetic quote failure")
        with self.assertRaisesRegex(OSError, "quote failure"):
            run_batch(adapter, quote=failing_quote)
        self.assertEqual(adapter.state, before)

    def test_keyboard_interrupt_also_rolls_back(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[1]: "SIGNAL"})
        before = deepcopy(adapter.state)
        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_batch(adapter, quote=interrupt)
        self.assertEqual(adapter.state, before)

    def test_hold_only_unknown_does_not_consume_bar(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[1]: "HOLD"})
        before = deepcopy(adapter.state)
        with self.assertRaisesRegex(RuntimeError, "NATIVE_BAR_NOT_CONSUMED"):
            run_batch(adapter)
        self.assertEqual(adapter.state, before)
        adapter.outcomes.clear()
        self.assertEqual(len(run_batch(adapter)), 2)
        self.assertEqual(len(adapter.state["events"]), 2)

    def test_bar_committed_bootstrap_unknown_is_a_real_consumed_decision(self):
        adapter = FakeNativeAdapter(outcomes={LABELS[1]: "UNKNOWN"})
        rows = run_batch(adapter)
        self.assertEqual(rows[1]["status"], "UNKNOWN")
        self.assertEqual(rows[1]["native_event_kind"], "BAR")
        self.assertEqual(adapter.state["signals"][LABELS[1]]["last_open"], CLOSE-H)

    def test_duplicate_native_bar_cannot_create_duplicate_result(self):
        adapter = FakeNativeAdapter()
        run_batch(adapter)
        before = deepcopy(adapter.state)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_NATIVE_BAR"):
            run_batch(adapter)
        self.assertEqual(adapter.state, before)


class ResumeExistingTests(unittest.TestCase):
    def saved_fixture(self):
        adapter = FakeNativeAdapter()
        s = status()
        rows = run_batch(adapter)
        # Model genuinely missing legacy clocks; never backfill them on resume.
        old_rows = [{key: row[key] for key in ("symbol", "close_ts_ms", "available_ts_ms", "status", "signal")}
                    for row in rows]
        append_batch(s, rows)
        s["decisions"] = old_rows
        del s["source_receipt_snapshots"]
        return s, adapter

    def test_two_restart_checkpoint_keeps_origin_pin_and_adds_only_new_decisions(self):
        s, adapter = self.saved_fixture()
        old_rows = deepcopy(s["decisions"])
        old_events = deepcopy(adapter.state["events"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            origin = j.commit_checkpoint(path, s, adapter.state, CONTRACT_SHA, ORIGIN_SHA)
            saved = j.read_checkpoint(path, CONTRACT_SHA, ORIGIN_SHA)
            obs.validate_resume_checkpoint(saved, LABELS, CLOSE+H+1000)
            s = deepcopy(saved["status"])
            obs.append_producer_run(s, saved, actual_observer_sha=CURRENT_SHA,
                                    checkpoint_observer_sha=ORIGIN_SHA, resumed_at_ms=CLOSE+H+1000)
            self.assertEqual(s["producer_runs"][-1]["prior_checkpoint_sha256"], origin)
            resumed = FakeNativeAdapter(saved["adapter"])
            rows = run_batch(resumed, CLOSE+H)
            append_batch(s, rows)
            j.commit_checkpoint(path, s, resumed.state, CONTRACT_SHA, ORIGIN_SHA)
            saved2 = j.read_checkpoint(path, CONTRACT_SHA, ORIGIN_SHA)
            obs.validate_resume_checkpoint(saved2, LABELS, CLOSE+2*H+1000)
            self.assertEqual(saved2["observer_source_sha256"], ORIGIN_SHA)
            self.assertEqual(saved2["status"]["decisions"][:2], old_rows)
            self.assertNotIn("decision_ts_ms", saved2["status"]["decisions"][0])
            self.assertEqual(saved2["adapter"]["events"][:2], old_events)
            self.assertEqual(saved2["status"]["event_clock_applies_from_decision_index"], 2)
            self.assertEqual(len(saved2["status"]["decisions"]), 4)
            self.assertEqual(saved2["status"]["virtual_fills"], 0)
            self.assertEqual(saved2["status"]["signals"], [])

    def test_wrong_explicit_origin_pin_is_rejected_by_unchanged_journal(self):
        s, adapter = self.saved_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            j.commit_checkpoint(path, s, adapter.state, CONTRACT_SHA, ORIGIN_SHA)
            with self.assertRaisesRegex(ValueError, "CODE_BINDING_MISMATCH"):
                j.read_checkpoint(path, CONTRACT_SHA, CURRENT_SHA)

    def assert_bad(self, mutate, error):
        s, adapter = self.saved_fixture()
        saved = {"status": s, "adapter": adapter.state, "contract_sha256": CONTRACT_SHA}
        mutate(saved)
        with self.assertRaisesRegex(ValueError, error):
            obs.validate_resume_checkpoint(saved, LABELS, CLOSE+H+1000)

    def test_duplicate_decision_rejected(self):
        self.assert_bad(lambda data: data["status"]["decisions"].append(deepcopy(data["status"]["decisions"][0])),
                        "DUPLICATE_OR_INCOMPLETE")

    def test_partial_batch_rejected(self):
        self.assert_bad(lambda data: data["status"]["decisions"].pop(), "DUPLICATE_OR_INCOMPLETE")

    def test_unprojected_native_event_rejected(self):
        def mutate(data):
            event(data["adapter"], "BAR", {"symbol": LABELS[0], "close_ts_ms": CLOSE+H,
                                           "decision_ts_ms": CLOSE+H+100, "status": "NO_SIGNAL", "signal": None})
        self.assert_bad(mutate, "NATIVE_BAR_DECISION_MISMATCH")

    def test_hidden_pending_is_rejected_even_if_hold_projection_empty(self):
        self.assert_bad(lambda data: data["adapter"]["pending"].update({LABELS[0]: {"signal": {}}}),
                        "UNRESOLVED_PREVIOUS_NEXT_OPEN_HOLD")

    def test_legacy_hold_unknown_cannot_skip_a_bar_on_resume(self):
        def mutate(data):
            # This malformed but formerly writable checkpoint consumed a batch
            # in status while its native cursors remained on the prior bar.
            s = data["status"]
            for sym in LABELS:
                s["decisions"].append({"symbol": sym, "close_ts_ms": CLOSE+H,
                                       "status": "UNKNOWN", "signal": None})
                event(data["adapter"], "HOLD", {"symbol": sym, "asof_ms": CLOSE+H+100,
                                               "reason": "synthetic prior guard"})
            s["last_complete_30m_close_ms"] = CLOSE+H
            s["next_expected_complete_close_ms"] = CLOSE+2*H
        self.assert_bad(mutate, "UNCONSUMED_LEGACY_DECISION_NO_RETRO_REPAIR")

    def test_missing_native_cursor_cannot_bootstrap_again_after_restart(self):
        self.assert_bad(lambda data: data["adapter"]["signals"].pop(LABELS[0]),
                        "ADAPTER_CURSOR_NOT_AT_COMMITTED_BATCH")

    def test_adapter_cursor_ahead_is_rejected(self):
        self.assert_bad(lambda data: data["adapter"]["signals"][LABELS[0]].update(last_open=CLOSE),
                        "ADAPTER_CURSOR_MISMATCH")

    def test_native_hash_mutation_is_rejected(self):
        self.assert_bad(lambda data: data["adapter"]["events"][0]["body"].update(status="SIGNAL"),
                        "NATIVE_EVENT_HASH_MISMATCH")

    def test_original_context_or_start_cannot_be_reset(self):
        self.assert_bad(lambda data: data["status"].update(first_context_open_ms=CLOSE), "CONTEXT_CLOCK_MISMATCH")

    def test_signal_projection_cannot_be_added_or_dropped(self):
        self.assert_bad(lambda data: data["status"]["signals"].append({"signal": "invented"}), "SIGNAL_LEDGER_MISMATCH")

    def test_resume_origin_provenance_does_not_mutate_saved_object(self):
        s, adapter = self.saved_fixture()
        saved = {"status": deepcopy(s), "adapter": adapter.state, "contract_sha256": CONTRACT_SHA}
        before = deepcopy(saved)
        obs.append_producer_run(s, saved, actual_observer_sha=CURRENT_SHA,
                                checkpoint_observer_sha=ORIGIN_SHA, resumed_at_ms=CLOSE+H)
        self.assertEqual(saved, before)

    def test_new_clock_projection_is_checked_against_native_event(self):
        for field, value in (("native_receipt_sha256", "0"*64), ("native_event_seq", 99),
                             ("native_signal_ts_ms", CLOSE), ("native_asof_ts_ms", CLOSE+999)):
            with self.subTest(field=field):
                adapter = FakeNativeAdapter()
                s = status()
                append_batch(s, run_batch(adapter))
                s["decisions"][0][field] = value
                with self.assertRaises(ValueError):
                    obs.validate_resume_checkpoint({"status": s, "adapter": adapter.state,
                                                    "contract_sha256": CONTRACT_SHA}, LABELS, CLOSE+H)

    def test_new_actual_decision_cannot_precede_native_or_be_in_future(self):
        for decision_time in (CLOSE+999, CLOSE+H+1):
            with self.subTest(decision_time=decision_time):
                adapter = FakeNativeAdapter()
                s = status()
                append_batch(s, run_batch(adapter))
                s["decisions"][0]["decision_ts_ms"] = decision_time
                with self.assertRaises(ValueError):
                    obs.validate_resume_checkpoint({"status": s, "adapter": adapter.state,
                                                    "contract_sha256": CONTRACT_SHA}, LABELS, CLOSE+H)

    def test_new_source_snapshot_hash_and_reference_are_required(self):
        for mutation in ("missing", "mutated"):
            with self.subTest(mutation=mutation):
                adapter = FakeNativeAdapter()
                s = status()
                append_batch(s, run_batch(adapter))
                if mutation == "missing":
                    s["source_receipt_snapshots"] = []
                else:
                    s["source_receipt_snapshots"][0]["snapshot_asof_ms"] += 1
                with self.assertRaises(ValueError):
                    obs.validate_resume_checkpoint({"status": s, "adapter": adapter.state,
                                                    "contract_sha256": CONTRACT_SHA}, LABELS, CLOSE+H)


class SourceReceiptEvidenceTests(unittest.TestCase):
    def test_source_receipt_digests_leave_native_frame_columns_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = CLOSE-2*H
            identity = {"schema": "synthetic.source", "volume_units": "UNKNOWN", "synthetic_fill": False,
                        "symbols": LABELS, "interval": "1m"}
            identity_raw = json.dumps(identity).encode()
            (root/"IDENTITY.json").write_bytes(identity_raw)
            contract = {"source_identity_sha256": obs.file_sha(identity_raw), "source_schema": identity["schema"],
                        "required_context_symbols": LABELS}
            (root/"contract.json").write_text(json.dumps(contract))
            cursor = {"identity_sha256": obs.file_sha(identity_raw), "symbols": {}}
            for sym in LABELS:
                stream = io.StringIO()
                writer = csv.writer(stream)
                writer.writerow(["timestamp_ms", "open", "high", "low", "close"])
                for stamp in range(first, CLOSE, obs.MINUTE):
                    writer.writerow([stamp, 100, 105, 95, 102])
                norm = gzip.compress(stream.getvalue().encode(), mtime=0)
                (root/(sym+".csv.gz")).write_bytes(norm)
                receipt = {"symbol": sym, "start_ms": first, "end_exclusive_ms": CLOSE,
                           "http_status": 200, "synthetic_fill": False, "received_at_ms": CLOSE+100,
                           "normalized_path": sym+".csv.gz", "normalized_sha256": obs.file_sha(norm)}
                raw = json.dumps(receipt).encode()
                (root/(sym+".json")).write_bytes(raw)
                cursor["symbols"][sym] = [{"path": sym+".json", "sha256": obs.file_sha(raw)}]
            (root/"CURSOR.json").write_text(json.dumps(cursor))
            with patch.object(k, "PRICE_ONLY_CONTRACT", root/"contract.json"), patch.object(obs, "BARS", 2):
                frames = obs.source_snapshot(root, CLOSE+1000, CLOSE, first)
            for frame in frames.values():
                self.assertEqual(list(frame.columns), ["open_ts_ms", "close_ts_ms", "available_ts_ms", "segment_id",
                                                      "open", "high", "low", "close"])
                evidence = frame.attrs["source_receipt_evidence"]
                self.assertEqual(evidence["minute_count"], 60)
                self.assertEqual(evidence["receipt_binding_count"], 1)
                self.assertEqual(len(evidence["minute_binding_sha256"]), 64)
                self.assertTrue(evidence["normalized_source_verified"])
                self.assertFalse(evidence["raw_body_reverified_here"])


def ledger_event(events, kind, body):
    item = {"seq": len(events), "event_id": k.digest([kind, body]), "kind": kind,
            "body": deepcopy(body), "previous_sha256": events[-1]["event_sha256"] if events else None}
    item["event_sha256"] = k.digest(item)
    events.append(item)
    return item


class VirtualAdmissionExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Actual pinned frozen policy/helper definitions, with synthetic HG state.
        cls.dependencies = k.dependencies()

    def fixture(self):
        s = status()
        formal = FakeNativeAdapter().state
        virtual = obs.initialize_virtual_export(s, formal, ledger_path=Path('/synthetic/ledger.sqlite3'),
                                                helper_sha='f'*64)
        adapter = FakeNativeAdapter(virtual['adapter_state'], {LABELS[0]: 'SIGNAL'})
        rows = run_batch(adapter)
        append_batch(s, rows)
        for symbol in LABELS:
            hg = self.dependencies.positive.HolyGrailState()
            hg.side = 1
            hg.stage = 2
            adapter.state['signals'][symbol]['hg'] = self.dependencies.helpers['_hg_dump'](hg)
        virtual['pending_exports'][LABELS[0]] = k.digest(rows[0])
        return s, formal, adapter, rows[0]

    def acknowledgement(self, row, accepted=True):
        uid = k.digest(row)
        virtual_id = k.digest({'symbol': row['symbol'], 'rule': obs.VIRTUAL_RULE, 'signal': uid})
        events = []
        entry = {'virtual_id': virtual_id, 'original_signal_digest': uid, 'rule_id': obs.VIRTUAL_RULE,
                 'symbol': row['symbol'], 'decision_ms': row['decision_ts_ms'],
                 'virtual_entry_observed_at_ms': CLOSE+2000, 'source_quote_sha256': 'e'*64}
        entry_event = ledger_event(events, 'ENTRY', entry) if accepted else None
        ack = {'signal_id': virtual_id, 'original_signal_digest': uid, 'rule_id': obs.VIRTUAL_RULE,
               'symbol': row['symbol'], 'decision_ms': row['decision_ts_ms'], 'accepted': accepted,
               'acknowledgement_ts_ms': CLOSE+2000, 'reason': 'SYNTHETIC_OPEN' if accepted else 'SYNTHETIC_ACTUAL_BLOCKED',
               'source_entry_event_sha256': entry_event['event_sha256'] if accepted else None,
               'source_entry_virtual_id': virtual_id if accepted else None, 'source_evidence_sha256': 'e'*64}
        ack['ack_sha256'] = k.digest(ack)
        ledger_event(events, 'ADMISSION_ACK', ack)
        ledger_state = {'virtual_events': events, 'admission_acks': [ack], 'updated_at_ms': CLOSE+2000,
                        'positions': {row['symbol']: {'virtual_id': virtual_id, 'rule_id': obs.VIRTUAL_RULE,
                                                     'tracks': {'native': {}, 'runner': {}}}} if accepted else {}}
        proof = {'revision': 1, 'event_count': len(events), 'head_sha256': events[-1]['event_sha256'],
                 'state_sha256': k.digest(ledger_state), 'ledger_path': '/synthetic/ledger.sqlite3'}
        return ledger_state, proof

    def test_verified_open_uses_frozen_accept_callback_only_on_virtual_clone(self):
        s, formal, adapter, row = self.fixture()
        original = deepcopy(formal)
        ledger_state, proof = self.acknowledgement(row)
        self.assertEqual(obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof,
                                                           self.dependencies, CLOSE+3000), 1)
        self.assertTrue(adapter.state['signals'][LABELS[0]]['hg']['episode_traded'])
        self.assertEqual(adapter.state['signals'][LABELS[0]]['hg']['stage'], 2)
        self.assertEqual(adapter.state['pending'], {})
        self.assertEqual(s['virtual_signal_export']['pending_exports'], {})
        self.assertEqual(formal, original)
        self.assertEqual(s['signals'][0], row)
        self.assertFalse(s['virtual_signal_export']['admission_receipts'][0]['formal_native_entry_claimed'])

    def test_verified_blocked_uses_exact_frozen_event_reset_preserving_side(self):
        s, formal, adapter, row = self.fixture()
        ledger_state, proof = self.acknowledgement(row, accepted=False)
        obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof, self.dependencies, CLOSE+3000)
        hg = adapter.state['signals'][LABELS[0]]['hg']
        self.assertEqual(hg['stage'], 0)
        self.assertEqual(hg['side'], 1)
        self.assertFalse(hg['episode_traded'])

    def test_missing_ack_never_guesses_rejection_or_drops_pending(self):
        s, formal, adapter, row = self.fixture()
        before = deepcopy(adapter.state)
        empty = {'virtual_events': [], 'admission_acks': [], 'positions': {}, 'updated_at_ms': CLOSE+2000}
        self.assertEqual(obs.apply_virtual_acknowledgements(s, adapter, empty, {}, self.dependencies, CLOSE+3000), 0)
        self.assertEqual(adapter.state, before)

    def test_repeated_ack_is_idempotent(self):
        s, formal, adapter, row = self.fixture()
        ledger_state, proof = self.acknowledgement(row)
        obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof, self.dependencies, CLOSE+3000)
        before = deepcopy(adapter.state)
        self.assertEqual(obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof,
                                                           self.dependencies, CLOSE+4000), 0)
        self.assertEqual(adapter.state, before)
        self.assertEqual(len(s['virtual_signal_export']['admission_receipts']), 1)

    def test_bad_ack_clock_hash_or_entry_link_rolls_back_all_virtual_mutations(self):
        for mutation in ('clock', 'hash', 'entry'):
            with self.subTest(mutation=mutation):
                s, formal, adapter, row = self.fixture()
                before_s, before_a = deepcopy(s), deepcopy(adapter.state)
                ledger_state, proof = self.acknowledgement(row)
                ack = ledger_state['admission_acks'][0]
                if mutation == 'clock':
                    ack['acknowledgement_ts_ms'] = CLOSE-1
                elif mutation == 'hash':
                    ack['ack_sha256'] = '0'*64
                else:
                    ack['source_entry_event_sha256'] = '0'*64
                    ack['ack_sha256'] = k.digest({key: value for key, value in ack.items() if key != 'ack_sha256'})
                    ledger_state['virtual_events'][-1]['body'] = deepcopy(ack)
                with self.assertRaises(ValueError):
                    obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof, self.dependencies, CLOSE+3000)
                self.assertEqual(s, before_s)
                self.assertEqual(adapter.state, before_a)

    def test_source_only_exit_input_continues_without_consuming_pending_native_bar(self):
        s, formal, adapter, row = self.fixture()
        before = deepcopy(adapter.state)
        source = obs.source_only_result(LABELS[0], pd.DataFrame([bar(CLOSE+H)]), 'd'*64, CLOSE+H+1000)
        self.assertEqual(source['native_status'], 'NOT_RUN')
        self.assertIsNone(source['native_receipt_sha256'])
        self.assertEqual(source['native_exit_input']['bar']['close_ts_ms'], CLOSE+H)
        self.assertEqual(adapter.state, before)
        self.assertIn(LABELS[0], adapter.state['pending'])

    def test_source_only_rejects_invalid_geometry_or_incomplete_clock(self):
        for changes in ({'low': 110.0}, {'available_ts_ms': CLOSE-1}, {'high': float('nan')}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    obs.source_only_result(LABELS[0], pd.DataFrame([{**bar(), **changes}]), 'd'*64, CLOSE+1000)

    def test_pair_terminal_does_not_reset_hg_and_native_only_close_keeps_runner_exposure(self):
        s, formal, adapter, row = self.fixture()
        ledger_state, proof = self.acknowledgement(row)
        obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof, self.dependencies, CLOSE+3000)
        hg_before = deepcopy(adapter.state['signals'][LABELS[0]]['hg'])
        virtual_id = ledger_state['positions'][LABELS[0]]['virtual_id']
        for track, at in [('native', CLOSE+4000), ('runner', CLOSE+5000)]:
            terminal = {'virtual_id': virtual_id, 'symbol': LABELS[0], 'rule_id': obs.VIRTUAL_RULE, 'track': track}
            ledger_event(ledger_state['virtual_events'], 'EXIT', terminal)
            del ledger_state['positions'][LABELS[0]]['tracks'][track]
            if not ledger_state['positions'][LABELS[0]]['tracks']:
                del ledger_state['positions'][LABELS[0]]
            ledger_state['updated_at_ms'] = at
            obs.apply_virtual_acknowledgements(s, adapter, ledger_state, proof, self.dependencies, at+1)
            self.assertEqual(adapter.state['signals'][LABELS[0]]['hg'], hg_before)
            if track == 'native':
                self.assertEqual(s['virtual_signal_export']['virtual_exposure'][LABELS[0]]['active_tracks'], ['runner'])
                self.assertEqual(s['virtual_signal_export']['paired_terminal_ids'], [])
        self.assertEqual(s['virtual_signal_export']['paired_terminal_ids'], [virtual_id])
        self.assertTrue(all(r['hg_reset_applied'] is False for r in s['virtual_signal_export']['terminal_receipts']))

    def test_restart_preserves_formal_snapshot_pending_clone_and_then_next_bar(self):
        s, formal, adapter, row = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            obs.commit_observation(path, s, adapter, formal, CONTRACT_SHA, ORIGIN_SHA)
            saved = j.read_checkpoint(path, CONTRACT_SHA, ORIGIN_SHA)
            obs.validate_resume_checkpoint(saved, LABELS, CLOSE+3000)
            self.assertEqual(saved['adapter'], formal)
            s = deepcopy(saved['status'])
            restarted = FakeNativeAdapter(s['virtual_signal_export']['adapter_state'])
            ledger_state, proof = self.acknowledgement(row)
            obs.apply_virtual_acknowledgements(s, restarted, ledger_state, proof, self.dependencies, CLOSE+3000)
            new_rows = run_batch(restarted, CLOSE+H)
            append_batch(s, new_rows)
            obs.commit_observation(path, s, restarted, formal, CONTRACT_SHA, ORIGIN_SHA)
            again = j.read_checkpoint(path, CONTRACT_SHA, ORIGIN_SHA)
            obs.validate_resume_checkpoint(again, LABELS, CLOSE+2*H)
            self.assertEqual(again['adapter'], formal)
            self.assertEqual(len(again['status']['decisions']), 4)
            self.assertEqual(again['status']['signals'], [row])

    def test_formal_pending_cannot_be_reinterpreted_as_virtual(self):
        formal = FakeNativeAdapter().state
        formal['pending'][LABELS[0]] = {'signal': {}}
        with self.assertRaisesRegex(ValueError, 'UNRESOLVED_FORMAL_PENDING'):
            obs.initialize_virtual_export(status(), formal, ledger_path=Path('/synthetic/ledger.sqlite3'), helper_sha='f'*64)


class ReadOnlyAckLedgerTests(unittest.TestCase):
    def test_heartbeat_persists_actual_pid_clock_poll_and_stopped_with_unchanged_decisions(self):
        s = status()
        adapter = FakeNativeAdapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for at, stopped in [(CLOSE+1, False), (CLOSE+30_001, False), (CLOSE+30_002, True)]:
                obs.stamp_heartbeat(s, now_ms=at, poll_seconds=30, stopped=stopped)
                seal = obs.commit_observation(path, s, adapter, deepcopy(adapter.state), CONTRACT_SHA, ORIGIN_SHA)
                obs.safe_status(path, {**s, 'checkpoint_sha256': seal})
                saved = j.read_checkpoint(path, CONTRACT_SHA, ORIGIN_SHA)
                projected = json.loads((path/'STATUS.json').read_text())
                self.assertEqual(saved['status']['pid'], obs.os.getpid())
                self.assertEqual(saved['status']['updated_at_ms'], at)
                self.assertEqual(saved['status']['producer_poll_seconds'], 30)
                self.assertEqual(saved['status']['stopped'], stopped)
                self.assertEqual(saved['status']['decisions'], [])
                self.assertEqual({key: value for key, value in projected.items() if key != 'checkpoint_sha256'}, saved['status'])

    def test_sqlite_reader_binds_full_checkpoint_to_events_without_writing_database(self):
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        helper = SimpleNamespace(verify=lambda state: None, canonical=canonical)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'ledger.sqlite3'
            events = []
            ledger_event(events, 'ADMISSION_ACK', {'synthetic_test_only': True})
            state = {'virtual_events': events}
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE checkpoint(singleton INTEGER, revision INTEGER,state_sha256 TEXT,event_count INTEGER,head_sha256 TEXT,payload TEXT)')
            connection.execute('CREATE TABLE events(seq INTEGER,event_id TEXT,event_sha256 TEXT,payload TEXT)')
            connection.execute('INSERT INTO checkpoint VALUES(1,1,?,?,?,?)', (k.digest(state), 1, events[-1]['event_sha256'], canonical(state)))
            for item in events:
                connection.execute('INSERT INTO events VALUES(?,?,?,?)', (item['seq'],item['event_id'],item['event_sha256'],canonical(item)))
            connection.commit(); connection.close()
            before = path.read_bytes()
            loaded, proof = obs.read_virtual_ack_ledger(path, helper)
            self.assertEqual(loaded, state)
            self.assertEqual(proof['state_sha256'], k.digest(state))
            self.assertEqual(path.read_bytes(), before)
            connection = sqlite3.connect(path)
            connection.execute("UPDATE events SET payload='{}'")
            connection.commit(); connection.close()
            with self.assertRaisesRegex(ValueError, 'EVENT_CHECKPOINT_MISMATCH'):
                obs.read_virtual_ack_ledger(path, helper)

    def test_helper_source_must_match_explicit_code_pin_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'helper.py'
            path.write_text("raise AssertionError('must never execute')\n")
            with self.assertRaisesRegex(ValueError, 'CODE_PIN_MISMATCH'):
                obs.load_virtual_ledger_helper(path, '0'*64)


if __name__ == "__main__":
    unittest.main()
