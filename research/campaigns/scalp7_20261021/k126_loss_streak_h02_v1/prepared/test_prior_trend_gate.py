import unittest
from prior_trend_gate import PriorTrendGate, WitnessState, positive
TF=1800000

def row(i, *, adx=32., touch=False, turn=False, short=False):
    side=-1 if short else 1
    ema=100+side*i*.1
    x={'open_ts_ms':i*TF,'close_ts_ms':(i+1)*TF,'feature_available_ts_ms':(i+1)*TF,
       'adx14':adx,'g20':ema,'high':106.,'low':102.,'close':103.,'hi20':120.,'lo20':80.}
    for n in positive.LONG_GMMA: x[f'g{n}']=100-side*n*.1+side*i*.01
    x['g20']=ema
    if short: x.update(high=98.,low=94.,close=97.)
    if touch:
        if short:x.update(high=102.,low=96.,close=99.)
        else:x.update(high=104.,low=99.,close=101.)
    if turn:
        if short:x.update(high=97.,low=92.,close=93.)
        else:x.update(high=110.,low=102.,close=109.)
    return x

class Tests(unittest.TestCase):
    def sequence(self, seq):
        g=PriorTrendGate(True);s=WitnessState()
        for a,b in zip(seq[1:],seq):g.event(s,a,b)
        return g,s
    def test_prior_rise_then_falling_adx_touch_is_valid(self):
        g,s=self.sequence([row(0,adx=31),row(1,adx=33),row(2,adx=32,touch=True),row(3,adx=31,turn=True)])
        self.assertTrue(g.current['qualified']);self.assertLess(g.current['prior_rising_adx_ts_ms'],g.current['first_native_touch_ts_ms'])
    def test_rising_at_same_touch_is_not_prior(self):
        g,s=self.sequence([row(0,adx=31),row(1,adx=33,touch=True),row(2,adx=34,turn=True)])
        self.assertFalse(g.current['qualified'])
    def test_late_rise_cannot_retroactively_qualify_touch(self):
        g,s=self.sequence([row(0,adx=34),row(1,adx=33,touch=True),row(2,adx=35,turn=True)])
        self.assertFalse(g.current['qualified'])
    def test_low_adx_reset_clears_prior(self):
        g,s=self.sequence([row(0,adx=31),row(1,adx=33),row(2,adx=24)])
        self.assertIsNone(s.prior_rise_ts);self.assertEqual(s.stage,0)
    def test_rejection_event_reset_clears_witness(self):
        s=WitnessState();s.prior_rise_ts=1;s.touch_ts=2;s.touch_witness_ts=1;s.stage=1;s.event_reset()
        self.assertIsNone(s.prior_rise_ts);self.assertIsNone(s.touch_witness_ts)
    def test_direction_reset_clears_witness(self):
        s=WitnessState();s.prior_rise_ts=1;s.reset();self.assertIsNone(s.prior_rise_ts);self.assertEqual(s.side,0)
    def test_short_is_symmetric(self):
        g,s=self.sequence([row(0,adx=31,short=True),row(1,adx=33,short=True),row(2,adx=32,touch=True,short=True),row(3,adx=31,turn=True,short=True)])
        self.assertTrue(g.current['qualified']);self.assertEqual(g.current['side'],-1)
    def test_no_future_or_duplicate_timestamp(self):
        g=PriorTrendGate(True);s=WitnessState()
        with self.assertRaises(ValueError):g.event(s,row(0),row(1))
    def test_disabled_preserves_native_event_sequence(self):
        g=PriorTrendGate(False);s=WitnessState();plain=positive.HolyGrailState()
        seq=[row(0,adx=31),row(1,adx=33),row(2,adx=32,touch=True),row(3,adx=31,turn=True)]
        for a,b in zip(seq[1:],seq):self.assertEqual(g.event(s,a,b),positive._hg_event(plain,a,b))
    def test_builder_is_local_and_does_not_mutate_protected_module(self):
        old=(positive._hg_event,positive.HolyGrailState)
        self.assertTrue(callable(PriorTrendGate(True).build()));self.assertEqual(old,(positive._hg_event,positive.HolyGrailState))
    def test_missing_witness_fails_closed(self):
        with self.assertRaises(ValueError):PriorTrendGate(True).evidence('BTC-USDT',row(0),{'side':1,'signal_ts_ms':TF},'rolling')

if __name__=='__main__':unittest.main()
