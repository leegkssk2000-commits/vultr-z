"""Pure preregistration/access guard; never reads market data or grants G5 PASS.

The root sole writer persists the returned allocation BEFORE any validation IO.
No defaults create a fresh budget: the inherited campaign allocation is required.
An explicit, externally authenticated approval receipt must be supplied by the
caller; its byte digest is pinned independently of this module's self seal.
"""
from copy import deepcopy
import hashlib
import json
import math

PURPOSE = 'ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
CANDIDATE = 'KELTNER_KR3_PRIOR_SUPPRESSED_BREACH_EXTENSION_VETO_DEV_V1'
REPORTS = ('base_replay', 'realistic_cost', 'cost2x', 'purged_oos',
           'chronological_split', 'symbol_decomposition', 'regime_decomposition',
           'parameter_neighbor_stability', 'negative_controls')
IDENTITY = ('candidate_id', 'code_sha', 'config_sha', 'entry_sha', 'exit_sha',
            'cost_sha', 'source_definition_sha', 'candidate_contract_sha')


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def seal(value):
    out = deepcopy(value)
    out['receipt_sha256'] = sha(out)
    return out


def verified(value):
    if not isinstance(value, dict) or value.get('receipt_sha256') != sha({
            k: v for k, v in value.items() if k != 'receipt_sha256'}):
        raise ValueError('RECEIPT_HASH')
    return value


def allocation(campaign):
    if campaign.get('logical_purpose') != PURPOSE:
        raise ValueError('CAMPAIGN_IDENTITY')
    a = campaign.get('independent_validation')
    if not isinstance(a, dict) or set(a) != {
            'max_bundles', 'used', 'reservations', 'exposed_data_shas'}:
        raise ValueError('INHERITED_BUDGET_REQUIRED')
    if a['max_bundles'] != 1 or type(a['used']) is not int or a['used'] not in (0, 1):
        raise ValueError('INDEPENDENT_BUDGET')
    if not isinstance(a['reservations'], list) or len(a['reservations']) != a['used']:
        raise ValueError('RESERVATION_PARITY')
    if not isinstance(a['exposed_data_shas'], list):
        raise ValueError('EXPOSURE_HISTORY_REQUIRED')
    return a


def preregister(identity, design, roles, campaign, authority, *,
                authenticated_authority_sha, registered_ms):
    """Require actual approval, role split and complete pre-outcome definition."""
    allocation(campaign)
    if set(identity) != set(IDENTITY) or any(not identity[k] for k in IDENTITY):
        raise ValueError('EXACT_IDENTITY_REQUIRED')
    if identity['candidate_id'] != CANDIDATE:
        raise ValueError('SELECTED_CANDIDATE_ONLY')
    verified(authority)
    if sha(authority) != authenticated_authority_sha or authority.get('principal') != 'USER':
        raise ValueError('EXTERNAL_AUTHORITY_REQUIRED')
    if authority.get('status') != 'APPROVED' or authority.get('design_sha') != sha(design):
        raise ValueError('PENDING_AUTHORITY')
    if authority.get('identity_sha') != sha(identity) or authority.get('campaign') != PURPOSE:
        raise ValueError('AUTHORITY_IDENTITY')
    developers = roles.get('developers')
    validator = roles.get('validator')
    if not isinstance(developers, list) or not developers or not validator or validator in developers:
        raise ValueError('ROLE_SEPARATION_REQUIRED')
    if roles.get('validator_may_propose_hypotheses') is not False or roles.get('ai_holdout_access') is not False:
        raise ValueError('INFORMATION_BOUNDARY_REQUIRED')
    if design.get('status') != 'APPROVED' or design.get('candidate_count') != 1 or design.get('bundle_count') != 1:
        raise ValueError('ONE_FROZEN_BUNDLE')
    if design.get('reports') != list(REPORTS):
        raise ValueError('NINE_REPORTS_REQUIRED')
    windows = design.get('windows')
    if not isinstance(windows, list) or len(windows) != 3:
        raise ValueError('W1_W2_W3_REQUIRED')
    for index, window in enumerate(windows):
        if (window.get('name') != 'W'+str(index+1) or
                type(window.get('start_ms')) is not int or type(window.get('end_ms')) is not int or
                window['start_ms'] >= window['end_ms'] or
                (index and window['start_ms'] != windows[index-1]['end_ms'])):
            raise ValueError('WINDOW_DEFINITION')
    if design.get('source_class') not in ('HOLDOUT_SEALED', 'FORWARD_UNCOLLECTED'):
        raise ValueError('DEV_CANNOT_BE_OOS')
    if design['source_class'] == 'HOLDOUT_SEALED' and design.get('unused_history_verified') is not True:
        raise ValueError('UNUSED_HISTORY_UNVERIFIED_USE_PROSPECTIVE')
    if design['source_class'] == 'FORWARD_UNCOLLECTED' and windows[0]['start_ms'] < registered_ms:
        raise ValueError('NO_RETROSPECTIVE_FORMAL_BOUNDARY')
    if (type(design.get('review_ms')) is not int or
            design['review_ms'] < windows[-1]['end_ms'] or design.get('terminal_looks') != 1):
        raise ValueError('FIXED_REVIEW_REQUIRED')
    for name in ('purge_rule_sha', 'runoff_rule_sha', 'regime_rule_sha', 'control_rule_sha',
                 'neighbor_rule_sha', 'statistics_rule_sha', 'source_authority_sha',
                 'retention_baseline_sha', 'shared_gate_sha'):
        if not design.get(name):
            raise ValueError('DESIGN_RULE_REQUIRED:'+name)
    return seal({'schema_version': 'zel.step7.independent_preregistration.v1',
                 'logical_purpose': PURPOSE, 'identity': identity, 'design': design,
                 'roles': roles, 'registered_ms': registered_ms,
                 'authority_sha': authenticated_authority_sha,
                 'inherited_campaign_sha': sha(campaign), 'state': 'PREREGISTERED_NOT_EXECUTED',
                 'formal_credit': 0, 'order_authority': 'BLOCKED'})


