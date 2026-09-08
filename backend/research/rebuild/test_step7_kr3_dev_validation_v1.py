"""Synthetic-only new finite DEV runner regression; never decode actual DEV."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild import step7_kr3_dev_validation_v1 as v


def fixture():
    source = v.native.fixture_input()
    rows = {s: x['bars'] for s, x in source['source'].items()}
    policy = {'development_interval_ms': [240*v.native.BAR, 390*v.native.BAR],
              'batch_id': 'SYNTHETIC_ONLY', 'combined_data_sha256': 'FIXTURE',
              'receipt_sha256': 'FIXTURE', 'code_files_sha256': {}, 'cost_binding_sha256': 'FIXTURE'}
    costs = {s: {'fee_bps': 4., 'spread_bps': 2., 'impact_bps': 1.,
                  'funding_p95_per_settlement_bps': .2} for s in rows}
    spec = v.propose_spec(rows, policy, costs, {'evidence_kind': 'SYNTHETIC_ONLY'})
    return rows, policy, costs, spec


class DEVValidationTests(unittest.TestCase):
    def test_exact_finite_manifest_and_byte_change_rejected(self):
        rows, policy, costs, spec = fixture()
        self.assertEqual(len(spec['variants']), 12)
        self.assertNotIn('without_kr3_veto', [x['id'] for x in spec['variants']])
        tampered = deepcopy(rows)
        tampered['BTC-USDT'][250]['close'] += 1
        with self.assertRaisesRegex(ValueError, 'FROZEN_DEV_BYTES'):
            v.run_variant(spec['variants'][0], tampered, costs, policy, spec)
        changed = deepcopy(spec)
        changed['variants'][0]['parameters'] = [18, 50, 12]
        changed = v.native.contracts.seal({k: x for k, x in changed.items() if k != 'receipt_sha256'})
        with self.assertRaisesRegex(ValueError, 'EXACT_FINITE'):
            v.validate_spec(changed, rows, costs, policy)

    def test_direction_reflection_cost_open_and_trace_preserved(self):
        rows, policy, costs, spec = fixture()
        result = v.run_variant(spec['variants'][0], rows, costs, policy, spec)
        self.assertTrue(result['trades'])
        self.assertTrue(result['reference_opportunities'])
        self.assertTrue(result['trace'])
        for trade in result['trades']:
            self.assertEqual(trade['side'], 'short')
            self.assertEqual(trade['gross_bps'], -(trade['exit_price']/trade['entry_price']-1)*10000)
            self.assertGreaterEqual(trade['cost_bps'], 20.)
            self.assertEqual(trade['net_bps'], trade['gross_bps']-trade['cost_bps'])
            self.assertIsNone(trade['mfe_bps'])
            self.assertLessEqual(trade['signal_ts'], trade['entry_ts'])
        self.assertEqual(result['metrics']['terminal_net_bps'], result['metrics']['daily'][-1]['cumulative_net_mark_bps'])

    def test_delay_uses_shifted_geometry_and_new_reference_slots(self):
        rows, policy, costs, spec = fixture()
        original = v.native.d.build_bundle(rows['BTC-USDT'], v.native.d.PARENT_SPEC,
                          eval_start_ms=spec['start_ms'], eval_end_ms=spec['runoff_end_ms'])
        for variant, offset in ((spec['variants'][1], 6), (spec['variants'][2], 1)):
            result = v.run_variant(variant, rows, costs, policy, spec)
            admissible = {s['signal_index']+offset for s in original['signals']
                          if s['signal_index']+offset < len(rows['BTC-USDT']) and
                          rows['BTC-USDT'][s['signal_index']+offset]['bar_close_ts'] < spec['entry_stop_ms']}
            for reference in result['reference_opportunities']:
                if reference['symbol'] == 'BTC-USDT':
                    self.assertIn(reference['reference_signal_index'], admissible)
            for t in result['trades']+result['open_observations']:
                self.assertEqual(t['signal_ts'], rows[t['symbol']][t['signal_index']]['bar_close_ts'])
                self.assertEqual(t['entry_ts'], rows[t['symbol']][t['signal_index']+1]['bar_open_ts'])

    def test_individual_ablations_restore_native_and_neighbors_propagate(self):
        rows, policy, costs, spec = fixture()
        before = deepcopy(v.native.d.PARENT_SPEC)
        observer = v.native.reservation.n.entry_observation
        for variant in spec['variants'][3:6]:
            out = v.run_variant(variant, rows, costs, policy, spec)
            self.assertTrue(out['audit'])
            self.assertEqual(v.native.d.PARENT_SPEC, before)
            self.assertIs(v.native.reservation.n.entry_observation, observer)
        with v.native.sensitivity((20,50,11)):
            self.assertEqual([owner.HOLD for owner in (v.native.d,v.native.reservation,v.native.m2,v.native.kr,v.native.kr3)], [11]*5)
        self.assertEqual(v.native.kr3.HOLD, 12)

    def _synthetic_allocation(self, root, spec):
        path=root/v.evidence.CAMPAIGN/'BUDGET.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'trials':[], 'kr3_dev_validation_allocation':{
            'specification_sha256':spec['receipt_sha256'],
            'variant_ids':[x['id'] for x in spec['variants']],
            'max_actual_variants':12, 'used':0}}))
        return path

    def test_exception_consumes_durable_attempt_before_replay(self):
        rows, policy, costs, spec = fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            out=root/v.evidence.CAMPAIGN/'DEV_VALIDATION/VARIANTS'
            budget=self._synthetic_allocation(root,spec)
            def fail(*args):
                self.assertTrue((out/'direction_flip'/'ATTEMPT.json').exists())
                current=json.loads(budget.read_text())
                self.assertEqual(current['kr3_dev_validation_allocation']['used'],1)
                self.assertEqual(len(current['trials']),1)
                raise RuntimeError('SYNTHETIC_FAILURE')
            with patch.object(v,'ROOT',root), \
                 patch.object(v,'code_dependencies',return_value=spec['code_files_sha256']), \
                 patch.object(v,'validate_actual_dev_entry'), \
                 patch.object(v,'run_variant',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_FAILURE'):
                    v.run_manifest(spec,rows,costs,policy,out)
                receipt=json.loads((out/'direction_flip'/'RECEIPT.json').read_text())
                self.assertEqual(receipt['status'],'FAILED_CONSUMED')
                with patch.object(v,'run_variant') as execute:
                    with self.assertRaisesRegex(ValueError,'CONSUMED_OR_DIFFERENT'):
                        v.run_manifest(spec,rows,costs,policy,out)
                    execute.assert_not_called()
                self.assertEqual(json.loads(budget.read_text())['kr3_dev_validation_allocation']['used'],1)

    def test_new_output_path_cannot_reset_shared_allocation(self):
        rows,policy,costs,spec=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);budget=self._synthetic_allocation(root,spec)
            before=budget.read_bytes()
            out=root/'renamed-task'/'VARIANTS'
            with patch.object(v,'ROOT',root), \
                 patch.object(v,'code_dependencies',return_value=spec['code_files_sha256']), \
                 patch.object(v,'validate_actual_dev_entry'), \
                 patch.object(v,'run_variant') as execute:
                with self.assertRaisesRegex(ValueError,'CANONICAL_SHARED_ALLOCATION_REQUIRED_NO_PATH_RESET'):
                    v.run_manifest(spec,rows,costs,policy,out)
                execute.assert_not_called()
            self.assertEqual(budget.read_bytes(),before)
            self.assertFalse(out.exists())

    def test_synthetic_actual_entry_rejected_before_budget_access(self):
        rows,policy,costs,spec=fixture()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(v,'run_variant') as execute:
            with self.assertRaisesRegex(ValueError,'ACTUAL_DEV_EXACT_SCOPE_REQUIRED'):
                v.run_manifest(spec,rows,costs,policy,Path(folder)/'unused')
            execute.assert_not_called()
            self.assertFalse((Path(folder)/'unused').exists())

    def test_actual_entry_lineage_reseal_does_not_permit_oos(self):
        rows,policy,costs,spec=fixture()
        calendar=[v.evidence.DEV_START,v.evidence.DEV_END]
        policy.update(data_ref=v.evidence.DATA_REF,development_interval_ms=calendar)
        spec.update(start_ms=calendar[0],entry_stop_ms=calendar[1],runoff_end_ms=calendar[1])
        lineage={'calendar_ms':calendar,'data_ref':v.evidence.DATA_REF,
          'candidate_sha256':v.CANDIDATE,'cost_sha256':policy['cost_binding_sha256'],
          'decoded_OOS_rows':1,'decoded_validation_rows':0,'new_collection_calls':0,
          'immutable_history_verified':True}
        spec['data_input_receipt']=v.evidence.seal(lineage)
        with self.assertRaisesRegex(ValueError,'ACTUAL_DEV_LINEAGE_REQUIRED'):
            v.validate_actual_dev_entry(spec,rows,policy)

    def test_regime_decomposition_is_existing_ledger_annotation_only(self):
        rows, policy, costs, spec = fixture()
        # Generate an artificial center only, not an actual DEV base replay.
        raw = v.native.native_replay(rows, spec)
        center = {'trades': [], 'open_observations': []}
        for symbol in rows:
            selected = {k: [t for t in raw[k] if t['symbol'] == symbol]
                        for k in ('trades','open_positions','events','trace')}
            selected['audit'] = raw['audit'][symbol]
            charged = v.account.charge_result(selected, symbol, 'keltner_trend_main', 'FIXTURE', policy, costs, rows[symbol])
            for k in center:
                center[k].extend(charged[k])
        with patch.object(v.native, 'native_replay', side_effect=AssertionError('NO_REPLAY')):
            out = v.regime_decomposition(center, rows, spec)
        self.assertEqual(out['replay_count'], 0)
        self.assertEqual(sum(g['closed_T'] for g in out['by_regime'].values()), len(center['trades']))
        self.assertEqual(sum(g['open_T'] for g in out['by_regime'].values()), len(center['open_observations']))
        self.assertFalse(out['regime_permutation']['applicable'])


if __name__ == '__main__':
    unittest.main()
