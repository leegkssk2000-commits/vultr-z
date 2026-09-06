"""Synthetic integration/authority tests; never loads historical market prices."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import break_channel_source_v1 as x
from backend.research.rebuild.test_break_channel_structure_v1 import bars


REPOSITORY_ROOT = x.ROOT
COSTS = {'TEST': {'fee_bps': 10, 'spread_bps': 2, 'impact_bps': 1,
                  'funding_p95_per_settlement_bps': 3}}


def parent_metadata():
    # Frozen rule metadata only. No archive, price, baseline outcome or OOS read.
    freeze = json.loads((REPOSITORY_ROOT / x.old.FREEZE).read_text())
    return next(c for c in freeze['children'] if c['lane_id'] == x.LANE)


def policy():
    return {
        'development_interval_ms': [0, 300 * x.BAR],
        'batch_id': 'SYNTHETIC_BREAK_CHANNEL_TEST', 'receipt_sha256': 'synthetic-policy',
        'combined_data_sha256': 'synthetic-data', 'cost_binding_sha256': 'synthetic-cost',
        'code_files_sha256': {}, 'symbols': ['TEST'],
        'uncertainty': {'method': 'SYNTHETIC_WEEK_DIAGNOSTIC', 'replications': 1000, 'seed': 1178},
    }


def contract():
    return x.old.seal({
        'authorization': 'EXPLICIT_USER_BREAK_CHANNEL_Q_QMINUS_AFTER_PR1189',
        'budget': deepcopy(x.BUDGET), 'cell': deepcopy(x.CELL), 'rules': deepcopy(x.RULES),
        'outcomes_seen_at_freeze': False, 'code_files_sha256': {}, 'preserved_files_sha256': {},
        'validation_access': False, 'OOS_access': False, 'G5B_changed': False,
        'G6_authorized': False, 'operating_changed': False,
        'batch_id': 'SYNTHETIC_BREAK_CHANNEL_TEST',
        'evaluation_interval_ms': [40 * x.DAY, 50 * x.DAY],
        'data_sha256': 'synthetic-data', 'cost_sha256': 'synthetic-cost',
        'symbols': ['TEST'], 'parent_sha256': x.old.digest(parent_metadata()),
        'data_reuse_history': [{'scope': 'SYNTHETIC_TEST_NO_HISTORICAL_PRICES'}],
        **x.old.probe.DEV_AUTH,
    })


def reseal(value):
    return x.old.seal({k: v for k, v in value.items() if k != 'receipt_sha256'})


def authorization_reads(c, prior_count=22):
    def read(path):
        if path == x.CONTRACT:
            return c
        if path == x.prior.OUTPUT + '/receipt.json':
            return {'budget': {'cumulative_after': prior_count}}
        raise AssertionError('UNEXPECTED_AUTHORIZATION_READ:' + str(path))
    return read


class AuthorizationTests(unittest.TestCase):
    def test_consumed_allocation_blocks_loader_before_any_input_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / x.OUTPUT
            out.mkdir(parents=True)
            (out / 'receipt.json').write_text('{}')
            with patch.object(x, 'ROOT', root), patch.object(x, 'authorize', return_value=contract()), \
                 patch.object(x.inputs, 'load_inputs') as loader:
                with self.assertRaisesRegex(RuntimeError, 'ALLOCATION_CONSUMED'):
                    x.run(root / 'no-price-files')
                loader.assert_not_called()

    def test_resealed_semantic_mutations_fail_before_data(self):
        cases = [
            ('budget', lambda c: c['budget'].update(cumulative_after=26)),
            ('previous22', lambda c: c['budget'].update(previous_applications=20)),
            ('cell', lambda c: c['cell'].update(j_days=3)),
            ('rules', lambda c: c['rules'].update(exit='changed after outcomes')),
            ('authorization', lambda c: c.update(authorization='NOT_APPROVED')),
            ('seen_outcomes', lambda c: c.update(outcomes_seen_at_freeze=True)),
            ('G6', lambda c: c.update(G6_authorized=True)),
            ('OOS', lambda c: c.update(OOS_access=True)),
            ('validation', lambda c: c.update(validation_access=True)),
            ('operating', lambda c: c.update(operating_changed=True)),
            ('G5B', lambda c: c.update(G5B_changed=True)),
        ]
        for label, mutate in cases:
            c = contract()
            mutate(c)
            c = reseal(c)
            with self.subTest(mutation=label), \
                 patch.object(x.old, 'read', side_effect=authorization_reads(c)), \
                 patch.object(x.inputs, 'load_inputs') as loader:
                with self.assertRaises(RuntimeError):
                    x.run(Path('DO_NOT_LOAD_SYNTHETIC_OR_REAL_DATA'))
                loader.assert_not_called()

    def test_prior_trial_count_and_preserved_bytes_are_checked(self):
        c = contract()
        with patch.object(x.old, 'read', side_effect=authorization_reads(c, prior_count=23)):
            with self.assertRaisesRegex(RuntimeError, 'PREVIOUS_ALLOCATION_IDENTITY'):
                x.authorize()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            protected = root / 'preserved.txt'
            protected.write_text('prior 22 immutable evidence')
            c['preserved_files_sha256'] = {'preserved.txt': x.old.file_sha(protected)}
            c = reseal(c)
            with patch.object(x, 'ROOT', root), patch.object(x.old, 'read', side_effect=authorization_reads(c)):
                self.assertEqual(x.authorize(), c)
                protected.write_text('changed evidence')
                with self.assertRaisesRegex(RuntimeError, 'FROZEN_IDENTITY:preserved.txt'):
                    x.authorize()


class NativeParentTests(unittest.TestCase):
    def test_native_hold6_fresh_flat_start_and_tail_censor(self):
        rows = bars(300)
        p = parent_metadata()
        original = deepcopy((rows, p))
        signals = [236, 239, 240, 245, 246, 295, 297, 299]
        with patch.object(x.prior.previous.prep, 'causal_signals', return_value=signals):
            result = x.parent_replay(rows, p, 40 * x.DAY, 50 * x.DAY)
        self.assertEqual([t['signal_index'] for t in result['trades']], [239, 246])
        first = result['trades'][0]
        self.assertEqual(first['entry_ts'], 40 * x.DAY)
        self.assertEqual(first['exit_index'], 245)
        self.assertEqual(first['hold_ms'], 6 * x.BAR)
        self.assertTrue(result['audit']['freshflat_common_start'])
        self.assertEqual(len(result['open_positions']), 1)
        opened = result['open_positions'][0]
        self.assertEqual(opened['signal_index'], 295)
        self.assertEqual(opened['mark_ts'], 50 * x.DAY)
        self.assertEqual(opened['hold_ms'], 4 * x.BAR)
        self.assertEqual(opened['native_hold_bars'], 6)
        self.assertFalse(opened['terminal_liquidation'])
        self.assertFalse({'exit_ts', 'exit_price', 'gross_bps', 'net_bps'} & opened.keys())
        state = {e['signal_index']: e['status'] for e in result['events']}
        self.assertNotIn(236, state)
        self.assertNotIn(299, state)
        self.assertEqual(state[245], 'EXCLUDED')
        self.assertEqual(state[295], 'CENSORED')
        self.assertEqual(state[297], 'EXCLUDED')
        shared = x.old.common.evaluate_development_events(rows, [239, 246],
            split_start_ms=0, split_end_ms=50 * x.DAY + x.BAR,
            interval_ms=x.BAR, side='long', hold_bars=6)
        self.assertEqual(result['trades'], shared['trades'])
        self.assertEqual((rows, p), original)

    def test_parent_filters_future_bars_before_feature_evaluation(self):
        rows = bars(310)
        p = parent_metadata()
        with patch.object(x.prior.previous.prep, 'causal_signals', return_value=[]) as signals:
            x.parent_replay(rows, p, 40 * x.DAY, 50 * x.DAY)
        observed = signals.call_args.args[0]
        self.assertEqual(len(observed), 300)
        self.assertEqual(observed[-1]['bar_close_ts'], 50 * x.DAY)


class DailyValuationTests(unittest.TestCase):
    def test_after_open_orders_and_final_close_valuation_bridge(self):
        rows = bars(13)
        rows[5].update(close=110, high=110)
        rows[6].update(open=120, high=120, low=119, close=120)
        rows[11].update(close=130, high=130)
        rows[12].update(open=999, high=999, low=999, close=999)
        raw_closed = {'signal_index': 0, 'entry_index': 0, 'exit_index': 5,
            'signal_ts': 0, 'entry_ts': 0, 'exit_ts': x.DAY, 'side': 'long',
            'entry_price': 100, 'exit_price': 110, 'gross_bps': 1000,
            'hold_ms': x.DAY, 'mfe_bps': 1000, 'mae_bps': 0}
        raw_open = {'signal_index': 5, 'entry_index': 6, 'mark_index': 11,
            'signal_ts': x.DAY, 'entry_ts': x.DAY, 'mark_ts': 2 * x.DAY, 'side': 'long',
            'entry_price': 120, 'mark_price': 130, 'gross_mark_bps': (130 / 120 - 1) * 10000,
            'hold_ms': x.DAY, 'mfe_bps': 1000, 'mae_bps': 0,
            'status': 'CENSORED', 'terminal_liquidation': False}
        closed = x.charge(raw_closed, 'TEST', 'P', policy(), COSTS, rows)
        opened = x.charge_open(raw_open, 'TEST', 'P', policy(), COSTS, rows)
        result = x.daily_valuation([closed], [opened], {'TEST': rows}, COSTS, 0, 2 * x.DAY)
        self.assertEqual(result[0]['valuation_phase'], 'AFTER_OPEN_ORDERS')
        self.assertEqual(result[0]['active_marked_positions'], 1)
        self.assertAlmostEqual(result[0]['cumulative_gross_mark_bps'], 1000)
        self.assertAlmostEqual(result[0]['cumulative_net_mark_bps'], closed['net_bps'] - 20)
        self.assertEqual(result[1]['valuation_phase'], 'FINAL_CLOSE_NO_FUTURE_OPEN')
        target = closed['net_bps'] + opened['hypothetical_liquidation_net_mark_bps']
        self.assertAlmostEqual(result[-1]['cumulative_net_mark_bps'], target)
        self.assertAlmostEqual(sum(t['value'] for t in result), target)
        rows[12].update(open=1, high=999999, low=.0001, close=99)
        self.assertEqual(result, x.daily_valuation([closed], [opened], {'TEST': rows}, COSTS, 0, 2 * x.DAY))
        self.assertEqual(opened['funding_settlements_elapsed'], 3)
        self.assertEqual(opened['modeled_funding_accrued_bps'], 9)
        self.assertEqual(opened['hypothetical_liquidation_cost_bps'], 22)

    def test_missing_mark_does_not_interpolate_or_create_a_price(self):
        t = {'entry_ts': 0, 'entry_price': 100, 'symbol': 'TEST'}
        with self.assertRaisesRegex(RuntimeError, 'MISSING_DAILY_VALUATION_PRICE'):
            x.daily_valuation([], [t], {'TEST': bars(5)}, COSTS, 0, x.DAY)


class SyntheticEndToEndTests(unittest.TestCase):
    def test_real_components_measure_synthetic_prices_and_verify_identical_bytes(self):
        rows = bars(300)
        tail = {40: 101, 41: 102, 42: 103, 43: 104, 44: 102,
                45: 101, 46: 101.1, 47: 102, 48: 103, 49: 104}
        for i, row in enumerate(rows):
            px = tail.get(i // 6, 100)
            row.update(open=px, high=px + .1, low=px - .1, close=px,
                       volume=50 if i % 6 == 0 else 10)
        unchanged = deepcopy(rows)
        c = contract()
        p = policy()
        parent = parent_metadata()
        raw_parent = x.parent_replay(rows, parent, 0, 50 * x.DAY)
        whole = [x.charge(t, 'TEST', 'P', p, COSTS, rows) for t in raw_parent['trades']]
        baseline = x.old.metrics(whole, [], p, ['TEST'])
        source_text = (REPOSITORY_ROOT / x.SOURCE).read_text()

        def reads(path):
            if path == x.old.FREEZE:
                return {'children': [parent]}
            if path == x.old.OUTPUT + '/baseline/receipt.json':
                return {'lanes': {x.LANE: {'metrics': {'base': baseline}}}}
            raise AssertionError('UNEXPECTED_SYNTHETIC_RUN_READ:' + str(path))

        loaded = (p, {'cost_by_symbol': COSTS}, {'TEST': rows}, {},
                  {'TEST': {'decoded_partition': 'SYNTHETIC_ONLY', 'decoded_validation_rows': 0, 'decoded_OOS_rows': 0}})
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / x.OUTPUT
            out.mkdir(parents=True)
            (root / x.SOURCE).write_text(source_text)
            (root / x.CONTRACT).write_text('{}')
            with patch.object(x, 'ROOT', root), patch.object(x, 'authorize', return_value=c), \
                 patch.object(x.inputs, 'load_inputs', return_value=loaded), \
                 patch.object(x.inputs, 'read_lines', return_value=whole), \
                 patch.object(x.old, 'read', side_effect=reads):
                result = x.run(root / 'SYNTHETIC_NO_DATA_FILES')
                before = {p.name: p.read_bytes() for p in out.iterdir()}
                reproduced = x.run(root / 'SYNTHETIC_NO_DATA_FILES', verify_only=True)
                self.assertEqual(result, reproduced)
                self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
            self.assertEqual(result['budget']['cumulative_after'], 24)
            self.assertEqual(result['budget']['new_trials_consumed'], 2)
            self.assertEqual(result['budget']['remaining_allocated_trials'], 0)
            self.assertGreater(result['metrics']['P']['base_cost']['completed_T'], 0)
            self.assertGreater(result['metrics']['Q']['base_cost']['completed_T'], 0)
            self.assertGreater(result['metrics']['Q']['open_observations']['T'], 0)
            self.assertEqual(result['metrics']['CASH']['base_cost']['net_bps'], 0)
            self.assertEqual(result['whole_parent_preserved']['matching_economics_parity'], 'PASS')
            self.assertEqual(result['comparisons']['P_to_Q']['uncertainty']['calendar_days'], 10)
            self.assertEqual(result['comparisons']['P_to_Q']['uncertainty']['status'], 'INSUFFICIENT_CALENDAR')
            self.assertEqual(result['validation_rows_decoded'], 0)
            self.assertEqual(result['OOS_rows_decoded'], 0)
            self.assertEqual(result['paid_external_AI_calls'], 0)
            self.assertFalse(result['G5B_changed'])
            self.assertFalse(result['operating_changed'])
            for name, value in x.old.probe.DEV_AUTH.items():
                self.assertEqual(result[name], value)
            self.assertIn('durable_receipt.json', before)
            self.assertIn('RESULTS.md', before)
            self.assertIn('daily_valuation.jsonl.gz', before)
        self.assertEqual(rows, unchanged)


if __name__ == '__main__':
    unittest.main()
