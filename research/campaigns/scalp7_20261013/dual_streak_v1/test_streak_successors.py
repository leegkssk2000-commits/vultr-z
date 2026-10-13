from __future__ import annotations
from dataclasses import dataclass
import math,unittest
from streak_successor_policies import RejectedHGEventReset,squeeze_signal_low_invalidation

@dataclass
class State:
    side:int=1
    episode_traded:bool=True
    stage:int=1
    pull_low:float=99.0
    pull_high:float=106.0
    def event_reset(self):
        self.stage=0;self.pull_low=math.inf;self.pull_high=-math.inf

class PolicyTests(unittest.TestCase):
    def test_rejected_generated_setup_requires_new_touch(self):
        s=State();p=RejectedHGEventReset();p.generated(1_800_000)
        p.decided(s,accepted=False,decision_ts_ms=1_800_000)
        self.assertFalse(s.episode_traded);self.assertEqual(s.stage,0)
        self.assertEqual(s.side,1);self.assertEqual(s.pull_low,math.inf)

    def test_accepted_event_does_not_clear_original_geometry(self):
        s=State();p=RejectedHGEventReset();p.generated(1_800_000)
        p.decided(s,accepted=True,decision_ts_ms=1_800_000)
        self.assertTrue(s.episode_traded);self.assertEqual(s.stage,1);self.assertEqual(s.pull_low,99)

    def test_no_signal_cannot_reset_trade_state(self):
        s=State();p=RejectedHGEventReset()
        with self.assertRaisesRegex(ValueError,'NO_GENERATED'):
            p.decided(s,accepted=False,decision_ts_ms=1_800_000)
        self.assertEqual(s.stage,1)

    def test_invalid_or_missing_admission_decision_is_not_reject(self):
        s=State();p=RejectedHGEventReset();p.generated(1_800_000)
        with self.assertRaisesRegex(ValueError,'ADMISSION_DECISION'):
            p.decided(s,accepted=None,decision_ts_ms=1_800_000)
        self.assertEqual(s.stage,1);self.assertTrue(s.episode_traded)

    def test_entry_clock_before_signal_rejected(self):
        p=RejectedHGEventReset();p.generated(1_800_000)
        with self.assertRaisesRegex(ValueError,'BEFORE_SIGNAL'):
            p.decided(State(),accepted=False,decision_ts_ms=0)

    def test_duplicate_pending_event_rejected(self):
        p=RejectedHGEventReset();p.generated(1_800_000)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_PRIOR'):
            p.generated(3_600_000)

    def args(self,**overrides):
        args=dict(regime='TREND_DISPERSED',signal_low=100.0,signal_segment=0,
           bar=dict(open_ts_ms=1_800_000,close_ts_ms=3_600_000,available_ts_ms=3_600_000,close=99.0,segment_id=0),
           signal_available_ts_ms=1_800_000,entry_ts_ms=1_800_000,asof_ms=3_600_000,
           parent_update={'exit_next_open':False,'next_stop':95.0,'reason':'PARENT_HOLD'})
        args.update(overrides);return args

    def test_signal_low_break_marks_next_open_not_fill(self):
        args=self.args();out=squeeze_signal_low_invalidation(**args)
        self.assertTrue(out['exit_next_open']);self.assertEqual(out['next_stop'],95)
        self.assertNotIn('exit_price',out);self.assertFalse(args['parent_update']['exit_next_open'])

    def test_panics_parent_path_untouched(self):
        args=self.args(regime='PANIC_DISPERSION');self.assertEqual(squeeze_signal_low_invalidation(**args),args['parent_update'])

    def test_existing_parent_exit_has_priority(self):
        args=self.args(parent_update={'exit_next_open':True,'reason':'SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN'})
        self.assertEqual(squeeze_signal_low_invalidation(**args),args['parent_update'])

    def test_no_exit_at_equal_signal_low(self):
        args=self.args();args['bar']['close']=100
        self.assertFalse(squeeze_signal_low_invalidation(**args)['exit_next_open'])

    def test_future_bar_is_never_a_feature(self):
        with self.assertRaisesRegex(ValueError,'CAUSAL_CLOSED_BAR'):
            squeeze_signal_low_invalidation(**self.args(asof_ms=1_800_000))

    def test_gap_segment_fails_closed(self):
        args=self.args();args['bar']['segment_id']=1
        with self.assertRaisesRegex(ValueError,'SEGMENT_BREAK'):
            squeeze_signal_low_invalidation(**args)

    def test_missing_signal_low_is_not_invented(self):
        with self.assertRaisesRegex(ValueError,'FROZEN_SIGNAL_LOW'):
            squeeze_signal_low_invalidation(**self.args(signal_low=None))

if __name__=='__main__':unittest.main()
