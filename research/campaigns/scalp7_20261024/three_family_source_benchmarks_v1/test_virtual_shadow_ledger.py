"""Synthetic ledger fixtures only; no live source, economic run, or credit."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import virtual_shadow_ledger as v


def state():
    out = {'order_calls': 0, 'real_broker_fills': 0, 'formal_shadow': False,
           'account_NAV': None, 'positions': {}, 'updated_at_ms': 1000}
    v.initialize(out)
    return out


def position(**changes):
    out = {'symbol': 'BTC-USDT', 'rule_id': 'K117', 'original_signal_digest': 'a' * 64,
           'decision_ms': 100, 'entry_quote_ts_ms': 200, 'entry_ask_price': 100.0,
           'base_stop_price': 90.0, 'initial_risk_price': 10.0,
           'last_quote_ts_ms': 200, 'quote_read_at_ms': 250, 'last_quote_read_at_ms': 250,
           'quote_received_at_ms': None, 'quote_entry_sha256': 'b' * 64,
           'source_quote_clock_kind': 'BUCKET_END', 'cost_assumption_roundtrip_bps': 40,
           'formal_shadow': False, 'real_broker_fill': False, 'original_next_open_fill_verified': False,
           'active_floor_stop_price': 90.0}
    out.update(changes)
    return out


def evidence(**changes):
    out = {'symbol': 'BTC-USDT', 'rule_id': 'K117', 'terminal_quote_ts_ms': 400,
           'read_at_ms': 450, 'terminal_received_at_ms': None, 'terminal_bid_price': 110.0,
           'source_quote_clock_kind': 'BUCKET_END', 'source_quote_sha256': 'c' * 64,
           'observational_net_bps_at_40bp': 960.0, 'observational_net_R': .96,
           'reason': 'OBSERVED_STOP', 'real_trade': False, 'order_calls': 0}
    out.update(changes)
    return out


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.s = state()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_one_common_entry_two_separate_tracks(self):
        v.enter(self.s, position())
        self.assertEqual(self.s['virtual_entry_T'], 1)
        self.assertEqual(self.s['virtual_open_T'], 1)
        self.assertEqual(set(self.s['positions']['BTC-USDT']['tracks']), set(v.TRACKS))
        v.exit_at_bid(self.s, evidence(), track='native')
        self.assertEqual(self.s['virtual_closed_T'], 1)
        self.assertEqual(self.s['runner_closed_T'], 0)
        self.assertEqual(self.s['virtual_open_T'], 0)
        self.assertEqual(self.s['symbol_exposure_open_T'], 1)
        v.exit_at_bid(self.s, evidence(), track='runner')
        self.assertEqual(self.s['virtual_open_T'], 0)
        self.assertAlmostEqual(self.s['virtual_net_trade_bps_sum'], 960)
        self.assertAlmostEqual(self.s['runner_net_trade_bps_sum'], 960)
        self.assertAlmostEqual(self.s['virtual_net_R_sum'], .96)

    def test_same_symbol_held_until_both_tracks_end(self):
        v.enter(self.s, position()); v.exit_at_bid(self.s, evidence())
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_SYMBOL'):
            v.enter(self.s, position(original_signal_digest='d' * 64))
        v.censor(self.s, 'BTC-USDT', 'GAP', at_ms=500)
        self.assertEqual(self.s['virtual_open_T'], 0)
        self.assertEqual(self.s['runner_censored_T'], 1)
        v.enter(self.s, position(original_signal_digest='d' * 64, decision_ms=510,
                                entry_quote_ts_ms=600, last_quote_ts_ms=600,
                                quote_read_at_ms=650, last_quote_read_at_ms=650))
        self.assertEqual(self.s['virtual_entry_T'], 2)

    def test_signal_dedupe_ignores_quote_change(self):
        identifier = v.enter(self.s, position())
        self.assertEqual(v.enter(self.s, position()), identifier)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_VIRTUAL_SIGNAL'):
            v.enter(self.s, position(entry_quote_ts_ms=210))
        self.assertEqual(len(self.s['virtual_events']), 2)

    def test_signal_retry_after_terminal_cannot_reenter(self):
        v.enter(self.s, position()); v.censor(self.s, 'BTC-USDT', 'GAP', at_ms=500)
        before = v.digest(self.s)
        v.enter(self.s, position())
        self.assertEqual(v.digest(self.s), before)
        self.assertFalse(self.s['positions'])

    def test_exit_exact_retry_does_not_append(self):
        v.enter(self.s, position()); first = v.exit_at_bid(self.s, evidence())
        before = v.digest(self.s)
        self.assertEqual(v.exit_at_bid(self.s, evidence()), first)
        self.assertEqual(v.digest(self.s), before)
        v.exit_at_bid(self.s, evidence(), track='runner')
        before = v.digest(self.s)
        v.exit_at_bid(self.s, evidence())
        self.assertEqual(v.digest(self.s), before)

    def test_censor_partial_track_retry_is_idempotent(self):
        v.enter(self.s, position())
        first = v.censor(self.s, 'BTC-USDT', 'GAP', track='native', at_ms=500)
        before = v.digest(self.s)
        self.assertEqual(v.censor(self.s, 'BTC-USDT', 'GAP', track='native', at_ms=500), first)
        self.assertEqual(v.digest(self.s), before)
        v.censor(self.s, 'BTC-USDT', 'GAP', at_ms=500)
        before = v.digest(self.s)
        v.censor(self.s, 'BTC-USDT', 'GAP', at_ms=500)
        self.assertEqual(v.digest(self.s), before)
        self.assertEqual(len(self.s['virtual_censored']), 2)
        self.assertEqual(self.s['virtual_net_trade_bps_sum'], 0)

    def test_received_unknown_preserved_fill_observed_separate(self):
        v.enter(self.s, position()); row = v.exit_at_bid(self.s, evidence())
        self.assertEqual(row['exit_quote_ts_ms'], 400)
        self.assertEqual(row['virtual_exit_observed_at_ms'], 450)
        self.assertIsNone(row['quote_received_at_ms'])
        self.assertIsNone(self.s['virtual_entries'][0]['quote_received_at_ms'])
        self.assertFalse(row['funding_actual_verified'])

    def test_net_and_r_are_independently_checked(self):
        v.enter(self.s, position()); before = v.digest(self.s)
        for changes in ({'observational_net_bps_at_40bp': 1000.0}, {'observational_net_R': 1.0}):
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_NET_OR_R'):
                v.exit_at_bid(self.s, evidence(**changes))
            self.assertEqual(v.digest(self.s), before)

    def test_nonfinite_risk_price_bid_or_hidden_state_rejected(self):
        for changes in ({'entry_ask_price': float('nan')}, {'initial_risk_price': float('inf')},
                        {'initial_risk_price': 11.0}, {'active_floor_stop_price': float('nan')}):
            with self.assertRaises(ValueError):
                v.enter(self.s, position(**changes))
        v.enter(self.s, position())
        with self.assertRaises(ValueError):
            v.exit_at_bid(self.s, evidence(terminal_bid_price=float('inf')))

    def test_authority_and_cost_are_fail_closed(self):
        for key, value in [('order_calls', 1), ('API_calls', 1), ('formal_shadow', True),
                           ('real_broker_fills', 1), ('account_NAV', 10.0)]:
            s = deepcopy(self.s); s[key] = value
            with self.assertRaises(ValueError):
                v.verify(s)
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_OR_COST'):
            v.enter(self.s, position(cost_assumption_roundtrip_bps=0))

    def test_entry_evidence_and_clock_rejected(self):
        for changes in ({'quote_entry_sha256': 'bad'}, {'original_signal_digest': 'bad'},
                        {'decision_ms': 200}, {'quote_read_at_ms': 199},
                        {'quote_received_at_ms': 251}, {'source_quote_clock_kind': 'FILL'}):
            with self.assertRaises(ValueError):
                v.enter(self.s, position(**changes))
        self.assertEqual(self.s['virtual_entries'], [])

    def test_no_retro_exit_observed_or_source_clock(self):
        v.enter(self.s, position())
        for changes in ({'terminal_quote_ts_ms': 200}, {'read_at_ms': 250},
                        {'terminal_received_at_ms': 451}, {'source_quote_sha256': 'bad'}):
            with self.assertRaises(ValueError):
                v.exit_at_bid(self.s, evidence(**changes))

    def test_event_observation_clock_rollback_across_new_entries(self):
        v.enter(self.s, position()); v.censor(self.s, 'BTC-USDT', 'GAP', at_ms=500)
        with self.assertRaisesRegex(ValueError, 'EVENT_OBSERVATION_CLOCK_ROLLBACK'):
            v.enter(self.s, position(original_signal_digest='d' * 64))

    def test_checkpoint_restart_exact_once_and_wal_full(self):
        v.enter(self.s, position())
        with v.Store(self.path) as db:
            self.assertIsNone(db.load())
            self.assertEqual(db.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(db.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertEqual(db.commit(self.s), 1)
            self.assertEqual(db.commit(self.s), 1)
        with v.Store(self.path) as db:
            recovered = db.load()
            v.enter(recovered, position())
            self.assertEqual(db.commit(recovered), 1)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_sql_events_are_insert_only(self):
        v.enter(self.s, position())
        with v.Store(self.path) as db:
            db.commit(self.s)
            for sql in ('DELETE FROM events', "UPDATE events SET payload='{}'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.db.execute(sql)

    def test_checkpoint_tamper_is_detected_and_lock_released(self):
        with v.Store(self.path) as db:
            db.commit(self.s)
            db.db.execute("UPDATE checkpoint SET state_sha256='bad'")
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_HASH'):
            v.Store(self.path)
        # Failed open must release lock; the next failure is integrity, not lock.
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_HASH'):
            v.Store(self.path)

    def test_single_writer(self):
        with v.Store(self.path):
            with self.assertRaises(BlockingIOError):
                v.Store(self.path)
        with v.Store(self.path):
            pass

    def test_event_hash_record_and_prefix_tamper_rejected(self):
        v.enter(self.s, position())
        bad = deepcopy(self.s); bad['virtual_events'][0]['body']['entry_ask'] = 111
        with self.assertRaisesRegex(ValueError, 'HASH_CHAIN'):
            v.verify(bad)
        with v.Store(self.path) as db:
            db.commit(self.s)
            with self.assertRaisesRegex(ValueError, 'APPEND_ONLY_PREFIX'):
                db.commit(state())

    def test_persisted_quote_clock_rollback_rejected(self):
        v.enter(self.s, position())
        stale = deepcopy(self.s)
        with v.Store(self.path) as db:
            db.commit(self.s)
            self.s['positions']['BTC-USDT']['tracks']['native'].update(last_quote_ts_ms=600, last_quote_read_at_ms=650)
            db.commit(self.s)
            with self.assertRaisesRegex(ValueError, 'CHECKPOINT_OBSERVATION_CLOCK'):
                db.commit(stale)

    def test_stale_terminal_clone_cannot_bypass_persisted_quote_clock(self):
        for terminal in ('exit', 'censor', 'partial'):
            with self.subTest(terminal=terminal):
                path = self.path.with_name(terminal + '.sqlite3')
                current = state(); v.enter(current, position()); stale = deepcopy(current)
                with v.Store(path) as db:
                    db.commit(current)
                    current['positions']['BTC-USDT']['tracks']['native'].update(last_quote_ts_ms=600, last_quote_read_at_ms=650)
                    db.commit(current)
                    if terminal == 'exit':
                        v.exit_at_bid(stale, evidence())
                    elif terminal == 'partial':
                        v.partial_at_bid(stale, evidence(partial_fraction=.1, partial_decision_ts_ms=300))
                    else:
                        v.censor(stale, 'BTC-USDT', 'GAP', track='native', at_ms=500)
                    with self.assertRaisesRegex(ValueError, 'CHECKPOINT_TERMINAL_CLOCK'):
                        db.commit(stale)

    def test_existing_model_authority_not_silently_normalized(self):
        for key, value in [('virtual_model_roundtrip_bps', 0), ('native_exit_parity', True)]:
            bad = deepcopy(self.s); bad[key] = value
            with self.assertRaises(ValueError):
                v.initialize(bad)

    def test_partial_fraction_cost_then_remaining_terminal(self):
        v.enter(self.s, position())
        first = v.partial_at_bid(self.s, evidence(partial_fraction=.1, partial_decision_ts_ms=300))
        self.assertAlmostEqual(first['charged_model_cost_bps'], 4)
        self.assertAlmostEqual(first['net_bps_40_model'], 96)
        self.assertEqual(self.s['virtual_closed_T'], 0)
        self.assertEqual(self.s['virtual_partial_T'], 1)
        self.assertAlmostEqual(self.s['positions']['BTC-USDT']['tracks']['native']['remaining_fraction'], .9)
        last = v.exit_at_bid(self.s, evidence(terminal_quote_ts_ms=500, read_at_ms=550))
        self.assertAlmostEqual(last['closed_fraction'], .9)
        self.assertAlmostEqual(last['charged_model_cost_bps'] + first['charged_model_cost_bps'], 40)
        self.assertAlmostEqual(self.s['virtual_net_trade_bps_sum'], 960)
        self.assertAlmostEqual(self.s['virtual_net_R_sum'], .96)
        self.assertEqual(self.s['virtual_closed_T'], 1)
        self.assertEqual(self.s['virtual_entry_T'], 1)
        self.assertEqual(self.s['runner_open_T'], 1)

    def test_partial_retry_after_restart_exact_once(self):
        v.enter(self.s, position())
        request = evidence(partial_fraction=.1, partial_decision_ts_ms=300)
        with v.Store(self.path) as db:
            v.partial_at_bid(self.s, request); db.commit(self.s)
        with v.Store(self.path) as db:
            recovered = db.load(); before = v.digest(recovered)
            v.partial_at_bid(recovered, request); db.commit(recovered)
            self.assertEqual(v.digest(recovered), before)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 3)

    def test_partial_then_adverse_exit_weighted_net_and_r(self):
        v.enter(self.s, position())
        v.partial_at_bid(self.s, evidence(partial_fraction=.1, partial_decision_ts_ms=300))
        v.exit_at_bid(self.s, evidence(terminal_quote_ts_ms=500, read_at_ms=550,
            terminal_bid_price=90., observational_net_bps_at_40bp=-1040., observational_net_R=-1.04))
        self.assertAlmostEqual(self.s['virtual_net_trade_bps_sum'], -840.)
        self.assertAlmostEqual(self.s['virtual_net_R_sum'], -.84)

    def test_partial_uses_later_observed_bid_not_decision_bar_price(self):
        v.enter(self.s, position())
        for request in [evidence(partial_fraction=.1, partial_decision_ts_ms=400),
                        evidence(partial_fraction=.1, partial_decision_ts_ms=249)]:
            with self.assertRaises(ValueError):
                v.partial_at_bid(self.s, request)
        self.assertEqual(self.s['virtual_partial_T'], 0)

    def test_partial_invalid_fraction_and_conflicting_retry(self):
        v.enter(self.s, position())
        for fraction in (0, -.1, 1.1, float('nan')):
            with self.assertRaises(ValueError):
                v.partial_at_bid(self.s, evidence(partial_fraction=fraction, partial_decision_ts_ms=300))
        v.partial_at_bid(self.s, evidence(partial_fraction=.1, partial_decision_ts_ms=300))
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_PARTIAL'):
            v.partial_at_bid(self.s, evidence(partial_fraction=.2, partial_decision_ts_ms=300))

    def test_partial_exhausting_remainder_counts_closed_once(self):
        v.enter(self.s, position())
        request = evidence(partial_fraction=1., partial_decision_ts_ms=300)
        v.partial_at_bid(self.s, request)
        self.assertEqual(self.s['virtual_closed_T'], 1)
        self.assertEqual(self.s['virtual_open_T'], 0)
        before = v.digest(self.s); v.partial_at_bid(self.s, request)
        self.assertEqual(v.digest(self.s), before)

    def test_partial_then_censor_never_invents_full_net(self):
        v.enter(self.s, position())
        v.partial_at_bid(self.s, evidence(partial_fraction=.1, partial_decision_ts_ms=300))
        rows = v.censor(self.s, 'BTC-USDT', 'UNOBSERVED_PATH', at_ms=1000)
        self.assertEqual(self.s['virtual_closed_T'], 0)
        self.assertEqual(self.s['virtual_net_trade_bps_sum'], 0)
        self.assertAlmostEqual(self.s['virtual_partial_net_trade_bps_sum'], 96)
        native = next(row for row in rows if row['track'] == 'native')
        self.assertAlmostEqual(native['remaining_fraction'], .9)
        self.assertIsNone(native['net_R_unavailable'])

    def test_repeated_decimal_partials_last_exact_retry(self):
        v.enter(self.s, position())
        for index in range(10):
            request = evidence(partial_fraction=.1, partial_decision_ts_ms=300 + index * 100,
                               terminal_quote_ts_ms=350 + index * 100, read_at_ms=360 + index * 100)
            v.partial_at_bid(self.s, request)
        self.assertEqual(self.s['virtual_closed_T'], 1)
        self.assertEqual(self.s['virtual_partial_T'], 9)
        before = v.digest(self.s); v.partial_at_bid(self.s, request)
        self.assertEqual(v.digest(self.s), before)
        charged = [row['charged_model_cost_bps'] for row in self.s['virtual_partials'] + self.s['virtual_exits']]
        self.assertAlmostEqual(sum(charged), 40.)

    def test_entry_ack_is_atomic_and_bound_to_entry_event(self):
        uid = v.enter(self.s, position())
        ack = self.s['admission_acks'][0]
        self.assertTrue(ack['accepted'])
        self.assertEqual(ack['source_entry_virtual_id'], uid)
        self.assertEqual(ack['source_entry_event_sha256'], self.s['virtual_events'][0]['event_sha256'])
        self.assertEqual(ack['acknowledgement_ts_ms'], 250)
        self.assertEqual(ack['source_evidence_sha256'], 'b' * 64)
        self.assertEqual(self.s['virtual_events'][1]['kind'], 'ADMISSION_ACK')
        with v.Store(self.path) as db:
            db.commit(self.s)
        with v.Store(self.path) as db:
            self.assertEqual(db.load()['admission_acks'], self.s['admission_acks'])

    def test_rejected_ack_exact_retry_and_changed_ack_rejected(self):
        request = dict(accepted=False, reason='UNSUPPORTED_SIDE', at_ms=300, evidence_sha256='e' * 64)
        ack = v.ack_signal(self.s, position(), **request)
        before = v.digest(self.s)
        self.assertEqual(v.ack_signal(self.s, position(), **request), ack)
        self.assertEqual(v.digest(self.s), before)
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_ADMISSION_ACK'):
            v.ack_signal(self.s, position(), **{**request, 'at_ms': 301})
        self.assertEqual(v.digest(self.s), before)
        self.assertIsNone(ack['source_entry_event_sha256'])
        self.assertEqual(self.s['virtual_entry_T'], 0)

    def test_rejected_ack_blocks_later_entry_same_original_signal(self):
        v.ack_signal(self.s, position(), accepted=False, reason='UNSUPPORTED_SIDE', at_ms=200, evidence_sha256='e' * 64)
        before = v.digest(self.s)
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_ADMISSION_ACK'):
            v.enter(self.s, position())
        self.assertEqual(v.digest(self.s), before)

    def test_ack_missing_identity_clock_and_evidence_fail_closed(self):
        for request in [dict(at_ms=99, evidence_sha256='e' * 64), dict(at_ms=300, evidence_sha256='bad')]:
            with self.assertRaises(ValueError):
                v.ack_signal(self.s, position(), accepted=False, reason='BLOCKED', **request)
        missing = position(); missing.pop('decision_ms')
        with self.assertRaises(KeyError):
            v.ack_signal(self.s, missing, accepted=False, reason='BLOCKED', at_ms=300, evidence_sha256='e' * 64)
        self.assertEqual(self.s['admission_acks'], [])

    def test_ack_inner_hash_and_entry_binding_checked(self):
        v.enter(self.s, position())
        for key, value in [('ack_sha256', 'f' * 64), ('source_entry_event_sha256', 'f' * 64)]:
            bad = deepcopy(self.s); bad['admission_acks'][0][key] = value
            if key != 'ack_sha256':
                ack = bad['admission_acks'][0]
                ack['ack_sha256'] = v.digest({k: value for k, value in ack.items() if k != 'ack_sha256'})
            bad['virtual_events'][1]['body'] = deepcopy(bad['admission_acks'][0])
            e = bad['virtual_events'][1]
            e['event_sha256'] = v.digest({k: value for k, value in e.items() if k != 'event_sha256'})
            with self.assertRaisesRegex(ValueError, 'ADMISSION_ACK'):
                v.verify(bad)

    def test_rejected_ack_recovered_exact_once(self):
        request = dict(accepted=False, reason='ALREADY_OCCUPIED', at_ms=300, evidence_sha256='e' * 64)
        with v.Store(self.path) as db:
            v.ack_signal(self.s, position(), **request); db.commit(self.s)
        with v.Store(self.path) as db:
            recovered = db.load(); v.ack_signal(recovered, position(), **request); db.commit(recovered)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
            self.assertEqual(len(recovered['admission_acks']), 1)

    def test_same_original_digest_cannot_ack_two_identities(self):
        request = dict(accepted=False, reason='BLOCKED', at_ms=300, evidence_sha256='e' * 64)
        v.ack_signal(self.s, position(), **request)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_OR_INVALID_ADMISSION_ACK'):
            v.ack_signal(self.s, position(symbol='ETH-USDT'), **request)
        self.assertEqual(len(self.s['admission_acks']), 1)

    def test_ack_cannot_precede_its_entry_event(self):
        v.enter(self.s, position())
        bad = deepcopy(self.s)
        events = bad['virtual_events']; events.reverse()
        previous = None
        # Rehashing an invalid ordering must not make it causally valid.
        for index, event in enumerate(events):
            event['seq'] = index; event['previous_sha256'] = previous
            event['event_sha256'] = v.digest({k: value for k, value in event.items() if k != 'event_sha256'})
            previous = event['event_sha256']
        ack = bad['admission_acks'][0]
        ack['source_entry_event_sha256'] = events[1]['event_sha256']
        ack['ack_sha256'] = v.digest({k: value for k, value in ack.items() if k != 'ack_sha256'})
        events[0]['body'] = deepcopy(ack)
        # Invalid cyclic dependency cannot be represented by a valid hash chain;
        # either chain verification or explicit ACK-entry binding must reject it.
        with self.assertRaises(ValueError):
            v.verify(bad)

    def test_real_process_crash_before_commit_rolls_back_events(self):
        with v.Store(self.path) as db:
            db.commit(self.s)
        program = '''
import os,sys
import virtual_shadow_ledger as v
from test_virtual_shadow_ledger import position
s=v.Store(sys.argv[1]);state=s.load();v.enter(state,position())
s.db.create_function('crash',0,lambda:os._exit(23))
s.db.execute('CREATE TEMP TRIGGER crash_checkpoint BEFORE UPDATE ON checkpoint BEGIN SELECT crash(); END')
s.commit(state)
'''
        run = subprocess.run([sys.executable, '-B', '-c', program, str(self.path)], cwd=Path(v.__file__).parent)
        self.assertEqual(run.returncode, 23)
        with v.Store(self.path) as db:
            self.assertEqual(db.load()['virtual_entry_T'], 0)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            recovered = db.load(); v.enter(recovered, position()); db.commit(recovered)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_real_process_crash_after_commit_recovers_without_status(self):
        program = '''
import os,sys
import virtual_shadow_ledger as v
from test_virtual_shadow_ledger import state,position
s=v.Store(sys.argv[1]);x=state();v.enter(x,position());s.commit(x);os._exit(24)
'''
        run = subprocess.run([sys.executable, '-B', '-c', program, str(self.path)], cwd=Path(v.__file__).parent)
        self.assertEqual(run.returncode, 24)
        with v.Store(self.path) as db:
            recovered = db.load(); v.enter(recovered, position()); db.commit(recovered)
            self.assertEqual(recovered['virtual_entry_T'], 1)
            self.assertEqual(db.db.execute('SELECT count(*) FROM events').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
