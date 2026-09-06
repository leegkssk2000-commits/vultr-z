import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import top5_diverse_batch_execution_v1 as x
from backend.research.rebuild.test_top5_diverse_batch_preparation_v1 import parent
from backend.research.rebuild.test_top5_development_repair_v1 import fixture


def trade(origin, net, entry=10):
    return dict(lane_id=x.prep.SUPERTREND,symbol='TEST',signal_ts=origin,side='long',
                entry_ts=entry,net_bps=net,gross_bps=net+20,cost_bps=20,funding_bps=2)


class Execution(unittest.TestCase):
    def test_delay_uses_original_signal_and_actual_twelve_bar_hold(self):
        rows=fixture(300,x.INTERVAL);p=parent(x.prep.SUPERTREND)
        b=x.prep.replay_prepared_rows(rows,p,selected_signals=[240])['trades'][0]
        c=x.prep.replay_prepared_rows(rows,p,candidate=True,selected_signals=[240])['trades'][0]
        self.assertEqual(c['signal_ts'],b['signal_ts'])
        self.assertEqual(c['entry_ts']-b['entry_ts'],x.INTERVAL)
        self.assertEqual(c['exit_ts']-b['exit_ts'],x.INTERVAL)
        self.assertEqual(c['hold_ms'],12*x.INTERVAL)
        self.assertEqual(c['entry_price'],rows[242]['open'])
        self.assertEqual(c['exit_price'],rows[253]['close'])

    def test_common_tail_excludes_parent_trade_child_cannot_finish(self):
        rows=fixture(300,x.INTERVAL)
        base,_=x.eligible_signals(rows,[285,286,287],12,0,300*x.INTERVAL)
        common,excluded=x.eligible_signals(rows,[285,286,287],12,1,300*x.INTERVAL)
        self.assertEqual(base,[285,286]);self.assertEqual(common,[285]);self.assertEqual(excluded,[286,287])

    def test_waiting_exit_bar_blocked_no_reschedule_and_next_origin_allowed(self):
        p=parent(x.prep.SUPERTREND);rows=fixture(310,x.INTERVAL)
        r=x.prep.replay_prepared_rows(rows,p,candidate=True,selected_signals=[240,241,253,254])
        self.assertEqual([t['signal_index'] for t in r['trades']],[240,254])
        self.assertEqual([t['entry_index'] for t in r['trades']],[242,256])
        self.assertEqual([e['signal_index'] for e in r['exclusions']],[241,253])

    def test_missing_scheduled_bar_fails_integrity(self):
        p=parent(x.prep.SUPERTREND);rows=fixture(300,x.INTERVAL)
        with self.assertRaisesRegex(RuntimeError,'DEVELOPMENT_GAP_DUPLICATE_OR_ORDER'):
            x.prep.replay_prepared_rows(rows[:242]+rows[243:],p,candidate=True,selected_signals=[240])

    def test_delayed_entry_matches_origin_not_entry_price_timestamp(self):
        a=x.attribute([trade(1,100)],[trade(1,80,entry=20)])
        self.assertEqual((a['common_T'],a['removed_T'],a['new_T']),(1,0,0))
        self.assertEqual(a['common_net_delta_bps'],-20)
        self.assertEqual(a['winner_amount_retention'],.8)

    def test_accounting_bridge_and_winner_loss_separation(self):
        a=x.attribute([trade(1,100),trade(2,-70),trade(3,20)],
                      [trade(1,-30),trade(2,-20),trade(4,40)])
        self.assertEqual(a['net_delta_bps'],-60)
        self.assertEqual(a['cut_positive_winner_profit_bps'],100)
        self.assertEqual(a['additional_loss_on_parent_winners_bps'],30)
        self.assertEqual(a['saved_common_loss_bps'],50)
        self.assertEqual(a['missed_winner_bps'],20)
        self.assertEqual(a['new_net_bps'],40)
        self.assertEqual(a['winner_to_loss_T'],1)

    def test_retention_capped_and_duplicate_origin_rejected(self):
        self.assertEqual(x.attribute([trade(1,100)],[trade(1,200)])['large_winner_amount_retention'],1)
        with self.assertRaisesRegex(RuntimeError,'DUPLICATE_ORIGIN'):
            x.attribute([trade(1,100),trade(1,20)],[])

    def test_actual_timing_is_used_to_charge_funding(self):
        rows=fixture(300,x.INTERVAL);p=parent(x.prep.SUPERTREND)
        policy={'development_interval_ms':[0,300*x.INTERVAL],'batch_id':'SYNTHETIC','receipt_sha256':'synthetic',
                'combined_data_sha256':'synthetic','cost_binding_sha256':'synthetic','code_files_sha256':{}}
        costs={'TEST':{'fee_bps':10,'spread_bps':2,'impact_bps':1,'funding_p95_per_settlement_bps':3}}
        # Spy on the shared charge function: actual delayed times must reach it.
        with patch.object(x.old.probe,'cost_components',wraps=x.old.probe.cost_components) as spy:
            ts,_=x.evaluate(rows,[240],p,policy,costs,'TEST','child',1)
        self.assertEqual(spy.call_args.args[:2],(rows[242]['bar_open_ts'],rows[253]['bar_close_ts']))
        self.assertEqual(ts[0]['pending_reservation_ms'],x.INTERVAL)
        self.assertEqual(ts[0]['cost2x_net_bps'],ts[0]['gross_bps']-2*ts[0]['cost_bps'])

    def test_budget_is_new_allocation_without_history_reset(self):
        c=x.old.read(x.CONTRACT)
        self.assertEqual(c['budget'],x.BUDGET)
        self.assertEqual(sum(c['budget']['per_lane'].values()),2)
        self.assertEqual(c['budget']['cumulative_after'],20)
        self.assertEqual(x.old.read(x.prep.PROPOSAL)['allocated_new_trials'],0)
        self.assertFalse(c['outcomes_seen_at_freeze'])
        x.authorize()

    def test_changed_budget_timing_or_authority_cannot_run(self):
        original=x.old.read(x.CONTRACT)
        for key,value in [('budget',dict(x.BUDGET,new_allocations=3)),('timing',{}),('formal_credit',1),('OOS_access',True)]:
            altered={**original,key:value};altered.pop('receipt_sha256')
            c=x.old.seal(altered)
            x.old.probe.verify_seal(c,'TEST_CHANGED_CONTRACT')
            with patch.object(x.old,'read',return_value=c),patch.object(x.prior.previous,'load_inputs',side_effect=AssertionError('MUST_NOT_READ_DATA')):
                with self.assertRaises(RuntimeError):x.run(Path('/unused'))

    def test_consumed_allocation_blocks_before_data_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/x.OUTPUT;out.mkdir(parents=True);(out/'receipt.json').write_text('{}')
            with patch.object(x,'ROOT',Path(tmp)),patch.object(x,'authorize',return_value={}),patch.object(x.prior.previous,'load_inputs',side_effect=AssertionError('MUST_NOT_READ_DATA')):
                with self.assertRaisesRegex(RuntimeError,'BUDGET_CONSUMED'):x.run(Path('/unused'))


if __name__=='__main__':unittest.main()
