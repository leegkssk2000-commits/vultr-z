"""Counterexamples for the isolated Q0 read-only witness, with no production writes."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import q0_readonly_audit as audit

SNAPSHOT=Path(__file__).resolve().parents[3]

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        for path in audit.INPUTS:
            target=self.root/path
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(SNAPSHOT/path,target)
    def tearDown(self):self.tmp.cleanup()
    def read_events(self):
        return [json.loads(x) for x in (self.root/audit.INPUTS[1]).read_text().splitlines()]
    def write_events(self,events):
        (self.root/audit.INPUTS[1]).write_text(''.join(json.dumps(e)+'\n' for e in events))
    def test_original_sealed_archive_and_independent_native_parity(self):
        r=audit.build(self.root)
        self.assertEqual(r['integrity']['state_and_event_chain_errors'],[])
        self.assertEqual(r['counts']['closed_verified_ledger_T'],17)
        self.assertEqual(r['counts']['minute_rows_verified'],2400)
        self.assertLess(r['integrity']['cost_arithmetic_max_abs_diff_bps'],1e-10)
        self.assertEqual(r['official_accounting']['status'],'G5_ACCOUNTING_INPUT_BLOCKED')
        self.assertEqual(r['official_accounting']['first_field'],'entry_source_4h_open_row')
        self.assertEqual(r['integrity']['missing_entry_4h_source_T'],14)
    def test_two_x_doubles_the_floor_and_keeps_gross_unchanged(self):
        r=audit.build(self.root)
        for t in r['trade_rows']:
            self.assertGreaterEqual(t['model_cost_bps'],20)
            self.assertAlmostEqual(t['model_net1x_bps']-t['model_net2x_bps'],t['model_cost_bps'])
        self.assertAlmostEqual(r['model_diagnostic']['cost2x_total_bps'],2*r['model_diagnostic']['cost1x_total_bps'])
    def test_unsealed_timestamp_mutation_blocks_publishable_metrics(self):
        e=self.read_events();e[0]['observed_at_ms']+=1;self.write_events(e)
        r=audit.build(self.root)
        self.assertIn('EVENT_HASH:0',r['integrity']['state_and_event_chain_errors'])
        self.assertIsNone(r['model_diagnostic'])
    def test_duplicate_signal_not_a_new_trade(self):
        e=self.read_events();e.append(e[0]);self.write_events(e)
        r=audit.build(self.root)
        self.assertEqual(r['integrity']['duplicate_event_ids'],1)
        self.assertIn('SIGNAL_COUNT',r['integrity']['state_and_event_chain_errors'])
        self.assertIsNone(r['model_diagnostic'])
    def test_missing_minute_rejected_by_native_witness_parser(self):
        e=self.read_events();w=next(x for x in e if x['kind']=='INTRABAR_STOP_WITNESS')['witness']
        w['full_stop_bar_1m_rows'].pop(0);self.write_events(e)
        with self.assertRaisesRegex(RuntimeError,'Q0_1M_STOP_BAR_INCOMPLETE'):
            audit.build(self.root)

if __name__=='__main__':unittest.main()
