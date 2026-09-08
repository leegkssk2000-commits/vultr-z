import tempfile,unittest,json,gzip
from copy import deepcopy
from pathlib import Path
import verify_saved as v
class SavedEvidenceTests(unittest.TestCase):
    def values(self,period='DEV2025'):
        return (v.gz(v.HERE/period/'RAW.json.gz'),v.gz(v.HERE/period/'RESULT.json.gz'),v.read(v.HERE/'COSTS.json'),v.read(v.HERE/'SPEC.json')['periods'][period])
    def test_actual_raw_bound_both_periods(self):
        for p,n in [('DEV2025',203),('SEEN2026',79)]:self.assertEqual(v.check_raw(*self.values(p)),n)
    def test_actual_metric_arithmetic(self):
        for p in v.PERIODS:self.assertGreater(v.check_metrics(self.values(p)[1]),0)
    def test_whole_pinned_scope(self):self.assertEqual(v.verify()['evaluation_total'],80)
    def test_internally_consistent_fabricated_pnl_rejected(self):
        raw,r,c,cal=self.values();t=r['trades'][0]
        t['exit_price']*=1.01;t['gross_bps']=(t['exit_price']/t['entry_price']-1)*10000
        t['net_bps']=t['gross_bps']-t['cost_bps'];t['cost2x_net_bps']=t['gross_bps']-2*t['cost_bps']
        with self.assertRaisesRegex(ValueError,'RAW_GEOMETRY'):v.check_raw(raw,r,c,cal)
    def test_raw_fill_edit_rejected(self):
        raw,r,c,cal=self.values();next(iter(raw.values()))['trades'][0]['entry_price']*=1.01
        with self.assertRaisesRegex(ValueError,'RAW_GEOMETRY'):v.check_raw(raw,r,c,cal)
    def test_cost_component_mismatch_rejected(self):
        raw,r,c,cal=self.values();r['trades'][0]['funding_bps']+=1
        with self.assertRaisesRegex(ValueError,'INDEPENDENT_COST'):v.check_raw(raw,r,c,cal)
    def test_fake_net_rejected(self):
        raw,r,c,cal=self.values();r['trades'][0]['net_bps']+=100
        with self.assertRaisesRegex(ValueError,'NET_FROM_RAW'):v.check_raw(raw,r,c,cal)
    def test_open_is_mandatory(self):
        raw,r,c,cal=self.values();r['open_observations']=[]
        with self.assertRaisesRegex(ValueError,'RAW_RESULT_ORIGINS'):v.check_raw(raw,r,c,cal)
    def test_open_is_not_real_fill(self):
        raw,r,c,cal=self.values();r['open_observations'][0]['actual_exit']=True
        with self.assertRaisesRegex(ValueError,'OPEN_IS_NOT_FILL'):v.check_raw(raw,r,c,cal)
    def test_duplicate_origin_rejected(self):
        raw,r,c,cal=self.values();r['trades'].append(deepcopy(r['trades'][0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ORIGIN'):v.check_raw(raw,r,c,cal)
    def test_eval_period_guard(self):
        raw,r,c,cal=self.values();cal['start_ms']=cal['runoff_end_ms']
        with self.assertRaisesRegex(ValueError,'INVALID_CALENDAR'):v.check_raw(raw,r,c,cal)
    def test_metrics_edited_rejected(self):
        r=self.values()[1];r['metrics']['terminal_net_bps']+=100
        with self.assertRaisesRegex(ValueError,'TERMINAL_NET'):v.check_metrics(r)
    def test_dd_edited_rejected(self):
        r=self.values()[1];r['metrics']['marked_DD_trade_sum_bps']-=100
        with self.assertRaisesRegex(ValueError,'DAILY_DD'):v.check_metrics(r)
    def test_credit_cannot_be_raised(self):
        raw,r,c,cal=self.values();r['trades'][0]['formal_credit']=1
        with self.assertRaisesRegex(ValueError,'CREDIT_OR_ORDER_DRIFT'):v.check_raw(raw,r,c,cal)
    def test_savings_cannot_replace_winner_damage(self):
        raw,r,c,cal=self.values();parent=v.gz(v.HERE.parents[2]/v.PARENT/'DEV2025.json.gz')['views']['FULL'];a=v.read(v.HERE/'DEV2025/ACCOUNTING.json')
        a['resolved_common_effects']['cut_positive_winner_profit_bps']=0
        with self.assertRaisesRegex(ValueError,'GAIN_HARM_ACCOUNTING'):v.compare_parent(parent,r,a)
    def test_pinned_manifest_rejects_joint_changes(self):
        pin=v.sha((v.HERE/'FINAL_HASHES.json').read_bytes())
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'repo/research/development_evidence/scope';root.mkdir(parents=True);(root/'FINAL_HASHES.json').write_bytes(b'{"changed": "value"}')
            with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):v.verify(root,pin)
    def test_funding_boundary_formula(self):
        b={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':2.}
        self.assertEqual(v.costs_for(b,v.STEP-1,v.STEP)[2],1)
        self.assertEqual(v.costs_for(b,v.STEP,v.STEP+1)[2],0)
        self.assertEqual(v.costs_for(b,0,1)[1],20.)
    def test_no_economic_dispatch_after_completion(self):
        text=(v.HERE.parents[2]/'.github/workflows/kr3-whole-failure-v1.yml').read_text()
        for bad in ['contents: write','git push','pip install','--inputs','workflow_dispatch:','schedule:','persist-credentials: true']:
            self.assertNotIn(bad,text)
        self.assertIn('verify_saved.py',text)
if __name__=='__main__':unittest.main()
