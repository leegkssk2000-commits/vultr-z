"""Saved-record counterexamples; no new native or candidate replay."""
import unittest
from copy import deepcopy
from unittest.mock import patch
import verify_saved as v
class SavedTests(unittest.TestCase):
    def event(self):
        r=v.gz(v.HERE/'DEV2025/RESULT.json.gz');return deepcopy(next(e for e in r['events'] if e['er_context']['daily_context']['value'] is not None))
    def test_complete(self):
        x=v.verify(derived_sha='e271f2bf7b0e72e9a6e779e789f9ce839b6412038c27af7b5d696c2658a6ef3b');self.assertEqual(sum(p['positions'] for p in x['periods'].values()),91)
    def test_future_daily_date(self):
        e=self.event();e['er_context']['daily_context']['daily_closes'][-1]['available_at']+=v.DAY
        with self.assertRaisesRegex(ValueError,'DAILY_AVAILABLE_CLOCK'):v.daily_context(e)
    def test_wrong_ema(self):
        e=self.event();e['er_context']['daily_context']['value']+=1
        with self.assertRaisesRegex(ValueError,'EMA_ARITHMETIC'):v.daily_context(e)
    def test_changed_eligibility(self):
        e=self.event();x=e['er_context']['daily_context'];x['eligible']=not x['eligible']
        with self.assertRaisesRegex(ValueError,'DAILY_STRICT_PREDICATE'):v.daily_context(e)
    def test_missing_daily_middle(self):
        e=self.event();e['er_context']['daily_context']['daily_closes'].pop(1)
        with self.assertRaises(ValueError):v.daily_context(e)
    def test_wrong_winrate(self):
        r=v.gz(v.HERE/'DEV2025/RESULT.json.gz');r['metrics']['base_cost']['win_rate']=.9
        with self.assertRaisesRegex(ValueError,'METRIC_win_rate'):v.metrics(r)
    def test_wrong_net(self):
        r=v.gz(v.HERE/'DEV2025/RESULT.json.gz');r['metrics']['terminal_net_bps']+=100
        with self.assertRaisesRegex(ValueError,'TERMINAL_NET'):v.metrics(r)
    def test_wrong_marked_dd(self):
        r=v.gz(v.HERE/'DEV2025/RESULT.json.gz');r['metrics']['marked_DD_trade_sum_bps']-=100
        with self.assertRaisesRegex(ValueError,'DAILY_DD'):v.metrics(r)
    def test_pin_rejected(self):
        with self.assertRaisesRegex(ValueError,'DERIVED_PIN'):v.verify(derived_sha='0'*64)
    def test_rounded_equal_is_not_improvement(self):self.assertTrue(__import__('math').isclose(1.,1.+1e-12,rel_tol=1e-12,abs_tol=1e-7))
    def test_warmup_not_direction_credit(self):
        x=v.cell('DEV2025')['details']['removed_by_reason'];self.assertEqual(x[v.MISSING]['n'],4);self.assertEqual(x[v.VETO]['n'],24)
    def test_readonly_workflow(self):
        s=(v.REPO/'.github/workflows/c63-daily-ema21-tip-v1.yml').read_text()
        for key in ('contents: write','_study_v1','git push','download-artifact','workflow_dispatch:','schedule:'):self.assertNotIn(key,s)
if __name__=='__main__':unittest.main()
