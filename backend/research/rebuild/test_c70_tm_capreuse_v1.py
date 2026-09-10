"""Artificial-price capacity, timing, prefix and weighted-cash acceptance."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import fsum
from unittest.mock import patch
import unittest
from backend.research.rebuild import c70_tm_capreuse_v1 as e
from backend.research.rebuild import c70_tm_capreuse_account_v1 as a
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST, POLICY, rows_of


def run_fixture(entries, *, n=150, bars=None, features=None, enabled=True):
    b,s,f=fixture(n=n)
    b=b if bars is None else bars;f=f if features is None else features
    signals=[dict(s,signal_index=j-1,signal_ts=j*e.tm.BAR,setup_id=str(j)) for j in entries]
    obs=dict(eligible=True,reason=None,range_context=dict(rescued=False))
    with patch.object(e.tm.native,'m1_setups',return_value=(signals,[],f)), \
         patch.object(e.tm.c63,'context',return_value=obs), \
         patch.object(e.tm,'c70_context',side_effect=lambda original,daily:original):
        return e.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*e.tm.BAR,cost=COST,enabled=enabled)


class CapacityTests(unittest.TestCase):
    def test_off_is_exact_pr1260_delegation(self):
        sentinel={'frozen_parent':True}
        with patch.object(e.tm,'replay',return_value=sentinel) as call:
            self.assertIs(e.replay([],eval_start_ms=0,eval_end_ms=1,cost=COST,enabled=False),sentinel)
            call.assert_called_once_with([],parent='C70_LOCAL',eval_start_ms=0,eval_end_ms=1,cost=COST)
    def test_pre_partial_all_admission_matches_parent(self):
        on=run_fixture([60,70,77,78]);off=run_fixture([60,70,77,78],enabled=False)
        self.assertEqual([(x['admission'],x['exclusion_reason']) for x in on['events']],
                         [(x['admission'],x['exclusion_reason']) for x in off['events']])
    def test_partial_decision_and_equal_timestamp_fill_do_not_release_early(self):
        r=run_fixture([60,78,79])
        self.assertEqual(r['events'][1]['available_capacity'],0)
        self.assertFalse(r['events'][1]['admission'])
        self.assertAlmostEqual(r['events'][2]['entry_normalized_qty'],1/3)
        self.assertTrue(r['events'][2]['capacity_reuse_entry'])
    def test_repeated_partial_reuse_has_no_overlay_count_tuning(self):
        r=run_fixture([60,79,97,115,133])
        self.assertEqual(len(r['open_positions']),5)
        self.assertEqual([e.allocation(t) for t in r['open_positions']],
                         [Fraction(1),Fraction(1,3),Fraction(1,9),Fraction(1,27),Fraction(1,81)])
        self.assertTrue(all(x['active_after_open']<=1 for x in r['capacity_timeline']))
    def test_entry_never_exceeds_available_and_full_pool_blocks(self):
        r=run_fixture([60,79,80,81,97])
        self.assertEqual([x['admission'] for x in r['events']],[True,True,False,False,True])
        for x in r['events']:self.assertLessEqual(x['entry_normalized_qty'],x['available_capacity'])
    def test_gap_invalidates_new_lot(self):
        b,s,f=fixture();b[79]=replace(b[79],open=85.,low=84.)
        r=run_fixture([60,79],bars=b)
        self.assertEqual(r['events'][1]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_equal_timestamp_final_exit_does_not_fund_prior_close_entry(self):
        b,s,f=fixture();f[70]['momentum']=0
        r=run_fixture([60,71,72],features=f)
        self.assertFalse(r['events'][1]['admission']);self.assertTrue(r['events'][2]['admission'])
        self.assertEqual(r['events'][2]['entry_normalized_qty'],1)
    def test_partial_plus_final_same_open_conservative_order(self):
        b,s,f=fixture()
        for j in range(60):b[j]=replace(b[j],open=150.,high=151.,low=149.,close=150.)
        r=run_fixture([60,78,79],bars=b)
        self.assertEqual(len(r['trades'][0]['tm_legs']),2)
        self.assertFalse(r['events'][1]['admission']);self.assertEqual(r['events'][2]['entry_normalized_qty'],1)
    def test_pending_boundary_keeps_full_quantity(self):
        r=run_fixture([60,78],n=78)
        self.assertEqual(r['open_positions'][0]['remaining_qty'],1)
        self.assertFalse(r['events'][1]['admission'])
    def test_available_but_no_next_open_preserves_pending(self):
        r=run_fixture([60,80],n=80)
        self.assertEqual(r['events'][1]['exclusion_reason'],'NO_NEXT_OPEN_IN_APPROVED_WINDOW')
        self.assertEqual(len(r['pending_entries']),1)
    def test_future_mutation_and_truncation_preserve_capacity_and_entries(self):
        b,s,f=fixture();changed=deepcopy(b)
        for j in range(100,len(b)):changed[j]=replace(changed[j],open=50.,high=500.,low=1.,close=50.)
        original=run_fixture([60,78,79,97,115],bars=b)
        mutated=run_fixture([60,78,79,97,115],bars=changed)
        truncated=run_fixture([60,78,79,97],n=100,bars=b[:100],features=f[:100])
        def decisions(result):
            return [{k:v for k,v in x.items() if k!='status'} for x in result['events'] if x['signal_ts']<100*e.tm.BAR]
        self.assertEqual(decisions(original),decisions(mutated));self.assertEqual(decisions(original),decisions(truncated))
        def prefix(result):return [x for x in result['trace'] if x['ts']<100*e.tm.BAR]
        self.assertEqual(prefix(original),prefix(mutated));self.assertEqual(prefix(original),prefix(truncated))
    def test_new_lot_uses_exact_parent_unit_lifecycle(self):
        b,s,f=fixture();r=run_fixture([60,79]);child=r['open_positions'][1]
        signal=dict(s,signal_index=78,signal_ts=79*e.tm.BAR,setup_id='79')
        _,raw,trace=e.tm.position(b,signal,'M1',f,len(b)*e.tm.BAR,COST)
        for name,value in raw.items():self.assertEqual(child[name],value,name)
        self.assertEqual(child['tm_legs'][0]['index'],96)
    def test_closed_scope_cannot_reenter_but_new_authority_can(self):
        with self.assertRaises(ValueError):e.assert_authorized(e.tm.SCOPE,'REPORT_ONLY')
        with self.assertRaises(ValueError):e.assert_authorized(e.SCOPE,'REPORT_ONLY')
        e.assert_authorized(e.SCOPE,'FROZEN_AUTHORIZED_FIRST_FULL')
    def test_missing_native_bar_rejected(self):
        b,s,f=fixture();del b[70]
        with self.assertRaises(ValueError):run_fixture([60,79],bars=b)


class CashTests(unittest.TestCase):
    def test_new_fractional_lot_terminal_and_cost_funding_scale(self):
        r=run_fixture([60,79],n=100);b,s,f=fixture(n=100)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        result=a.charge({'TEST':r},packet,dict(start_ms=0,runoff_end_ms=len(b)*e.tm.BAR))
        self.assertEqual(len(result['open_observations']),2);self.assertEqual(len(result['trades']),0)
        self.assertIsNone(result['metrics']['base_cost']['win_rate'])
        self.assertEqual(a.snapshot(result,result)['capacity_reuse_entry_count'],1)
        for raw,row in zip(r['open_positions'],result['open_observations']):
            q=float(e.allocation(raw));vals=a.a.bridge._values(('O',row))
            expected=q*fsum(l['qty']*((l['price']/raw['entry_price']-1)*10000-e.tm.cost_at(COST,raw['entry_ts'],l['ts'])) for l in raw['tm_legs'])
            self.assertAlmostEqual(vals['net_bps'],expected)
            self.assertAlmostEqual(vals['fee_bps'],10*q)
            self.assertAlmostEqual(fsum(l['qty'] for l in row['weighted_legs']),q)
            self.assertAlmostEqual(vals['gross_bps']-2*vals['cost_bps'],vals['cost2x_net_bps'])
        self.assertAlmostEqual(result['metrics']['daily'][-1]['cumulative_net_mark_bps'],result['metrics']['terminal_net_bps'])
    def test_partials_not_extra_campaigns_but_new_signal_is(self):
        b,s,f=fixture();b[131]=replace(b[131],close=95.,low=94.)
        r=run_fixture([60,79],bars=b)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        result=a.charge({'TEST':r},packet,dict(start_ms=0,runoff_end_ms=len(b)*e.tm.BAR))
        self.assertEqual(len(result['trades']),2)
        self.assertEqual(sum(len(t['weighted_legs']) for t in result['trades']),4)


if __name__=='__main__':unittest.main()
