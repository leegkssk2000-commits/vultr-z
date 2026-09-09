"""Artificial prefix, state, fill, loss and completion tests; no market outcomes."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from backend.research.rebuild import c63_pre_release_pullback_v1 as c

class EntryTests(unittest.TestCase):
    def fixture(self,n=60):
        bars=[c.f.Bar(i*c.BAR,102.,105.,101.,102.,1.) for i in range(n)]
        bars[20]=replace(bars[20],low=95.)
        bars[23]=replace(bars[23],low=99.,close=102.)
        features=[None if i<20 else dict(squeeze_on=20<=i<=28,release=i==29,long_release=i==29,momentum=2.,available_at=(i+1)*c.BAR,bb_upper=105.) for i in range(n)]
        return bars,features
    def setups(self,b,features,start=0):
        with patch.object(c.f,'squeeze_features',return_value=features),patch.object(c.f,'_average',return_value=[100.]*len(b)):
            return c.prepare_setups(b,start,len(b)*c.BAR)
    def call(self,b,features):
        rows=[dict(bar_open_ts=x.open_ts,bar_close_ts=x.open_ts+c.BAR,open=x.open,high=x.high,low=x.low,close=x.close,volume=x.volume) for x in b]
        with patch.object(c.f,'squeeze_features',return_value=features),patch.object(c.f,'_average',return_value=[100.]*len(b)):
            return c.replay(rows,eval_start_ms=0,eval_end_ms=len(b)*c.BAR)
    def test_third_squeeze_prep_not_same_bar_signal(self):
        b,f=self.fixture();s,l,_=self.setups(b,f);self.assertEqual(next(x for x in l if x['kind']=='PREPARED')['prep_index'],22);self.assertEqual(s[0]['signal_index'],23);self.assertLess(s[0]['setup_available_at'],s[0]['signal_ts'])
    def test_no_future_release_required(self):
        b,f=self.fixture();f[29]=dict(f[29],release=False,long_release=False)
        self.assertEqual(len(self.setups(b,f)[0]),1)
    def test_release_touch_cannot_backfill_entry(self):
        b,f=self.fixture();f[23]=dict(f[23],squeeze_on=False,release=True,long_release=True)
        self.assertFalse(self.setups(b[:24],f[:24])[0])
    def test_no_touch_no_entry(self):
        b,f=self.fixture();b[23]=replace(b[23],low=101.)
        self.assertFalse(self.setups(b,f)[0])
    def test_reclaim_equality_not_signal(self):
        b,f=self.fixture();b[23]=replace(b[23],close=100.)
        self.assertFalse(self.setups(b,f)[0])
    def test_touch_equality_allowed(self):
        b,f=self.fixture();b[23]=replace(b[23],low=100.)
        self.assertEqual(len(self.setups(b,f)[0]),1)
    def test_negative_momentum_no_signal(self):
        b,f=self.fixture();f[23]=dict(f[23],momentum=0.)
        self.assertFalse(self.setups(b,f)[0])
    def test_floor_cancel_no_rearm_in_episode(self):
        b,f=self.fixture();b[23]=replace(b[23],low=94.,close=95.);b[24]=replace(b[24],low=99.)
        self.assertFalse(self.setups(b,f)[0])
    def test_floor_not_widened_to_later_pullback_low(self):
        b,f=self.fixture();b[23]=replace(b[23],low=94.)
        self.assertEqual(self.setups(b,f)[0][0]['floor'],95.)
    def test_one_signal_per_episode(self):
        b,f=self.fixture();b[24]=replace(b[24],low=99.)
        self.assertEqual(len(self.setups(b,f)[0]),1)
    def test_prefix_signal_identity(self):
        b,f=self.fixture();self.assertEqual(self.setups(b,f)[0],self.setups(b[:24],f[:24])[0])
    def test_no_carry_in_preparation(self):
        b,f=self.fixture();s,l,_=self.setups(b,f,start=24*c.BAR)
        self.assertTrue(all(x.get('prep_index',100)>=23 for x in l if x['kind']=='PREPARED'));self.assertFalse(s)
    def test_real_next_open_not_level(self):
        b,f=self.fixture();b[24]=replace(b[24],open=103.)
        t=self.call(b,f)['trades'][0];self.assertEqual(t['entry_price'],103.);self.assertNotEqual(t['entry_price'],100.);self.assertEqual(t['entry_index'],24)
    def test_gap_below_floor_cancel(self):
        b,f=self.fixture();b[24]=replace(b[24],open=94.,low=93.)
        r=self.call(b,f);self.assertFalse(r['trades']);self.assertEqual(r['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_twenty_bars_from_actual_entry(self):
        b,f=self.fixture();t=self.call(b,f)['trades'][0];self.assertEqual(t['exit_index'],44);self.assertEqual(t['exit_reason'],'FIXED_TIME_CLOSE_NEXT_OPEN')
    def test_native_floor_exit_priority(self):
        b,f=self.fixture();b[24]=replace(b[24],close=94.,low=93.);f[24]=dict(f[24],momentum=-1.)
        t=self.call(b,f)['trades'][0];self.assertEqual(t['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN')
    def test_pending_signal_not_fabricated(self):
        b,f=self.fixture(24);r=self.call(b,f);self.assertFalse(r['trades']);self.assertEqual(len(r['pending_entries']),1)
    def test_open_tail_not_forced_close(self):
        b,f=self.fixture(28);r=self.call(b,f);self.assertFalse(r['trades']);self.assertEqual(len(r['open_positions']),1);self.assertFalse(r['open_positions'][0]['terminal_liquidation'])
    def test_input_unchanged(self):
        b,f=self.fixture();old=deepcopy((b,f));self.call(b,f);self.assertEqual((b,f),old)
    def test_native_gap_invalid(self):
        b,f=self.fixture();b[4]=replace(b[4],open_ts=5*c.BAR)
        with self.assertRaises(ValueError):self.call(b,f)
if __name__=='__main__':unittest.main()
