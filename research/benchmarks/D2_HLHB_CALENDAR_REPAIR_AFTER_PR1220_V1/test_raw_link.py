import gzip,json,unittest
from copy import deepcopy
import verify_saved as v

class RawEngineLinkChecks(unittest.TestCase):
    def setUp(self):
        import raw_link
        self.link=raw_link
        self.r=json.loads(gzip.decompress((v.HERE/'results/HLHB/RESULT.json.gz').read_bytes()))
        self.raw=json.loads(gzip.decompress((v.HERE/'results/HLHB/RAW_ENGINE.json.gz').read_bytes()))
        self.context=json.loads((v.HERE/'NORMALIZATION_CONTEXT.json').read_bytes())
        self.spec=json.loads((v.HERE/'SPEC.json').read_bytes())
    def check(self):
        return self.link.validate_raw_link(self.r,self.raw,self.context,self.spec)
    def test_62_actual_raw_trades_match(self):
        for kind in ('D2','HLHB'):
            r=json.loads(gzip.decompress((v.HERE/f'results/{kind}/RESULT.json.gz').read_bytes()))
            raw=json.loads(gzip.decompress((v.HERE/f'results/{kind}/RAW_ENGINE.json.gz').read_bytes()))
            self.assertTrue(self.link.validate_raw_link(r,raw,self.context,self.spec)['one_to_one_identity'])
    def test_internally_consistent_fabricated_report_rejected(self):
        t=self.r['normalized_trades'][0]
        t['exit_price']*=1.1
        g=(t['exit_price']/t['entry_price']-1)*10000
        t.update(gross_bps=g,net_bps=g-t['cost_bps'],cost2_bps=g-2*t['cost_bps'],
                 net_upper_bps=g-t['cost_lower_bps'],cost2_upper_bps=g-2*t['cost_lower_bps'])
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:exit_price'):self.check()
    def test_deleted_raw_trade_rejected(self):
        self.raw['trades'].pop()
        with self.assertRaisesRegex(ValueError,'RAW_REPORT_CARDINALITY'):self.check()
    def test_duplicated_raw_trade_rejected(self):
        self.raw['trades'][1]=deepcopy(self.raw['trades'][0])
        with self.assertRaisesRegex(ValueError,'RAW_DUPLICATE_ORIGIN'):self.check()
    def test_reordered_raw_rows_are_supported(self):
        self.raw['trades'].reverse()
        self.assertTrue(self.check()['one_to_one_identity'])
    def test_changed_report_symbol_rejected(self):
        self.r['normalized_trades'][0]['symbol']='BTC-USDT'
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:symbol'):self.check()
    def test_different_entry_clock_rejected(self):
        self.r['normalized_trades'][0]['entry_ts']+=1
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:entry_ts'):self.check()
    def test_report_exit_reason_cannot_be_substituted(self):
        self.r['normalized_trades'][0]['reason']='roi'
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:reason'):self.check()
    def test_open_mark_not_engine_forced_fill(self):
        t=next(t for t in self.r['normalized_trades'] if not t['closed'])
        t['exit_price']=t['engine_close_rate']
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:exit_price'):self.check()
    def test_open_mark_not_completed_winner(self):
        next(t for t in self.r['normalized_trades'] if not t['closed'])['closed']=True
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:closed'):self.check()
    def test_intrabar_cost_time_not_exact_fill_timestamp(self):
        t=next(t for t in self.r['normalized_trades'] if t['intrabar_time_unobserved'])
        t['exit_ts']=t['exit_ts_lower']
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:exit_ts'):self.check()
    def test_engine_native_fees_not_common_cost_double_deduction(self):
        self.r['normalized_trades'][0]['engine']['fee_open']=0.002
        with self.assertRaisesRegex(ValueError,'RAW_LINK_MISMATCH:engine.fee_open'):self.check()
    def test_modified_common_cost_context_rejected(self):
        self.context['costs']['BTC-USDT']['fee_bps']+=1
        with self.assertRaisesRegex(ValueError,'CONTEXT_COST_BINDING'):self.check()
    def test_changed_resolved_strategy_rejected(self):
        self.r['resolved']['stoploss']=-.01
        with self.assertRaisesRegex(ValueError,'RAW_REPORT_METADATA:resolved'):self.check()
    def test_original_measured_evidence_unchanged(self):
        old=json.loads((v.HERE/'FINAL_HASHES.json').read_bytes())
        for name,digest in old.items():
            self.assertEqual(v.sha((v.HERE/name).read_bytes()),digest,name)

if __name__=='__main__':unittest.main()
