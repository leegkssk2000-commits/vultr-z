import unittest
from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as u


def row(symbol,signal,entry,end,side='long',opened=False):
    x={'symbol':symbol,'signal_ts':signal,'signal_index':signal//10,'side':side,'entry_ts':entry,'entry_price':100.0}
    if opened:x.update(mark_ts=end,mark_price=101.0)
    else:x.update(exit_ts=end,exit_price=101.0,net_bps=50.0)
    return x


class NativeSleeveTests(unittest.TestCase):
    def test_donor_is_preempted_by_later_core_entry(self):
        core=[row('BTC-USDT',200,20,40)]
        donor=[row('BTC-USDT',100,10,30)]
        p=u.chronological_plan(core,donor)
        self.assertEqual(len(p['accepted_natural']),0)
        self.assertEqual(len(p['accepted_preempt']),1)
        self.assertEqual(p['accepted_preempt'][0]['preempt_ts'],20)

    def test_core_entry_same_open_beats_donor_entry(self):
        core=[row('BTC-USDT',200,20,40)]
        donor=[row('BTC-USDT',100,20,30)]
        p=u.chronological_plan(core,donor)
        self.assertEqual(len(p['accepted_preempt']),0)
        self.assertEqual(p['excluded'][0]['reason'],'CORE_ACTIVE_AT_DONOR_ENTRY')

    def test_natural_donor_exit_same_open_precedes_core_entry(self):
        core=[row('BTC-USDT',200,20,40)]
        donor=[row('BTC-USDT',100,10,20)]
        p=u.chronological_plan(core,donor)
        self.assertEqual(len(p['accepted_natural']),1)
        self.assertEqual(len(p['accepted_preempt']),0)

    def test_core_end_same_open_allows_donor(self):
        core=[row('BTC-USDT',100,10,20)]
        donor=[row('BTC-USDT',200,20,30)]
        p=u.chronological_plan(core,donor)
        self.assertEqual(len(p['accepted_natural']),1)
        self.assertFalse(p['excluded'])

    def test_different_symbols_do_not_conflict(self):
        core=[row('BTC-USDT',100,10,40)]
        donor=[row('ETH-USDT',200,20,30)]
        # Engine active_core is global by event today; same-symbol authority must be enforced.
        # This test documents the required behavior and fails if symbol isolation is absent.
        p=u.chronological_plan(core,donor)
        self.assertEqual(len(p['accepted_natural']),1)

    def test_preempt_raw_uses_open_only_not_exit_bar_high_low(self):
        raw={'signal_ts':0,'signal_index':0,'side':'long','entry_index':1,'entry_ts':10,'entry_price':100.0,
             'mfe_bps':9999.0,'mae_bps':-9999.0,'mark_index':3,'mark_ts':40,'mark_price':103.0,'gross_mark_bps':300.0,'status':'CENSORED'}
        rows=[{'bar_open_ts':0,'open':99.,'high':100.,'low':98.,'close':99.},
              {'bar_open_ts':10,'open':100.,'high':102.,'low':99.,'close':101.},
              {'bar_open_ts':20,'open':101.,'high':999.,'low':1.,'close':500.}]
        out=u.preempt_raw(raw,rows,20)
        self.assertEqual(out['exit_price'],101.)
        self.assertEqual(out['exit_reason'],u.PREEMPT)
        self.assertLess(out['mfe_bps'],1000.)
        self.assertGreater(out['mae_bps'],-1000.)

if __name__=='__main__': unittest.main()
