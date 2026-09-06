"""One frozen Keltner N occupancy repair; virtual reference never earns PnL."""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path

from backend.research.rebuild import keltner_cumulative_entry_v1 as prior
from backend.research.rebuild import keltner_opportunity_reservation_adapter_v1 as adapter
from backend.research.rebuild import keltner_opportunity_reservation_metrics_v1 as metrics
from backend.research.rebuild import keltner_opportunity_reservation_diagnosis_v1 as diagnosis

old, ROOT = prior.old, prior.ROOT
OUTPUT = 'research/development_evidence/KELTNER_OPPORTUNITY_RESERVATION_20260906_V1'
SPEC, DESIGN = OUTPUT + '/SPEC.json', OUTPUT + '/DESIGN.md'
AUTHORIZATION = 'EXPLICIT_USER_ONE_CAUSAL_D_OPPORTUNITY_RESERVATION_AFTER_PR1197'
CANDIDATE = 'KELTNER_D_CAUSAL_OPPORTUNITY_RESERVATION_DEV_V1'
PRIOR_SEAL = '864843a20c40d76a10a536192f09e89ff081cc589aa0671579f1fd92d2de19b7'
CODE = ['backend/research/rebuild/' + prefix + name + '_v1.py'
        for name in ('keltner_opportunity_reservation', 'keltner_opportunity_reservation_adapter',
                     'keltner_opportunity_reservation_metrics', 'keltner_opportunity_reservation_diagnosis')
        for prefix in ('', 'test_')]
AUTH = {**prior.AUTH, 'comparison_type': 'ENTRY_FILTER', 'change_axis': 'CAUSAL_D_OPPORTUNITY_RESERVATION'}
RULE = {'parent': 'PR1197_N_UNADOPTED', 'entry_predicate': prior.RULE['expression'],
        'entry_exit_fill_cost': 'UNCHANGED_N_D_NEXT_OPEN_TREND_INVALIDATION_MAX12',
        'reference': 'PER_SYMBOL_ORIGINAL_D_SIGNAL_AND_OCCUPANCY_CLOCK',
        'reserve': 'ON_EACH_CAUSALLY_ELIGIBLE_D_SIGNAL_INCLUDING_N_VETO',
        'release': 'BAR_BY_BAR_D_TIMEOUT_CLOSE_OR_CONFIRMED_EMA_INVALIDATION_NEXT_OPEN',
        'exit_bar_ownership': 'SIGNAL_INDEX_LE_EXIT_INDEX_BLOCKED',
        'virtual_economics': 'NONE_NO_QUANTITY_COST_FUNDING_PNL_OR_EXPOSURE',
        'historical_ids_exit_times_or_outcomes_as_execution_inputs': False,
        'batch_D_paths': 'AFTER_CAUSAL_ADMISSIONS_FOR_UNCHANGED_FILL_ACCOUNTING_ONLY',
        'new_indicators_parameters_or_candidates': False,
        'reproduction_consumes_new_candidate': False}


def load_stored():
    nc = prior.authorize()
    nr = old.read(prior.OUTPUT + '/receipt.json'); old.probe.verify_seal(nr, 'PR1197')
    if nr['receipt_sha256'] != PRIOR_SEAL or nr['candidate_cumulative_after'] != 29:
        raise RuntimeError('RESERVATION_PRIOR_RESULT_OR_COUNT')
    documents = {}
    for period in nc['calendars']:
        ref = nr['artifacts'][period]
        if old.file_sha(ROOT / ref['path']) != ref['file_sha256']:
            raise RuntimeError('RESERVATION_PRIOR_LEDGER_BYTES')
        documents[period] = json.loads(gzip.decompress((ROOT / ref['path']).read_bytes()))
    dc, old_documents = prior.load_stored()
    return nc, dc, documents, old_documents


