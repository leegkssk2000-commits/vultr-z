"""Orchestration/authority regressions using temporary synthetic evidence only."""
from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import q0_b_seen_replication_v1 as x


@contextmanager
def authorized_fixture():
    """Real seals and byte identities, with the old authorization chain isolated."""
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        root = Path(folder)
        stack.enter_context(patch.object(x, 'ROOT', root))
        stack.enter_context(patch.object(x.original, 'ROOT', root))
        out = root / x.OUTPUT
        out.mkdir(parents=True)
        old_out = root / x.original.OUTPUT
        old_out.mkdir(parents=True)
        old_result = x.old.seal({'synthetic': True, 'independent': False})
        old_result_path = old_out / 'receipt.json'
        old_result_path.write_bytes(x.old.probe.canonical(old_result))
        stack.enter_context(patch.object(x, 'ORIGINAL_RESULT', old_result['receipt_sha256']))
        files = ['prior/ledger.json', 'prior/engine.py', *x.CODE, x.DESIGN]
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic fixture: ' + name + '\n')
        base = {'reference': deepcopy(x.adapter.REFERENCE), 'symbols': list(x.adapter.SYMBOLS),
                'data_sha256': 'original-dev-data', 'cost_sha256': 'frozen-cost',
                'preserved_files_sha256': {'prior/ledger.json': x.old.file_sha(root / 'prior/ledger.json')},
                'code_files_sha256': {'prior/engine.py': x.old.file_sha(root / 'prior/engine.py')}}
        q0 = {'receipt_sha256': 'q0-seal'}
        old_authorize = stack.enter_context(patch.object(x.original, 'authorize', return_value=(base, q0, {}, {})))
        protected = {**base['preserved_files_sha256'], **base['code_files_sha256'],
                     str(old_result_path.relative_to(root)): x.old.file_sha(old_result_path)}
        spec = {**x.AUTH, 'authorization': x.AUTHORIZATION, 'budget': deepcopy(x.BUDGET),
                'evaluation_id': 'Q0_B_SEEN_2026_V1', 'batch_id': 'Q0_B_SEEN_2026_V1',
                'new_evaluation_outcomes_seen_at_freeze': False,
                'underlying_market_history_previously_used': True,
                'evaluation_interval_ms': [1778198400000, 1788566400000],
                'original_raw_candidate_interval_ms': [1778169600000, 1788609600000],
                'reference': deepcopy(base['reference']), 'goal': deepcopy(x.original.GOAL),
                'symbols': base['symbols'], 'Q0_receipt_sha256': q0['receipt_sha256'],
                'B_receipt_sha256': old_result['receipt_sha256'],
                'original_DEV_data_sha256': base['data_sha256'], 'data_sha256': 'seen-input-identity',
                'cost_sha256': base['cost_sha256'], 'preserved_files_sha256': protected,
                'code_files_sha256': {name: x.old.file_sha(root / name) for name in x.CODE},
                'design_sha256': x.old.file_sha(root / x.DESIGN),
                'preserved_states': {'Q0': 'DEV_INCONCLUSIVE', 'B': 'DEV_INCONCLUSIVE_TRADEOFF'},
                'prior_independent_comparison': {'status': 'NOT_RUN', 'used': 0, 'allocated': 1},
                'data_reuse_history': [{'synthetic': True, 'previously_used': True}],
                'future_readiness': {'active': False}}

        def freeze():
            spec.pop('receipt_sha256', None)
            spec.update(x.old.seal(spec))
            (root / x.CONTRACT).write_bytes(x.old.probe.canonical(spec))

        freeze()
        yield root, spec, freeze, old_authorize


