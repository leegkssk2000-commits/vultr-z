"""P1: omissions/delays must fail even with no new-exit trace recorded."""
from copy import deepcopy
from pathlib import Path
import os,unittest
import verify_first_breach as v

class FirstBreachTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=Path(os.environ['C57_ORIGINAL_INPUTS'])
        cls.spec=v.read(v.HERE/'SPEC.json');cls.packets={};cls.raw={};cls.arrays={}
        for per in v.PERIODS:
            p=cls.inputs/(per+'.json.gz')
            v.need(v.sha(p)==cls.spec['input_packet_sha256'][per],'TEST_PACKET_HASH')
            cls.packets[per]=v.gz(p);cls.raw[per]=v.gz(v.HERE/per/'RAW.json.gz')
            for sym,rows in cls.packets[per]['rows_by'].items():cls.arrays[per,sym]=(v.bounded_ema(rows,20),v.bounded_ema(rows,50))
    def sample(self,floor=True):
        per='DEV2025'
        for sym,raw in self.raw[per].items():
            for t in raw['trades']:
                if (t.get('exit_reason')==v.FILL)==floor:
                    trace=[x for x in raw['trace'] if x['signal_index']==t['signal_index']]
                    return per,sym,deepcopy(t),deepcopy(trace)
    def check(self,per,sym,t,trace,rows=None):
        return v.check_position(t,trace,rows or self.packets[per]['rows_by'][sym],*self.arrays[per,sym],self.packets[per]['costs'][sym],self.spec['periods'][per]['runoff_end_ms'])
    def test_all_262_positions_and_2692_held_closes(self):
        result=v.verify(self.inputs)
        self.assertEqual(sum(x['positions'] for x in result['periods'].values()),262)
        self.assertEqual(sum(x['held_closes_checked'] for x in result['periods'].values()),2692)
        self.assertEqual(sum(x['first_floor_intents'] for x in result['periods'].values()),29)
        self.assertEqual(sum(x['nonfloor_paths_checked'] for x in result['periods'].values()),233)
    def test_deleted_floor_trace_is_not_a_no_trigger_pass(self):
        per,sym,t,trace=self.sample();trace=[x for x in trace if x['kind'] not in (v.FLOOR,v.FILL)]
        t['exit_reason']='TIME_STOP'
        with self.assertRaisesRegex(ValueError,'MISSING_OR_DELAYED_FIRST_FLOOR_BREACH'):self.check(per,sym,t,trace)
    def test_delayed_floor_trace_rejected(self):
        per,sym,t,trace=self.sample();next(x for x in trace if x['kind']==v.FLOOR)['index']+=1
        with self.assertRaisesRegex(ValueError,'MISSING_OR_DELAYED_FIRST_FLOOR_BREACH'):self.check(per,sym,t,trace)
    def test_skipped_breach_on_originally_no_floor_path(self):
        per='DEV2025'
        for sym,r in self.raw[per].items():
            for t in r['trades']:
                if t.get('exit_reason')==v.FILL or not t['original_pullback_floor']['available']:continue
                j=t['entry_index'];floor=t['original_pullback_floor']['price'];e20,e50=self.arrays[per,sym]
                if not e20[j]>e50[j] or floor*(1-1e-6)<=e50[j]:continue
                rows=deepcopy(self.packets[per]['rows_by'][sym]);rows[j]['close']=floor*(1-1e-6)
                trace=[x for x in r['trace'] if x['signal_index']==t['signal_index']]
                with self.assertRaisesRegex(ValueError,'MISSING_OR_DELAYED_FIRST_FLOOR_BREACH'):self.check(per,sym,t,trace,rows)
                return
        self.fail('No suitable omission fixture')
    def test_fake_early_guard_cannot_hide_breach(self):
        per,sym,t,trace=self.sample();t['profit_zone_state']['armed_index']=t['entry_index']
        with self.assertRaisesRegex(ValueError,'C51_ACTIVATION'):self.check(per,sym,t,trace)
    def test_incomplete_source_clock_rejected(self):
        per,sym,t,trace=self.sample();rows=deepcopy(self.packets[per]['rows_by'][sym]);rows[t['entry_index']]['bar_close_ts']+=1
        with self.assertRaisesRegex(ValueError,'SOURCE_HELD_CLOSE_CLOCK'):self.check(per,sym,t,trace,rows)
    def test_next_open_is_not_trigger_line(self):
        per,sym,t,trace=self.sample();t['exit_price']=t['original_pullback_floor']['price']
        with self.assertRaisesRegex(ValueError,'SOURCE_NEXT_OPEN'):self.check(per,sym,t,trace)
    def test_suffix_after_recorded_hold_does_not_affect_decision(self):
        per,sym,t,trace=self.sample();rows=deepcopy(self.packets[per]['rows_by'][sym]);before=self.check(per,sym,t,trace)
        for row in rows[t['exit_index']+1:]:row.update(close=1e8,low=.00001,high=1e9)
        self.assertEqual(before,self.check(per,sym,t,trace,rows))
if __name__=='__main__':unittest.main()