def authorize():
    c = old.read(SPEC); old.probe.verify_seal(c, 'RESERVATION_SPEC')
    if (c['authorization'] != AUTHORIZATION or c['candidate_id'] != CANDIDATE
            or c['candidate_cumulative_before'] != 29 or c['allocated_new_candidates'] != 1
            or c['rule'] != RULE or c['goal'] != metrics.GOAL
            or c['new_M_replay_completed_at_freeze'] is not False
            or c['expected_common_D_result_previously_seen'] is not True):
        raise RuntimeError('RESERVATION_RULE_GOAL_ALLOCATION')
    for k, v in AUTH.items():
        if c.get(k) != v:
            raise RuntimeError('RESERVATION_AUTHORITY:' + k)
    if set(c['code_files_sha256']) != set(CODE):
        raise RuntimeError('RESERVATION_CODE_COVERAGE')
    for path, sha in {**c['preserved_files_sha256'], **c['code_files_sha256'], **c['ci_files_sha256']}.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('RESERVATION_FROZEN_BYTES:' + path)
    if old.file_sha(ROOT / DESIGN) != c['design_sha256']:
        raise RuntimeError('RESERVATION_DESIGN_BYTES')
    nc = prior.authorize()
    for key in ('data_sha256', 'cost_sha256', 'period_data_sha256', 'calendars', 'symbols'):
        if c[key] != nc[key]:
            raise RuntimeError('RESERVATION_INPUT_AUTHORITY:' + key)
    return c


def artifact(name, value, verify_only=False):
    path = ROOT / OUTPUT / name; canonical = old.probe.canonical(value)
    payload = path.read_bytes() if path.exists() else gzip.compress(canonical, mtime=0)
    if gzip.decompress(payload) != canonical:
        raise RuntimeError('RESERVATION_IMMUTABLE_DRIFT:' + name)
    old.probe.write_immutable(path, payload, verify_only=verify_only)
    return {'path': str(path.relative_to(ROOT)), 'file_sha256': old.file_sha(path)}


def charge(raw, symbol, policy, costs, rows):
    result = prior.charge(raw, symbol, 'M_FULL', policy, costs, rows)
    for key, seal in (('trades', 'trade_sha256'), ('open_observations', 'observation_sha256')):
        for t in result[key]:
            t.pop(seal, None)
            t.update(candidate_id=CANDIDATE, evidence_type='REUSED_DEV_CAUSAL_RESERVATION',
                     base_entry='PR1197_N_UNCHANGED', virtual_reference=False)
            t[seal] = old.digest(t)
    # Reference events are diagnostic clocks only, never passed to cost/PnL.
    result['reference_events'] = [dict(e, symbol=symbol) for e in raw.get('reference_events', [])]
    result['reference_opportunities'] = [dict(e, symbol=symbol) for e in raw.get('reference_opportunities', [])]
    result['reference_state'] = raw.get('reference_checkpoint')
    return result


def replay(rows_by, bundles, costs, policy, start, end, enabled=True):
    result = {k: [] for k in ('trades', 'open_observations', 'events', 'trace', 'reference_events', 'reference_opportunities')}
    result.update(admission={}, reference_states={})
    for symbol, rows in sorted(rows_by.items()):
        raw = adapter.replay(rows, bundles[symbol], eval_start_ms=start, eval_end_ms=end, enabled=enabled)
        value = charge(raw, symbol, policy, costs, rows)
        for k in ('trades', 'open_observations', 'events', 'trace', 'reference_events', 'reference_opportunities'):
            result[k].extend(value[k])
        result['admission'][symbol] = value['audit']
        result['reference_states'][symbol] = value['reference_state']
    return result


def comparison_only_common_parity(actual, expected):
    """Post-replay regression only; this never returns executable admissions."""
    fields = ('signal_index', 'entry_ts', 'entry_price', 'hold_ms')
    differences = []
    for key, extra in (('trades', ('exit_ts', 'exit_price', 'gross_bps', 'net_bps', 'cost_bps', 'funding_bps', 'cost2x_net_bps')),
                       ('open_observations', ('mark_ts', 'mark_price', 'gross_mark_bps', 'hypothetical_liquidation_net_mark_bps',
                                              'hypothetical_liquidation_cost_bps'))):
        aa, bb = ({t['origin_key']: t for t in v[key]} for v in (actual, expected))
        if set(aa) != set(bb):
            differences.append({'kind': key, 'missing': sorted(set(bb) - set(aa)), 'extra': sorted(set(aa) - set(bb))})
        for origin in sorted(set(aa) & set(bb)):
            for field in fields + extra:
                if aa[origin][field] != bb[origin][field]:
                    differences.append({'origin': origin, 'field': field})
    return {'status': 'MATCH' if not differences else 'DIFFERENCE_REQUIRES_SEMANTIC_REVIEW',
            'differences': differences, 'historical_common_list_used_for_execution': False,
            'result_expected_from_seen_diagnostic_not_new_independent_discovery': True}


