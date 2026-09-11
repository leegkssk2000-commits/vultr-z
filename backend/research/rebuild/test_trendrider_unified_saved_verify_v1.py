from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import unittest

from backend.research.rebuild import trendrider_unified_saved_verify_v1 as verifier


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        original = Path(__file__).resolve().parents[3]
        manifest_path = verifier.EVIDENCE + '/EVIDENCE_MANIFEST.json'
        manifest = json.loads((original / manifest_path).read_text())
        for relative in [manifest_path, *manifest['files_sha256']]:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original / relative, destination)

    def reseal_changed_document(self, name, change):
        relative = verifier.EVIDENCE + '/' + name
        path = self.root / relative
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))
        mp = self.root / verifier.EVIDENCE / 'EVIDENCE_MANIFEST.json'
        manifest = json.loads(mp.read_text())
        manifest['files_sha256'][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        mp.write_text(json.dumps(manifest))

    def test_saved_closure_passes(self):
        self.assertEqual(verifier.verify(self.root)['economic_runs'], 0)

    def test_resealed_budget_cannot_claim_extra_full(self):
        self.reseal_changed_document('BUDGET_AND_TERMINAL.json', lambda d: d.update(child_FULL=1))
        with self.assertRaisesRegex(ValueError, 'ECONOMIC_OR_AUTHORITY_NONZERO'):
            verifier.verify(self.root)

    def test_resealed_absent_screen_cannot_be_called_zero_survivors(self):
        self.reseal_changed_document('BUDGET_AND_TERMINAL.json', lambda d: d.update(survivor_count=0))
        with self.assertRaisesRegex(ValueError, 'UNEVALUATED_GENES_RELABELED'):
            verifier.verify(self.root)

    def test_resealed_handoff_stays_closed(self):
        self.reseal_changed_document('BUDGET_AND_TERMINAL.json', lambda d: d.update(qualification_boundary=123))
        with self.assertRaisesRegex(ValueError, 'UNAUTHORIZED_HANDOFF'):
            verifier.verify(self.root)

    def test_resealed_feature_cannot_replace_missing_snapshot(self):
        self.reseal_changed_document('DECISION_FEATURES.json', lambda d: d['rows'][0].update(snapshot={'chase_state': 'COOLING_OR_FLAT'}))
        with self.assertRaisesRegex(ValueError, 'SAVED_AUDIT_DRIFT'):
            verifier.verify(self.root)


if __name__ == '__main__':
    unittest.main()