def reserve_access(plan, campaign, source, *, actor, now_ms):
    """Return next immutable state/ticket; caller durably commits before data IO."""
    verified(plan)
    a = allocation(campaign)
    if a['used'] != 0:
        raise ValueError('BUNDLE_ALREADY_USED_NO_RETRY_OR_NEW_CANDIDATE')
    if sha(campaign) != plan['inherited_campaign_sha']:
        raise ValueError('CAMPAIGN_CHANGED_RECONCILE_NO_RESET')
    if actor != plan['roles']['validator'] or actor in plan['roles']['developers']:
        raise ValueError('VALIDATOR_ONLY')
    if now_ms < plan['design']['review_ms']:
        raise ValueError('INTERIM_ACCESS_FORBIDDEN')
    verified(source)
    if (source.get('source_definition_sha') != plan['identity']['source_definition_sha'] or
            source.get('cost_sha') != plan['identity']['cost_sha'] or not source.get('data_sha')):
        raise ValueError('SOURCE_IDENTITY')
    # G5A prospective validation is sealed evidence, never a G5B cohort.
    expected_class = 'HOLDOUT_SEALED'
    if source.get('classification') != expected_class or source.get('unused_history_verified') is not True:
        raise ValueError('SOURCE_NOT_INDEPENDENT')
    if source['data_sha'] in a['exposed_data_shas'] or source.get('prior_performance_exposures') != 0:
        raise ValueError('SOURCE_ALREADY_EXPOSED')
    if source.get('windows') != plan['design']['windows'] or source.get('complete') is not True:
        raise ValueError('SOURCE_WINDOWS_INCOMPLETE')
    next_campaign = deepcopy(campaign)
    ticket = seal({'preregistration_sha': plan['receipt_sha256'], 'candidate_id': CANDIDATE,
                   'data_sha': source['data_sha'], 'source_receipt_sha': source['receipt_sha256'],
                   'actor': actor, 'reserved_ms': now_ms, 'attempt': 1,
                   'state': 'RESERVED_BEFORE_IO', 'economic_pass': False, 'formal_credit': 0})
    b = next_campaign['independent_validation']
    b['used'] = 1
    b['reservations'].append(ticket)
    b['exposed_data_shas'].append(source['data_sha'])
    return next_campaign, ticket


