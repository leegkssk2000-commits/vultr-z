"""Synthetic native-engine comparisons, never market performance evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from ops import scalp7_squeeze_signal_low_economics_v1 as candidate
from ops import scalp7_squeeze_signal_low_successor_v1 as preparation

TF = 1_800_000
SYMBOL = 'BTC-USDT'


def bars():
    rows = [dict(open_ts_ms=i*TF, close_ts_ms=(i+1)*TF, available_ts_ms=(i+1)*TF,
                 segment_id='A', open=103.0, high=104.0, low=101.0, close=103.0)
            for i in range(16)]
    rows[0]['low'] = 100.0
    rows[1].update(low=98.0, close=99.0)
    rows[2].update(open=97.0, high=99.0, low=96.0, close=98.0)
    return pd.DataFrame(rows)


def signal(regime='TREND_DISPERSED', opened=0):
    return dict(identity=positive.SQUEEZE_PARENT, lane='squeeze_break', symbol=SYMBOL,
                timeframe_min=30, side=1, signal_open_ts_ms=opened,
                signal_ts_ms=opened+TF, segment_id='A', stop_price=90.0,
                max_hold_bars=11, take_profit_r=None,
                meta=dict(regime=regime, be_arm_r=None, frozen_cost_bps=14.0,
                          fallback_stop_atr_mult=2.0,
                          entry_cost_gate=dict(atr_price=2.0, min_ratio=4.0)))


def run(signals, frame, enabled=True):
    return candidate.replay_window(signals, {SYMBOL: frame}, {SYMBOL: 14.0}, enabled=enabled)


class SqueezeSignalLowEconomicsTests(unittest.TestCase):
    def test_all_economic_dependencies_match_actual_frozen_sources(self):
        contract = json.loads(candidate.CONTRACT.read_text())
        candidate._verify_source_pins(contract, candidate.ROOT)

    def test_omitted_result_dependency_cannot_weaken_runtime_pins(self):
        contract = json.loads(candidate.CONTRACT.read_text())
        contract['frozen_source_git_blob_sha1'].pop('backend/research/rebuild/scalp7_metrics_v2.py')
        with self.assertRaisesRegex(ValueError, 'DEPENDENCY_COVERAGE'):
            candidate._verify_source_pins(contract, candidate.ROOT)

    def test_mutated_result_dependency_fails_closed(self):
        import shutil
        contract = json.loads(candidate.CONTRACT.read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in candidate.REQUIRED_SOURCE_PINS:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate.ROOT / name, target)
            target = root / 'ops/scalp7_keltner_fresh_touch_successor_v1.py'
            target.write_bytes(target.read_bytes() + b'\n# changed aggregation\n')
            with self.assertRaisesRegex(ValueError, 'FROZEN_SOURCE_CHANGED'):
                candidate._verify_source_pins(contract, root)

    def test_disabled_synthetic_control_exact_frozen_engine_parity(self):
        frame, signals = bars(), [signal(), signal(opened=TF)]
        expected = execution.replay(signals, {SYMBOL: frame}, {SYMBOL: 14.0},
            identity=positive.SQUEEZE_PARENT, exit_update=positive.exit_update,
            entry_update=positive.entry_update)
        observed = run(signals, frame, enabled=False)
        for key in ('trades', 'unresolved', 'rejections', 'signal_count'):
            self.assertEqual(observed[key], expected[key])

    def test_panic_trade_unresolved_and_occupancy_unchanged(self):
        frame, signals = bars(), [signal('PANIC_DISPERSION'), signal('PANIC_DISPERSION', TF)]
        new, old = run(signals, frame), run(signals, frame, enabled=False)
        for key in ('trades', 'unresolved', 'rejections', 'admitted_entry_ts_ms'):
            self.assertEqual(new[key], old[key])
        self.assertEqual(new['traces'], [])

    def test_new_exit_uses_actual_next_open_not_signal_low(self):
        result = run([signal()], bars())
        trade = result['trades'][0]
        self.assertEqual(trade['reason'], preparation.EXIT_REASON)
        self.assertEqual(trade['exit_prices'][SYMBOL], 97.0)
        self.assertEqual(trade['exit_ts_ms'], 2*TF)
        self.assertEqual(result['traces'][0]['frozen_signal_low'], 100.0)

    def test_current_bar_stop_still_wins(self):
        frame = bars()
        frame.loc[1, 'low'] = 89.0
        result = run([signal()], frame)
        self.assertEqual(result['trades'][0]['reason'], 'STOP_FIRST')
        self.assertEqual(result['trades'][0]['exit_prices'][SYMBOL], 90.0)
        self.assertEqual(result['traces'], [])

    def test_pending_exit_gap_stop_wins_and_blocks_same_open_reentry(self):
        frame = bars()
        frame.loc[2, ['open', 'high', 'low', 'close']] = [85.0, 89.0, 84.0, 88.0]
        result = run([signal(), signal(opened=TF)], frame)
        old = run([signal()], frame, enabled=False)['trades'][0]
        new = result['trades'][0]
        for key in ('reason', 'entry_ts_ms', 'exit_ts_ms', 'outcome_available_ts_ms',
                    'exit_prices', 'gross_bps', 'cost_bps', 'net_bps', 'hold_bars',
                    'hold_minutes', 'outcome_time_precision'):
            self.assertEqual(new[key], old[key], key)
        self.assertEqual(result['rejections'].get('POSITION_ALREADY_OWNED'), 1)
        self.assertEqual(result['traces'][0]['ownership_until_ms'], 3*TF)

    def test_exact_stop_at_exit_open_preserves_stop_clock(self):
        frame = bars()
        frame.loc[2, ['open', 'high', 'low', 'close']] = [90.0, 94.0, 89.0, 93.0]
        new = run([signal()], frame)['trades'][0]
        old = run([signal()], frame, enabled=False)['trades'][0]
        for key in ('reason', 'exit_ts_ms', 'outcome_available_ts_ms', 'hold_bars', 'hold_minutes', 'net_bps'):
            self.assertEqual(new[key], old[key], key)

    def test_synthetic_loss_reduction_is_counted(self):
        frame = bars()
        frame.loc[3, ['open', 'high', 'low', 'close']] = [95.0, 97.0, 89.0, 92.0]
        old = run([signal()], frame, enabled=False)['trades']
        new = run([signal()], frame)['trades']
        report = candidate.exit_attribution(old, new, 2.0)
        self.assertGreater(report['total_net_delta_bps'], 0)
        self.assertEqual(report['common_trade_changes']['loss_reduced']['T'], 1)

    def test_synthetic_false_break_winner_sacrifice_is_not_hidden(self):
        frame = bars()
        frame.loc[12, ['open', 'high', 'low', 'close']] = [120.0, 121.0, 119.0, 120.0]
        old = run([signal()], frame, enabled=False)['trades']
        new = run([signal()], frame)['trades']
        report = candidate.exit_attribution(old, new, 2.0)
        self.assertLess(report['total_net_delta_bps'], 0)
        self.assertEqual(report['common_trade_changes']['winner_sacrificed']['T'], 1)

    def test_earlier_exit_changes_later_occupancy_not_only_saved_trade_pnl(self):
        frame = bars()
        frame.loc[3, ['open', 'high', 'low', 'close']] = [95.0, 97.0, 89.0, 92.0]
        signals = [signal(), signal(opened=TF)]
        old, new = run(signals, frame, enabled=False), run(signals, frame)
        self.assertEqual(len(old['trades']), 1)
        self.assertEqual(len(new['trades']), 2)
        report = candidate.exit_attribution(old['trades'], new['trades'], 1.0)
        self.assertEqual(report['added_T'], 1)
        self.assertAlmostEqual(report['total_net_delta_bps'],
            sum(t['net_bps'] for t in new['trades']) - sum(t['net_bps'] for t in old['trades']))

    def test_gap_after_invalidation_stays_unresolved_and_owned(self):
        frame = bars().drop(index=2).reset_index(drop=True)
        result = run([signal(), signal(opened=4*TF)], frame)
        self.assertEqual(len(result['unresolved']), 1)
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['rejections'].get('POSITION_ALREADY_OWNED'), 1)
        self.assertEqual(result['traces'][0]['disposition'], 'UNRESOLVED_NEXT_OPEN')

    def test_window_end_cannot_borrow_following_bar(self):
        windows = [dict(label='w', partition='rolling', start_ms=TF, end_ms=2*TF)]
        result = candidate.replay_windows([signal()], {SYMBOL: bars()}, {SYMBOL: 14.0}, windows)
        self.assertEqual(result['trades'], [])
        self.assertEqual(len(result['unresolved']), 1)
        self.assertEqual(len(result['admitted_entry_ts_ms']), 1)

    def test_outcome_equal_end_excluded_but_admitted_count_kept(self):
        frame = bars()
        frame.loc[1, 'low'] = 89.0
        windows = [dict(label='w', partition='rolling', start_ms=TF, end_ms=2*TF)]
        result = candidate.replay_windows([signal()], {SYMBOL: frame}, {SYMBOL: 14.0}, windows)
        self.assertEqual(result['trades'], [])
        self.assertEqual(len(result['boundary_excluded']), 1)
        self.assertEqual(len(result['admitted_entry_ts_ms']), 1)

    def test_late_bar_does_not_create_historical_exit(self):
        frame = bars()
        frame.loc[1, 'available_ts_ms'] = 2*TF + 1
        result = run([signal()], frame)
        self.assertEqual(result['trades'], [])
        self.assertEqual(len(result['unresolved']), 1)
        self.assertEqual(result['traces'], [])

    def test_inputs_unmodified(self):
        frame, sig = bars(), signal()
        old_frame, old_signal = frame.copy(deep=True), deepcopy(sig)
        run([sig], frame)
        pd.testing.assert_frame_equal(frame, old_frame)
        self.assertEqual(sig, old_signal)

    def test_duplicate_signal_matches_native_rejection(self):
        sig = signal()
        result = run([sig, deepcopy(sig)], bars())
        self.assertEqual(result['rejections']['DUPLICATE_SIGNAL'], 1)
        self.assertEqual(len(result['trades']), 1)

    def test_wrong_identity_or_timeframe_never_reaches_economics(self):
        for field, value in (('identity', 'other'), ('side', -1), ('timeframe_min', 15)):
            sig = signal()
            sig[field] = value
            with self.assertRaises(ValueError):
                run([sig], bars())

    def test_report_exclusive_write_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            report = candidate._publish({'state': 'SYNTHETIC_ONLY', 'value': 1}, path)
            self.assertEqual(report['receipt_sha256'], candidate._digest(report))
            self.assertEqual(json.loads(path.read_text()), report)
            with self.assertRaises(FileExistsError):
                candidate._publish({'state': 'REPLACEMENT_FORBIDDEN'}, path)
            self.assertEqual(json.loads(path.read_text()), report)

    def test_attribution_rejects_duplicated_trade_keys(self):
        rows = run([signal()], bars())['trades']
        with self.assertRaises(ValueError):
            candidate.exit_attribution(rows + rows, rows, 1.0)

    def test_missing_ordered_keltner_evidence_fails_before_source_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            receipt = {'state': 'WRONG_IDENTITY'}
            receipt['receipt_sha256'] = candidate._digest(receipt)
            (path / 'k.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'KELTNER_ORDERED_RESULT_REQUIRED'):
                candidate.compare(path / 'absent', path / 'absent.json', path / 'out.json',
                    keltner_result=path / 'k.json', claim_id='synthetic-test-only')


if __name__ == '__main__':
    unittest.main()
