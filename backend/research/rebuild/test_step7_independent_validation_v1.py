import unittest
from copy import deepcopy
from backend.research.rebuild import step7_independent_validation_v1 as v


class IndependentValidationGuard(unittest.TestCase):
    def setUp(self):
        self.campaign = {'logical_purpose': v.PURPOSE, 'old_candidates': 44,
                         'api_used_usd': 0, 'independent_validation': {
                             'max_bundles': 1, 'used': 0, 'reservations': [], 'exposed_data_shas': []}}
        self.identity = {name: 'a'*64 for name in v.IDENTITY}
        self.identity['candidate_id'] = v.CANDIDATE
        self.roles = {'developers': ['root', 'S2'], 'validator': 'S4',
                      'validator_may_propose_hypotheses': False, 'ai_holdout_access': False}
        self.design = {'status': 'APPROVED', 'candidate_count': 1, 'bundle_count': 1,
                       'reports': list(v.REPORTS), 'source_class': 'FORWARD_UNCOLLECTED',
                       'windows': [{'name': 'W'+str(i+1), 'start_ms': 100+i*100,
                                    'end_ms': 200+i*100} for i in range(3)],
                       'review_ms': 500, 'terminal_looks': 1}
        for key in ('purge_rule_sha', 'runoff_rule_sha', 'regime_rule_sha', 'control_rule_sha',
                    'neighbor_rule_sha', 'statistics_rule_sha', 'source_authority_sha',
                    'retention_baseline_sha', 'shared_gate_sha'):
            self.design[key] = 'b'*64

    def plan(self, **kwargs):
        authority = v.seal({'principal': 'USER', 'status': 'APPROVED',
                            'design_sha': v.sha(self.design), 'identity_sha': v.sha(self.identity),
                            'campaign': v.PURPOSE})
        return v.preregister(self.identity, self.design, self.roles, self.campaign, authority,
                             authenticated_authority_sha=kwargs.get('auth_sha', v.sha(authority)),
                             registered_ms=100)

    def source(self, **kwargs):
        return v.seal({'source_definition_sha': 'a'*64, 'cost_sha': 'a'*64, 'data_sha': 'd'*64,
                       'classification': 'HOLDOUT_SEALED', 'unused_history_verified': True,
                       'prior_performance_exposures': 0, 'windows': self.design['windows'],
                       'complete': True, **kwargs})

    def test_only_one_access_preserves_prior_budgets(self):
        plan = self.plan()
        result, ticket = v.reserve_access(plan, self.campaign, self.source(), actor='S4', now_ms=500)
        self.assertEqual(result['old_candidates'], 44)
        self.assertEqual(result['api_used_usd'], 0)
        self.assertEqual(self.campaign['independent_validation']['used'], 0)
        self.assertFalse(ticket['economic_pass'])
        with self.assertRaisesRegex(ValueError, 'ALREADY_USED'):
            v.reserve_access(plan, result, self.source(), actor='S4', now_ms=501)

    def test_cannot_create_fresh_budget(self):
        del self.campaign['independent_validation']
        with self.assertRaisesRegex(ValueError, 'INHERITED_BUDGET'):
            self.plan()

    def test_no_developer_or_interim_access(self):
        plan = self.plan()
        for actor, now, error in [('root', 500, 'VALIDATOR_ONLY'), ('S4', 499, 'INTERIM')]:
            with self.assertRaisesRegex(ValueError, error):
                v.reserve_access(plan, self.campaign, self.source(), actor=actor, now_ms=now)

    def test_scope_rename_cannot_renew(self):
        self.campaign['logical_purpose'] += '_V2'
        with self.assertRaisesRegex(ValueError, 'CAMPAIGN_IDENTITY'):
            self.plan()

    def test_authority_must_be_external_and_exact(self):
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_AUTHORITY'):
            self.plan(auth_sha='fake')
        self.design['status'] = 'PENDING_AUTHORITY'
        with self.assertRaisesRegex(ValueError, 'ONE_FROZEN_BUNDLE'):
            self.plan()

    def test_no_lookahead_or_renamed_used_source(self):
        plan = self.plan()
        for changes in ({'classification': 'DEV_USED'}, {'prior_performance_exposures': 1},
                        {'unused_history_verified': False}, {'complete': False}):
            with self.assertRaises(ValueError):
                v.reserve_access(plan, self.campaign, self.source(**changes), actor='S4', now_ms=500)

    def test_receipt_and_campaign_drift_fail(self):
        plan = self.plan()
        source = self.source(); source['data_sha'] = 'tampered'
        with self.assertRaisesRegex(ValueError, 'RECEIPT_HASH'):
            v.reserve_access(plan, self.campaign, source, actor='S4', now_ms=500)
        campaign = deepcopy(self.campaign); campaign['old_candidates'] += 1
        with self.assertRaisesRegex(ValueError, 'CAMPAIGN_CHANGED'):
            v.reserve_access(plan, campaign, self.source(), actor='S4', now_ms=500)

    def test_exact_candidate_and_nine_reports(self):
        self.identity['candidate_id'] = 'Q0'
        with self.assertRaisesRegex(ValueError, 'SELECTED_CANDIDATE'):
            self.plan()
        self.identity['candidate_id'] = v.CANDIDATE
        self.design['reports'].pop()
        with self.assertRaisesRegex(ValueError, 'NINE_REPORTS'):
            self.plan()

    def test_no_retrospective_or_unverified_holdout(self):
        self.design['windows'][0]['start_ms'] = 99
        with self.assertRaisesRegex(ValueError, 'RETROSPECTIVE'):
            self.plan()
        self.design['source_class'] = 'HOLDOUT_SEALED'
        with self.assertRaisesRegex(ValueError, 'UNUSED_HISTORY'):
            self.plan()

    def test_role_split_and_frozen_rule_requirement(self):
        self.roles['validator'] = 'root'
        with self.assertRaisesRegex(ValueError, 'ROLE_SEPARATION'):
            self.plan()
        self.roles['validator'] = 'S4'
        del self.design['control_rule_sha']
        with self.assertRaisesRegex(ValueError, 'DESIGN_RULE_REQUIRED'):
            self.plan()

    def test_power_is_arithmetic_not_approval(self):
        n = v.power_sample_count(100, 5, .05/7, .2)
        self.assertGreater(n, 100)
        for args in [(0, 5, .01, .2), (100, 0, .01, .2), (100, 5, float('nan'), .2)]:
            with self.assertRaises(ValueError):
                v.power_sample_count(*args)


