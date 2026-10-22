"""No native prices: parity/join and process-local cleanup counterexamples."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import run_owner_be_observer as h


def fixture():
    # Deliberately not a market price series or a seeded-indicator simulation.
    rows = [{'symbol': 'SYNTHETIC', 'side': 1, 'signal_ts_ms': i,
             'partition': 'rolling', 'window_label': 'test', 'cost_bps': 10.0,
             'signal': {'meta': {'frozen_cost_bps': 10.0}}} for i in range(117)]
    saved = {'raw_trades': deepcopy(rows), 'trades': deepcopy(rows),
             'unresolved': [], 'boundary_excluded': []}
    result = {'trades': deepcopy(rows), 'unresolved': [], 'boundary_excluded': []}
    calls = []
    for row in rows:
        native = {k: v for k, v in row.items() if k not in ('partition', 'window_label')}
        calls.append({'trade': native, 'events': [{'event': 'SYNTHETIC_ONLY'}]})
    return saved, result, calls


class HarnessTests(unittest.TestCase):
    def test_all117_exact_full_ordered_rows(self):
        saved, result, _ = fixture()
        h.verify_parity(result, saved)
        result['trades'][0]['cost_bps'] += 0.001
        with self.assertRaisesRegex(ValueError, 'PARITY_FAILED'):
            h.verify_parity(result, saved)

    def test_reorder_unresolved_and_boundary_each_fail(self):
        for change in ['order', 'unresolved', 'boundary_excluded']:
            with self.subTest(change=change):
                saved, result, _ = fixture()
                if change == 'order':
                    result['trades'].reverse()
                else:
                    result[change].append({'partition': 'rolling', 'state': 'unexpected'})
                with self.assertRaisesRegex(ValueError, 'PARITY_FAILED'):
                    h.verify_parity(result, saved)

    def test_not_old126_or_duplicates(self):
        saved, result, _ = fixture()
        saved['raw_trades'].append(deepcopy(saved['raw_trades'][0]))
        result['trades'] = deepcopy(saved['raw_trades'])
        with self.assertRaisesRegex(ValueError, 'ALL117_REQUIRED'):
            h.verify_parity(result, saved)

    def test_join_all117_costs_only_after_trace(self):
        saved, _, calls = fixture()
        saved['trades'][0]['cost_bps'] += 0.9
        before = deepcopy(calls)
        joined = h.join_all117(calls, saved, deepcopy)
        self.assertEqual(len(joined), 117)
        self.assertAlmostEqual(joined[0]['extra_carry_scenario_bps'], 0.9)
        self.assertTrue(joined[0]['stress2x_is_posthoc_only'])
        self.assertFalse(joined[0]['decision_inputs_include_outcomes'])
        self.assertEqual(calls, before)

    def test_missing_call_fail_and_nonmatching_development_call_ignored(self):
        saved, _, calls = fixture()
        wrong = deepcopy(calls[0]); wrong['trade']['cost_bps'] = 99.0
        self.assertEqual(len(h.join_all117([wrong] + calls, saved, deepcopy)), 117)
        with self.assertRaisesRegex(ValueError, 'JOIN_INCOMPLETE'):
            h.join_all117(calls[1:], saved, deepcopy)

    def test_identical_duplicate_counted_ambiguous_duplicate_fails(self):
        saved, _, calls = fixture()
        duplicate = deepcopy(calls[0])
        joined = h.join_all117(calls + [duplicate], saved, deepcopy)
        self.assertEqual(joined[0]['identical_native_call_count'], 2)
        duplicate['events'][0]['event'] = 'DIFFERENT_CAUSAL_PATH'
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS'):
            h.join_all117(calls + [duplicate], saved, deepcopy)

    def test_in_memory_function_restored_even_on_failure(self):
        original, replacement = object(), object()
        module = SimpleNamespace(_single=original)
        with self.assertRaises(RuntimeError):
            with h.memory_only_single(module, replacement):
                self.assertIs(module._single, replacement)
                raise RuntimeError('synthetic failure')
        self.assertIs(module._single, original)

    def test_existing_lock_never_created(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'not-present.lock'
            with self.assertRaises(FileNotFoundError):
                with h.existing_lock(path):
                    self.fail('missing lock was accepted')
            self.assertFalse(path.exists())

    def test_exclusive_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            h.save_new(directory, 'receipt.json', {'original': True})
            with self.assertRaises(FileExistsError):
                h.save_new(directory, 'receipt.json', {'original': False})
            self.assertTrue(json.loads((directory / 'receipt.json').read_bytes())['original'])

    def test_symbol_order_rejected_before_any_price_read(self):
        dependency = {'source_symbols_order': ['BTC-USDT', 'ETH-USDT']}
        with self.assertRaisesRegex(ValueError, 'SYMBOL_ORDER_CHANGED'):
            h.bind_frames(SimpleNamespace(SYMBOLS=['ETH-USDT', 'BTC-USDT']),
                          None, None, dependency, None, None)

    def test_explicit_owner_required_without_import_or_write(self):
        with self.assertRaisesRegex(ValueError, 'A_ONLY'):
            h.run(SimpleNamespace(run_once=False, owner_ack=h.OWNER))
        with self.assertRaisesRegex(ValueError, 'A_ONLY'):
            h.run(SimpleNamespace(run_once=True, owner_ack='someone_else'))


if __name__ == '__main__':
    unittest.main()