def power_sample_count(sigma_bps, delta_bps, alpha_per_claim, beta):
    """Design arithmetic only; caller supplies APPROVED parameters, never authority."""
    from statistics import NormalDist
    values = (sigma_bps, delta_bps, alpha_per_claim, beta)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError('FINITE_NUMERIC_PARAMETERS')
    if sigma_bps <= 0 or delta_bps <= 0 or not 0 < alpha_per_claim < .5 or not 0 < beta < .5:
        raise ValueError('POWER_PARAMETER_RANGE')
    z = NormalDist().inv_cdf(1-alpha_per_claim) + NormalDist().inv_cdf(1-beta)
    return math.ceil((z*sigma_bps/delta_bps)**2)


def produce_ledger_diagnostics(ledger, specification):
    """Compute actual split/purge/cost diagnostics from supplied sealed rows.

    This pure producer performs no input loading, candidate replay or source
    attestation. The caller must reserve independent access before supplying real
    sealed rows. Synthetic output cannot satisfy any formal economic report.
    Final PnL after a declared run-off deadline is never included in metrics.
    """
    from backend.research.architecture_factory import g5a_development_probe_v1 as metrics
    verified(ledger)
    verified(specification)
    if ledger.get('candidate_id') != CANDIDATE or ledger.get('identity_sha') != specification.get('identity_sha'):
        raise ValueError('LEDGER_CANDIDATE_IDENTITY')
    if not ledger.get('data_sha') or not ledger.get('cost_sha') or ledger.get('cost_sha') != specification.get('cost_sha'):
        raise ValueError('LEDGER_DATA_COST_IDENTITY')
    windows = specification.get('windows')
    if not isinstance(windows, list) or len(windows) != 3:
        raise ValueError('W1_W2_W3_REQUIRED')
    for index, window in enumerate(windows):
        if (window.get('name') != 'W'+str(index+1) or
                type(window.get('start_ms')) is not int or type(window.get('end_ms')) is not int or
                window['start_ms'] >= window['end_ms'] or
                (index and window['start_ms'] != windows[index-1]['end_ms'])):
            raise ValueError('WINDOW_DEFINITION')
    embargo = specification.get('embargo_ms')
    deadline = specification.get('runoff_deadline_ms')
    if type(embargo) is not int or embargo < 0 or type(deadline) is not int or deadline < windows[-1]['end_ms']:
        raise ValueError('EXPLICIT_EMBARGO_RUNOFF_REQUIRED')
    trades, opens = ledger.get('trades'), ledger.get('open_positions')
    training = specification.get('training_intervals')
    if not isinstance(trades, list) or not isinstance(opens, list) or not isinstance(training, list):
        raise ValueError('EXPLICIT_LEDGER_PARTITIONS_REQUIRED')
    origins = []
    for row in trades + opens:
        for key in ('origin_id', 'symbol', 'signal_ts', 'entry_ts'):
            if key not in row:
                raise ValueError('LEDGER_ROW_REQUIRED:'+key)
        if row['entry_ts'] < row['signal_ts']:
            raise ValueError('ENTRY_BEFORE_SIGNAL')
        origins.append(row['origin_id'])
    if len(origins) != len(set(origins)):
        raise ValueError('DUPLICATE_ORIGIN')
    for row in trades:
        if (row.get('exit_ts', -1) < row['entry_ts'] or
                row.get('hold_ms') != row['exit_ts']-row['entry_ts']):
            raise ValueError('CLOSED_INTERVAL_INVALID')
        for key in ('net_bps', 'gross_bps', 'cost2x_net_bps', 'cost_bps'):
            if type(row.get(key)) not in (float, int) or not math.isfinite(row[key]):
                raise ValueError('FINITE_COSTED_LEDGER_REQUIRED:'+key)
        if not math.isclose(row['net_bps'], row['gross_bps']-row['cost_bps'], abs_tol=1e-8):
            raise ValueError('COST_ARITHMETIC_MISMATCH')
        if not math.isclose(row['cost2x_net_bps'], row['gross_bps']-2*row['cost_bps'], abs_tol=1e-8):
            raise ValueError('COST2_ARITHMETIC_MISMATCH')
    def end_of(row):
        # None reference end explicitly means unresolved, never zero duration.
        if 'reference_end_ts' in row and row['reference_end_ts'] is None:
            return float('inf')
        end = row.get('exit_ts')
        if end is None:
            return float('inf')
        return max(end, row.get('reference_end_ts', end))
    def summary(rows, start, end):
        symbols = {r['symbol'] for r in rows}
        kw = dict(start_ms=start, end_ms=end, symbol_count=max(1, len(symbols)))
        return {'base_cost': metrics.summarize(rows, **kw),
                'cost2x': metrics.summarize(rows, cost2x=True, **kw),
                'cost_bps': sum(r['cost_bps'] for r in rows)}
    output = []
    for window in windows:
        start, end = window['start_ms'], window['end_ms']
        selected = [r for r in trades + opens if start <= r['signal_ts'] < end]
        selected_closed = [r for r in selected if r in trades and r['exit_ts'] <= deadline]
        unresolved = [r for r in selected if r not in selected_closed]
        interval_end = max([end] + [r['exit_ts'] for r in selected_closed])
        purged, retained = [], []
        for row in training:
            if not all(key in row for key in ('origin_id', 'entry_ts', 'exit_ts')):
                raise ValueError('TRAIN_LABEL_INTERVAL_REQUIRED')
            right = end_of(row)
            reasons = []
            if row['entry_ts'] >= start:
                reasons.append('NONCHRONOLOGICAL_TRAIN_LABEL')
            if right == float('inf'):
                reasons.append('UNRESOLVED_TRAIN_LABEL')
            if any(row['entry_ts'] <= end_of(e) and e['entry_ts'] <= right for e in selected):
                reasons.append('LABEL_OR_RESERVATION_OVERLAP')
            if row['entry_ts'] < start and right + embargo >= start:
                reasons.append('ACTUAL_LABEL_END_PLUS_EMBARGO')
            if reasons:
                purged.append({'origin_id': row['origin_id'], 'reasons': reasons})
            else:
                retained.append(row['origin_id'])
        by_symbol = {symbol: summary([r for r in selected_closed if r['symbol'] == symbol], start, interval_end)
                     for symbol in sorted({r['symbol'] for r in selected})}
        regimes = sorted({r.get('regime_id') or 'UNKNOWN' for r in selected})
        by_regime = {regime: summary([r for r in selected_closed if (r.get('regime_id') or 'UNKNOWN') == regime], start, interval_end)
                     for regime in regimes}
        output.append({'window': window, 'closed_metrics': summary(selected_closed, start, interval_end),
                       'by_symbol': by_symbol, 'by_regime': by_regime,
                       'training_retained': retained, 'training_purged': purged,
                       'censored_open': len(unresolved),
                       'open_or_late_origins': [r['origin_id'] for r in unresolved],
                       'unresolved_not_zero_return_trades': True,
                       'mark_valuation': 'NOT_RECONSTRUCTED_FROM_CLOSED_OR_FUTURE_ROWS',
                       'missing_regime_origins': [r['origin_id'] for r in selected if not r.get('regime_id')],
                       'runoff_used_closed_origins': [r['origin_id'] for r in selected_closed if r['exit_ts'] >= end]})
    return seal({'schema_version': 'zel.step7.derived_ledger_reports.v1',
                 'candidate_id': CANDIDATE, 'identity_sha': ledger['identity_sha'],
                 'data_sha': ledger['data_sha'], 'cost_sha': ledger['cost_sha'],
                 'input_ledger_sha': ledger['receipt_sha256'], 'specification_sha': specification['receipt_sha256'],
                 'evidence_kind': ledger.get('evidence_kind', 'UNATTESTED_SUPPLIED_LEDGER'),
                 'computed_reports': ['realistic_cost', 'cost2x', 'chronological_split', 'symbol_decomposition', 'regime_decomposition'],
                 'purged_oos': 'INTERVAL_SELECTION_COMPUTED; INDEPENDENT_REPLAY_AND_PASS_NOT_ATTESTED',
                 'not_produced': ['base_replay', 'negative_controls', 'parameter_neighbor_stability'],
                 'windows': output, 'computed': True, 'complete': False,
                 'formal_credit': 0, 'economic_pass': False,
                 'meaning': 'DERIVED_LEDGER_DIAGNOSTICS_NOT_REPLAY_SOURCE_OR_G5_PROOF'})