def annotated_windows(comparison, d_view, n_view, m_view):
    """Name restored D opportunities inside already-computed same-day windows."""
    d_keys = {t['origin_key'] for key in ('trades', 'open_observations') for t in d_view[key]}
    n_keys = {t['origin_key'] for key in ('trades', 'open_observations') for t in n_view[key]}
    m_keys = {t['origin_key'] for key in ('trades', 'open_observations') for t in m_view[key]}
    answer = []
    for w in comparison['same_calendar_windows']:
        p, m = ({t['origin_key']: t for t in w[key]['position_contributions']} for key in ('parent', 'child'))
        groups = {k: 0. for k in ('COMMON', 'REMOVED_N', 'RESTORED_D', 'OTHER_NEW_M')}
        for key in p.keys() | m.keys():
            group = ('COMMON' if key in n_keys and key in m_keys else 'REMOVED_N' if key in n_keys
                     else 'RESTORED_D' if key in d_keys else 'OTHER_NEW_M')
            groups[group] += (m[key]['delta']['net_bps'] if key in m else 0.) - (p[key]['delta']['net_bps'] if key in p else 0.)
        metrics.previous.bridge._same(sum(groups.values()), w['child_minus_parent']['net_bps'], 'RESERVATION_SAME_WINDOW_GROUPS')
        answer.append({'start_ms': w['start_ms'], 'end_ms': w['end_ms'], 'labels': w['labels'],
                       'net_delta_bps': w['child_minus_parent']['net_bps'], 'groups': groups,
                       'overlapping_windows_must_not_be_summed': True, 'post_outcome_analysis_only': True})
    return answer


