"""Synthetic mathematical counterexamples, no stored economic execution."""
import unittest
from backend.research.rebuild import step7_design_feasibility_v1 as m


def node(i,start,end,*,kind='actual',net=1,signal=None):
    return dict(id=str(i),start=start,end=end,kind=kind,net=net,closed=end is not None,
                signal_ts=start if signal is None else signal,symbol=str(i))


class DesignTests(unittest.TestCase):
    def test_chained_overlap_collapses_raw_sample(self):
        rows=[node(i,i*10,i*10+11,net=i) for i in range(100)]
        groups=m.components(rows,same_signal_day=False)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['actual_T'],100)
        self.assertIsNone(m.summarize_components(groups,0,m.DAY)['sigma_component_mean_trade_bps'])

    def test_reference_can_bridge_but_never_earn_zero_returns(self):
        rows=[node(1,0,1,net=8),node(2,3,4,net=12),node(3,1,3,kind='reference',net=None)]
        g=m.components(rows,same_signal_day=False)[0]
        self.assertEqual((g['actual_T'],g['reference_T'],g['component_mean_net_trade_bps']),(2,1,10))

    def test_open_tail_cannot_be_dropped_for_sigma(self):
        g=m.components([node(0,0,None),node(1,1,3)],same_signal_day=False)[0]
        self.assertFalse(g['complete']);self.assertIsNone(g['component_mean_net_trade_bps'])

    def test_power_boundary_not_alternative(self):
        self.assertIsNone(m.required_n(100,null_bps=5,alternative_bps=5)['N'])
        self.assertEqual(m.required_n(100,null_bps=5,alternative_bps=10)['N'],
                         m.required_n(100,null_bps=0,alternative_bps=5)['N'])

    def test_no_occupancy_reset_at_calendar_boundary(self):
        g=m.components([node(1,29*m.DAY,31*m.DAY),node(2,30*m.DAY,32*m.DAY)],same_signal_day=False)
        s=m.summarize_components(g,0,60*m.DAY)
        self.assertEqual([b['N_complete_components'] for b in s['calendar_cohort_buckets_without_occupancy_reset']],[1,0])


if __name__=='__main__':unittest.main()
