from copy import deepcopy
import json
import unittest
from backend.research.rebuild import keltner_m1_signal_low_v1 as m1
from backend.research.rebuild.test_parallel_exit_keltner_v1 import bars, bundle


def run(rows, b=None, **kw):
    return m1.replay(rows, b or bundle(rows,[0]), eval_start_ms=0,
                     eval_end_ms=rows[-1]['bar_close_ts'], **kw)


def breach(rows, j, price=97.):
    rows[j].update(close=price, low=min(price,rows[j]['low']))


class M1Tests(unittest.TestCase):
    def test_disabled_exact_M(self):
        rows=bars(30); breach(rows,3); b=bundle(rows,[0,4,13,27])
        self.assertEqual(run(rows,b,enabled=False),m1.parent.replay(rows,b,eval_start_ms=0,eval_end_ms=30*m1.BAR))

    def test_equal_and_intrabar_touch_do_not_trigger(self):
        rows=bars(20); rows[2].update(low=90.,close=98.)
        out=run(rows); self.assertEqual(out['trades'][0]['exit_index'],12)
        self.assertFalse(any(e['kind']==m1.TRIGGER for e in out['trace']))

    def test_first_held_close_then_next_open_gap(self):
        rows=bars(20); breach(rows,1); rows[2].update(open=90.,low=89.,close=91.)
        t=run(rows)['trades'][0]
        self.assertEqual((t['exit_index'],t['exit_price'],t['exit_ts']),(2,90.,2*m1.BAR))
        self.assertEqual(t['exit_reason'],m1.EXIT)
        self.assertAlmostEqual(t['gross_bps'],-1000.)

    def test_exit_bar_future_range_not_used(self):
        rows=bars(20); breach(rows,2); a=run(rows)['trades'][0]
        rows[3].update(high=10000.,low=1.,close=500.)
        self.assertEqual(a,run(rows)['trades'][0])

    def test_signal_low_frozen_not_trailed(self):
        rows=bars(20); rows[1]['low']=90.; breach(rows,2)
        self.assertEqual(run(rows)['trades'][0]['exit_index'],3)

    def test_D_wins_simultaneous_trigger(self):
        rows=bars(20); breach(rows,2); b=bundle(rows,[0]); b['ema20'][2]=99.
        out=run(rows,b)
        self.assertEqual(len(out['trades']),1)
        self.assertEqual(out['trades'][0]['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN')
        self.assertFalse(any(e['kind']==m1.TRIGGER for e in out['trace']))

    def test_timeout_close_precedes_new_trigger(self):
        rows=bars(20); breach(rows,12)
        out=run(rows); self.assertEqual(out['trades'][0]['exit_index'],12)
        self.assertFalse(any(e['kind']==m1.TRIGGER for e in out['trace']))

    def test_prior_trigger_executes_before_timeout_close(self):
        rows=bars(20); breach(rows,11); rows[12]['open']=99.
        t=run(rows)['trades'][0]
        self.assertEqual((t['exit_reason'],t['exit_ts']),(m1.EXIT,12*m1.BAR))

    def test_strict_end_timeout_stays_open_without_new_trigger(self):
        rows=bars(13); breach(rows,12); out=run(rows)
        self.assertEqual(out['trades'],[])
        self.assertIsNone(out['open_positions'][0]['pending_exit_signal_ts'])
        self.assertFalse(out['open_positions'][0]['terminal_liquidation'])

    def test_end_trigger_pending_no_fabricated_fill(self):
        rows=bars(6); breach(rows,5); out=run(rows)
        self.assertEqual(out['trades'],[])
        self.assertEqual(out['open_positions'][0]['pending_exit_signal_ts'],6*m1.BAR)
        self.assertEqual(out['open_positions'][0]['mark_price'],97.)

    def test_actual_close_preserves_reference_and_blocks_replacement(self):
        rows=bars(30); breach(rows,1); b=bundle(rows,[0,3,12,13,27])
        p=run(rows,b,enabled=False); c=run(rows,b)
        for k in ('reference_events','reference_opportunities','reference_checkpoint'):
            self.assertEqual(p[k],c[k])
        self.assertEqual([e['signal_index'] for e in p['events'] if e['admission']],
                         [e['signal_index'] for e in c['events'] if e['admission']])
        self.assertEqual(c['events'][1]['exclusion_reason'],'REFERENCE_OPPORTUNITY_RESERVED')
        self.assertGreater(c['reference_opportunities'][0]['release_ts'],c['trades'][0]['exit_ts'])
        for k,v in c['audit'].items():
            if k.startswith('reference_virtual_'): self.assertEqual(v,0)

    def test_fixed_all_M_origins_matches_full_including_tail(self):
        rows=bars(30); breach(rows,1); b=bundle(rows,[0,3,13,27])
        a=run(rows,b); f=run(rows,b,fixed_signal_indices=[0,13,27])
        for k in ('trades','open_positions','trace'): self.assertEqual(a[k],f[k])

    def test_reference_checkpoint_restart_duplicate_safe(self):
        rows=bars(30); breach(rows,1); b=bundle(rows,[0,3,13,27])
        ck=m1.parent.causal_clock(rows,b,eval_start_ms=0,eval_end_ms=30*m1.BAR,stop_after_index=5)
        self.assertEqual(run(rows,b),run(rows,b,reference_checkpoint=json.loads(json.dumps(ck))))

    def test_trigger_prefix_matches_longer_run(self):
        rows=bars(20); breach(rows,3); a=run(rows)
        prefix=rows[:4]; b=run(prefix)
        ta=[e for e in a['trace'] if e['kind']==m1.TRIGGER]
        tb=[e for e in b['trace'] if e['kind']==m1.TRIGGER]
        self.assertEqual(ta,tb)

    def test_input_unchanged_and_hook_restored(self):
        rows=bars(20); breach(rows,2); original=deepcopy(rows); run(rows)
        self.assertEqual(original,rows); self.assertIs(m1.d._path,m1.ORIGINAL_PATH)

    def test_funding_exposure_stop_at_actual_fill(self):
        from backend.research.rebuild import parallel_exit_dev_v1 as runner
        from backend.research.rebuild.test_break_channel_source_v1 import policy,COSTS
        rows=bars(20); breach(rows,2); b=bundle(rows,[0]); pol=policy()
        pol['development_interval_ms']=[0,20*m1.BAR]
        p=runner.charge_result(run(rows,b,enabled=False),'TEST','keltner_trend_main','M',pol,COSTS,rows)
        c=runner.charge_result(run(rows,b),'TEST','keltner_trend_main','M1',pol,COSTS,rows)
        a,z=p['trades'][0],c['trades'][0]
        self.assertLess(z['hold_ms'],a['hold_ms']); self.assertLessEqual(z['funding_bps'],a['funding_bps'])
        self.assertGreaterEqual(z['cost_bps'],20.)
        self.assertAlmostEqual(z['cost2x_net_bps'],z['gross_bps']-2*z['cost_bps'])


if __name__=='__main__': unittest.main()
