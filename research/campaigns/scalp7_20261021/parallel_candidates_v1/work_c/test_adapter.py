"""Synthetic integration tests. No actual-price source loading or execution."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

HERE = Path(__file__).resolve().parent
handle = importlib.util.spec_from_file_location('work_c_integration', HERE / 'adapter.py')
a = importlib.util.module_from_spec(handle)
handle.loader.exec_module(a)
TF = 900_000
SYMBOL = 'BTC-USDT'


def frames(candles=None):
    candles = candles or [(100, 100.2, 99.8, 100)] * 8
    return {SYMBOL: pd.DataFrame([
        dict(open_ts_ms=i*TF, close_ts_ms=(i+1)*TF, available_ts_ms=(i+1)*TF,
             segment_id='s0', open=o, high=h, low=l, close=c)
        for i, (o, h, l, c) in enumerate(candles)])}


def signal(i=0, **updates):
    row = dict(identity='synthetic_candidate', lane='synthetic_only', symbol=SYMBOL,
               timeframe_min=15, signal_open_ts_ms=i*TF, signal_ts_ms=(i+1)*TF,
               segment_id='s0', side=1, stop_price=99., max_hold_bars=2,
               take_profit_r=2., meta={'feature_available_ts_ms':(i+1)*TF})
    row.update(updates)
    return row


def module(signals):
    return SimpleNamespace(IDENTITY='synthetic_candidate', TIMEFRAME_MIN=15,
                           generate_signals=lambda _:deepcopy(signals),
                           exit_update=lambda p,b,h:{'exit_next_open':False})


def windows(end=8*TF):
    return [dict(start_ms=0, end_ms=end, label='rolling_test', partition='rolling')]


class NativeIntegrationTests(unittest.TestCase):
    def replay(self, rows=None, bars=None, ws=None, costs=None):
        return a.replay_candidate(module([signal()] if rows is None else rows),
                                  bars or frames(), costs or {SYMBOL:10.}, ws or windows())

    def test_frozen_dependencies_match_without_price_read(self):
        with patch.object(a.source, 'load_candles', side_effect=AssertionError('price read')):
            self.assertEqual(a.verify_shared_freeze()['economic_executions_in_this_work'], 0)

    def test_normal_target_uses_native_fee_and_same_fill_stress(self):
        bars=frames([(100,100.2,99.8,100),(100,102.5,99.5,102)]+[(102,102.2,101.8,102)]*6)
        out=self.replay(bars=bars)
        self.assertEqual(len(out['trades']),1)
        trade=out['trades'][0]
        self.assertEqual(trade['reason'],'TARGET')
        self.assertEqual(trade['entry_ts_ms'],TF)
        self.assertAlmostEqual(trade['gross_bps'],200.)
        self.assertAlmostEqual(trade['net_bps'],190.)
        self.assertAlmostEqual(out['partitions']['rolling']['cost2x']['Net_bps'],180.)

    def test_stop_precedes_same_bar_target(self):
        bars=frames([(100,100.2,99.8,100),(100,103,98,102)]+[(102,103,101,102)]*6)
        trade=self.replay(bars=bars)['trades'][0]
        self.assertEqual(trade['reason'],'STOP_FIRST')
        self.assertEqual(trade['exit_prices'][SYMBOL],99.)

    def test_gap_stop_at_open(self):
        bars=frames([(100,100.2,99.8,100),(100,100.5,99.5,100),(98,98.5,97,98)]+[(98,98.5,97.5,98)]*5)
        trade=self.replay(bars=bars)['trades'][0]
        self.assertEqual(trade['reason'],'OPEN_GAP_STOP')
        self.assertEqual(trade['exit_prices'][SYMBOL],98.)

    def test_entry_gap_invalidates_stop_instead_of_fabricating_fill(self):
        bars=frames([(100,100.2,99.8,100)]+[(98,98.5,97.5,98)]*7)
        out=self.replay(bars=bars)
        self.assertEqual(out['trades'],[])
        self.assertEqual(out['window_receipts'][0]['rejections']['ENTRY_INVALIDATES_STOP'],1)

    def test_duplicate_signal_is_one_event(self):
        out=self.replay(rows=[signal(),signal()])
        self.assertEqual(len(out['trades']),1)
        self.assertEqual(out['window_receipts'][0]['rejections']['DUPLICATE_SIGNAL'],1)

    def test_no_signal_is_explicit_zero_not_missing_result(self):
        out=self.replay(rows=[])
        self.assertEqual(out['partitions']['rolling']['cost1x']['T'],0)
        self.assertEqual(out['partitions']['rolling']['cost1x']['PF_null_reason'],'NO_TRADES')
        self.assertEqual(out['partitions']['rolling']['calendar_days'],8*TF/a.DAY_MS)

    def test_missing_bar_leaves_open_ownership_unresolved(self):
        bars=frames()
        bars[SYMBOL]=bars[SYMBOL].drop(index=2).reset_index(drop=True)
        out=self.replay(bars=bars,rows=[signal(),signal(4)])
        self.assertEqual(out['trades'],[])
        self.assertEqual(len(out['unresolved']),1)
        self.assertEqual(out['window_receipts'][0]['rejections']['POSITION_ALREADY_OWNED'],1)
        self.assertEqual(out['unresolved'][0]['exclusion'],'NO_SYNTHETIC_EXIT_NO_REALIZED_PNL')

    def test_end_does_not_force_close(self):
        out=self.replay(rows=[signal(max_hold_bars=20)])
        self.assertEqual(out['trades'],[])
        self.assertEqual(len(out['unresolved']),1)

    def test_exact_boundary_completed_trade_excluded(self):
        # max hold2 schedules next open at3TF, excluded at end=3TF (no next bar).
        out=self.replay(ws=windows(3*TF))
        self.assertEqual(len(out['unresolved']),1)
        bars=frames([(100,100.2,99.8,100),(100,100.2,99.8,100),(100,102.5,99.5,102)]+[(102,102.5,101.5,102)]*5)
        out=self.replay(bars=bars,ws=windows(3*TF))
        self.assertEqual(out['trades'],[])
        self.assertEqual(len(out['boundary_excluded']),1)

    def test_validation_and_rolling_separate_and_flat_reset(self):
        ws=[dict(start_ms=0,end_ms=4*TF,label='validation',partition='validation'),
            dict(start_ms=4*TF,end_ms=8*TF,label='rolling',partition='rolling')]
        out=self.replay(rows=[signal(max_hold_bars=20),signal(4)],ws=ws)
        self.assertEqual(len(out['unresolved']),1)
        self.assertEqual(out['partitions']['validation']['cost1x']['T'],0)
        self.assertEqual(out['partitions']['rolling']['cost1x']['T'],1)

    def test_sides_are_reported_separately(self):
        out=self.replay()
        self.assertEqual(out['partitions']['rolling']['by_side']['1']['cost1x']['T'],1)
        self.assertEqual(out['partitions']['rolling']['by_side']['-1']['cost1x']['T'],0)

    def test_feature_after_signal_rejected(self):
        with self.assertRaisesRegex(ValueError,'FEATURE_AVAILABILITY'):
            self.replay(rows=[signal(meta={'feature_available_ts_ms':TF+1})])

    def test_identity_drift_rejected(self):
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_TF_DRIFT'):
            self.replay(rows=[signal(identity='another_identity')])

    def test_overlapping_windows_rejected(self):
        with self.assertRaisesRegex(ValueError,'WINDOWS_OVERLAP'):
            self.replay(ws=windows()+windows())

    def test_missing_cost_not_assumed_zero(self):
        with self.assertRaises(KeyError):
            self.replay(costs={'ETH-USDT':10.})

    def test_late_signal_not_backfilled_at_historical_open(self):
        out=self.replay(rows=[signal(signal_ts_ms=TF+1)])
        self.assertEqual(out['trades'],[])
        self.assertEqual(out['window_receipts'][0]['rejections']['LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL'],1)

    def test_actual_c2_candidate_through_shared_native_runner(self):
        c2, _ = a.load_candidate('c2_failed_downside_reclaim', verify=False)
        tf = 1_800_000
        candles = ([(100,110,90,100)] + [(100,110,95,100)]*19
                   + [(98,100,88,89),(89,94,89,92),(92,102,91,101),(101,102,100,101)])
        bars = {SYMBOL:pd.DataFrame([
            dict(open_ts_ms=i*tf,close_ts_ms=(i+1)*tf,available_ts_ms=(i+1)*tf,
                 segment_id='synthetic',open=o,high=h,low=l,close=c)
            for i,(o,h,l,c) in enumerate(candles)])}
        out = a.replay_candidate(c2,bars,{SYMBOL:10.},[
            dict(start_ms=0,end_ms=25*tf,label='synthetic',partition='rolling')])
        self.assertEqual(len(out['trades']),1)
        trade = out['trades'][0]
        self.assertEqual(trade['reason'],'FROZEN_MIDPOINT_CLOSE')
        self.assertEqual(trade['entry_ts_ms'],22*tf)
        self.assertEqual(trade['exit_ts_ms'],23*tf)
        self.assertEqual(trade['cost_bps'],10.)

    def test_candidate_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError,'DIRECTORY_NAME'):
            a.load_candidate('../outside')

    def _candidate_fixture(self, name):
        handle = importlib.util.spec_from_file_location('fixture_' + name, HERE / name / 'test_adapter.py')
        fixture = importlib.util.module_from_spec(handle)
        handle.loader.exec_module(fixture)
        return fixture

    def test_actual_c1_candidate_through_shared_native_runner(self):
        c1, _ = a.load_candidate('c1_box_rotation')
        f = self._candidate_fixture('c1_box_rotation')
        bars = f.frame(f.setup() + [(103,105,102,104),(104,106,103,105.5),(106,107,105,106)])
        out = a.replay_candidate(c1,{SYMBOL:bars},{SYMBOL:15.},[
            dict(start_ms=0,end_ms=17*f.TF,label='synthetic',partition='rolling')])
        self.assertEqual(len(out['trades']),1)
        self.assertEqual(out['trades'][0]['reason'],'BOX_CENTER_CLOSE_NEXT_OPEN')

    def test_actual_c3_candidate_through_shared_native_runner(self):
        c3, _ = a.load_candidate('c3_mtf_inside_continuation')
        f = self._candidate_fixture('c3_mtf_inside_continuation')
        bars = f.fixture([(113,124,112,120)])
        out = a.replay_candidate(c3,{SYMBOL:bars},{SYMBOL:15.},[
            dict(start_ms=0,end_ms=17*f.STEP,label='synthetic',partition='rolling')])
        self.assertEqual(len(out['trades']),1)
        self.assertEqual(out['trades'][0]['reason'],'TARGET')


if __name__=='__main__':
    unittest.main()
