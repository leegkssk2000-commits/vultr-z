"""Synthetic lifecycle plus sealed warmup-state parity; no market fetches."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import q0_prospective_observer_v1 as observer
from . import test_q0_prospective_weights_v1 as fixture
from . import test_q0_b_seen_adapter_v1 as cost_fixture

DAY, BAR = observer.archive.DAY, observer.archive.INTERVAL


def synthetic_inputs():
    rows = fixture.bars(80)
    path = [100, 100, 100, 100, 100, 100.2, 101, 102, 103, 104,
            99, 99, 99, 101, 102, 105, 105, 104, 103, 102]
    for index, symbol in enumerate(observer.SYMBOLS):
        for day, price in enumerate(path, 60):
            for row in rows[symbol][day * 6:(day + 1) * 6]:
                for field in ('open', 'high', 'low', 'close'):
                    row[field] = price * (1 + index / 100)
    start, end = fixture.START + 65 * DAY, fixture.START + 80 * DAY
    prefix = 65 * 6 - 1
    seed = {s: rs[:prefix] for s, rs in rows.items()}
    boot = {'engine': observer.engine.initialize(seed, observer.SYMBOLS, start, end),
            'weights': observer.weights.initialize(seed, observer.SYMBOLS),
            'observations': {}, 'recordings': [], 'delayed_baskets': [], 'accounting': None}
    costs = {s: deepcopy(cost_fixture.COSTS['BTC-USDT']) for s in observer.SYMBOLS}
    spec = {'receipt_sha256': 'synthetic-spec'}
    policy = {**cost_fixture.POLICY, 'development_interval_ms': [start, end]}
    return rows, prefix, start, end, seed, boot, costs, spec, policy


def packet_for(rows, index, recorded_at=None):
    fire = rows[observer.SYMBOLS[0]][index]['bar_close_ts']
    identity = {'G5_CLEAN_RUNNER_OWNER_ID': observer.archive.SOURCE_OWNER,
                'GITHUB_RUN_ID': str(index), 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_SHA': 'a' * 40}
    capture = observer.capture.Capture(identity)
    for symbol in observer.SYMBOLS:
        row = rows[symbol][index]
        raw = {'time': row['bar_open_ts'], **{k: str(row[k]) for k in
                ('open', 'high', 'low', 'close', 'volume')}}
        source = {'symbol': symbol, 'rows': [row], 'closed_rows': [row],
                  'source_received_ts': fire + 1000,
                  'source_id': 'bingx_usdtm_public_klines', 'stream_id': 'bingx_swap_4h_closed_v1'}
        capture.fetched(source, fire, [{'params': {'symbol': symbol}, 'value': {'data': [raw]},
                                      'received_ms': fire + 1000}],
                        observer.capture.base.BingxSourceAdapter._decode)
    with patch.object(observer.capture.base, 'now_ms', return_value=recorded_at or fire + 1000):
        return capture.packet(0)


class ObserverIntegrationTests(unittest.TestCase):
    def test_sealed_indicator_bootstrap_reproduces_without_historical_economics(self):
        root = observer.ROOT / observer.OUTPUT
        rows = json.loads(gzip.decompress((root / 'warmup.json.gz').read_bytes()))['rows_by_symbol']
        boot = json.loads(gzip.decompress((root / 'bootstrap.json.gz').read_bytes()))
        with patch.object(observer.previous.structure, 'replay', side_effect=AssertionError('NO_ECONOMIC_REPLAY')):
            self.assertEqual(observer.initialize_model(rows), boot)
        self.assertTrue(all(not s['trades'] and not s['events'] and not s['position']
                            for s in boot['engine']['by_symbol'].values()))

    def test_synthetic_capture_archive_channel_entry_exit_accounting_restart_exactly_once(self):
        rows, prefix, start, end, seed, boot, costs, spec, policy = synthetic_inputs()
        seed_end = start - BAR
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(observer, 'T0', start), patch.object(observer, 'TEND', end), \
             patch.object(observer, 'SEED_END', seed_end), \
             patch.object(observer.capture, 'CANONICAL_SEED_END_MS', seed_end), \
             patch.object(observer, 'verify', return_value=(spec, {'rows_by_symbol': seed}, boot, costs)), \
             patch.object(observer, 'policy_for', return_value=policy):
            root = Path(temporary)
            for index in range(prefix, len(rows[observer.SYMBOLS[0]])):
                packet = packet_for(rows, index)
                self.assertEqual(packet['errors'], [])
                status, delta = observer.consume(root, packet,
                    recorded_at=packet['generated_at_ms'] + 10, check_publication=False)
                self.assertTrue(delta['committed'])
            archive = observer.archive.load(root / 'archive')
            state = archive['engine_state']
            self.assertGreater(status['counts']['closed'], 0)
            self.assertEqual(status['phase'], 'COMPLETE')
            self.assertFalse(status['independent'])
            self.assertEqual(status['budget']['candidate_cumulative'], 26)
            self.assertEqual(status['budget']['independent_comparison_used'], 0)
            for symbol in observer.SYMBOLS:
                days = observer.previous.structure.aggregate_daily(rows[symbol])['daily']
                signals = observer.previous.structure.generate_signals(days, eval_start_ms=start, eval_end_ms=end)
                batch = observer.previous.structure.replay(rows[symbol], signals, eval_start_ms=start, eval_end_ms=end)
                self.assertEqual(state['engine']['by_symbol'][symbol]['trades'], batch['trades'])
            self.assertTrue(state['recordings'])
            self.assertTrue(all(r['consumer_recorded_at_ms'] >= r['source_observed_at_ms']
                                and r['actual_fill'] is False for r in state['recordings']))
            before = (root / 'archive' / 'CURRENT.json').read_bytes()
            result, delta = observer.consume(root, packet, recorded_at=end + 2000, check_publication=False)
            self.assertFalse(delta['committed'])
            self.assertEqual((root / 'archive' / 'CURRENT.json').read_bytes(), before)
            self.assertEqual(result, status)
            # Derived status can be repaired after a post-CURRENT write crash.
            (root / 'STATUS.json').unlink()
            result, delta = observer.consume(root, packet, recorded_at=end + 2000, check_publication=False)
            self.assertFalse(delta['committed'])
            self.assertEqual(json.loads((root / 'STATUS.json').read_text()), result)

    def test_source_packet_identity_raw_parity_future_and_capture_errors_rejected(self):
        rows, prefix, start, end, *_ = synthetic_inputs()
        with patch.object(observer, 'SEED_END', start - BAR), \
             patch.object(observer.capture, 'CANONICAL_SEED_END_MS', start - BAR):
            packet = packet_for(rows, prefix)
            observer.validate_packet(packet, start + 2000)
            for mutation in ('identity', 'raw', 'future', 'errors', 'source'):
                broken = deepcopy(packet)
                if mutation == 'identity': broken['records'][0]['run_id'] = 'different'
                elif mutation == 'raw': broken['records'][0]['raw']['close'] = '999'
                elif mutation == 'future': broken['records'][0]['observed_at_ms'] = end
                elif mutation == 'errors': broken['errors'] = [{'code': 'MISSING_RAW_VOLUME'}]
                else: broken['records'][0]['source_id'] = 'another-exchange'
                broken['receipt_sha256'] = observer.capture.base.sha_json(
                    {k: v for k, v in broken.items() if k != 'receipt_sha256'})
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    observer.validate_packet(broken, start + 2000)

    def test_conflict_holds_positions_and_gap_repair_never_rewrites_first_source(self):
        rows, prefix, start, end, seed, boot, costs, spec, policy = synthetic_inputs()
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(observer, 'T0', start), patch.object(observer, 'TEND', end), \
             patch.object(observer, 'SEED_END', start - BAR), \
             patch.object(observer.capture, 'CANONICAL_SEED_END_MS', start - BAR), \
             patch.object(observer, 'verify', return_value=(spec, {'rows_by_symbol': seed}, boot, costs)), \
             patch.object(observer, 'policy_for', return_value=policy):
            root = Path(temporary)
            late = packet_for(rows, prefix + 1)
            status, _ = observer.consume(root, late, recorded_at=start + 2 * BAR, check_publication=False)
            self.assertEqual(status['integrity'], 'GAP_HOLD')
            self.assertEqual(status['cursor_ms'], start - BAR)
            first = packet_for(rows, prefix)
            status, _ = observer.consume(root, first, recorded_at=start + 2 * BAR, check_publication=False)
            self.assertEqual(status['cursor_ms'], start + BAR)
            self.assertTrue(status['delayed_baskets'])
            state_before = observer.archive.load(root / 'archive')['engine_state']['engine']
            altered = deepcopy(rows)
            for field in ('open', 'high', 'low', 'close'):
                altered[observer.SYMBOLS[0]][prefix][field] *= 1.1
            conflict = packet_for(altered, prefix)
            status, _ = observer.consume(root, conflict, recorded_at=start + 2 * BAR, check_publication=False)
            self.assertEqual(status['integrity'], 'CONFLICT_HOLD')
            self.assertEqual(observer.archive.load(root / 'archive')['engine_state']['engine'], state_before)


if __name__ == '__main__':
    unittest.main()
