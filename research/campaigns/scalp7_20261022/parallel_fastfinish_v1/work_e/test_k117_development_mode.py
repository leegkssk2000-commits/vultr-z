"""Development opt-in stays distinct from fixtures and formal admission."""
from copy import deepcopy
import unittest
import k117_adapter as k
from test_k117_adapter import model, SOURCE, COST, T, pending


class DevelopmentMode(unittest.TestCase):
    def observer(self):
        return k.Adapter(enabled=True,fixture=False,development=True)

    def test_development_is_default_off(self):
        with self.assertRaisesRegex(ValueError,'DEFAULT_OFF'):
            k.Adapter(development=True)

    def test_development_does_not_grant_formal_admission(self):
        a=self.observer()
        self.assertFalse(a.state['fixture'])
        self.assertTrue(a.state['development_observation'])
        self.assertFalse(a.state['formal_fresh_credit'])
        self.assertEqual(a.state['formal_gate'],k.FORMAL_GATE)
        self.assertIsNone(a.state['NAV'])
        with self.assertRaisesRegex(ValueError,k.FORMAL_GATE):
            k.Adapter(enabled=True,fixture=False)

    def test_ambiguous_fixture_development_rejected(self):
        with self.assertRaisesRegex(ValueError,'SINGLE_OBSERVATION_MODE'):
            k.Adapter(enabled=True,fixture=True,development=True)

    def test_unknown_units_preserve_real_observation_hold(self):
        a=self.observer()
        result=model(a,source={**SOURCE,'volume_units':'UNKNOWN'})
        self.assertEqual(result['reason'],'VOLUME_UNIT_UNKNOWN')
        self.assertFalse(a.state['fixture'])
        self.assertFalse(a.state['signals'])
        self.assertFalse(a.state['pending'])
        self.assertEqual(a.state['order_calls'],0)

    def test_fixture_state_cannot_be_resumed_as_real_observation(self):
        a=k.Adapter(enabled=True,fixture=True)
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_CODE_MISMATCH'):
            k.Adapter(enabled=True,development=True,state=a.state)

    def test_real_observer_cannot_accept_fixture_cost(self):
        a=self.observer();_,event=pending(a)
        before=deepcopy(a.state)
        with self.assertRaisesRegex(ValueError,'FIXTURE_COST_FOR_REAL_OBSERVATION_FORBIDDEN'):
            a.entry_open(symbol='BTC-USDT',opened=event,cost_model=COST,asof_ms=T+k.TF)
        self.assertEqual(a.state,before)

    def test_development_restart_preserves_nonformal_binding(self):
        a=self.observer();model(a,source={**SOURCE,'volume_units':'UNKNOWN'})
        resumed=k.Adapter(enabled=True,development=True,state=a.state)
        self.assertEqual(a.state,resumed.state)
        tampered=deepcopy(a.state);tampered['formal_fresh_credit']=True
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_CODE_MISMATCH'):
            k.Adapter(enabled=True,development=True,state=tampered)


if __name__=='__main__':unittest.main()