def ledger_fixture():
    def closed(origin, signal, entry, exit_, gross, cost, symbol='BTC', regime='UP'):
        return {'origin_id': origin, 'signal_ts': signal, 'entry_ts': entry,
                'exit_ts': exit_, 'hold_ms': exit_-entry, 'symbol': symbol,
                'gross_bps': gross, 'cost_bps': cost, 'net_bps': gross-cost,
                'cost2x_net_bps': gross-2*cost, 'regime_id': regime}
    ledger = {'candidate_id': v.CANDIDATE, 'identity_sha': 'i'*64, 'data_sha': 'd'*64,
              'cost_sha': 'c'*64, 'evidence_kind': 'SYNTHETIC_ONLY',
              'trades': [closed('win', 110, 111, 190, 12, 2),
                         closed('loss', 210, 211, 310, -5, 2, 'ETH', 'DOWN'),
                         closed('late', 320, 321, 700, 999, 1)],
              'open_positions': [{'origin_id': 'open', 'symbol': 'BTC', 'signal_ts': 350,
                                  'entry_ts': 351, 'mark_ts': 400, 'regime_id': 'UP'}]}
    spec = {'identity_sha': 'i'*64, 'cost_sha': 'c'*64, 'embargo_ms': 10,
            'runoff_deadline_ms': 500, 'windows': [
                {'name': 'W'+str(i+1), 'start_ms': 100+i*100, 'end_ms': 200+i*100}
                for i in range(3)], 'training_intervals': [
                    {'origin_id': 'safe', 'entry_ts': 1, 'exit_ts': 50},
                    {'origin_id': 'embargo', 'entry_ts': 60, 'exit_ts': 95},
                    {'origin_id': 'gap', 'entry_ts': 60, 'exit_ts': 150},
                    {'origin_id': 'unresolved', 'entry_ts': 60, 'exit_ts': None},
                    {'origin_id': 'reference', 'entry_ts': 60, 'exit_ts': 70, 'reference_end_ts': 180}]}
    return v.seal(ledger), v.seal(spec)


