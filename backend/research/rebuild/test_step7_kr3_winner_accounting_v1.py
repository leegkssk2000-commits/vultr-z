import unittest
from backend.research.rebuild import step7_kr3_winner_accounting_v1 as a


def trade(signal, net, symbol='BTC-USDT'):
    return dict(lane_id='keltner_trend_main', symbol=symbol, signal_ts=signal,
        side='long', net_bps=net, gross_bps=net+2., cost_bps=2., cost2x_net_bps=net-2.,
        fee_bps=2., funding_bps=0., spread_bps=0., impact_bps=0., slippage_bps=0.,
        frozen_floor_reserve_bps=0.)


def result(trades, opened=()):
    return {'trades':trades, 'open_observations':list(opened), 'metrics':{'daily':[]}}


class StoredAccountingTests(unittest.TestCase):
    def test_full_delta_keeps_costs_once_and_loss_revival_actual(self):
        kr3=result([trade(1,100.),trade(2,-20.)])
        aa=result([trade(1,-50.),trade(2,-40.)])
        b=result([]); e=result([trade(1,30.),trade(2,-8.)])
        value=a.compare(b,e)
        self.assertEqual(value['four_way_terminal_delta']['new'],22.)
        self.assertEqual(value['bridges']['marked']['delta']['cost_bps'],4.)
        cohort=a.repair_cohorts(kr3,b,e,aa)
        self.assertEqual(cohort['restored_KR3_capped_profit_bps'],30.)
        self.assertEqual(cohort['A85']['actual_child_closed_net_bps'],22.)
        self.assertEqual(cohort['A85']['original_A_net_of_revived_bps'],-90.)

    def test_open_is_transition_not_removed_or_winner(self):
        t=trade(1,100.)
        o={k:v for k,v in t.items() if k not in a.owner.VALUE_FIELDS}
        o.update(gross_mark_bps=82.,hypothetical_liquidation_net_mark_bps=80.,
            hypothetical_liquidation_cost2x_net_mark_bps=78.,hypothetical_liquidation_cost_bps=2.,
            hypothetical_cost_components_bps={k:t[k] for k in a.owner.COST_FIELDS})
        p=result([t]); e=result([],[o])
        value=a.compare(p,e)
        self.assertEqual(value['counts']['CO'],1)
        self.assertEqual(value['four_way_terminal_delta']['closed_open_transitions'],-20.)
        self.assertEqual(value['winner']['amount_retention_lower'],0.)
        self.assertEqual(value['winner']['amount_retention_upper'],1.)
        self.assertEqual(a.repair_cohorts(p,result([]),e)['restored_to_completed_win'],0)

    def test_duplicate_origin_rejected_and_large_winner_owner_unchanged(self):
        t=trade(1,10.)
        with self.assertRaises(RuntimeError): a.index(result([t,t]))
        p=result([trade(i,float(i+1)) for i in range(11)])
        e=result([trade(i,float(i+1)*2.) for i in range(11)])
        value=a.compare(p,e)
        self.assertEqual(value['large_winner']['parent_T'],2)
        self.assertEqual(value['large_winner']['amount_retention_lower'],1.)


if __name__=='__main__':unittest.main()
