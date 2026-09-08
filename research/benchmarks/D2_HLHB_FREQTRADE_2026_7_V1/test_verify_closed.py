"""Tamper checks using stored ledgers or tiny synthetic bytes. No replay."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import verify_closed as v

HERE = Path(__file__).resolve().parent


class ClosureTests(unittest.TestCase):
    def record(self):
        return json.loads(gzip.decompress((HERE/'results/D2_DEV2025/RESULT.json.gz').read_bytes()))

    def test_saved_valid_ledger_arithmetic(self):
        v.validate_record(self.record())

    def test_winner_count_tamper_rejected(self):
        r = self.record(); r['metrics']['wins'] += 1
        with self.assertRaisesRegex(ValueError, 'LEDGER_COUNTS'):
            v.validate_record(r)

    def test_cost_double_charge_rejected(self):
        r = self.record(); r['normalized_trades'][0]['cost_bps'] += 1
        with self.assertRaisesRegex(ValueError, 'NET_COST'):
            v.validate_record(r)

    def test_paired_file_and_manifest_change_rejected_by_external_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'result').write_bytes(b'original')
            original = json.dumps({'files': {'result': v.sha(b'original')}}).encode()
            v.validate_manifest(root, original, v.sha(original))
            (root/'result').write_bytes(b'changed')
            forged = json.dumps({'files': {'result': v.sha(b'changed')}}).encode()
            with self.assertRaisesRegex(ValueError, 'EXTERNAL_MANIFEST_HASH'):
                v.validate_manifest(root, forged, v.sha(original))

    def test_prior_history_edit_rejected(self):
        old = json.loads((HERE/'INHERITED_BUDGET_PR1219.json').read_bytes())
        new = json.loads((HERE/'BUDGET.json').read_bytes())
        v.validate_budget(old, new)
        new['trials'][0]['retry_allowed'] = True
        with self.assertRaisesRegex(ValueError, 'INHERITED_BUDGET_MUTATION'):
            v.validate_budget(old, new)


if __name__ == '__main__':
    unittest.main()