def run(data_dir, verify_only=False):
    c = authorize(); out = ROOT / OUTPUT
    if (out / 'receipt.json').exists() != verify_only:
        raise RuntimeError('RESERVATION_CONSUMED_OR_MISSING_USE_REPRODUCTION')
    nc, dc, stored, old_stored = load_stored()
    links = diagnosis.diagnose(stored, old_stored)
    if old.digest(links) != c['lineage_content_sha256']:
        raise RuntimeError('RESERVATION_PREVIOUS_LINEAGE_DRIFT')
    artifacts = {'lineage': artifact('LINEAGE.json.gz', links, verify_only)}
    base, costs, periods, access = prior.previous.load_inputs(Path(data_dir), dc)
    results = {}
    for period, (start, end) in c['calendars'].items():
        rows_by = periods[period]
        if {s: old.digest(rows) for s, rows in rows_by.items()} != old_stored[period]['record']['economic_rows_sha256_by_symbol']:
            raise RuntimeError('RESERVATION_ORIGINAL_ROWS_PARITY')
        policy = {**base, 'batch_id': c['batch_id'], 'receipt_sha256': c['receipt_sha256'],
                  'code_files_sha256': c['code_files_sha256'], 'combined_data_sha256': c['period_data_sha256'][period],
                  'development_interval_ms': [start, end]}
        # Execution receives prices + original causal signal features only.
        # Stored P/D/N origins and diagnosis are never passed to the adapter.
        with old.probe.io_boundary([], out):
            bundles = {s: adapter.build_bundle(rows, prior.previous.kexit.PARENT_SPEC,
                        eval_start_ms=start, eval_end_ms=end) for s, rows in rows_by.items()}
            disabled = replay(rows_by, bundles, costs, policy, start, end, enabled=False)
            prior.assert_D_parity(disabled, stored[period]['views']['N'])
            full = replay(rows_by, bundles, costs, policy, start, end)
            views = {k: stored[period]['views'][k] for k in ('P', 'D', 'N')}
            views['M'] = full
            stages = {k: stored[period]['record']['stages'][k] for k in ('P', 'D', 'N')}
            stages['M'] = prior.previous.metrics.build_stage(full['trades'], full['open_observations'], full['events'],
                              rows_by, costs, policy, c['symbols'], start, end)
            comparisons = {}
            for reference in ('P', 'D', 'N'):
                v = views[reference]
                comparisons[reference + '_to_M'] = metrics.compare(stages[reference], stages['M'], v['trades'],
                    v['open_observations'], full['trades'], full['open_observations'], rows_by, costs, start, end,
                    role='N_PRIMARY' if reference == 'N' else reference + '_CONTEXT')
            context = {**comparisons, 'P_to_D': old_stored[period]['record']['comparisons']['FULL'],
                       'P_to_N': stored[period]['record']['comparisons']['P_to_N'],
                       'D_to_N': stored[period]['record']['comparisons']['D_to_N']}
            table = metrics.reservation_table(stages['P'], stages['D'], stages['N'], stages['M'], context)
            questions = metrics.summarize_cumulative(stages['P'], stages['D'], stages['N'], stages['M'], period)
            post_audit = diagnosis.after_M_audit(stored[period], full, period)
            common_parity = comparison_only_common_parity(full, stored[period]['views']['N_COMMON_D'])
            windows = annotated_windows(comparisons['N_to_M'], views['D'], views['N'], full)
        record = {'period': period, 'calendar_ms': [start, end], 'candidate_id': CANDIDATE,
                  'independent': False, 'full_replay': True, 'disabled_N_parity': 'EXACT',
                  'stages': stages, 'comparisons': comparisons, 'questions': questions,
                  'post_replay_origin_audit': post_audit, 'common_D_regression': common_parity,
                  'N_M_same_calendar_contributions': windows, 'table': table,
                  'funnel_by_symbol': full['admission'], 'reference_events_are_economic_trades': False}
        artifacts[period] = artifact(period + '.json.gz', {'record': record, 'views': views}, verify_only)
        summary = deepcopy(record)
        for v in summary['stages'].values(): v.pop('daily', None)
        for v in summary['comparisons'].values(): v.pop('same_calendar_windows', None)
        results[period] = summary
    decision = metrics.candidate_decision({p: r['comparisons'] for p, r in results.items()})
    result = old.seal({**AUTH, 'schema': 'keltner.opportunity.reservation.result.v1', 'batch_id': c['batch_id'],
        'candidate_id': CANDIDATE, 'decision': decision, 'results': results, 'artifacts': artifacts,
        'contract_sha256': c['receipt_sha256'], 'previous_result_seal': PRIOR_SEAL,
        'candidate_cumulative_before': 29, 'candidate_cumulative_after': 30, 'new_candidates_measured': 1,
        'candidate_period_evaluations': 2, 'remaining_allocated_candidates': 0,
        'source_access': access, 'decoded_after_20260905_00UTC': 0,
        'prior_independent_comparison': c['prior_independent_comparison'], 'prior_seen_evaluation': '1/1_PRESERVED',
        'preserved_states': c['preserved_states'], 'data_reuse_history': c['data_reuse_history'],
        'Gemini_actual_video': 'NOT_RUN'})
    old.probe.write_immutable(out / 'receipt.json', old.probe.canonical(result), verify_only=verify_only)
    old.probe.write_immutable(out / 'RESULTS.md', report(result), verify_only=verify_only)
    paths = [SPEC, DESIGN, OUTPUT + '/receipt.json', OUTPUT + '/RESULTS.md'] + [v['path'] for v in artifacts.values()]
    durable = old.seal({**AUTH, 'result_receipt_sha256': result['receipt_sha256'],
        'files_sha256': {p: old.file_sha(ROOT / p) for p in paths}, 'code_files_sha256': c['code_files_sha256'],
        'preserved_files_sha256': c['preserved_files_sha256']})
    old.probe.write_immutable(out / 'durable_receipt.json', old.probe.canonical(durable), verify_only=verify_only)
    return result


