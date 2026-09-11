"""Artificial-only group cash, prefix, exit ordering and accounting checks."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import fsum
from unittest.mock import patch
import unittest
from backend.research.rebuild import c70_profitlock_v1 as e
from backend.research.rebuild import c70_profitlock_account_v1 as a
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture,COST,POLICY,rows_of


def run(entries,*,n=150,bars=None,features=None,enabled=True):
    b,s,f=fixture(n=n);b=b if bars is None else bars;f=f if features is None else features
    signals=[dict(s,signal_index=j-1,signal_ts=j*e.tm.BAR,setup_id=str(j)) for j in entries]
    obs=dict(eligible=True,reason=None,range_context=dict(rescued=False))
    with patch.object(e.tm.native,'m1_setups',return_value=(signals,[],f)),patch.object(e.tm.c63,'context',return_value=obs),patch.object(e.tm,'c70_context',side_effect=lambda original,daily:original):
        return e.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*e.tm.BAR,cost=COST,enabled=enabled)


def reversal(n=150):
    b,s,f=fixture(n=n)
    for j in range(91,n):b[j]=replace(b[j],open=111.,high=112.,low=110.,close=111.)
    return b,s,f


class EnvelopeTests(unittest.TestCase):
    def test_off_exact_capreuse_delegation(self):
        sentinel={'exact':True}
        with patch.object(e.cap,'replay',return_value=sentinel) as call:
            self.assertIs(e.replay([],eval_start_ms=0,eval_end_ms=1,cost=COST,enabled=False),sentinel)
            call.assert_called_once_with([],eval_start_ms=0,eval_end_ms=1,cost=COST)
    def test_before_partial_and_no_drawdown_matches_capreuse(self):
        for n in (78,90):
            on=run([60,70,78,79],n=n);off=run([60,70,78,79],n=n,enabled=False)
            for actual,prior in zip(on['events'],off['events'],strict=True):
                self.assertEqual({k:actual[k] for k in prior},prior)
            for raw,prior in zip(on['trades']+on['open_positions'],off['trades']+off['open_positions']):
                for k,v in prior.items():self.assertEqual(raw[k],v,k)
            self.assertEqual(on['audit']['profitlock_triggers'],0)
    def test_partial_decision_does_not_create_bank_or_peak(self):
        r=run([60],n=78)
        for t in r['group_trace']:
            if t['kind']=='GROUP_CLOSE_OBSERVATION':
                self.assertEqual(t['realized_bank_net'],0);self.assertIsNone(t['peak_group_marked_net'])
        self.assertEqual(r['open_positions'][0]['partial_count'],0)
    def test_realized_bank_uses_actual_gap_fill_net_and_quantity(self):
        r=run([60,79]);raw=r['open_positions'][0];t=next(x for x in r['group_trace'] if x.get('first_partial_fill_ts'))
        l=raw['tm_legs'][0];expected=(1/3)*((l['price']/raw['entry_price']-1)*10000-e.tm.cost_at(COST,raw['entry_ts'],l['ts']))
        self.assertAlmostEqual(t['realized_bank_net'],expected)
        self.assertEqual(t['first_partial_fill_ts'],78*e.tm.BAR)
    def test_zero_negative_partial_does_not_fund_bank(self):
        b,s,f=fixture();b[78]=replace(b[78],open=95.,low=94.)
        r=run([60],bars=b)
        first=next(t for t in r['group_trace'] if t.get('first_partial_fill_ts'))
        self.assertEqual(first['realized_bank_net'],0);self.assertFalse(first['trigger'])
    def test_giveback_triggers_next_open_with_gap(self):
        b,s,f=reversal();b[92]=replace(b[92],open=108.,low=107.)
        r=run([60],bars=b);trigger=next(t for t in r['group_trace'] if t.get('trigger'))
        closed=r['trades'][0];self.assertEqual(closed['exit_index'],trigger['index']+1)
        self.assertEqual(closed['exit_price'],b[closed['exit_index']].open)
        self.assertEqual(closed['exit_reason'],e.EXIT+'_NEXT_OPEN')
        self.assertEqual(closed['partial_count'],1)
    def test_envelope_equality_uses_less_equal(self):
        original=e.group_value
        def controlled(lots,stamp,price,cost):
            value=original(lots,stamp,price,cost)
            if value['first_partial_fill_ts'] is not None:
                value.update(realized_bank_net=100.,group_marked_net=1000. if stamp==79*e.tm.BAR else 900.)
            return value
        with patch.object(e,'group_value',side_effect=controlled):r=run([60],n=90)
        trigger=next(t for t in r['group_trace'] if t.get('trigger'))
        self.assertEqual(trigger['group_marked_net'],trigger['peak_group_marked_net']-trigger['realized_bank_net'])
        self.assertEqual(r['trades'][0]['exit_ts'],80*e.tm.BAR)
    def test_group_exit_closes_root_and_reuse_lot_once(self):
        b,s,f=reversal();r=run([60,79],bars=b)
        first=next(t for t in r['group_trace'] if t.get('trigger'))
        fills=[t for t in r['group_trace'] if t['kind']=='GROUP_EXIT_FILL']
        self.assertEqual(len(fills),1);self.assertEqual(len(fills[0]['lots']),2)
        self.assertTrue(all(t['exit_index']==first['index']+1 for t in r['trades']))
        self.assertEqual(len(r['trades']),2)
    def test_native_floor_same_close_has_priority_and_no_double_cost(self):
        b,s,f=reversal();b[91]=replace(b[91],close=80.,low=79.)
        r=run([60,79],bars=b)
        self.assertTrue(all(t['exit_reason']=='FIXED_FLOOR_CLOSE_NEXT_OPEN' for t in r['trades']))
        for raw in r['trades']:self.assertAlmostEqual(fsum(l['qty'] for l in raw['tm_legs']),1)
    def test_BE_same_close_has_one_full_final_fill(self):
        b,s,f=reversal();b[91]=replace(b[91],close=99.,low=98.)
        r=run([60],bars=b);raw=r['trades'][0]
        self.assertEqual(raw['exit_reason'],'RUNNER_BREAKEVEN_CLOSE_NEXT_OPEN')
        self.assertEqual(len(raw['tm_legs']),2)
    def test_due_source_partial_preserved_with_group_risk_exit(self):
        b,s,f=fixture();b[95]=replace(b[95],close=111.,low=110.)
        r=run([60,79],bars=b);reuse=next(t for t in r['trades'] if t['signal_index']==78)
        self.assertEqual(reuse['exit_index'],96);self.assertEqual(reuse['partial_count'],1)
        self.assertEqual([l['ts'] for l in reuse['tm_legs']],[96*e.tm.BAR]*2)
        self.assertEqual(reuse['tm_legs'][0]['reason'],'D3_PROFIT_PARTIAL_NEXT_OPEN')
        self.assertEqual(reuse['tm_legs'][1]['reason'],e.EXIT+'_NEXT_OPEN')
        self.assertAlmostEqual(fsum(l['qty'] for l in reuse['tm_legs']),1.)
    def test_equal_open_reserved_entry_starts_new_group_without_upsizing(self):
        b,s,f=reversal();r=run([60,92],bars=b)
        event=r['events'][1];self.assertTrue(event['admission'])
        self.assertAlmostEqual(event['entry_normalized_qty'],1/3)
        self.assertNotEqual(event['group_id'],r['events'][0]['group_id'])
    def test_risk_decision_no_early_release_and_next_root_allowed(self):
        b,s,f=reversal();r=run([60,79,92,93],bars=b)
        events={x['signal_index']+1:x for x in r['events']}
        self.assertFalse(events[92]['admission']);self.assertTrue(events[93]['admission'])
        self.assertEqual(events[93]['entry_normalized_qty'],1)
        self.assertNotEqual(events[93]['group_id'],events[60]['group_id'])
    def test_terminal_pending_keeps_mark_costs_and_qty(self):
        b,s,f=reversal(n=92);r=run([60],bars=b,n=92)
        raw=r['open_positions'][0];self.assertIn('pending_risk_envelope',raw)
        self.assertAlmostEqual(raw['remaining_qty'],2/3);self.assertFalse(raw['terminal_liquidation'])
        self.assertEqual(raw['tm_legs'][-1]['status'],'O')
    def test_future_mutation_and_truncation_preserve_group_prefix(self):
        b,s,f=reversal();mutated=deepcopy(b)
        for j in range(100,len(b)):mutated[j]=replace(mutated[j],open=50.,high=500.,low=1.,close=50.)
        original=run([60,79,93,110],bars=b);changed=run([60,79,93,110],bars=mutated)
        short=run([60,79,93],n=100,bars=b[:100],features=f[:100])
        prefix=lambda r:[x for x in r['group_trace'] if x['ts']<100*e.tm.BAR]
        self.assertEqual(prefix(original),prefix(changed));self.assertEqual(prefix(original),prefix(short))
        decisions=lambda r:[{k:v for k,v in x.items() if k!='status'} for x in r['events'] if x['signal_ts']<100*e.tm.BAR]
        self.assertEqual(decisions(original),decisions(changed));self.assertEqual(decisions(original),decisions(short))
    def test_cap_never_exceeded_in_multiple_reuse_and_resets(self):
        r=run([60,79,97,115,133])
        self.assertTrue(all(t['active_after_open']<=1 for t in r['capacity_timeline']))
        self.assertEqual([e.cap.allocation(t) for t in r['open_positions']],[Fraction(1),Fraction(1,3),Fraction(1,9),Fraction(1,27),Fraction(1,81)])
    def test_old_report_only_blocked_new_scope_authorized(self):
        for scope in (e.cap.SCOPE,e.SCOPE):
            with self.assertRaises(ValueError):e.assert_authorized(scope,'REPORT_ONLY')
        e.assert_authorized(e.SCOPE,'FROZEN_AUTHORIZED_FIRST_FULL')
    def test_group_cash_retains_closed_member_realized_until_flat(self):
        r=run([60,79]);root,reuse=r['open_positions'];root=deepcopy(root)
        root['tm_legs'][-1].update(status='C',ts=100*e.tm.BAR,price=120.,reason='TEST_FINAL')
        v=e.group_value([root,reuse],101*e.tm.BAR,120.,COST)
        cash=fsum(l['qty']*((l['price']/root['entry_price']-1)*10000-e.tm.cost_at(COST,root['entry_ts'],l['ts'])) for l in root['tm_legs'])
        alone=e.group_value([reuse],101*e.tm.BAR,120.,COST)
        self.assertAlmostEqual(v['group_marked_net']-alone['group_marked_net'],cash)
    def test_group_exit_campaign_cash_and_WR_denominator(self):
        b,s,f=reversal();r=run([60,79],bars=b)
        packet=dict(policy=POLICY,costs={'TEST':COST},rows_by={'TEST':rows_of(b)})
        result=a.charge({'TEST':r},packet,dict(start_ms=0,runoff_end_ms=len(b)*e.tm.BAR))
        self.assertEqual(len(result['trades']),2)
        for raw,row in zip(r['trades'],result['trades']):
            q=float(e.cap.allocation(raw));expected=q*fsum(l['qty']*((l['price']/raw['entry_price']-1)*10000-e.tm.cost_at(COST,raw['entry_ts'],l['ts'])) for l in raw['tm_legs'])
            self.assertAlmostEqual(row['net_bps'],expected);self.assertAlmostEqual(row['fee_bps'],10*q)
        self.assertAlmostEqual(result['metrics']['daily'][-1]['cumulative_net_mark_bps'],result['metrics']['terminal_net_bps'])
    def test_saved_JSON_group_and_source_prefix_verification(self):
        import json
        from backend.research.rebuild import c70_profitlock_verify_v1 as verify
        for n in (92,150):
            b,s,f=reversal(n=n)
            f=[dict(momentum=b[j].close-b[j-14].close if j>=14 else 0.) for j in range(n)]
            raw=run([60,79,93],n=n,bars=b,features=f)
            raw=json.loads(a.a.canon(raw));rows=rows_of(b)
            verify.verify_groups(raw,rows,COST,n*e.tm.BAR)
            for lot in raw['trades']+raw['open_positions']:
                trace=[t for t in raw['trace'] if t['signal_index']==lot['signal_index']]
                verify.verify_source_actual(lot,trace,raw['source_references'][str(lot['signal_index'])],rows,COST,n*e.tm.BAR,raw['group_trace'])


if __name__=='__main__':unittest.main()
