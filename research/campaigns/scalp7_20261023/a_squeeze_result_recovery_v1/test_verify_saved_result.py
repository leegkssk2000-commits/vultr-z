"""Finite synthetic counterexamples only; no historical strategy replay."""
from copy import deepcopy
import unittest
import verify_saved_result as v


def sign(body):
    body['receipt_sha256'] = v.unsigned_digest(body)
    return body


def fixture():
    freeze = sign({'candidate_id': v.CANDIDATE, 'claim_id': v.OWNER,
                   'source_inventory_sha256': v.INVENTORY, 'context_fit_sha256': v.CONTEXT,
                   'saved_rejected_receipt': v.SAVED_S, 'keltner_result_receipt_sha256': v.ORDERED_K,
                   'candidate_comparisons_attempted': 1})
    rows = []
    for symbol, gross, offset in zip(('BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'LINK-USDT'),
                                     (-9, -4, 31, 6), (3, 3, 4, 5)):
        rows.append({'symbol': symbol, 'identity': v.CANDIDATE, 'partition': 'rolling',
                     'side': 1, 'timeframe_min': 30, 'signal_open_ts_ms': v.START - 1800000,
                     'signal_ts_ms': v.START, 'entry_ts_ms': v.START,
                     'exit_ts_ms': v.START + offset * 1800000,
                     'outcome_available_ts_ms': v.START + offset * 1800000,
                     'signal': {'meta': {'feature_available_ts_ms': v.START}},
                     'gross_bps': gross, 'cost_bps': 1, 'net_bps': gross - 1})
    # Hand-derived expected arithmetic, independent of measure().
    views = {}
    for multiplier, net, cost, pf, dd, worst in ((1, 20, 4, 35/15, 15, -10),
                                               (2, 16, 8, 33/17, 17, -11)):
        views[f'cost{multiplier}x'] = {'successor': {
            'T': 4, 'Gross_bps': 24, 'Cost_bps': cost, 'Net_bps': net,
            'Net_bps_per_T': net/4, 'Net_bps_per_day': net/245,
            'WR_pct': 50, 'PF': pf, 'MaxLossStreak': 2, 'DD_bps': dd,
            'DD_kind': 'REALIZED_SIMULTANEOUS_OUTCOME_COHORT_TRADE_BPS',
            'worst_trade_bps': worst, 'completed_subset_only': False},
            'vs_parent': {}, 'vs_saved_rejected': {}}
    report = {'candidate_id': v.CANDIDATE, 'input_freeze_sha256': v.unsigned_digest(freeze),
              'source_inventory_sha256': v.INVENTORY, 'saved_rejected_receipt': v.SAVED_S,
              'window': {'start_ms': v.START, 'end_exclusive_ms': v.END},
              'state': 'USED_DEV_MEASURED_AWAITING_SSOT_ADJUDICATION',
              'used_dev_only': True, 'fresh_or_oos': False, 'account_nav_or_mtm': False,
              'promotion': False, 'economic_runs': 1, 'old_candidate_replayed': False,
              'order_paper_live_deploy': 'BLOCKED', 'trade_rows': rows,
              'all_partition_trade_rows': deepcopy(rows), 'unresolved': [], 'boundary_excluded': [],
              'comparison_complete': True, 'views': views, 'accepted_entries': 4,
              'entries_per_calendar_day': 4/245,
              'decisions': [dict(symbol=r['symbol'], signal_ts_ms=r['signal_ts_ms'],
                                  signal_open_ts_ms=r['signal_open_ts_ms'], entry_ts_ms=r['entry_ts_ms'],
                                  partition='rolling', state='ACCEPTED') for r in rows]}
    return sign(report), freeze


class SyntheticArtifactTests(unittest.TestCase):
    def setUp(self):
        self.report, self.freeze = fixture()

    def rejected(self, fragment):
        sign(self.report)
        with self.assertRaisesRegex(ValueError, fragment):
            v.verify(self.report, self.freeze)

    def test_hand_calculated_costs_and_simultaneous_dd(self):
        result = v.verify(self.report, self.freeze)
        self.assertEqual(result['views']['cost1x']['DD_bps'], 15)
        self.assertEqual(result['views']['cost2x']['Net_bps'], 16)
        self.assertEqual(result['new_economic_runs'], 0)

    def test_hash_tampering(self):
        self.report['accepted_entries'] = 5
        with self.assertRaisesRegex(ValueError, 'RECEIPT_MISMATCH'):
            v.verify(self.report, self.freeze)

    def test_resigned_wrong_cost2_metric(self):
        self.report['views']['cost2x']['successor']['Net_bps'] = 20
        self.rejected('METRIC_MISMATCH:cost2x.Net_bps')

    def test_duplicate_trade(self):
        self.report['trade_rows'].append(deepcopy(self.report['trade_rows'][0]))
        self.rejected('DUPLICATE_TRADE_KEY')

    def test_future_feature(self):
        for key in ('trade_rows', 'all_partition_trade_rows'):
            self.report[key][0]['signal']['meta']['feature_available_ts_ms'] = v.START + 1
        self.rejected('FUTURE_FEATURE')

    def test_feature_after_signal_but_before_delayed_entry(self):
        for key in ('trade_rows', 'all_partition_trade_rows'):
            self.report[key][0]['entry_ts_ms'] = v.START + 100
            self.report[key][0]['signal']['meta']['feature_available_ts_ms'] = v.START + 1
        self.report['decisions'][0]['entry_ts_ms'] = v.START + 100
        self.rejected('FUTURE_FEATURE')

    def test_decision_entry_must_match_trade_entry(self):
        self.report['decisions'][0]['entry_ts_ms'] += v.DAY
        self.rejected('ACCEPTED_TRADE_ENTRY_MISMATCH|ACCEPTED_TRADE_ENTRY_CLOCK_MISMATCH')

    def test_exact_end_is_unavailable(self):
        for key in ('trade_rows', 'all_partition_trade_rows'):
            self.report[key][0]['outcome_available_ts_ms'] = v.END
        self.rejected('UNAVAILABLE_CLOCK_OR_BOUNDARY')

    def test_zero_cost(self):
        for key in ('trade_rows', 'all_partition_trade_rows'):
            self.report[key][0]['cost_bps'] = 0
        self.rejected('NONPOSITIVE_COST')

    def test_unresolved_cannot_claim_complete(self):
        self.report['unresolved'] = [{'fixture': True}]
        self.rejected('INCOMPLETE_COMPARISON_MISLABEL')

    def test_incomplete_comparison_cannot_claim_avoided_loss(self):
        self.report['unresolved'] = [{'fixture': True}]
        self.report['comparison_complete'] = False
        self.report['state'] = 'INCOMPLETE_NO_ADOPTION'
        for view in self.report['views'].values():
            view['successor']['completed_subset_only'] = True
        self.rejected('UNRESOLVED_TREATED_AS_AVOIDED_LOSS')

    def test_wrong_freeze_source(self):
        self.freeze['source_inventory_sha256'] = 'wrong'
        sign(self.freeze)
        self.report['input_freeze_sha256'] = v.unsigned_digest(self.freeze)
        self.rejected('WRONG_SOURCE')

    def test_old_overlay_is_not_successor(self):
        self.report['candidate_id'] = 'scalp7_squeeze_panic_plus_trend_disperse_utc30m_v1'
        self.rejected('WRONG_CANDIDATE')

    def test_trade_requires_accepted_event(self):
        self.report['decisions'].pop()
        self.rejected('TRADE_WITHOUT_ACCEPTANCE')


if __name__ == '__main__':
    unittest.main()