class LedgerProducerTests(unittest.TestCase):
    def test_resealed_cost2_omission_or_double_charge_rejected(self):
        ledger, spec = ledger_fixture()
        for wrong_cost2 in (12, 4):
            changed = {k: deepcopy(value) for k, value in ledger.items() if k != 'receipt_sha256'}
            changed['trades'][0]['cost2x_net_bps'] = wrong_cost2
            with self.assertRaisesRegex(ValueError, 'COST2_ARITHMETIC_MISMATCH'):
                v.produce_ledger_diagnostics(v.seal(changed), spec)

    def test_real_derived_metrics_reuse_cost_owner(self):
        ledger, spec = ledger_fixture()
        result = v.produce_ledger_diagnostics(ledger, spec)
        self.assertEqual(result['windows'][0]['closed_metrics']['base_cost']['net_bps'], 10)
        self.assertEqual(result['windows'][0]['closed_metrics']['cost2x']['net_bps'], 8)
        self.assertEqual(result['windows'][1]['by_symbol']['ETH']['base_cost']['net_bps'], -7)
        self.assertEqual(result['windows'][1]['by_regime']['DOWN']['cost2x']['net_bps'], -9)
        self.assertFalse(result['complete'])
        self.assertEqual(result['formal_credit'], 0)

    def test_overlap_embargo_gap_and_reference_purge(self):
        ledger, spec = ledger_fixture()
        window = v.produce_ledger_diagnostics(ledger, spec)['windows'][0]
        self.assertEqual(window['training_retained'], ['safe'])
        reasons = {r['origin_id']: r['reasons'] for r in window['training_purged']}
        self.assertIn('ACTUAL_LABEL_END_PLUS_EMBARGO', reasons['embargo'])
        self.assertIn('LABEL_OR_RESERVATION_OVERLAP', reasons['gap'])
        self.assertIn('LABEL_OR_RESERVATION_OVERLAP', reasons['reference'])
        self.assertIn('UNRESOLVED_TRAIN_LABEL', reasons['unresolved'])

    def test_runoff_does_not_fake_close_or_use_late_profit(self):
        ledger, spec = ledger_fixture()
        windows = v.produce_ledger_diagnostics(ledger, spec)['windows']
        self.assertEqual(windows[1]['runoff_used_closed_origins'], ['loss'])
        self.assertEqual(windows[2]['closed_metrics']['base_cost']['completed_T'], 0)
        self.assertEqual(windows[2]['censored_open'], 2)
        self.assertEqual(windows[2]['open_or_late_origins'], ['late', 'open'])

    def test_cost_duplicate_and_identity_mismatch_fail(self):
        ledger, spec = ledger_fixture()
        for mutation, expected in [
            (lambda x: x['trades'][0].update(net_bps=777), 'COST_ARITHMETIC'),
            (lambda x: x['trades'].append(deepcopy(x['trades'][0])), 'DUPLICATE_ORIGIN'),
            (lambda x: x.update(identity_sha='wrong'), 'LEDGER_CANDIDATE')]:
            changed = {k: deepcopy(val) for k, val in ledger.items() if k != 'receipt_sha256'}
            mutation(changed)
            with self.assertRaisesRegex(ValueError, expected):
                v.produce_ledger_diagnostics(v.seal(changed), spec)


if __name__ == '__main__':
    unittest.main()