def report(r):
    f = lambda v: 'NA' if v is None else f'{v:,.4f}' if isinstance(v, (float, int)) else str(v)
    lines = ['# Keltner causal opportunity reservation — P / D / N / M', '',
        'All numbers are reused development evidence, independent=false. P/D/N remain unchanged; M retains N entry and D exit rules. PnL and marked risk are equal nominal trade-bps, never account returns or account MDD.', '']
    for period, result in r['results'].items():
        lines += ['| Period / metric | P | D | N | M | M-N | M-D | M-P |', '|---|---:|---:|---:|---:|---:|---:|---:|']
        for row in result['table']:
            lines.append('| ' + period + ' / ' + row['metric'] + ' | ' + ' | '.join(f(row[k]) for k in
                ('P', 'D', 'N', 'M', 'M_minus_N', 'M_minus_D', 'M_minus_P')) + ' |')
        lines += ['', 'Cumulative gains and deficits:', '', '```json', json.dumps(result['questions'], indent=2), '```', '',
                  'Post-replay common-D check: ' + result['common_D_regression']['status'], '',
                  'Reference reservation and actual entry funnels:', '', '```json', json.dumps(result['funnel_by_symbol'], indent=2), '```', '']
        for name, cmp in result['comparisons'].items():
            lines += [name + ' — contributions / uncertainty / separate decisions:', '', '```json',
                json.dumps({k: cmp[k] for k in ('net_decomposition', 'uncertainty', 'decision')}, indent=2), '```', '']
    lines += ['Overall interpretation (incremental repair and absolute economics remain separate):', '',
        '```json', json.dumps(r['decision'], indent=2), '```', '',
        'The prior2025 COMMON_D result was already seen and motivated this candidate. Agreement is a regression result, not unused evidence. Admission is calculated sequentially from completed bars; historical D IDs, planned future EMA exits and outcome labels never enter the execution adapter. The D engine supplies actual fill/path accounting only after causal admission decisions.', '',
        'Rejected opportunities retain a virtual reference reservation with zero money, quantity, PnL, fee, funding or exposure. Only actual M model positions enter economics. The original no-separate-SL research limitation is unchanged; this is not live safety readiness.', '',
        'Each period gzip includes P/D/N/M trades, open marks, original signals, reference events/state, daily marked paths, monthly/symbol concentration, common/removed/restored/new same-calendar contributions, and2026 residual gross/cost/open accounting. Retrospective labels are diagnosis only. Windows overlap and must not be summed; distinct worst maxima are not causal attribution.', '',
        'Original EMA seed/warmup and4h calendars, seven symbols, research costs/funding/20bps floor and full cost2 remain fixed. Open marks use hypothetical full roundtrip costs, never forced closes. The seen prefix retains original partition labels; no unused validation or post2026-09-05T00Z/observer data is decoded.', '',
        'Prior29 candidates preserved; M is ordinal30, two period applications, zero remaining automatic slots. Reproduction/old-ledger diagnosis/synthetic tests are not new candidates. No M2, sweep, extra indicator, exit tuning, paid external AI, operating change or observer redesign. execution=NONE/order=BLOCKED/live=BLOCKED; formal credit0. A separate future candidate/data freeze and authorization would be needed for unused validation.', '']
    return '\n'.join(lines).encode()


def main():
    p = argparse.ArgumentParser(); p.add_argument('--data-dir', type=Path)
    p.add_argument('--check-only', action='store_true'); p.add_argument('--verify-only', action='store_true')
    args = p.parse_args()
    if args.check_only:
        c = authorize(); print(json.dumps({'status': 'FROZEN_CHECK_PASS', 'spec_sha256': c['receipt_sha256']}))
    else:
        if args.data_dir is None: p.error('--data-dir required')
        r = run(args.data_dir.resolve(), args.verify_only)
        print(json.dumps({'receipt_sha256': r['receipt_sha256'], 'decision': r['decision']}, indent=2))


if __name__ == '__main__':
    main()
