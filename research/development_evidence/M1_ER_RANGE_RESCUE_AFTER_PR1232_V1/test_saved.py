"""Saved evidence regressions, no strategy replay or source acquisition."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import verify_saved as s

class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=s.gz(s.HERE/'DEV2025/RESULT.json.gz')
        cls.event=next(e for e in cls.r['events'] if e['er_context']['range_context']['rescued'])
    def source(self,e):return {str(z['index']):dict(close=z['close'],bar_close_ts=z['ts']) for z in e['er_context']['source_closes']}
    def test_complete(self):self.assertEqual(s.verify()['positions'],131)
    def test_original_ER_still_recomputed(self):
        e=deepcopy(self.event);e['er_context']['current']['value']+=.1
        with self.assertRaises(ValueError):s.feature(e,self.source(e),s.v)
    def test_range_cannot_include_release_high(self):
        e=deepcopy(self.event);r=e['er_context']['range_context'];r['source_highs'].append(dict(index=e['signal_index'],ts=e['signal_ts'],high=r['signal_close']))
        with self.assertRaisesRegex(ValueError,'RANGE_SOURCE_LENGTH'):s.feature(e,self.source(e),s.v)
    def test_future_high_clock_rejected(self):
        e=deepcopy(self.event);e['er_context']['range_context']['source_highs'][0]['ts']+=1
        with self.assertRaisesRegex(ValueError,'RANGE_SOURCE_CLOCK'):s.feature(e,self.source(e),s.v)
    def test_original_high_value_bound(self):
        e=deepcopy(self.event);src=self.source(e);z=e['er_context']['range_context']['source_highs'][0];src.setdefault(str(z['index']),{})['high']=z['high']+1
        with self.assertRaisesRegex(ValueError,'RANGE_ORIGINAL_PRICE'):s.feature(e,src,s.v)
    def test_false_escape_rejected(self):
        e=deepcopy(self.event);e['er_context']['range_context']['strict_escape']=False
        with self.assertRaises(ValueError):s.feature(e,self.source(e),s.v)
    def test_rescued_signal_cannot_stay_vetoed(self):
        e=deepcopy(self.event);e['er_context']['eligible']=False
        with self.assertRaisesRegex(ValueError,'RESCUE_ELIGIBILITY'):s.feature(e,self.source(e),s.v)
    def test_fake_restored_profit_detected(self):
        original=s.read;meta=deepcopy(original(s.HERE/'DERIVED.json'));meta['details']['DEV2025']['restored_winner_net_bps']+=1
        def changed(path):return meta if str(path).endswith('DERIVED.json') else original(path)
        with patch.object(s,'read',changed):
            with self.assertRaises(ValueError):s.verify()
    def test_derived_file_pin(self):
        with self.assertRaisesRegex(ValueError,'DERIVED_FILE_DRIFT'):s.verify(derived_sha='0'*64)
    def test_roundoff_not_DD_improvement(self):
        parent=s.gz(s.HERE.parents[2]/s.old.OLD/'M1/DEV2025/RESULT.json.gz');child=deepcopy(parent);child['metrics']['marked_DD_trade_sum_bps']-=1e-12
        self.assertFalse(s.old.checks(parent,child,s.v)['DD_down'])
    def test_workflow_closed(self):
        wf=(s.HERE.parents[2]/'.github/workflows/m1-er-range-rescue-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:','persist-credentials: true'):self.assertNotIn(bad,wf)
if __name__=='__main__':unittest.main()
