"""Generated-price regressions only; no recorded-market replay in tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from ops import kp_connected_research_validation_v1 as run
from backend.research.rebuild import scalp7_execution_v2 as engine
from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild.scalp7_source_data_v2 import aggregate_minutes


def signal():
    return {'identity':run.CANDIDATE,'lane':'keltner_holygrail','symbol':'BTC-USDT','timeframe_min':30,
            'signal_open_ts_ms':0,'signal_ts_ms':run.TF,'segment_id':0,'side':1,'stop_price':99.0,
            'max_hold_bars':25,'take_profit_r':None,'partial_take_profit_r':2.0,'partial_fraction':0.10,
            'meta':{'frozen_cost_bps':14.0,'be_arm_r':1.0,'entry_cost_gate':{'atr_price':2.0,'min_ratio':4.5},'fallback_stop_atr_mult':1.2}}


def frame():
    # Generated next-open100 -> first bar survives initial99 and touches2R102
    # -> next bar hits fee-BE100.16. No ambiguous initial-stop/partial conflict.
    prices=[(100,101,99.5,100),(100,102.2,99.5,102),(102,102.1,100,100.5)]
    return pd.DataFrame([{'open_ts_ms':i*run.TF,'close_ts_ms':(i+1)*run.TF,'available_ts_ms':(i+1)*run.TF,
                         'segment_id':0,'open':o,'high':h,'low':lo,'close':c,'volume':1.0}
                        for i,(o,h,lo,c) in enumerate(prices)])


class ConnectedTests(unittest.TestCase):
    def test_synthetic_frozen_partial_be_lifecycle(self):
        traces=[]
        def observe(p,b,h):
            result=parent.exit_update(p,b,h)
            traces.append({'signal_key':run.key(p['signal']),'partial_fraction':result.get('partial_fraction',0),
                           'partial_price':result.get('partial_price')})
            return result
        result=engine.replay([signal()],{'BTC-USDT':frame()},{'BTC-USDT':14},identity=run.CANDIDATE,
                             entry_update=parent.entry_update,exit_update=observe)
        self.assertEqual(len(result['trades']),1)
        t=result['trades'][0]
        self.assertAlmostEqual(t['gross_bps'],34.4)
        self.assertAlmostEqual(t['net_bps'],20.4)
        self.assertEqual(run.arithmetic_audit(result['trades'],traces)['partial_trades_checked'],1)

    def test_late_receipt_guard_is_unchanged(self):
        s=signal();s['signal_ts_ms']+=100
        result=engine.replay([s],{'BTC-USDT':frame()},{'BTC-USDT':14})
        self.assertEqual(result['rejections'],{'LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL':1})
        self.assertEqual(len(result['trades']),0)

    def test_stop_first_never_awards_partial(self):
        f=frame();f.loc[1,'low']=98
        result=engine.replay([signal()],{'BTC-USDT':f},{'BTC-USDT':14},exit_update=parent.exit_update)
        self.assertAlmostEqual(result['trades'][0]['gross_bps'],-100)
        self.assertEqual(run.arithmetic_audit(result['trades'],[])['partial_trades_checked'],0)

    def test_unresolved_end_is_not_forced_realized(self):
        f=frame().iloc[:2].copy()
        result=engine.replay([signal()],{'BTC-USDT':f},{'BTC-USDT':14},exit_update=parent.exit_update)
        self.assertEqual(len(result['trades']),0)
        self.assertEqual(len(result['unresolved']),1)
        self.assertAlmostEqual(result['unresolved'][0]['position']['remaining'],0.9)

    def test_same_signal_occupancy_deduplicated(self):
        result=engine.replay([signal(),signal()],{'BTC-USDT':frame()},{'BTC-USDT':14},exit_update=parent.exit_update)
        self.assertEqual(result['rejections'].get('DUPLICATE_SIGNAL'),1)
        self.assertEqual(len(result['trades']),1)

    def test_cost_stress_not_second_replay(self):
        result=engine.replay([signal()],{'BTC-USDT':frame()},{'BTC-USDT':14},exit_update=parent.exit_update)
        a=metrics.summarize(result['trades'],0,4*run.TF,1)
        b=metrics.summarize(result['trades'],0,4*run.TF,2)
        self.assertEqual(a['T'],b['T'])
        self.assertAlmostEqual(a['Net_bps']-b['Net_bps'],14)
        self.assertIsNone(b['risk_limits']['leverage'])

    def test_receipt_and_model_clock_projections_remain_distinct(self):
        f=pd.DataFrame([{'timestamp_ms':i*60000,'open':100,'high':101,'low':99,'close':100,'volume':1,
                         'received_at_ms':(i+1)*60000+100} for i in range(30)])
        before=f.copy(deep=True)
        model=aggregate_minutes(f,30,observed=False);actual=aggregate_minutes(f,30,observed=True)
        self.assertEqual(int(model.iloc[0].available_ts_ms),run.TF)
        self.assertEqual(int(actual.iloc[0].available_ts_ms),run.TF+100)
        pd.testing.assert_frame_equal(before,f)

    def test_missing_minute_not_forward_filled(self):
        f=pd.DataFrame([{'timestamp_ms':i*60000,'open':100,'high':101,'low':99,'close':100,'volume':1}
                         for i in range(29)])
        self.assertTrue(aggregate_minutes(f,30,observed=False).empty)

    def test_wrong_input_hash_precedes_any_model_import(self):
        with self.assertRaisesRegex(Exception,'INPUT_HASH'):
            run.verify_input(b'{}',{'input_payload_sha256':'0'*64})

    def test_contract_hash_mismatch(self):
        with self.assertRaisesRegex(Exception,'CONTRACT_HASH'):
            run.verify_contract(b'{}',{'contract_sha256':'0'*64})

    def test_result_evidence_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);run.write_once(root,'row.json',{'count':1})
            with self.assertRaises(FileExistsError):run.write_once(root,'row.json',{'count':2})
            self.assertEqual(json.loads((root/'row.json').read_text()),{'count':1})

    def test_arithmetic_rejects_changed_gross(self):
        t={'signal':signal(),'symbol':'BTC-USDT','side':1,'entry_prices':{'BTC-USDT':100},
           'exit_prices':{'BTC-USDT':101},'gross_bps':101,'cost_bps':14,'net_bps':87}
        with self.assertRaisesRegex(Exception,'NEW_TRADE_ARITHMETIC'):run.arithmetic_audit([t],[])

    def test_trace_cannot_double_count_partial(self):
        t={'signal':signal()};trace={'signal_key':run.key(signal()),'partial_fraction':.1,'partial_price':102}
        with self.assertRaisesRegex(Exception,'REPEATED_PARTIAL'):run.arithmetic_audit([t],[trace,trace])

    def test_nonfinite_outputs_rejected(self):
        with self.assertRaises(ValueError):run.encoded({'x':float('nan')})

    def test_seed_round_trip_parser_matches_frozen_runtime(self):
        import gzip
        from unittest.mock import patch
        raw=gzip.compress(b'close,volume\n100.0,0.30661019938070999\n')
        with patch.object(run.pd, 'read_csv', wraps=pd.read_csv) as read:
            run.read_seed(raw)
        self.assertEqual(read.call_args.kwargs['float_precision'], 'round_trip')

    def test_other_symbol_late_clock_prevents_false_eligibility(self):
        clocks={s:{0:run.TF} for s in run.SYMBOLS}
        clocks['ETH-USDT'][0]=run.TF+5000
        w=run.causal_clock_witness(signal(),clocks)
        self.assertEqual(w['recorded_constituent_available_ms'],run.TF)
        self.assertEqual(w['recorded_causal_prefix_available_ms'],run.TF+5000)
        self.assertIs(w['historical_next_open_available_in_realtime'],False)

    def test_earlier_input_lateness_is_not_discarded(self):
        s=signal();s['signal_open_ts_ms']=run.TF;s['signal_ts_ms']=2*run.TF
        clocks={x:{0:run.TF,run.TF:2*run.TF} for x in run.SYMBOLS}
        clocks['ETH-USDT'][0]=3*run.TF
        w=run.causal_clock_witness(s,clocks)
        self.assertIs(w['historical_next_open_available_in_realtime'],False)
        self.assertEqual(w['recorded_causal_prefix_available_ms'],3*run.TF)

    def test_on_time_prices_do_not_certify_missing_seed_clocks(self):
        clocks={s:{0:run.TF} for s in run.SYMBOLS}
        w=run.causal_clock_witness(signal(),clocks)
        self.assertIsNone(w['historical_next_open_available_in_realtime'])
        self.assertFalse(w['seed_and_config_live_observation_certified'])
        clocks.pop('ETH-USDT')
        with self.assertRaisesRegex(Exception,'CLOCK_EXACT_SIX_SYMBOLS'):
            run.causal_clock_witness(signal(),clocks)

    def test_completed_entrypoint_cannot_replay(self):
        with self.assertRaisesRegex(SystemExit,'COMPLETED_RUN_ENTRYPOINT_DISABLED'):
            run.main()


if __name__=='__main__':unittest.main()
