"""Boundary, indicator provenance and ledger attribution regressions."""
import copy,json,gzip,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild.test_top5_development_repair_v1 import fixture
from backend.research.rebuild import top5_external_features_v1 as f
from backend.research.rebuild import top5_external_metrics_v1 as m
from backend.research.rebuild import top5_external_repair_v1 as r

class Features(unittest.TestCase):
    def test_adx_official_seed_and_direction(self):
        rows=[{'high':100+i+2,'low':100+i-1,'close':100+i+1} for i in range(60)]
        d=f.directional_movement(rows)
        self.assertTrue(all(x is None for x in d['adx'][:27]))
        self.assertAlmostEqual(d['adx'][27],100)
        self.assertAlmostEqual(d['plus_di'][27],100/3)
        self.assertEqual(d['minus_di'][27],0)
        flat=f.directional_movement([{'high':1,'low':1,'close':1}]*60)
        self.assertEqual(flat['adx'][27:], [0.]*33)

    def test_future_prefix_and_partial_htf_bar(self):
        rows=fixture(260);full=f.Features(rows,3600000)
        for i in [30,63,119,199,202,259]:
            for side in ['long','short']:
                self.assertEqual(full.at(i,side),f.Features(rows[:i+1],3600000).at(i,side))
            value=full.at(i)
            self.assertLessEqual(value['htf_available_close_ts'],rows[i]['bar_close_ts'])
        tamper=copy.deepcopy(rows)
        for row in tamper[203:]:
            for k in ['open','high','low','close']:row[k]*=100
        self.assertEqual(full.at(202),f.Features(tamper,3600000).at(202))
        self.assertEqual(f.aggregate_closed(rows[:3],14400000,3600000),[])
        self.assertEqual(len(f.aggregate_closed(rows[:4],14400000,3600000)),1)

    def test_supertrend_seed_and_closed_crossing(self):
        rows=[{'high':101,'low':99,'close':100} for _ in range(15)]
        rows += [{'high':110,'low':100,'close':109}]
        state=f.supertrend(rows)
        self.assertEqual(state['direction'][9:15],[-1]*6)
        self.assertEqual(state['direction'][15],1)
        self.assertEqual(state['upper'][14],106)
        self.assertEqual(state['lower'][14],94)

    def test_no_outcome_as_entry_input(self):
        value=f.Features(fixture(260),3600000).at(240)
        a=r.predicate_values(value)
        self.assertFalse(a['runtime_uses_outcome_labels'])
        self.assertFalse(any(k in a for k in ['mfe_bps','net_bps','loss_streak','future_close']))

class Attribution(unittest.TestCase):
    def trade(self,key,net,ts=10):
        return dict(identity=key,net_bps=net,cost_bps=20,gross_bps=net+20,entry_price=100,exit_price=100+net/100,entry_ts=0,exit_ts=ts,side='long')
    def test_exact_loss_win_new_decomposition(self):
        p=[self.trade('keep',50),self.trade('miss',30),self.trade('loss',-100)]
        c=[self.trade('keep',50),self.trade('new',10)]
        a=m.attribution(p,c)
        self.assertEqual(a['net_delta_bps'],80)
        self.assertEqual(a['removed_loss_bps'],100);self.assertEqual(a['missed_win_bps'],30)
        self.assertEqual(a['winner_amount_retention'],.625)
        self.assertEqual(a['winner_count_retention'],.5)
        c[0]['cost_bps']=19
        with self.assertRaisesRegex(RuntimeError,'COST_CHANGED'):m.attribution(p,c)
    def test_simultaneous_groups_order_independent(self):
        rows=[self.trade('a',-100),self.trade('b',120),self.trade('c',-50,20),self.trade('d',60,30)]
        self.assertEqual(m.drawdown(rows,0,40),m.drawdown(list(reversed(rows)),0,40))
        self.assertEqual(m.streaks(m.grouped(rows))[0],m.streaks(m.grouped(list(reversed(rows))))[0])
        self.assertEqual(m.drawdown(rows,0,40)['closed_group_DD_trade_sum_bps'],50)

class Guard(unittest.TestCase):
    def test_previous_immutable_owners_and_receipts(self):r.verify_previous()
    def test_holdout_and_network_denied(self):
        import socket
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'out';out.mkdir();hidden=Path(t)/'validation.json';hidden.write_text('[42]')
            with r.old.probe.io_boundary([],out):
                with self.assertRaisesRegex(RuntimeError,'READ_FORBIDDEN'):hidden.read_text()
                with self.assertRaisesRegex(RuntimeError,'NETWORK_OR_PROCESS'):socket.socket()
    def test_frozen_diagnostics_do_not_change_originals(self):
        root=r.ROOT/r.OUTPUT
        before=json.loads((root/'loss_winner_map_pre_source_parity.json').read_text())
        after=json.loads((root/'loss_winner_map.json').read_text())
        for lane in after['lanes']:
            self.assertEqual(before['lanes'][lane]['feature_conditions'],after['lanes'][lane]['feature_conditions'])
        self.assertFalse(after['validation_OOS_read'])
    def test_results_if_present_are_development_only(self):
        path=r.ROOT/r.OUTPUT/'comparison/receipt.json'
        if not path.exists():self.skipTest('No child outcomes before freeze')
        value=json.loads(path.read_text());r.old.probe.verify_seal(value,'EXTERNAL')
        self.assertEqual(set(value['lanes']),set(r.LANES))
        for key,v in r.old.probe.DEV_AUTH.items():self.assertEqual(value[key],v)
        self.assertEqual(value['validation_rows_decoded'],0);self.assertEqual(value['OOS_rows_decoded'],0)
        for lane,v in value['lanes'].items():
            self.assertEqual(v['P0'],'UNCONFIRMED')
            self.assertFalse(v['formal_pass'])
            b=v['metrics']['child']['base_cost'];stress=v['metrics']['child']['cost2x']
            self.assertAlmostEqual(stress['net_bps'],2*b['net_bps']-b['gross_bps'])
        trades=r.read_lines(r.ROOT/value['artifacts']['trades']['path'])
        for lane in r.LANES:
            p=[t for t in trades if t['lane_id']==lane and t['scenario']=='base']
            c=[t for t in trades if t['lane_id']==lane and t['scenario']=='child']
            self.assertEqual(m.attribution(p,c),value['lanes'][lane]['attribution'])
            for scenario in ['base','child']:
                subset=[t for t in trades if t['lane_id']==lane and t['scenario']==scenario]
                self.assertEqual(len(subset),len({t['identity'] for t in subset}))

if __name__=='__main__':unittest.main()
