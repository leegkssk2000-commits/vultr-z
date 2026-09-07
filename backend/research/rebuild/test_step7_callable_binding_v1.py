"""PR1210 callable P1 regressions. Only synthetic signed fixtures; no sealed data."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from backend.research.rebuild import step7_authorized_io_v1 as io
from backend.research.rebuild import test_step7_authorized_io_v1 as fixture
from backend.research.rebuild.step7_callable_binding_v1 import producer_binding


def impostor(raw):
    raise AssertionError('Unapproved implementation must never receive bytes')


class CallableBindingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='step7-code-binding-fixture-')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'producer.py'
        self.path.write_text("def consume(raw):\n    return {'size': len(raw)}\n")
        name = '_step7_callable_fixture'
        spec = importlib.util.spec_from_file_location(name, self.path)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[name] = self.module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(self.module)
        self.fn = self.module.consume

    def test_canonical_code_matches_exact_file(self):
        digest, name = producer_binding(self.fn)
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(name, '_step7_callable_fixture:consume')

    def test_matching_labels_and_co_filename_do_not_authenticate_new_function(self):
        forged = types.FunctionType(impostor.__code__.replace(co_filename=str(self.path)),
                                    self.module.__dict__, 'consume')
        forged.__module__ = self.module.__name__
        forged.__qualname__ = 'consume'
        with self.assertRaisesRegex(ValueError, 'CANONICAL_FUNCTION'):
            producer_binding(forged)

    def test_replacing_canonical_code_object_is_rejected(self):
        self.fn.__code__ = impostor.__code__.replace(co_filename=str(self.path),
                                                     co_name='consume', co_qualname='consume')
        with self.assertRaisesRegex(ValueError, 'EXECUTABLE_CODE_MISMATCH'):
            producer_binding(self.fn)

    def test_replacing_module_attribute_cannot_hide_wrong_code(self):
        forged = types.FunctionType(impostor.__code__.replace(co_filename=str(self.path),
                                    co_name='consume', co_qualname='consume'),
                                    self.module.__dict__, 'consume')
        forged.__qualname__ = 'consume'
        self.module.consume = forged
        with self.assertRaisesRegex(ValueError, 'EXECUTABLE_CODE_MISMATCH'):
            producer_binding(forged)

    def test_identical_code_with_foreign_globals_is_rejected(self):
        forged = types.FunctionType(self.fn.__code__, dict(self.module.__dict__), 'consume')
        self.module.consume = forged
        with self.assertRaisesRegex(ValueError, 'GLOBAL_NAMESPACE'):
            producer_binding(forged)

    def test_mutated_argument_defaults_are_rejected(self):
        self.fn.__defaults__ = (b'not approved',)
        with self.assertRaisesRegex(ValueError, 'MUTABLE_ARGUMENT'):
            producer_binding(self.fn)

    def test_changed_disk_code_is_rejected_without_execution(self):
        self.path.write_text("raise AssertionError('must not execute module')\ndef consume(raw):\n    return None\n")
        with self.assertRaisesRegex(ValueError, 'EXECUTABLE_CODE_MISMATCH'):
            producer_binding(self.fn)

    def test_nested_callback_is_not_a_top_level_producer(self):
        def nested(raw):
            return raw
        with self.assertRaisesRegex(ValueError, 'TOP_LEVEL_PINNED'):
            producer_binding(nested)


class SignedDispatchBindingTests(unittest.TestCase):
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
        original = fixture.producer.__code__
        self.addCleanup(setattr, fixture.producer, '__code__', original)

    def mutated_code(self):
        return impostor.__code__.replace(co_filename=fixture.producer.__code__.co_filename,
                                         co_name='producer', co_qualname='producer')

    def test_forged_callback_rejected_before_reservation_and_read(self):
        forged = types.FunctionType(self.mutated_code(), fixture.__dict__, 'producer')
        forged.__qualname__ = 'producer'
        with self.assertRaisesRegex(ValueError, 'CANONICAL_FUNCTION'):
            io._execute(self.f.request, forged, self.f.trust, self.f.campaign,
                        self.f.journal, 500, self.f.reader, fixture=True)
        self.assertEqual(self.f.calls['read'], 0)
        self.assertFalse(list(self.f.journal.glob('*.reservation.json')))

    def test_real_function_code_replacement_rejected_before_io(self):
        fixture.producer.__code__ = self.mutated_code()
        with self.assertRaisesRegex(ValueError, 'EXECUTABLE_CODE_MISMATCH'):
            self.f.execute()
        self.assertEqual(self.f.calls['read'], 0)
        self.assertFalse(list(self.f.journal.glob('*.reservation.json')))

    def test_code_changed_during_read_never_receives_bytes_and_budget_stays_used(self):
        def reader(request, trust):
            raw = self.f.reader(request, trust)
            fixture.producer.__code__ = self.mutated_code()
            return raw
        with self.assertRaisesRegex(ValueError, 'EXECUTABLE_CODE_MISMATCH'):
            io._execute(self.f.request, fixture.producer, self.f.trust, self.f.campaign,
                        self.f.journal, 500, reader, fixture=True)
        self.assertEqual(self.f.calls['read'], 1)
        self.assertEqual(len(list(self.f.journal.glob('*.reservation.json'))), 1)
        # Restore code only. Never delete or restore the consumed access journal.
        fixture.producer.__code__ = self._clean_code()
        with self.assertRaisesRegex(ValueError, 'QUERY_RIGHT_ALREADY_RESERVED'):
            self.f.execute()
        self.assertEqual(self.f.calls['read'], 1)

    def _clean_code(self):
        code = compile(Path(fixture.__file__).read_bytes(), fixture.__file__, 'exec', dont_inherit=True)
        return next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name=='producer')

    def test_authenticated_request_is_copied_before_reader_mutation(self):
        original = deepcopy(self.f.request)
        def reader(request, trust):
            # A separate caller mutates its original request after authorization.
            self.f.request['source']['data_sha'] = '0'*64
            self.f.request['signed_approval']['payload']['binding']['producer_code_sha256'] = '0'*64
            return self.f.reader(request, trust)
        result = io._execute(self.f.request, fixture.producer, self.f.trust, self.f.campaign,
                             self.f.journal, 500, reader, fixture=True)
        self.assertEqual(result['output']['rows'], 1)
        self.assertEqual(result['access_receipt']['formal_credit'], 0)
        self.assertNotEqual(self.f.request, original)


if __name__ == '__main__':
    unittest.main()
