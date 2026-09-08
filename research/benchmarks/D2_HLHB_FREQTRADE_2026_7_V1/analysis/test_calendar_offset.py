"""Synthetic calendar/cache alignment regression. No economic engine replay."""
import sys
from pathlib import Path
import unittest
from types import SimpleNamespace

import pandas as pd
from freqtrade.data.dataprovider import DataProvider
from freqtrade.enums import RunMode, CandleType

ROOT = Path('/workspace/scratch/91d255a1335a')
sys.path.insert(0, str(ROOT / 'vultr-z-external/research/benchmarks/D2_HLHB_FREQTRADE_2026_7_V1'))
from D2Independent import D2Independent, BAR


class CalendarCacheOffset(unittest.TestCase):
    def test_cropped_engine_index_on_full_cache_is_stale_and_guard_rejects(self):
        dates = pd.date_range('2020-01-01', periods=400, freq='4h', tz='UTC')
        df = pd.DataFrame({'date': dates, 'zel_index': range(400), 'low': 90.0})
        config = {'runmode': RunMode.BACKTEST, 'timeframe': '4h', 'candle_type_def': CandleType.SPOT,
                  'zel_start_ms': int(dates[300].timestamp() * 1000),
                  'zel_end_ms': int(dates[-1].timestamp() * 1000) + BAR}
        strategy = D2Independent(config)
        dp = DataProvider(config, None)
        strategy.dp = dp
        # Match FT _get_ohlcv_as_lists cache-before-trim and
        # time_pair_generator(required_startup + cropped_row_index).
        dp._set_cached_df('SYNTH/USDT', '4h', df, CandleType.SPOT)
        cropped_prefix = 300
        anchor = 320
        callback_max_index = anchor - cropped_prefix + 1
        dp._set_dataframe_max_index('SYNTH/USDT', callback_max_index)
        when = dates[anchor + 1].to_pydatetime()
        row = strategy._latest('SYNTH/USDT', when)
        self.assertEqual(int(row['zel_index']), 20)
        trade = SimpleNamespace(id=1, enter_tag='d2:314:320', open_rate=100.0,
                                entry_side='buy', exit_side='sell')
        with self.assertRaisesRegex(ValueError, 'D2_ENTRY_FEATURE_CALLBACK_TIME_MISMATCH'):
            strategy.order_filled('SYNTH/USDT', trade, SimpleNamespace(ft_order_side='buy'), when)
        self.assertEqual(strategy._held, {})
        self.assertEqual(strategy.audit['entries'], [])

    def test_aligned_synthetic_cache_returns_intended_completed_row(self):
        dates = pd.date_range('2020-01-01', periods=400, freq='4h', tz='UTC')
        df = pd.DataFrame({'date': dates, 'zel_index': range(400), 'low': 90.0})
        config = {'runmode': RunMode.BACKTEST, 'timeframe': '4h', 'candle_type_def': CandleType.SPOT,
                  'zel_start_ms': int(dates[300].timestamp() * 1000),
                  'zel_end_ms': int(dates[-1].timestamp() * 1000) + BAR}
        strategy = D2Independent(config)
        dp = DataProvider(config, None)
        strategy.dp = dp
        # Only a comparison of the alignment contract on synthetic frames;
        # no frozen benchmark code or market data is changed.
        dp._set_cached_df('SYNTH/USDT', '4h', df.iloc[300:], CandleType.SPOT)
        dp._set_dataframe_max_index('SYNTH/USDT', 21)
        self.assertEqual(int(strategy._latest('SYNTH/USDT', dates[321].to_pydatetime())['zel_index']), 320)


if __name__ == '__main__':
    unittest.main()
