import json,tempfile,unittest
from pathlib import Path
from backend.research.rebuild import top5_break_validation_v1 as b
from backend.research.rebuild.test_top5_development_repair_v1 import fixture

class Validation(unittest.TestCase):
    def test_exact_plan_review_and_authority(self):
        p,cfg,plan,dev=b.authorize()
        self.assertEqual(cfg['candidate'],plan['candidate'])
        self.assertEqual(cfg['stage_review']['P0'],'UNCONFIRMED')
        self.assertFalse(cfg['OOS_authorized']);self.assertFalse(cfg['g5b_entry_authorized'])
    def test_prefix_stops_before_poisoned_oos(self):
        rows=fixture(310,14400000)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'rows.json';p.write_text(json.dumps(rows)+',MALFORMED_UNREAD_OOS')
            parsed,offset=b.validation_prefix(p,250*14400000,300*14400000,0)
            self.assertEqual(parsed,rows[:300]);self.assertEqual(offset,250)
    def test_shared_evaluator_same_geometry_on_validation_slice(self):
        p,cfg,plan,dev=b.authorize();symbol=p['symbols'][0]
        rows=fixture(550,14400000);p={**p,'development_interval_ms':[300*14400000,550*14400000]}
        spec=next(x['executable_spec'] for x in b.core.read(b.core.FREEZE)['children'] if x['lane_id']==b.LANE)
        trades,events=b.simulate(rows,300,symbol,spec,p,dev['cost_by_symbol'],'base',None)
        self.assertTrue(events)
        indices=[e['signal_index'] for e in events]
        raw=b.core.common.evaluate_development_events(rows[300:],indices,split_start_ms=p['development_interval_ms'][0],split_end_ms=p['development_interval_ms'][1],interval_ms=14400000,hold_bars=6)
        for x,y in zip(trades,raw['trades']):
            for k in ['entry_ts','exit_ts','entry_price','exit_price','gross_bps']:self.assertEqual(x[k],y[k])
            self.assertEqual(x['split'],'VALIDATION_EVIDENCE_ONLY')
            self.assertFalse(x['G5A_economic_PASS'])
    def test_durable_validation_if_present(self):
        p=b.core.ROOT/b.OUTPUT/'receipt.json'
        if not p.exists():self.skipTest('Pre-outcome test')
        r=json.loads(p.read_text());b.core.probe.verify_seal(r,'BREAK')
        self.assertEqual(r['comparison_budget_consumed'],1)
        self.assertEqual(r['OOS_budget_consumed'],0)
        self.assertFalse(r['formal_economic_PASS']);self.assertFalse(r['other_lane_context_receives_validation'])
        for v in r['source_access'].values():self.assertEqual(v['purged_OOS_rows_decoded'],0)
        for a in r['artifacts'].values():self.assertEqual(b.core.file_sha(b.core.ROOT/a['path']),a['file_sha256'])
        self.assertEqual(r['candidate'],b.core.read(b.PLAN)['candidate']['child_id'])

if __name__=='__main__':unittest.main()
