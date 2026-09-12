import unittest
from backend.research.rebuild import squeeze_kr3_unified_v1 as u
from backend.research.rebuild import chart_mechanism_features_v1 as f


class SqueezeKr3UnifiedTests(unittest.TestCase):
    def test_k1_exact_boundaries(self):
        self.assertFalse(u.k1_values(100, 100, 10)['eligible'])
        self.assertTrue(u.k1_values(110, 100, 10)['eligible'])
        self.assertFalse(u.k1_values(110.0001, 100, 10)['eligible'])
        self.assertFalse(u.k1_values(99, 100, 10)['eligible'])
        self.assertFalse(u.k1_values(110, 100, None)['available'])

    def test_k1_previous_atr_is_causal(self):
        bars=[]
        for i in range(70):
            px=100+i*.1
            bars.append(f.Bar(i*f.BAR_MS,px,px+1,px-1,px+.2,1000))
        av=u._averages(bars)
        obs=u.k1_observation(bars,55,av)
        changed=list(bars)
        changed[56]=f.Bar(changed[56].open_ts,1,10000,.5,9000,1000)
        obs2=u.k1_observation(changed,55,u._averages(changed))
        self.assertEqual(obs['eligible'],obs2['eligible'])
        self.assertAlmostEqual(obs['extension_atr'],obs2['extension_atr'])

    def test_profit_zone_arming_and_prior_line_trigger(self):
        state=u._new_guard()
        bar=f.Bar(1000,110,112,108,111,100)
        cost={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':1.}
        state,hit,event=u.k2_step(state,bar=bar,index=10,ema20=108.,ema50=105.,entry_price=100.,entry_ts=0,cost=cost)
        self.assertFalse(hit);self.assertEqual(event,u.K2_ARM);self.assertEqual(state['protected_line'],108.)
        bar2=f.Bar(1000+f.BAR_MS,109,115,107,110,100)
        state,hit,event=u.k2_step(state,bar=bar2,index=11,ema20=109.,ema50=106.,entry_price=100.,entry_ts=0,cost=cost)
        self.assertFalse(hit);self.assertEqual(event,u.K2_UPDATE);self.assertEqual(state['protected_line'],109.)
        bar3=f.Bar(1000+2*f.BAR_MS,108,110,106,108.5,100)
        state,hit,event=u.k2_step(state,bar=bar3,index=12,ema20=110.,ema50=107.,entry_price=100.,entry_ts=0,cost=cost)
        self.assertTrue(hit);self.assertEqual(event,u.K2_TRIGGER);self.assertTrue(state['exit_requested'])

    def test_profit_zone_does_not_arm_without_cost_cover(self):
        state=u._new_guard();cost={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':1.}
        bar=f.Bar(1000,100.1,101,99.5,100.1,100)
        state,hit,event=u.k2_step(state,bar=bar,index=10,ema20=100.05,ema50=99.,entry_price=100.,entry_ts=0,cost=cost)
        self.assertFalse(hit);self.assertIsNone(event);self.assertIsNone(state['armed_index'])

    def test_variants_are_frozen(self):
        self.assertEqual(u.VARIANTS,('U1','U2','U3'))
        self.assertIn('C54_ATR_ENTRY',u.RULES['U1'])
        self.assertIn('C51_POSTPARTIAL',u.RULES['U2'])
        self.assertIn('C54_ATR_ENTRY_PLUS_C51_POSTPARTIAL',u.RULES['U3'])


if __name__=='__main__':
    unittest.main()
