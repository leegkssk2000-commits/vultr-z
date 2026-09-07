"""Causal boundaries of the read-only diagnostic, not economic-policy tests."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from backend.research.rebuild import primary_entry_diagnostic_v1 as d


class DiagnosticBoundaryTests(unittest.TestCase):
    def test_exit_bar_never_read_and_no_final_mfe(self):
        rows = [{'close':101.,'bar_close_ts':2}, {'close':100.1,'bar_close_ts':3}, object()]
        trade = {'side':'long','entry_price':100.,'entry_index':0,'exit_index':2,'entry_ts':1,'net_bps':-50.,'mfe_bps':999999.}
        with patch.object(d.n.a.old.probe,'cost_components',return_value={'cost_bps':20.}):
            actual = d.close_progress(rows,trade,{})
        self.assertEqual(actual['category'],'ABOVE_COST_COMPLETED_CLOSE')
        self.assertEqual(actual['completed_pre_exit_bars'],2)
        self.assertEqual(actual['first_above_cost_completed_index'],0)

    def test_first_bar_sl_is_unknown(self):
        trade = {'side':'long','entry_price':100.,'entry_index':0,'exit_index':0,'entry_ts':1,'net_bps':-50.}
        self.assertEqual(d.close_progress([object()],trade,{})['category'],'NO_COMPLETED_PRE_EXIT_BAR_UNKNOWN_INTRABAR')

    def test_appended_future_does_not_change_entry_state(self):
        rows = [{'open':98.,'close':99.,'high':100.,'low':97.}, {'open':101.,'close':100.,'high':102.,'low':99.}]
        cache = SimpleNamespace(st=[(95.,1),(96.,1)],ema=[97.,98.],atr=[2.,2.])
        event = {'side':'long','signal_index':1,'signal_ts':2}
        before = d.state_at(rows,cache,event,0)
        rows.append({'open':0.,'close':100000.,'high':100000.,'low':0.})
        cache.st.append((100000.,-1));cache.ema.append(100000.);cache.atr.append(100000.)
        self.assertEqual(before,d.state_at(rows,cache,event,0))
        self.assertEqual(before['signal_body_state'],'ADVERSE')
        with self.assertRaisesRegex(RuntimeError,'PRIOR_OUTCOME_NOT_YET_AVAILABLE'):
            d.state_at(rows,cache,event,0,{'exit_ts':3})


if __name__ == '__main__':
    unittest.main()
