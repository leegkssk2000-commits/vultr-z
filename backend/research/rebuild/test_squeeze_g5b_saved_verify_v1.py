from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.research.rebuild import squeeze_g5b_saved_verify_v1 as saved


class ClosureTests(unittest.TestCase):
    def test_saved_verification_never_qualifies_or_creates_boundary(self):
        from backend.research.rebuild import g5b_operational_terminal_v1 as boundary
        from backend.research.rebuild import c70_tm_capreuse_v1 as replay
        with patch.object(saved.qualification, 'qualify_once', side_effect=AssertionError('NO_REQUALIFICATION')), \
             patch.object(saved.qualification.alpha, 'evaluate_bundle', side_effect=AssertionError('NO_GATE_REEXECUTION')), \
             patch.object(boundary, 'freeze_boundary', side_effect=AssertionError('NO_BOUNDARY')), \
             patch.object(replay, 'replay', side_effect=AssertionError('NO_ECONOMIC_REPLAY')):
            self.assertEqual(saved.verify()['status'], 'PASS_SAVED_BLOCKED_SCOPE_VERIFIED')

    def test_resealed_activation_claim_is_rejected(self):
        original = saved.read
        for key, value in [('runtime_registered', True), ('fresh_collection_started', True),
                           ('formal_fresh_T', 1), ('boundary_ms', 1_789_100_000_000),
                           ('g6_allowed', True), ('open_T', True)]:
            def changed(path):
                data = original(path)
                if path.name == 'STATUS.json':
                    data = deepcopy(data)
                    data.pop('receipt_sha256')
                    data[key] = value
                    data = saved.qualification.seal(data)
                return data
            with self.subTest(key=key), patch.object(saved, 'read', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'STATUS_AUTHORITY:' + key):
                    saved.verify()

    def test_static_cutover_pass_does_not_establish_freshness(self):
        sample = saved.read(saved.ROOT / saved.REL / 'SOURCE_STATE_SNAPSHOT.json')
        result = saved.source_diagnostic(sample)
        self.assertTrue(result['durable_cutover_pass'])
        self.assertFalse(result['stored_source_fresh'])
        self.assertFalse(result['production_grade_ready'])
        self.assertIsNone(result['squeeze_fresh_source_receipt'])
        last = result['latest_stored_bar_ms']
        limit = result['stale_authority_ms']
        for now, fresh in [(last-1, False), (last+limit-1, True), (last+limit, False)]:
            with self.subTest(now=now):
                sample['observed_at_ms'] = now
                self.assertEqual(saved.source_diagnostic(sample)['stored_source_fresh'], fresh)


if __name__ == '__main__':
    unittest.main()
