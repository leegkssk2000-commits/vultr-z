import unittest
from copy import deepcopy

from backend.research.rebuild import squeeze_kr3_native_sleeve_row_seal_repair_v1 as repair


class RowSealRepairTests(unittest.TestCase):
    def test_closed_natural_row_resealed_after_sleeve_metadata(self):
        row = {
            'symbol': 'BTC-USDT', 'signal_index': 1, 'signal_ts': 10,
            'entry_ts': 20, 'entry_price': 100.0,
            'exit_ts': 30, 'exit_price': 101.0,
            'sleeve_role': repair.ROLE,
            'trade_sha256': 'stale',
        }
        fixed = repair.reseal_natural_row(row)
        self.assertNotEqual(fixed['trade_sha256'], 'stale')
        payload = deepcopy(fixed)
        got = payload.pop('trade_sha256')
        payload.pop('observation_sha256', None)
        self.assertEqual(got, repair.p.sha(payload))

    def test_open_natural_row_resealed_after_sleeve_metadata(self):
        row = {
            'symbol': 'ETH-USDT', 'signal_index': 2, 'signal_ts': 10,
            'entry_ts': 20, 'entry_price': 100.0,
            'mark_ts': 30, 'mark_price': 101.0,
            'status': 'CENSORED',
            'sleeve_role': repair.ROLE,
            'observation_sha256': 'stale',
        }
        fixed = repair.reseal_natural_row(row)
        self.assertNotEqual(fixed['observation_sha256'], 'stale')
        payload = deepcopy(fixed)
        got = payload.pop('observation_sha256')
        payload.pop('trade_sha256', None)
        self.assertEqual(got, repair.p.sha(payload))

    def test_persisted_rows_if_repair_receipt_exists(self):
        receipt = repair.OUT / 'ROW_SEAL_REPAIR.json'
        if not receipt.exists():
            self.skipTest('saved-only repair has not run yet')
        info = repair.read(receipt)
        counts = repair.verify_persisted(int(info['total_rows']))
        self.assertEqual(sum(counts.values()), 167)


if __name__ == '__main__':
    unittest.main()
