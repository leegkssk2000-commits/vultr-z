"""Mutation tests for saved authority/identity closure; no economic execution.

Fixtures hard-link immutable bytes into temporary roots. Every mutation unlinks
its target before writing, so the repository's source evidence remains intact.
"""
from copy import deepcopy
import builtins
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.research.rebuild import squeeze_sprint_closure_verify_v1 as v


class ClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = v.ROOT / v.REL
        spec = v.read(out / 'SPEC.json')
        seal = v.read(out / 'ARCHITECTURE_SEAL.json')
        handoff = v.read(out / 'G5B_HANDOFF.json')
        paths = set(spec['source_files_sha256']) | set(spec['preserved_files_sha256'])
        paths.update(v.CLOSURE_SOURCES)
        paths.update(str(v.REL / name) for name in v.CORE)
        paths.update(str(v.REL / name) for name in ('REMOTE_FREEZE.json', 'HISTORY_PRIOR.json', 'CHALLENGE_WINDOW_SEALED.json'))
        paths.add(seal['identity']['parent_source_binding_path'])
        paths.add(str(v.PARENT / 'SPEC.json'))
        for field in ('runtime_registry', 'runtime_freeze_registry'):
            paths.add(handoff[field].split('#')[0])
        paths.update(item['source'].split('::')[0] for item in handoff['activation_blockers'])
        for slot in v.SLOTS:
            for per in v.PERIODS:
                folder = out / 'STAGE1' / slot / per
                paths.update(str((folder / name).relative_to(v.ROOT)) for name in
                             v.read(folder / 'RECEIPT.json')['files'])
                paths.add(str((folder / 'RECEIPT.json').relative_to(v.ROOT)))
        cls.paths = sorted(paths)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in self.paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(v.ROOT / name, target)
        self.out = self.root / v.REL

    def write(self, name, value, *, relative=True):
        path = (self.out if relative else self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()  # Never mutate the original hard-linked source inode.
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False) + '\n')

    def mutate(self, name, changes):
        value = v.read(self.out / name)
        changes(value)
        self.write(name, value)
        return value

    def test_actual_closure_passes_without_market_decode_import_or_writes(self):
        original_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == 'gzip' or name.startswith('backend.research'):
                raise AssertionError('NO_STRATEGY_OR_OUTCOME_IMPORT')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=guarded), \
             patch.object(Path, 'write_text', side_effect=AssertionError('NO_WRITES')), \
             patch.object(Path, 'write_bytes', side_effect=AssertionError('NO_WRITES')):
            result = v.verify(self.root)
        self.assertEqual(result['status'], 'PASS_SAVED_CLOSURE')
        self.assertEqual(result['implementation_files'], 65)
        for field in ('economic_FULL', 'new_candidates', 'economic_replays', 'market_packets_decoded',
                      'result_packets_decoded', 'formal_fresh_T', 'new_orders', 'file_writes'):
            self.assertEqual(result[field], 0)

    def test_metadata_cannot_silently_replace_exact_parent(self):
        self.mutate('ARCHITECTURE_SEAL.json', lambda s: s['identity'].update(canonical_candidate_ordinal=84))
        with self.assertRaisesRegex(AssertionError, 'EXACT_PARENT_IDENTITY'):
            v.verify(self.root)

    def test_removed_dependency_rejected_even_when_identity_is_rehashed(self):
        def change(seal):
            seal['identity']['implementation_files_sha256'].pop('backend/research/rebuild/c70_tm_capreuse_v1.py')
            seal['strategy_digest'] = v.canonical_digest(seal['identity'])
        self.mutate('ARCHITECTURE_SEAL.json', change)
        with self.assertRaisesRegex(AssertionError, 'EXACT_PARENT_DEPENDENCY_SET'):
            v.verify(self.root)

    def test_changed_parent_runtime_bytes_rejected(self):
        name = 'backend/research/rebuild/c70_tm_capreuse_v1.py'
        path = self.root / name
        content = path.read_bytes()
        path.unlink()
        path.write_bytes(content + b'\n# altered runtime\n')
        with self.assertRaisesRegex(AssertionError, 'FILE_HASH:.*c70_tm_capreuse_v1.py'):
            v.verify(self.root)

    def test_rule_text_requires_mechanism_and_identity_digest(self):
        self.mutate('ARCHITECTURE_SEAL.json', lambda s: s['identity']['exact_rules'].update(partial='Changed partial'))
        with self.assertRaisesRegex(AssertionError, 'MECHANISM_DIGEST'):
            v.verify(self.root)

    def test_fabricated_survivor_cannot_keep_parent_fallback_closure(self):
        self.mutate('STAGE1_SELECTION.json', lambda s: s.update(survivors=['S1-02']))
        with self.assertRaisesRegex(AssertionError, 'ZERO_SURVIVOR_SELECTION'):
            v.verify(self.root)

    def test_fabricated_gate_pass_is_recomputed_from_saved_metrics(self):
        def change(selection):
            gate = selection['decisions']['S1-02']['SEEN2026']
            gate['checks'] = {k: True for k in gate['checks']}
            gate['passed'] = True
        self.mutate('STAGE1_SELECTION.json', change)
        with self.assertRaisesRegex(AssertionError, 'INDEPENDENT_GATE_DECISION'):
            v.verify(self.root)

    def test_aggregate_table_cannot_replace_per_window_saved_metrics(self):
        def change(table):
            table['S1-02']['SEEN2026']['normal_increment_bps'] = 1000000.
        self.mutate('STAGE1_TABLE.json', change)
        with self.assertRaisesRegex(AssertionError, 'SCREEN_TABLE_BOUND_TO_SAVED_METRICS'):
            v.verify(self.root)

    def test_duplicate_screen_window_start_is_rejected(self):
        def change(budget):
            starts = budget['squeeze_sprint_allocation']['screen_window_starts']
            starts[-1] = deepcopy(starts[0])
        self.mutate('BUDGET.json', change)
        with self.assertRaisesRegex(AssertionError, 'EIGHT_UNIQUE_SCREEN_STARTS'):
            v.verify(self.root)

    def test_saved_raw_corruption_is_detected_without_decode(self):
        path = self.out / 'STAGE1/S1-02/DEV2025/RAW.json.gz'
        path.unlink()
        path.write_bytes(b'corrupted opaque packet')
        with self.assertRaisesRegex(AssertionError, 'FILE_HASH:RAW.json.gz'):
            v.verify(self.root)

    def test_new_stage2_economic_receipt_cannot_hide_behind_zero_counts(self):
        self.write('STAGE2/S1-02/DEV2025/EXECUTION_STARTED.json', {'status': 'STARTED'})
        with self.assertRaisesRegex(AssertionError, 'UNDECLARED_ECONOMIC_STAGE:STAGE2'):
            v.verify(self.root)

    def test_historical_trial_and_closed_budget_authority_cannot_change(self):
        original = v.read(self.out / 'BUDGET.json')
        changed = deepcopy(original)
        changed['trials'].append({'candidate_ordinal': 85})
        self.write('BUDGET.json', changed)
        with self.assertRaisesRegex(AssertionError, 'ALL_PRIOR_HISTORY_UNCHANGED'):
            v.verify(self.root)
        changed = deepcopy(original)
        changed['squeeze_sprint_allocation']['remaining_authorized_FULL'] = 1
        self.write('BUDGET.json', changed)
        with self.assertRaisesRegex(AssertionError, 'CLOSED_ECONOMIC_AUTHORITY'):
            v.verify(self.root)

    def test_prepared_handoff_rejects_every_activation_or_authority_escalation(self):
        original = v.read(self.out / 'G5B_HANDOFF.json')
        changes = dict(runtime_registered=True, promotion_authority=True, selection_authority=True,
                       fresh_collection_started=True, g5a_formal_pass=True, g5b_terminal_pass=True,
                       g6_allowed=True, historical_backfill=True, formal_fresh_T=1,
                       preboundary_formal_credit=1, boundary_ms=1, activation_id='old-lane',
                       cohort_id='old-cohort', execution_authority='LIVE',
                       order_authority='ALLOWED', live_trade_authority='ALLOWED')
        for key, value in changes.items():
            with self.subTest(key=key):
                self.write('G5B_HANDOFF.json', dict(original, **{key: value}))
                with self.assertRaisesRegex(AssertionError, 'G5B_PREPARED_AUTHORITY'):
                    v.verify(self.root)

    def test_numeric_zero_is_not_a_false_authority_flag(self):
        self.mutate('G5B_HANDOFF.json', lambda h: h.update(selection_authority=0))
        with self.assertRaisesRegex(AssertionError, 'G5B_PREPARED_AUTHORITY:selection_authority'):
            v.verify(self.root)

    def test_provisional_checkpoint_cannot_be_reported_terminal(self):
        self.mutate('G5B_HANDOFF.json', lambda h: h['checkpoints'].update(T12='TERMINAL_PASS'))
        with self.assertRaisesRegex(AssertionError, 'FORMAL_TERMINAL_BOUNDARY'):
            v.verify(self.root)

    def test_missing_activation_blocker_and_cross_scope_seal_are_rejected(self):
        original = v.read(self.out / 'G5B_HANDOFF.json')
        changed = deepcopy(original)
        changed['activation_blockers'].pop()
        self.write('G5B_HANDOFF.json', changed)
        with self.assertRaisesRegex(AssertionError, 'ALL_ACTIVATION_BLOCKERS'):
            v.verify(self.root)
        self.write('G5B_HANDOFF.json', dict(original, architecture_seal_path=str(v.PARENT / 'SPEC.json')))
        with self.assertRaisesRegex(AssertionError, 'G5B_EXACT_SEAL_PATH'):
            v.verify(self.root)

    def test_manifest_is_required_for_ci_and_covers_closure_files(self):
        with self.assertRaisesRegex(AssertionError, 'CLOSURE_EVIDENCE_MANIFEST_REQUIRED'):
            v.verify(self.root, require_evidence_manifest=True)
        self.write('CLOSURE_SOURCE_HASHES.json', dict(schema_version='zel.squeeze_continuation.closure_sources.v1',
                   files={name: v.file_digest(self.root / name) for name in v.CLOSURE_SOURCES}))
        hashes = {name: v.file_digest(self.out / name) for name in v.CORE + ('CLOSURE_SOURCE_HASHES.json',)}
        self.write('EVIDENCE_HASHES.json', hashes)
        self.assertEqual(v.verify(self.root, require_evidence_manifest=True)['evidence_manifest_files'], len(v.CORE) + 1)
        hashes.pop('G5B_HANDOFF.json')
        self.write('EVIDENCE_HASHES.json', hashes)
        with self.assertRaisesRegex(AssertionError, 'CLOSURE_EVIDENCE_MANIFEST_COVERAGE'):
            v.verify(self.root, require_evidence_manifest=True)

    def test_manifest_cannot_reference_outside_evidence_root(self):
        self.write('CLOSURE_SOURCE_HASHES.json', dict(schema_version='zel.squeeze_continuation.closure_sources.v1',
                   files={name: v.file_digest(self.root / name) for name in v.CLOSURE_SOURCES}))
        hashes = {name: v.file_digest(self.out / name) for name in v.CORE + ('CLOSURE_SOURCE_HASHES.json',)}
        hashes['../outside.json'] = '0' * 64
        self.write('EVIDENCE_HASHES.json', hashes)
        with self.assertRaisesRegex(AssertionError, 'BOUND_REFERENCE_REQUIRED'):
            v.verify(self.root, require_evidence_manifest=True)


if __name__ == '__main__':
    unittest.main()
