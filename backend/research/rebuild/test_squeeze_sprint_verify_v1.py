"""Artificial evidence tamper tests. No historical screen or FULL execution."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from backend.research.rebuild import squeeze_sprint_verify_v1 as v
from backend.research.rebuild import squeeze_sprint_screen_v1 as screen
from backend.research.rebuild import c70_tm_capreuse_account_v1 as account
from backend.research.rebuild.test_squeeze_sprint_screen_v1 import parent, raw_of
from backend.research.rebuild.test_c63_c70_trader_management_v1 import fixture, COST, POLICY
from backend.research.rebuild.test_chart_mechanism_execution_v1 import rows_of


def example(slot='S1-02', n=150, allocation=(1, 3), mutate=None):
    bars, signal, _ = fixture(n=n)
    if mutate:
        mutate(bars)
    features = [dict(momentum=b.close - bars[j - 14].close if j >= 14 else 1.)
                for j, b in enumerate(bars)]
    source = parent(bars, signal, features, *allocation)
    rows = rows_of(bars)
    end = bars[-1].open_ts + v.B
    out = screen.screen_symbol(source, rows, COST, end, slot)
    return source, out, rows, end


class SavedVerificationTests(unittest.TestCase):
    def test_independent_verifier_never_calls_source_predicate_or_replay(self):
        for slot in v.REASONS:
            source, out, rows, end = example(slot)
            with (patch.object(screen.comp, 'observe', side_effect=AssertionError('PREDICATE_REUSE')),
                  patch.object(screen.tm, 'position', side_effect=AssertionError('SOURCE_REPLAY')),
                  patch.object(screen.cap, 'replay', side_effect=AssertionError('FULL_REPLAY'))):
                result = v.verify_screen_saved(out, source, rows, COST, end)
            self.assertEqual(result['economic_replays'], 0)
            self.assertEqual(result['campaigns'], 1)

    def test_runner_extension_after_parent_exit_checks_only_saved_prefix(self):
        def mutate(bars):
            for j in (130, 131):
                bars[j] = replace(bars[j], close=110., low=109.)
        source, out, rows, end = example(mutate=mutate)
        self.assertIn('exit_ts', raw_of(source))
        self.assertNotIn('exit_ts', raw_of(out))
        v.verify_screen_saved(out, source, rows, COST, end)

    def test_rejects_fabricated_trigger_feature(self):
        source, out, rows, end = example()
        out['screen_trace'][0]['features']['sma10'] += 1.
        with self.assertRaisesRegex(AssertionError, 'CAUSAL_FEATURE_sma10'):
            v.verify_screen_saved(out, source, rows, COST, end)

    def test_rejects_missing_component_observation(self):
        source, out, rows, end = example()
        out['screen_trace'].pop(2)
        with self.assertRaisesRegex(AssertionError, 'MISSING_SCREEN_OBSERVATIONS'):
            v.verify_screen_saved(out, source, rows, COST, end)

    def test_rejects_new_admission_and_resized_entry(self):
        source, out, rows, end = example()
        for changed in ('events', 'allocation'):
            tampered = deepcopy(out)
            if changed == 'events':
                tampered['events'][0]['admission'] = False
            else:
                raw_of(tampered)['allocation_denominator'] = 1
            with self.assertRaisesRegex(AssertionError, 'STAGE1_'):
                v.verify_screen_saved(tampered, source, rows, COST, end)

    def test_rejects_intrabar_stop_fill_price(self):
        def mutate(bars):
            bars[95] = replace(bars[95], close=99., low=98.)
            bars[96] = replace(bars[96], open=85., low=84.)
        source, out, rows, end = example(mutate=mutate)
        v.verify_screen_saved(out, source, rows, COST, end)
        raw = raw_of(out)
        self.assertEqual(raw['exit_price'], 85.)
        for event in out['trace']:
            if event['kind'] == 'FINAL_FILL':
                event['price'] = raw['entry_price']
        with self.assertRaisesRegex(AssertionError, 'GAP_OPEN_PRICE'):
            v.verify_screen_saved(out, source, rows, COST, end)

    def test_rejects_fictitious_terminal_liquidation(self):
        source, out, rows, end = example(n=100)
        raw_of(out)['terminal_liquidation'] = True
        with self.assertRaises(AssertionError):
            v.verify_screen_saved(out, source, rows, COST, end)

    def test_no_actual_partial_means_no_runner_observations(self):
        source, out, rows, end = example(n=78)
        self.assertEqual(raw_of(out)['partial_count'], 0)
        self.assertEqual(out['screen_trace'], [])
        v.verify_screen_saved(out, source, rows, COST, end)

    def test_future_changed_rows_cannot_change_prefix_predicate(self):
        source, out, rows, end = example()
        j, ei = 90, 60
        before = v.component_prefix('S1-03', rows, j, ei, rows[ei]['open'], True, COST)
        changed = deepcopy(rows)
        for row in changed[j + 1:]:
            row['close'] *= 100
        self.assertEqual(before, v.component_prefix('S1-03', changed, j, ei, rows[ei]['open'], True, COST))

    def test_daily_predicate_ignores_incomplete_day(self):
        _, _, rows, _ = example()
        j = 90
        result = v.component_prefix('S1-07', rows, j, 60, rows[60]['open'], True, COST)
        self.assertFalse(result['trigger'])
        self.assertFalse(result['features']['is_daily_close'])

    def test_unit_and_allocated_cash_with_terminal_funding_cost(self):
        source, out, rows, end = example(n=100)
        packet = dict(policy=POLICY, rows_by={'TEST': rows}, costs={'TEST': COST})
        cal = dict(start_ms=60 * v.B, eval_end_ms=end, runoff_end_ms=end)
        result = account.charge({'TEST': out}, packet, cal)
        proof = v.verify_money_saved({'TEST': out}, result, packet)
        self.assertGreater(proof['totals']['funding_bps'], 0)
        changed = deepcopy(result)
        changed['open_observations'][0]['weighted_legs'][-1]['qty'] *= 2
        with self.assertRaisesRegex(AssertionError, 'WEIGHTED_LEG_QTY'):
            v.verify_money_saved({'TEST': out}, changed, packet)
        changed = deepcopy(result)
        changed['metrics']['terminal_cost2x_net_bps'] += 1
        with self.assertRaisesRegex(AssertionError, 'INDEPENDENT_TERMINAL_COST2'):
            v.verify_money_saved({'TEST': out}, changed, packet)

    def test_frozen_hash_change_is_rejected_before_evidence_decode(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            for name in ('engine.py', 'parent.json', 'input/DEV2025.json.gz'):
                (root / name).write_bytes(b'FROZEN')
            digest = sha256(b'FROZEN').hexdigest()
            spec = dict(source_files_sha256={'engine.py': digest},
                        preserved_files_sha256={'parent.json': digest},
                        input_packet_sha256={'DEV2025': digest})
            v.verify_hashes(spec, root, root / 'input')
            (root / 'engine.py').write_bytes(b'CHANGED')
            with self.assertRaisesRegex(AssertionError, 'source_files_sha256'):
                v.verify_hashes(spec, root, root / 'input')

    def test_preoutcome_cli_does_not_decode_any_packet(self):
        from backend.research.rebuild import squeeze_sprint_account_v1 as c
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            out = root / 'evidence'
            out.mkdir()
            for name in ('engine.py', 'parent.json', 'input/DEV2025.json.gz'):
                (root / name).write_bytes(b'FROZEN')
            digest = sha256(b'FROZEN').hexdigest()
            spec = dict(source_files_sha256={'engine.py': digest},
                        preserved_files_sha256={'parent.json': digest},
                        input_packet_sha256={'DEV2025': digest})
            (out / 'SPEC.json').write_text(json.dumps(spec))
            with patch.object(c, 'OUT', out), patch.object(c.a, 'ROOT', root), \
                 patch.object(c.a, 'INPUTS', root / 'input'), \
                 patch.object(c.a, 'gz', side_effect=AssertionError('OUTCOME_DECODE')):
                result = v.verify()
            self.assertEqual(result['status'], 'PREOUTCOME_NO_ECONOMIC_RESULTS')
            self.assertEqual(result['outcome_packets_decoded'], 0)

    def test_stage1_exact_retention_boundary_and_no_aggregate_rescue(self):
        from backend.research.rebuild import squeeze_sprint_account_v1 as c
        metric = dict(source_conformance='PASS', causal_integrity='PASS', normal_increment_bps=1.,
                      cost2_increment_bps=1., ordinary_winner_retention=.6, top_decile_winner_retention=.6)
        table = {'S1-02': {per: dict(metric) for per in c.PERIODS}}
        registry = {'S1-02': dict(performance_grade='C')}
        selection = c.select_stage1(table, registry)
        self.assertEqual(v.verify_stage1_selection(table, registry, selection)['survivors'], ['S1-02'])
        table['S1-02']['SEEN2026']['cost2_increment_bps'] = 0.
        selection = c.select_stage1(table, registry)
        self.assertEqual(v.verify_stage1_selection(table, registry, selection)['survivors'], [])
        selection['survivors'] = ['S1-02']
        with self.assertRaisesRegex(AssertionError, 'INDEPENDENT_STAGE1_SURVIVORS'):
            v.verify_stage1_selection(table, registry, selection)

    def test_receipt_detects_changed_raw_before_json_decode(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {}
            for name in ('RAW.json.gz', 'RESULT.json.gz'):
                (root / name).write_bytes(b'FROZEN')
                files[name] = sha256(b'FROZEN').hexdigest()
            receipt = dict(spec_sha256='SPEC', freeze_commit='COMMIT', files=files)
            (root / 'RECEIPT.json').write_text(json.dumps(receipt))
            (root / 'EXECUTION_STARTED.json').write_text(json.dumps(dict(spec_sha256='SPEC', freeze_commit='COMMIT')))
            v.verify_receipt(root, 'SPEC')
            (root / 'RAW.json.gz').write_bytes(b'CHANGED')
            with self.assertRaisesRegex(AssertionError, 'RECEIPT_FILE_RAW'):
                v.verify_receipt(root, 'SPEC')


if __name__ == '__main__':
    unittest.main()
