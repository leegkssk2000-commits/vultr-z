"""Actual FT engine on artificial prices only; no market data or economic reruns."""
import sys
from pathlib import Path
import json
import tempfile
import unittest
import pandas as pd

ROOT = Path('/workspace/scratch/91d255a1335a')
FROZEN = ROOT / 'vultr-z-external/research/benchmarks/D2_HLHB_FREQTRADE_2026_7_V1'
sys.path.insert(0, str(FROZEN))
from D2Independent import D2Independent
from offline_engine import external_class, BAR
from engine_view_fix import aligned_view, run_frame_aligned

RECEIPTS = []


def frame(kind):
    dates = pd.date_range('2003-01-01', periods=360, freq='4h', tz='UTC')
    if kind == 'D2':
        close = [100 + j * .08 + (2 if j % 9 == 0 else -2 if j % 9 == 1 else 0) for j in range(360)]
    else:
        close = [100 - .2 * (j % 60) + (20 if j % 60 >= 30 else 0) for j in range(360)]
    return pd.DataFrame({'date': dates, 'open': close, 'close': close,
                         'high': [x + .1 for x in close], 'low': [x - .1 for x in close],
                         'volume': 100.0})


class EngineViewFix(unittest.TestCase):
    def execute(self, kind):
        data = frame(kind)
        start = int(data.date.iloc[120].timestamp() * 1000)
        end = int(data.date.iloc[-1].timestamp() * 1000) + BAR
        strategy = D2Independent if kind == 'D2' else external_class(FROZEN / 'hlhb.py')
        with tempfile.TemporaryDirectory(prefix='zel-alignment-synthetic-') as work:
            result, signals, audit, resolved, config, markets = run_frame_aligned(strategy, {'SYNTH/USDT': data}, start, end, work)
        trades = result['results']
        self.assertGreater(len(trades), 0, 'nonvacuous synthetic entries required')
        outside = [int(t['open_date'].timestamp() * 1000) for t in trades.to_dict('records')
                   if not start <= int(t['open_date'].timestamp() * 1000) < end]
        self.assertEqual(outside, [])
        if audit is not None:
            self.assertEqual(audit['callback_errors'], [])
            self.assertEqual(len(audit['entries']), len(trades))
            self.assertTrue(all(t['decision_index'] >= 239 for t in audit['entries']))
        RECEIPTS.append({'strategy': kind, 'synthetic_only': True, 'market_data_reads': 0,
                         'economic_runs': 0, 'market_data_validation': 'UNEXECUTED_ON_MARKET_DATA',
                         'evaluation_start_original_index': 120, 'original_prefix_length': 360,
                         'required_startup': resolved['engine_required_startup'],
                         'trade_count': len(trades), 'entry_outside_boundary': outside,
                         'callback_errors': [] if audit is None else audit['callback_errors'],
                         'entry_callbacks': None if audit is None else len(audit['entries']),
                         'exit_reasons': trades['exit_reason'].value_counts().to_dict()})

    def test_d2_nonzero_calendar_callback_alignment(self):
        self.execute('D2')

    def test_hlhb_nonzero_calendar_no_preperiod_entries(self):
        self.execute('HLHB')

    def test_view_preserves_features_and_origin_coordinates(self):
        data = frame('D2')
        data['zel_index'] = range(len(data))
        data['frozen_feature'] = [1.2345 + j for j in range(len(data))]
        start = int(data.date.iloc[120].timestamp() * 1000)
        for startup, first in [(0, 119), (30, 89)]:
            view = aligned_view({'SYNTH/USDT': data}, start, startup)['SYNTH/USDT']
            pd.testing.assert_frame_equal(view, data.iloc[first:])


if __name__ == '__main__':
    program = unittest.main(exit=False)
    if program.result.wasSuccessful():
        (Path(__file__).parent / 'SYNTHETIC_ENGINE_VIEW_FIX.json').write_text(json.dumps(RECEIPTS, indent=2) + '\n')
    sys.exit(not program.result.wasSuccessful())
