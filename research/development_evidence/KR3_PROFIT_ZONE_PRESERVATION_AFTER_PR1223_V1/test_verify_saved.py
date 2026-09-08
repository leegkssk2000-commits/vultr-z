"""Artificial ledgers and trace tampering only; no historical packets/replay."""
from copy import deepcopy
import unittest
import verify_saved as v
from backend.research.rebuild import step7_kr3_winner_accounting_v1 as accounting

COST={'fee_bps':3.,'spread_bps':4.,'impact_bps':5.,'funding_p95_per_settlement_bps':2.}


def row(origin,net,opened=False):
    parts={'fee_bps':3.,'spread_bps':4.,'impact_bps':5.,'slippage_bps':0.,'funding_bps':0.,'frozen_floor_reserve_bps':8.}
    x={'lane_id':'keltner_trend_main','symbol':'SYNTH-USDT','signal_index':origin,'signal_ts':origin*v.BAR,
       'entry_index':origin+1,'entry_ts':origin*v.BAR,'entry_price':100.,'side':'long'}
    if opened:x.update(gross_mark_bps=net+20,hypothetical_liquidation_net_mark_bps=net,
        hypothetical_liquidation_cost2x_net_mark_bps=net-20,hypothetical_liquidation_cost_bps=20.,hypothetical_cost_components_bps=parts)
    else:x.update(gross_bps=net+20,net_bps=net,cost2x_net_bps=net-20,cost_bps=20.,**parts)
    return x


def pair():
    events=[{'symbol':'SYNTH-USDT','signal_index':i,'signal_ts':i*v.BAR,'side':'long'} for i in range(1,9)]
    parent={'trades':[row(1,-30),row(2,60),row(5,-20)],
            'open_observations':[row(3,20,True),row(4,-10,True),row(6,10,True)],
            'events':events,'reference_states':{},'metrics':{'daily':[]}}
    child={'trades':[row(1,40),row(3,-10),row(7,30)],
           'open_observations':[row(2,-5,True),row(4,15,True),row(8,-15,True)],
           'events':deepcopy(events),'reference_states':{},'metrics':{'daily':[]}}
    return parent,child


def trace_fixture():
    parts,total,count=v.costs_for(COST,0,2*v.BAR)
    cost={**parts,'cost_bps':total,'funding_settlements_crossed':count,'model_accrual_cutoff_ts':2*v.BAR,
          'actual_historical_execution_cost_evidence':False}
    raw={'trades':[{'signal_index':0,'entry_ts':0,'entry_price':100.,'exit_price':90.}],
         'open_positions':[],'trace':[
        {'kind':'KR3_PROFIT_ZONE_ARMED_CLOSE','signal_index':0,'index':1,'ts':2*v.BAR,
         'observed_close':103.,'ema20':102.,'ema50':101.,'entry_price':100.,'protected_line':102.,'decision_cost':cost},
        {'kind':'KR3_PROFIT_ZONE_LINE_UPDATED_CLOSE','signal_index':0,'index':2,'ts':3*v.BAR,
         'prior_protected_line':102.,'protected_line':104.,'ema20':104.},
        {'kind':'KR3_PROFIT_ZONE_SUPPORT_LOST_CLOSE','signal_index':0,'index':3,'ts':4*v.BAR,
         'prior_protected_line':104.,'observed_close':103.},
        {'kind':'KR3_PROFIT_ZONE_SUPPORT_LOST_NEXT_OPEN','signal_index':0,'index':4,'ts':4*v.BAR,'price':90.}]}
    return raw


class SavedVerifierSynthetic(unittest.TestCase):
    def test_all_eight_groups_reconcile_and_do_not_require_identical_full_entries(self):
        p,c=pair();report=accounting.compare(p,c);out=v.compare_parent(p,c,report)
        self.assertEqual(out['counts'],dict.fromkeys(('CC','CO','OC','OO','removed_C','removed_O','new_C','new_O'),1))
        self.assertAlmostEqual(out['net_delta'],25.)
        self.assertEqual(out['loss_to_win_T'],1)

    def test_removed_and_open_transition_tampering_rejected(self):
        p,c=pair();report=accounting.compare(p,c)
        for group in ('removed_C','CO','new_O'):
            bad=deepcopy(report);bad['groups'][group]['marked']['delta']['net_bps']+=1
            with self.assertRaises(ValueError):v.compare_parent(p,c,bad)

    def test_cost2_bridge_and_full_entry_geometry_tampering_rejected(self):
        p,c=pair();report=accounting.compare(p,c)
        bad=deepcopy(report);bad['groups']['OC']['marked']['delta']['cost2x_net_bps']+=1
        with self.assertRaises(ValueError):v.compare_parent(p,c,bad)
        badchild=deepcopy(c);badchild['trades'][0]['entry_price']=99.
        with self.assertRaises(ValueError):v.compare_parent(p,badchild,report)

    def test_elapsed_funding_and_floor_are_causal(self):
        parts,total,count=v.costs_for(COST,0,v.STEP-1)
        self.assertEqual((total,count),(20.,0));self.assertEqual(parts['funding_bps'],0)
        _,later,count=v.costs_for(COST,0,10*v.STEP)
        self.assertEqual((later,count),(32.,10))

    def test_prior_line_and_actual_adverse_gap_are_valid(self):
        self.assertEqual(v.check_guard_trace(trace_fixture(),COST),{'arms':1,'exits':1})

    def test_final_cost_same_bar_and_guaranteed_fill_forgery_rejected(self):
        for kind in ('future_cost','same_bar','guaranteed_line'):
            bad=trace_fixture()
            if kind=='future_cost':bad['trace'][0]['decision_cost']['funding_bps']=200.
            elif kind=='same_bar':bad['trace'][2]['index']=1
            else:bad['trace'][3]['price']=104.
            with self.assertRaises(ValueError):v.check_guard_trace(bad,COST)


if __name__=='__main__':unittest.main()