class SeenRunnerBoundaryTests(unittest.TestCase):
    def test_consumed_evaluation_blocks_price_loader(self):
        with authorized_fixture() as (root, _, _, _):
            (root / x.OUTPUT / 'receipt.json').write_text('{}')
            with patch.object(x.adapter, 'load_seen_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError, 'SEEN_EVALUATION_CONSUMED_USE_VERIFY_ONLY'):
                    x.run(root / 'unread-price-data')
                loader.assert_not_called()

    def test_verify_only_without_result_blocks_price_loader(self):
        with authorized_fixture() as (root, _, _, _):
            with patch.object(x.adapter, 'load_seen_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError, 'SEEN_NO_RESULT_TO_REPRODUCE'):
                    x.run(root / 'unread-price-data', verify_only=True)
                loader.assert_not_called()

    def test_resealed_spec_cannot_claim_independence_or_open_authority(self):
        for key in ('independent', 'operating_adoption', 'G5B_changed', 'G6_authorized',
                    'G7_formal_authorized', 'G11_formal_authorized', 'actual_account_sizing'):
            with self.subTest(key=key), authorized_fixture() as (root, spec, freeze, _):
                spec[key] = True
                freeze()
                with patch.object(x.adapter, 'load_seen_inputs') as loader:
                    with self.assertRaisesRegex(RuntimeError, 'SEEN_AUTHORITY:' + key):
                        x.run(root / 'unread-price-data')
                    loader.assert_not_called()

    def test_resealed_spec_cannot_reallocate_or_consume_independent_budget(self):
        for key, value in (('candidate_cumulative_after', 27), ('new_candidates', 1),
                           ('independent_comparison_used', 1), ('seen_evaluation_allocated', 2),
                           ('paid_external_AI_calls', 1)):
            with self.subTest(key=key), authorized_fixture() as (_, spec, freeze, _):
                spec['budget'][key] = value
                freeze()
                with self.assertRaisesRegex(RuntimeError, 'SEEN_AUTHORIZATION_OR_BUDGET'):
                    x.authorize()

    def test_goal_and_reference_cannot_be_relaxed_after_results(self):
        for group, key, value in (('goal', 'numerical_equality_abs_tolerance_bps', 50.60),
                                  ('reference', 'sigma_ref', 0.04), ('reference', 'N', 100)):
            with self.subTest(key=key), authorized_fixture() as (_, spec, freeze, _):
                spec[group][key] = value
                freeze()
                with self.assertRaisesRegex(RuntimeError, 'SEEN_REFERENCE_OR_GOAL_DRIFT'):
                    x.authorize()
        self.assertEqual(x.original.GOAL['numerical_equality_abs_tolerance_bps'], 1e-7)

    def test_original_authorization_failure_is_not_bypassed_by_new_permission(self):
        with authorized_fixture() as (root, _, _, old_authorize):
            old_authorize.side_effect = RuntimeError('ORIGINAL_SEALED_LINEAGE_INVALID')
            with patch.object(x.adapter, 'load_seen_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_SEALED_LINEAGE_INVALID'):
                    x.run(root / 'unread-price-data')
                loader.assert_not_called()

    def test_original_result_seal_and_preserved_artifact_bytes_are_checked(self):
        with authorized_fixture() as (root, _, _, _):
            path = root / x.original.OUTPUT / 'receipt.json'
            value = json.loads(path.read_text())
            value['independent'] = True
            path.write_bytes(x.old.probe.canonical(value))
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_RISK_RESULT_SEAL'):
                x.authorize()
        with authorized_fixture() as (root, _, _, _):
            (root / 'prior/ledger.json').write_text('changed sealed ledger')
            with self.assertRaisesRegex(RuntimeError, 'SEEN_FROZEN_BYTES:prior/ledger.json'):
                x.authorize()

    def test_spec_seal_and_current_implementation_bytes_are_checked(self):
        with authorized_fixture() as (root, spec, _, _):
            spec['underlying_market_history_previously_used'] = False
            (root / x.CONTRACT).write_bytes(x.old.probe.canonical(spec))
            with self.assertRaisesRegex(RuntimeError, 'SEEN_SPEC_SEAL'):
                x.authorize()
        with authorized_fixture() as (root, _, _, _):
            (root / x.CODE[0]).write_text('changed after freeze')
            with self.assertRaisesRegex(RuntimeError, 'SEEN_FROZEN_BYTES:'):
                x.authorize()

    def test_result_artifact_exact_reproduction_does_not_overwrite_drift(self):
        with authorized_fixture() as (root, _, _, _):
            first = x.artifact('synthetic.json.gz', {'net': 7}, False)
            path = root / first['path']
            before = path.read_bytes()
            self.assertEqual(x.artifact('synthetic.json.gz', {'net': 7}, True), first)
            with self.assertRaisesRegex(RuntimeError, 'SEEN_REPRODUCTION_DRIFT'):
                x.artifact('synthetic.json.gz', {'net': 8}, True)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(RuntimeError, 'DEVELOPMENT_RECEIPT_MISSING'):
                x.artifact('missing.json.gz', {'net': 7}, True)
            self.assertFalse((root / x.OUTPUT / 'missing.json.gz').exists())

    def test_synthetic_run_and_verify_keep_evaluation_count_and_authority(self):
        with authorized_fixture() as (root, spec, _, _), ExitStack() as stack:
            loader = stack.enter_context(patch.object(x.adapter, 'load_seen_inputs',
                return_value=({}, {'cost_by_symbol': {}}, {}, {'synthetic': True})))
            stack.enter_context(patch.object(x.adapter, 'frozen_market_state', return_value={
                'reference': deepcopy(spec['reference']), 'sigma_ref': spec['reference']['sigma_ref']}))
            stack.enter_context(patch.object(x.adapter, 'replay_q0', return_value={
                'trades': [], 'open_observations': [], 'events': []}))
            stack.enter_context(patch.object(x.original.weights, 'entry_weights', return_value={}))
            # An impossible-to-obtain-here optimistic arithmetic result still cannot grant authority.
            positive = x.original.study_decision(200, 100, 150, 10, 20, 5, 10, [1, 2])
            positive.update(x.metrics.EVIDENCE, decision='SEEN_PERIOD_SUPPORT')
            measured = {'stages': {}, 'decision': positive, 'attribution': {},
                        'uncertainty': {'synthetic': True}}
            stack.enter_context(patch.object(x.metrics, 'build', return_value=measured))
            stack.enter_context(patch.object(x.old.probe, 'io_boundary', return_value=nullcontext()))
            before_budget = deepcopy(x.BUDGET)
            first = x.run(root / 'synthetic-no-market-files')
            out = root / x.OUTPUT
            bytes_before = {p.name: p.read_bytes() for p in out.iterdir()}
            again = x.run(root / 'synthetic-no-market-files', verify_only=True)
            self.assertEqual(first, again)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, bytes_before)
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(x.BUDGET, before_budget)
            self.assertEqual(first['budget']['candidate_cumulative_after'], 26)
            self.assertEqual(first['budget']['new_candidates'], 0)
            self.assertEqual(first['budget']['seen_evaluation_used'], 1)
            self.assertEqual(first['budget']['independent_comparison_used'], 0)
            self.assertEqual(first['evidence_type'], 'SEEN_DATA_REPLICATION')
            self.assertFalse(first['independent'])
            self.assertFalse(first['operating_adoption'])
            self.assertEqual(first['formal_credit'], 0)
            text = (out / 'RESULTS.md').read_text()
            for phrase in ('independent=false', 'formal_credit=0', 'operating_adoption=false',
                           'Independent comparison0/1', 'SEEN_PERIOD_SUPPORT'):
                self.assertIn(phrase, text)
            self.assertNotIn('independent=true', text)
            self.assertNotIn('operating_adoption=true', text)
            self.assertFalse(first['accounting']['decision']['formal_pass'])


if __name__ == '__main__':
    unittest.main()
