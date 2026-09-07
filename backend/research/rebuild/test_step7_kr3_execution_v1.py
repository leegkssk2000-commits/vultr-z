"""New bounded synthetic regressions; no old DEV or protected source IO."""
import copy
import json
import unittest
from backend.research.rebuild import step7_kr3_execution_v1 as p

class NativeProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=p.fixture_input()
        cls.rows={s:cls.fixture['source'][s]['bars'] for s in p.SYMBOLS}
        cls.raw=p.native_replay(cls.rows,cls.fixture['specification'])
        cls.costed=p.cost_ledger(cls.raw,cls.fixture['source'],cls.fixture['cost'])

    def test_native_raw_generates_signals_trades_reservations_and_extensions(self):
        self.assertGreater(len(self.raw['trades']),0)
        self.assertGreater(len(self.raw['reference_opportunities']),0)
        kinds={r['kind'] for r in self.raw['trace']}
        self.assertIn('ENTRY_NEXT_OPEN',kinds)
        self.assertIn(p.kr.DECISION,kinds)
        for audit in self.raw['audit'].values():
            self.assertEqual(audit['same_symbol_max_positions'],1)
            self.assertEqual(audit['comparison_mode'],'FULL_ACTUAL_SLOT_AND_D_REFERENCE')
            self.assertEqual(audit['window_resets'],0)
        self.assertTrue(all(t['initial_protective_sl'] is None for t in self.raw['trades']))

    def test_costs_reuse_signed_funding_and_never_double_charge_spread(self):
        self.assertTrue(all(not r['cost_unknown_reasons'] for r in self.costed['trades']))
        for r in self.costed['trades']:
            self.assertAlmostEqual(r['cost_bps'],sum(r['cost_components'].values()))
            self.assertAlmostEqual(r['net_bps'],r['gross_bps']-r['cost_bps'])
            self.assertAlmostEqual(r['cost2x_net_bps'],r['gross_bps']-2*r['cost_bps'])
            self.assertNotIn('slippage_bps',r['cost_components'])
        self.assertEqual(p.signed_funding_cost_bps('long',[{'rate':-.001}]),-10.)

    def test_unknown_fee_late_bbo_and_funding_keep_trade_null(self):
        r=self.raw['trades'][0]; src=copy.deepcopy(self.fixture['source'][r['symbol']])
        cost=copy.deepcopy(self.fixture['cost']); cost['fee_bps_each_side']=None
        output=p._cost_row(r,src,cost)
        self.assertEqual(output['origin_id'],r['origin_id']); self.assertIsNone(output['net_bps'])
        self.assertIn('FEE_EVIDENCE_MISSING',output['cost_unknown_reasons'])
        for q in src['quotes']:
            if q['ts']==r['entry_ts']: q['available_ts']+=1
        output=p._cost_row(r,src,self.fixture['cost'])
        self.assertIsNone(output['net_bps'])
        self.assertIn('ENTRY_QUOTE_NOT_AVAILABLE_AT_MODEL_TIME',output['cost_unknown_reasons'])
        src['funding']=[]
        output=p._cost_row(r,src,self.fixture['cost'])
        self.assertIn('FUNDING_SETTLEMENT_GAP_DUPLICATE_OR_INVALID',output['cost_unknown_reasons'])

    def test_late_signal_no_retroactive_fill(self):
        r=self.raw['trades'][0]; src=copy.deepcopy(self.fixture['source'][r['symbol']])
        src['bars'][r['signal_index']]['available_ts']=r['entry_ts']+1
        output=p._cost_row(r,src,self.fixture['cost'])
        self.assertIsNone(output['net_bps'])
        self.assertIn('SIGNAL_AVAILABLE_AFTER_MODEL_ENTRY_NO_RETRO_FILL',output['cost_unknown_reasons'])

    def test_neighbor_hold_and_ema_dependency_propagation_restored(self):
        for params in p.NEIGHBORS:
            with p.sensitivity(params) as spec:
                self.assertEqual(spec['max_hold_bars'],params[2])
                self.assertEqual(spec['features'][0]['formula'],f'ema(close,{params[0]})')
                for owner in (p.d,p.reservation,p.m2,p.kr,p.kr3):
                    self.assertEqual(owner.HOLD,params[2])
        self.assertEqual(p.d.HOLD,12)
        self.assertEqual(p.d.PARENT_SPEC['features'][0]['formula'],'ema(close,20)')
        with self.assertRaisesRegex(ValueError,'FINITE_NEIGHBOR'):
            with p.sensitivity((22,50,12)): pass

    def test_gap_duplicate_rejected_before_paths(self):
        rows=copy.deepcopy(self.rows[p.SYMBOLS[0]])
        del rows[250]
        with self.assertRaises(RuntimeError):
            p.native_replay({p.SYMBOLS[0]:rows},self.fixture['specification'])
        rows=copy.deepcopy(self.rows[p.SYMBOLS[0]]); rows[250]=copy.deepcopy(rows[249])
        with self.assertRaises(RuntimeError):
            p.native_replay({p.SYMBOLS[0]:rows},self.fixture['specification'])

    def test_open_tail_not_forcedclosed(self):
        spec=copy.deepcopy(self.fixture['specification'])
        spec['entry_stop_ms']=spec['runoff_end_ms']=352*p.BAR
        rows={p.SYMBOLS[0]:self.rows[p.SYMBOLS[0]][:352]}
        raw=p.native_replay(rows,spec)
        self.assertGreater(len(raw['open_positions']),0)
        for r in raw['open_positions']:
            self.assertFalse(r['terminal_liquidation'])
            self.assertNotIn('exit_ts',r)

    def test_source_restart_metadata_has_no_fills_or_performance(self):
        rows={p.SYMBOLS[0]:self.rows[p.SYMBOLS[0]]}
        one=p.native_source_probe(rows,390*p.BAR)
        two=p.native_source_probe(rows,390*p.BAR+100,json.loads(json.dumps(one['state'])))
        self.assertEqual(one['state'],two['state'])
        self.assertTrue(two['metadata']['restart_parity'])
        self.assertEqual(two['metadata']['new_signal_count'],0)
        self.assertEqual(two['metadata']['actual_fills'],0)
        self.assertNotIn('net_bps',json.dumps(two))

    def test_midpoint_basis_missing_timestamp_and_parent_unknown_fail_closed(self):
        row=self.raw['trades'][0]; src=copy.deepcopy(self.fixture['source'][row['symbol']])
        value=p._cost_row(row,src,self.fixture['cost'])
        quotes={q['ts']:q for q in src['quotes']}
        a,b=quotes[row['entry_ts']],quotes[row['exit_ts']]
        real_mid_gross=((b['ask']+b['bid'])/(a['ask']+a['bid'])-1)*10000
        self.assertAlmostEqual(value['cost_components']['model_to_quote_mid_basis_bps'],row['gross_bps']-real_mid_gross)
        for q in src['quotes']:
            if q['ts']==row['entry_ts']: del q['event_ts']
        broken=p._cost_row(row,src,self.fixture['cost'])
        self.assertIsNone(broken['net_bps'])
        self.assertIn('ENTRY_QUOTE_TIMESTAMP_EVIDENCE_MISSING',broken['cost_unknown_reasons'])
        parent=copy.deepcopy(self.costed); parent['trades'][0]['net_bps']=None
        self.assertIsNone(p.retention(parent,self.costed)['retention'])

    def test_formal_fixture_input_rejected(self):
        with self.assertRaisesRegex(ValueError,'FORMAL_SPECIFICATION_NOT_APPROVED'):
            p.execute_sealed_bytes(p.canonical(self.fixture))

if __name__=='__main__': unittest.main()
