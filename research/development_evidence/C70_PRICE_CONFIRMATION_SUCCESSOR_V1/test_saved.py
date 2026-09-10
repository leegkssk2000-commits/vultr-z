"""Stored-source counterexamples only. No trading engine or new economics."""
import os,unittest,json,ast
from pathlib import Path
from copy import deepcopy
import verify_saved as v

class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=v.read(v.OUT/'SPEC.json');cls.summary=v.read(v.OUT/'SUMMARY.json')
        inputs=Path(os.environ['PRICE_INPUTS']);cls.packet=v.gz(inputs/'SEEN2026.json.gz')
        cls.result=v.gz(v.OUT/'SEEN2026/RESULT.json.gz')
        cls.e=next(e for e in cls.result['events'] if e['er_context']['recovery_context']['rescued'])
        cls.rows=cls.packet['rows_by'][cls.e['symbol']]
    def test_original_record_valid(self):v.verify_context(self.rows,self.e)
    def test_changed_daily_source_rejected(self):
        e=deepcopy(self.e);e['er_context']['daily_context']['daily_closes'][-1]['close']*=1.01
        with self.assertRaisesRegex(AssertionError,'DAILY_WITNESS'):v.verify_context(self.rows,e)
    def test_changed_previous_high_rejected(self):
        e=deepcopy(self.e);e['er_context']['recovery_context']['prior_session']['high']*=1.01
        with self.assertRaisesRegex(AssertionError,'SOURCE_PRIOR_SESSION'):v.verify_context(self.rows,e)
    def test_changed_boolean_rejected(self):
        e=deepcopy(self.e);e['er_context']['eligible']=False
        with self.assertRaisesRegex(AssertionError,'ELIGIBILITY'):v.verify_context(self.rows,e)
    def test_source_day_available_before_signal_open(self):
        x=v.expected_context(self.rows,self.e);i=self.e['signal_index']
        self.assertLessEqual(x['session']['available_at'],self.rows[i]['bar_open_ts'])
        self.assertLess(x['session']['source_highs'][-1]['open_ts'],self.rows[i]['bar_open_ts'])
    def test_future_rows_do_not_change_context(self):
        rows=deepcopy(self.rows);before=v.expected_context(rows,self.e)
        for row in rows[self.e['signal_index']+1:]:row['high']=1e9;row['close']=1e8
        self.assertEqual(before,v.expected_context(rows,self.e))
    def test_history_exact_prior_prefix_and_alias(self):
        old=v.read(v.OUT/'HISTORY_BEFORE_IMPORT.json');new=v.read(v.OUT/'BUDGET.json')
        self.assertEqual(new['candidate_trials'][:len(old['candidate_trials'])],old['candidate_trials'])
        self.assertEqual(new['trials'][:len(old['trials'])],old['trials'])
        self.assertEqual([x['ordinal'] for x in new['candidate_trials'][-2:]],[71,72])
        self.assertEqual(new['candidate_trials'][-2]['original_provisional_ordinal'],70)
        self.assertEqual([x['actual_experiment_ordinal'] for x in new['trials'][-4:]],[125,126,127,128])
        for k,val in old.items():
            if k not in ('candidate_trials','trials','cumulative_actual','cumulative_actual_evaluations','new_candidate_runs'):self.assertEqual(new[k],val,k)
    def test_two_completed_calls_no_remaining(self):
        b=v.read(v.OUT/'BUDGET.json');s=b['c70_price_confirmation_successor_allocation']
        self.assertEqual((s['started'],s['completed'],s['remaining'],s['failed']),(2,2,0,0))
        self.assertEqual((b['cumulative_actual'],b['cumulative_actual_evaluations']),(72,128))
        owners={v.read(v.OUT/p/'ATTEMPT.json')['owner_run'] for p in ('DEV2025','SEEN2026')}
        self.assertEqual(owners,{'34420415235'})
    def test_report_rows_derived_from_sealed_summary(self):
        report=(v.OUT/'REPORT_KO.md').read_text()
        for per,p in self.summary['periods'].items():
            for label,x in p['snapshots'].items():
                row='|'+ '|'.join([label,f"{x['closed']}/{x['open']}",f"{100*x['win_rate']:.2f}"]+[f'{x[k]:.2f}' for k in ('average_win_bps','average_loss_bps','PF','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
                self.assertIn(row,report)
    def test_goal_not_reclassified(self):
        flags=[b for x in self.summary['periods'].values() for b in x['checks']['C63'].values()]
        self.assertEqual(sum(flags),3);self.assertEqual(self.summary['status'],'REJECT_KEEP_C63')
        self.assertTrue(self.summary['report_only']);self.assertFalse(self.summary['further_dispatch_allowed'])
    def test_workflow_has_no_economic_dispatch(self):
        text=(v.ROOT/'.github/workflows/c70-price-confirmation-v1.yml').read_text()
        for token in ('contents: write','git push','workflow_dispatch','_study_v1','reserve --','execute --','finite:'):self.assertNotIn(token,text)
    def test_verifier_has_no_evaluator_import(self):
        tree=ast.parse((v.OUT/'verify_saved.py').read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom):self.assertFalse((n.module or '').startswith('backend'))
            if isinstance(n,ast.Import):self.assertFalse(any(a.name.startswith('backend') for a in n.names))
if __name__=='__main__':unittest.main()
