"""Synthetic copy-only preparation; no VPS, guard, runner or market data."""
from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('prepare_attempt_under_test', HERE / 'prepare_attempt.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.old = self.root / 'failed'; self.old.mkdir()
        self.new = self.root / 'attempt2'
        files = {'guarded_once.py': (HERE / 'guarded_once.before.py').read_bytes(),
                 'run_handoff.py': b'raise RuntimeError("MUST_NOT_EXECUTE")\n',
                 'FREEZE.json': b'{"fixed":true}\n',
                 'persist_addonly.py': b'raise RuntimeError("MUST_NOT_EXECUTE")\n',
                 'INPUT_BTC.csv.gz': b'synthetic_immutable_cache',
                 'STARTED.json': b'original_started_receipt',
                 'EXECUTION.log': b'original_failure_log', 'economic.lock': b'original_lock'}
        files['CODE_FREEZE.json'] = json.dumps({'sha256': {'run_handoff.py': prep.sha(files['run_handoff.py'])}}).encode()
        files['INPUT_CACHE.json'] = json.dumps({'symbols': {'BTC': {'path': 'INPUT_BTC.csv.gz', 'sha256': prep.sha(files['INPUT_BTC.csv.gz'])}}}).encode()
        for name, raw in files.items(): (self.old / name).write_bytes(raw)
        self.before = files
        for attr, name in [('CACHE', 'INPUT_CACHE.json'), ('FREEZE', 'FREEZE.json'),
                           ('CODE_FREEZE', 'CODE_FREEZE.json'), ('PERSIST', 'persist_addonly.py')]:
            p = patch.object(prep, attr, prep.sha(files[name])); p.start(); self.addCleanup(p.stop)

    def test_preparation_copies_inputs_only_and_preserves_failed_attempt(self):
        result = prep.prepare(self.old, self.new)
        self.assertEqual(result['state'], 'PREPARED_NOT_STARTED')
        self.assertEqual(result['guards_started'], 0)
        self.assertEqual(prep.sha((self.new / 'guarded_once.py').read_bytes()), prep.AFTER)
        for name, raw in self.before.items(): self.assertEqual((self.old / name).read_bytes(), raw)
        for name in ['STARTED.json', 'EXECUTION.log', 'economic.lock']:
            self.assertFalse((self.new / name).exists())
        with self.assertRaises(ValueError): prep.prepare(self.old, self.new)

    def test_changed_source_or_original_destination_fails_before_creating_attempt(self):
        with self.assertRaises(ValueError): prep.prepare(self.old, self.old)
        (self.old / 'guarded_once.py').write_bytes(b'already changed')
        with self.assertRaises(ValueError): prep.prepare(self.old, self.new)
        self.assertFalse(self.new.exists())


if __name__ == '__main__': unittest.main()
