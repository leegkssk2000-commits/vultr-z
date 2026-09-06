"""Lookahead, exact next-open fills, funding and scope boundaries."""
import copy
import unittest
from unittest.mock import patch
from backend.research.rebuild import supertrend_signal_invalidation_v1 as x
from backend.research.rebuild.test_top5_no_credit_exit_v1 import example, policy, costs


def fixture(terminal=6):
    rows,t,e=example(terminal=terminal)
    t['lane_id']=x.LANE
    e.pop('sl')  # The tested V2 parent has no protective stop specification.
    rows[0]['low']=99.5
    rows[1]['close']=100.
    rows[2]['close']=99.
    rows[3]['open']=98.5
    return rows,t,e


class Causality(unittest.TestCase):
    def test_close_signal_fills_next_open_and_keeps_entry(self):
        rows,t,e=fixture(); out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_index'],3)
        self.assertEqual(out['exit_price'],98.5)
        self.assertEqual(out['exit_ts'],3*x.prior.HOUR)
        self.assertEqual(out['entry_price'],t['entry_price'])
        self.assertIsNone(out['original_protective_sl'])

    def test_intrabar_low_and_equal_close_do_not_trigger(self):
        rows,t,e=fixture()
        for r in rows[1:]:r.update(close=99.5,low=1.)
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertFalse(out['exit_overlay']['exit_changed'])

    def test_future_outcomes_and_exit_bar_extremes_cannot_change_fill(self):
        rows,t,e=fixture();a=x.overlay(t,e,rows,policy(),costs(),'child')
        other=copy.deepcopy(rows)
        for r in other[3:]: r.update(close=9000.,high=10000.,low=.01)
        b=x.overlay(dict(t,net_bps=999999,mfe_bps=999999,exit_price=1.),e,other,policy(),costs(),'child')
        for k in ('exit_index','exit_ts','exit_price','net_bps','mfe_bps','mae_bps','exit_overlay'):
            self.assertEqual(a[k],b[k])

    def test_native_terminal_prevents_late_trigger(self):
        rows,t,e=fixture(terminal=2)
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertFalse(out['exit_overlay']['exit_changed'])
        self.assertEqual(out['exit_ts'],t['exit_ts'])

    def test_gap_open_is_observed_price_not_signal_low(self):
        rows,t,e=fixture();rows[3]['open']=90.
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['exit_price'],90.)
        self.assertAlmostEqual(out['gross_bps'],-1000.)

    def test_funding_recomputed_with_unchanged_cost_floor(self):
        rows,t,e=fixture(terminal=9)
        out=x.overlay(t,e,rows,policy(),costs(),'child')
        self.assertEqual(out['funding_settlements_crossed'],0)
        self.assertEqual(out['cost_bps'],20.)
        self.assertEqual(out['cost2x_net_bps'],out['gross_bps']-40.)

    def test_disabled_ablation_and_wrong_lane(self):
        rows,t,e=fixture();out=x.overlay(t,e,rows,policy(),costs(),'base',False)
        x.prior.assert_parent_parity([out],[t])
        with self.assertRaisesRegex(RuntimeError,'UNAUTHORIZED_LANE'):
            x.overlay(dict(t,lane_id='keltner_trend_main'),e,rows,policy(),costs(),'child')

    def test_unavailable_level_and_data_gap_block(self):
        rows,t,e=fixture()
        with self.assertRaisesRegex(RuntimeError,'NOT_AVAILABLE'):
            x.overlay(dict(t,entry_ts=0),e,rows,policy(),costs(),'child')
        rows[3]['bar_open_ts']+=1
        with self.assertRaisesRegex(RuntimeError,'NONCONTIGUOUS'):
            x.overlay(t,e,rows,policy(),costs(),'child')

    def test_frozen_scope_preserves_budget_and_authority(self):
        c=x.authorize()
        self.assertEqual(c['scope']['additional_trial_budget'],1)
        self.assertFalse(c['scope']['prior_trial_budgets_reset'])
        changed=copy.deepcopy(c);changed['scope']['validation_access']=True
        original=x.old.read
        with patch.object(x.old,'read',lambda p:changed if p==x.CONTRACT else original(p)), patch.object(x.old.probe,'verify_seal'):
            with self.assertRaisesRegex(RuntimeError,'SCOPE'):
                x.authorize()


if __name__=='__main__':unittest.main()
