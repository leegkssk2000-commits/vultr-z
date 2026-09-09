"""Attack saved evidence only; no strategy/market replay or paid requests."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import unittest
import verify_saved as c

class SavedTests(unittest.TestCase):
    def mutated(self,filename,change):
        original=c.gz;path=c.HERE/'DEV2025'/filename;obj=deepcopy(original(path));change(obj)
        def read(p):return deepcopy(obj) if Path(p)==path else original(p)
        with patch.object(c,'gz',side_effect=read):
            with self.assertRaises(ValueError):c.cell('DEV2025')
    def delayed_event(self,raw):
        return next(e for x in raw.values() for e in x['events'] if e['admission'] and e['wait_bars']>1)
    def delayed_trade(self,raw):
        return next(t for x in raw.values() for t in x['trades'] if t['wait_bars']>0)
    def test_valid_saved_result(self):
        self.assertEqual(c.verify()['status'],'REJECT_KEEP_C63')
    def test_no_skipped_pending_close(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_event(x)['pending_observations'].pop(0))
    def test_no_future_daily_available_time(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_event(x)['initial_daily_context']['daily_closes'][-1].update(available_at=10**16))
    def test_no_moved_decision_time(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_event(x).update(decision_ts=1))
    def test_no_clock_reset(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_trade(x).update(entry_clock_reset=True))
    def test_no_changed_entry_price(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_trade(x).update(entry_price=1.))
    def test_no_changed_exit_price(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_trade(x).update(exit_price=1.))
    def test_no_changed_origin(self):
        self.mutated('RAW.json.gz',lambda x:self.delayed_trade(x).update(signal_index=1))
    def test_no_missing_charged_trade(self):
        self.mutated('RESULT.json.gz',lambda x:x['trades'].pop())
    def test_no_fake_net(self):
        self.mutated('RESULT.json.gz',lambda x:x['trades'][0].update(net_bps=999999.))
    def test_no_fake_winrate(self):
        self.mutated('RESULT.json.gz',lambda x:x['metrics']['base_cost'].update(win_rate=1.))
    def test_no_fake_daily_mark(self):
        self.mutated('RESULT.json.gz',lambda x:x['metrics']['daily'][2].update(cumulative_net_mark_bps=999.))
    def test_no_fake_funding(self):
        self.mutated('RESULT.json.gz',lambda x:x['trades'][0].update(cost2x_net_bps=99999.))
    def test_no_changed_raw_held_clock(self):
        def change(x):
            row=next(h for raw in x.values() for h in raw['trace'] if h['kind']=='HELD_CLOSE_OBSERVATION');row['original_clock_bars']+=1
        self.mutated('RAW.json.gz',change)

if __name__=='__main__':unittest.main()
