"""PR1211 remaining P1 counterexamples; artificial inputs/keys only."""
import base64
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from backend.research.rebuild import step7_authorized_io_v1 as io
from backend.research.rebuild import step7_isolated_worker_v1 as worker
from backend.research.rebuild import step7_kr3_execution_v1 as native
from backend.research.rebuild import test_step7_authorized_io_v1 as fixture


class IsolatedSourceTests(unittest.TestCase):
    def module(self, source):
        temp = tempfile.TemporaryDirectory(prefix='step7-artificial-worker-')
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'producer.py'
        path.write_text(source)
        name = '_step7_worker_fixture'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        return module

    def test_parent_json_report_function_and_indirect_helper_never_receive_input(self):
        module = self.module("import json\ndef helper(obj):\n    return {'size': len(obj)}\ndef produce_reports(obj):\n    return helper(obj)\ndef consume(raw):\n    return produce_reports(json.loads(raw))\n")
        prepared = worker.snapshot(module.consume)
        def poison(*args, **kwargs):
            self.fail('Parent replacement received protected synthetic input')
        for name, value in [('json', types.SimpleNamespace(loads=poison)),
                            ('produce_reports', poison), ('helper', poison)]:
            with self.subTest(name=name), patch.object(module, name, value):
                self.assertEqual(worker.run(prepared, b'[1,2]'), {'size': 2})

    def test_staged_source_bytes_survive_original_disk_mutation(self):
        module = self.module("def consume(raw):\n    return {'size': len(raw)}\n")
        prepared = worker.snapshot(module.consume)
        Path(module.__file__).write_text("raise AssertionError('unapproved source')\n")
        self.assertEqual(worker.run(prepared, b'abc'), {'size': 3})

    def test_environment_and_import_path_not_inherited(self):
        module = self.module("import os, sys\ndef consume(raw):\n    return {'environment': dict(os.environ), 'path': sys.path, 'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site}\n")
        with patch.dict(os.environ, {'PYTHONPATH': '/unapproved', 'STEP7_SECRET_FIXTURE': 'do-not-inherit'}):
            result = worker.run(worker.snapshot(module.consume), b'')
        self.assertEqual(result['environment'], {'LC_ALL': 'C.UTF-8'})
        self.assertEqual((result['isolated'], result['no_site']), (1, 1))
        self.assertNotIn(str(Path.cwd()), result['path'])
        self.assertNotIn('/unapproved', result['path'])

    def test_child_source_hash_checked_before_callback(self):
        module = self.module("def consume(raw):\n    raise AssertionError('must not execute')\n")
        prepared = worker.snapshot(module.consume)
        with worker.staged(prepared) as (root, digest):
            target = root / '_step7_worker_fixture.py'
            target.chmod(0o600)
            target.write_text("def consume(raw):\n    return {'wrong': True}\n")
            result = subprocess.run([sys.executable, '-I', '-S', '-B',
                str(root/'backend/research/rebuild/step7_isolated_worker_v1.py'),
                '--child', str(root), digest], input=b'ARTIFICIAL', capture_output=True,
                env={'LC_ALL': 'C.UTF-8'}, cwd=root, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'WORKER_SOURCE_CHANGED', result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_timeout_terminates_and_reaps_owned_child(self):
        module = self.module("import time\ndef consume(raw):\n    time.sleep(5)\n    return {}\n")
        prepared = worker.snapshot(module.consume)
        prepared[0]['timeout_seconds'] = 0.15
        original = subprocess.Popen
        launched = []
        def tracked(*args, **kwargs):
            child = original(*args, **kwargs)
            launched.append(child)
            return child
        with patch.object(worker.subprocess, 'Popen', tracked), self.assertRaises(subprocess.TimeoutExpired):
            worker.run(prepared, b'')
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].poll())

    def test_non_dictionary_and_invalid_json_outputs_rejected(self):
        for source, reason in [("def consume(raw):\n    return []\n", 'DICTIONARY_REQUIRED'),
                               ("def consume(raw):\n    print('noise')\n    return {}\n", 'INVALID_JSON')]:
            module = self.module(source)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                worker.run(worker.snapshot(module.consume), b'')

    def test_output_byte_cap_enforced(self):
        module = self.module("def consume(raw):\n    return {'large': 'x' * 4096}\n")
        prepared = worker.snapshot(module.consume)
        prepared[0]['max_output_bytes'] = 1024
        with self.assertRaisesRegex(ValueError, 'WORKER_FAILED|OUTPUT_LIMIT'):
            worker.run(prepared, b'')

    def test_native_entrypoint_complete_import_closure_flat_artificial_input(self):
        # Constant, artificial bars create no trades. This checks the changed
        # native execution boundary, not the previously completed economics.
        spec = native.fixture_spec()
        spec.update(fixture_only=False, formal_parameters_approved=True)
        bars = [{'bar_open_ts': i*native.BAR, 'bar_close_ts': (i+1)*native.BAR,
                 'available_ts': (i+1)*native.BAR, 'open': 100., 'high': 100.,
                 'low': 100., 'close': 100., 'volume': 1.} for i in range(390)]
        raw = worker.canonical({'source': {symbol: {'bars': bars, 'quotes': [], 'funding': []}
                                          for symbol in native.SYMBOLS},
            'specification': spec, 'cost': {'fee_bps_each_side': 2.,
                'funding_interval_ms': 2*native.BAR, 'max_quote_age_ms': 0}})
        fixture.AuthorizedIOTests.setUpClass()
        self.addCleanup(fixture.AuthorizedIOTests.tearDownClass)
        f = fixture.AuthorizedIOTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.raw = raw
        f.source['data_sha'] = io._sha_bytes(raw)
        f.source.pop('receipt_sha256')
        f.source = fixture.old.seal(f.source)
        f.request['source'] = f.source
        code_sha, qualname = io._producer_binding(native.execute_sealed_bytes)
        f.payload['binding'].update(source_sha=fixture.old.sha(f.source),
                                    data_sha=f.source['data_sha'],
                                    producer_code_sha256=code_sha, producer_qualname=qualname)
        f.sign()
        with patch.object(native, 'produce_reports', side_effect=AssertionError('parent callback')):
            dispatched = io._execute(f.request, native.execute_sealed_bytes, f.trust,
                                     f.campaign, f.journal, 500, f.reader, fixture=True)
        result = dispatched['output']
        self.assertTrue(dispatched['access_receipt']['fixture_only'])
        self.assertEqual(result['consumer']['produced_count'], 9)
        self.assertIn('NO_COMPLETED_NATIVE_TRADES', result['consumer']['economic_readiness_blockers'])
        self.assertFalse(result['consumer']['formal_admission'])


class SignedGlobalMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.AuthorizedIOTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.AuthorizedIOTests.tearDownClass()

    def setUp(self):
        self.f = fixture.AuthorizedIOTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_global_replacement_during_reader_cannot_receive_raw(self):
        original = fixture.json
        self.addCleanup(setattr, fixture, 'json', original)
        poison = types.SimpleNamespace(loads=lambda raw: self.fail('parent json received bytes'))
        def reader(request, trust):
            raw = self.f.reader(request, trust)
            fixture.json = poison
            return raw
        result = io._execute(self.f.request, fixture.producer, self.f.trust,
            self.f.campaign, self.f.journal, 500, reader, fixture=True)
        self.assertEqual(result['output']['rows'], 1)
        self.assertEqual(result['access_receipt']['execution_mode'], 'FRESH_ISOLATED_SOURCE_SNAPSHOT')

    def test_failure_in_fresh_child_consumes_and_cannot_retry(self):
        with patch.object(io.isolated, 'run', side_effect=ValueError('synthetic worker failure')):
            with self.assertRaisesRegex(ValueError, 'synthetic worker failure'):
                self.f.execute()
        with self.assertRaisesRegex(ValueError, 'QUERY_RIGHT_ALREADY_RESERVED'):
            self.f.execute()
        self.assertEqual(self.f.calls['read'], 1)

    def test_path_shadow_cannot_accept_invalid_signature(self):
        binary = self.f.journal / 'openssl'
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o700)
        self.f.request['signed_approval']['signature_b64'] = base64.b64encode(bytes(64)).decode()
        with patch.dict(os.environ, {'PATH': str(self.f.journal)}):
            self.f.reject_before_read('INVALID_EXTERNAL_SIGNATURE')

    def test_source_snapshot_identity_binds_indirect_native_dependency(self):
        prepared = worker.snapshot(native.execute_sealed_bytes)
        digest, _ = worker.snapshot_identity(prepared)
        manifest, files = deepcopy(prepared)
        key = 'backend/research/rebuild/keltner_m2_context_v1.py'
        self.assertIn(key, files)
        manifest['files'][key] = '0'*64
        self.assertNotEqual(worker.snapshot_identity((manifest, files))[0], digest)


if __name__ == '__main__':
    unittest.main()
