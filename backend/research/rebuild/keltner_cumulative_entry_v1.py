"""One conditionally admitted entry repair on immutable PR1196 Keltner D.

P and D results stay sealed. This runner reuses D execution and shared costs;
the single eligibility observation is available at the original signal close.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import json
import math
from pathlib import Path

from backend.research.rebuild import parallel_exit_dev_v1 as previous
from backend.research.rebuild import keltner_cumulative_entry_adapter_v1 as adapter
from backend.research.rebuild import keltner_cumulative_entry_metrics_v1 as metrics

old, ROOT = previous.old, previous.ROOT
OUTPUT = 'research/development_evidence/KELTNER_CUMULATIVE_ENTRY_20260906_V1'
SPEC, DESIGN = OUTPUT + '/SPEC.json', OUTPUT + '/DESIGN.md'
PROTOCOL = OUTPUT + '/DIAGNOSIS_PROTOCOL.json'
AUTHORIZATION = 'EXPLICIT_USER_CONDITIONAL_ONE_KELTNER_ENTRY_REPAIR_AFTER_PR1196'
CANDIDATE = adapter.RULE_ID
LANE = 'keltner_trend_main'
CODE = ['backend/research/rebuild/' + prefix + name + '_v1.py'
        for name in ('keltner_cumulative_entry', 'keltner_cumulative_entry_adapter',
                     'keltner_cumulative_entry_metrics') for prefix in ('', 'test_')]
RULE = {'expression': 'signal close >= (signal high + signal low) / 2',
        'feature': 'top5_development_repair_v1.geometry.close_on_directional_half',
        'observation_time': 'ORIGINAL_COMPLETED_SIGNAL_4H_CLOSE',
        'parent': 'PR1196_KELTNER_FULL_D_NOT_ADOPTED',
        'entry_fill': 'UNCHANGED_NEXT_OPEN', 'exit': 'UNCHANGED_PR1196_TREND_INVALIDATION_AND_MAX12',
        'ownership': 'UNCHANGED_SIGNAL_INDEX_LE_EXIT_INDEX_BLOCK',
        'common_view': 'ELIGIBILITY_ON_D_ADMITTED_ORIGINS; NOT_IDENTICAL_ENTRY_EXIT_COMPARISON',
        'full_view': 'ORIGINAL_OPPORTUNITY_POOL_WITH_FILTER_AND_COMPLETE_OCCUPANCY_REPLAY',
        'numeric_search': False, 'extra_candidates': False, 'independent': False}
AUTH = {**previous.AUTH, 'comparison_type': 'ENTRY_FILTER', 'independent': False,
        'research_baseline_automatic_replacement': False}
PRIOR_RESULT = '3d5e26b24823fc558cda49f259d27a5f1366db393f009368846a3f2529e06703'


def load_stored():
    c = previous.authorize()
    r = old.read(previous.OUTPUT + '/receipt.json')
    old.probe.verify_seal(r, 'PR1196_RESULT')
    if r['receipt_sha256'] != PRIOR_RESULT or r['candidate_cumulative_after'] != 28:
        raise RuntimeError('CUMULATIVE_PR1196_RESULT_OR_COUNT')
    records = {}
    for period in previous.CALENDARS['KELTNER']:
        ref = r['artifacts']['KELTNER_' + period]
        if old.file_sha(ROOT / ref['path']) != ref['file_sha256']:
            raise RuntimeError('CUMULATIVE_STORED_LEDGER_BYTES')
        records[period] = json.loads(gzip.decompress((ROOT / ref['path']).read_bytes()))
    return c, records


def diagnose(stored, periods):
    """One declared cohort observation; no eligibility/occupancy simulation."""
    result = {}
    for period, document in stored.items():
        views = document['views']
        p = {t['origin_key']: t for t in views['P']['trades']}
        d = {t['origin_key']: t for t in views['FIXED']['trades']}
        if set(p) != set(d):
            raise RuntimeError('CUMULATIVE_FIXED_ORIGINS')
        observations = {}
        for event in views['FULL']['events']:
            rows = periods[period][event['symbol']]
            i = event['signal_index']; bar = rows[i]
            if bar['bar_close_ts'] != event['signal_ts']:
                raise RuntimeError('CUMULATIVE_FEATURE_SOURCE_CLOCK')
            observations[event['symbol'], event['signal_ts']] = {
                'eligible': old.geometry(rows, i)['close_on_directional_half'],
                'close': bar['close'], 'high': bar['high'], 'low': bar['low'],
                'available_at': bar['bar_close_ts']}
        def obs(t):
            value = observations[t['symbol'], t['signal_ts']]
            if value['available_at'] > t['entry_ts']:
                raise RuntimeError('CUMULATIVE_ENTRY_FEATURE_FUTURE')
            return value['eligible']
        cohorts = {}
        for label, trades in (('P', list(p.values())), ('D_FIXED', list(d.values())),
                              ('D_FULL', views['FULL']['trades'])):
            winners = sorted([t for t in trades if t['net_bps'] > 0],
                             key=lambda t: (-t['net_bps'], t['origin_key']))
            large = winners[:math.ceil(len(winners) * .1)]
            groups = {}
            for eligible in (False, True):
                group = [t for t in trades if obs(t) == eligible]
                groups[str(eligible)] = {
                    'T': len(group), 'wins': sum(t['net_bps'] > 0 for t in group),
                    'losses': sum(t['net_bps'] < 0 for t in group),
                    **{key: sum(t[key] for t in group) for key in
                       ('gross_bps', 'net_bps', 'cost_bps', 'funding_bps')},
                    'winning_amount_bps': sum(t['net_bps'] for t in group if t['net_bps'] > 0),
                    'large_winning_amount_bps': sum(t['net_bps'] for t in large if obs(t) == eligible)}
            cohorts[label] = groups
        categories = {}
        for key, trade in d.items():
            changed = any(trade[f] != p[key][f] for f in ('exit_ts', 'exit_price'))
            delta = trade['net_bps'] - p[key]['net_bps']
            label = ('HELPFUL_EXIT' if changed and delta > 0 else 'HARMFUL_EXIT' if changed and delta < 0
                     else 'UNTRIGGERED_LOSS' if not changed and p[key]['net_bps'] < 0 else 'OTHER')
            group = categories.setdefault(label, {'T': 0, 'P_net_bps': 0., 'D_net_bps': 0.,
                'delta_net_bps': 0., 'lower_half_T': 0, 'lower_half_D_net_bps': 0., 'cost_only_loss_T': 0})
            group['T'] += 1
            group['P_net_bps'] += p[key]['net_bps']; group['D_net_bps'] += trade['net_bps']
            group['delta_net_bps'] += delta
            if not obs(trade):
                group['lower_half_T'] += 1; group['lower_half_D_net_bps'] += trade['net_bps']
            group['cost_only_loss_T'] += trade['gross_bps'] >= 0 and trade['net_bps'] < 0
        lower, upper = cohorts['D_FULL']['False'], cohorts['D_FULL']['True']
        large = lower['large_winning_amount_bps'] + upper['large_winning_amount_bps']
        checks = {'excluded_cohort_exists': lower['T'] > 0,
            'excluded_net_negative': lower['net_bps'] < 0,
            'excluded_loss_rate_higher': (lower['losses'] / lower['T'] > upper['losses'] / upper['T']
                                         if lower['T'] and upper['T'] else False),
            'large_winner_retention_at_least_90pct': large > 0 and upper['large_winning_amount_bps'] / large >= .9}
        result[period] = {'cohorts': cohorts, 'categories': categories, 'checks': checks,
            'qualified': all(checks.values()),
            'fixed_decomposition': document['record']['comparisons']['FIXED']['net_decomposition'],
            'oracle_P_or_D_closed_upper_bps': sum(max(p[k]['net_bps'], d[k]['net_bps']) for k in p),
            'oracle_is_executable_strategy': False,
            'observations': [dict(symbol=s, signal_ts=ts, **value)
                             for (s, ts), value in sorted(observations.items())]}
    return {'periods': result, 'qualified': all(r['qualified'] for r in result.values()),
            'independent': False, 'new_strategy_replayed': False, 'only_axis': RULE['feature'],
            'prior_axis_was_seen_diagnostic': True, 'future_observer_inputs': False}


def authorize():
    c = old.read(SPEC); old.probe.verify_seal(c, 'CUMULATIVE_SPEC')
    if (c['authorization'] != AUTHORIZATION or c['candidate_id'] != CANDIDATE or c['rule'] != RULE
            or c['goal'] != metrics.GOAL or c['candidate_cumulative_before'] != 28
            or c['allocated_new_candidates'] != 1 or c['new_N_outcomes_seen_at_freeze'] is not False
            or c['calendars'] != previous.CALENDARS['KELTNER']):
        raise RuntimeError('CUMULATIVE_ALLOCATION_RULE_OR_GOAL')
    for key, value in AUTH.items():
        if c.get(key) != value:
            raise RuntimeError('CUMULATIVE_AUTHORITY:' + key)
    if set(c['code_files_sha256']) != set(CODE):
        raise RuntimeError('CUMULATIVE_CODE_COVERAGE')
    for path, sha in {**c['preserved_files_sha256'], **c['code_files_sha256'], **c['ci_files_sha256']}.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('CUMULATIVE_FROZEN_BYTES:' + path)
    for path, field in ((DESIGN, 'design_sha256'), (PROTOCOL, 'protocol_sha256')):
        if old.file_sha(ROOT / path) != c[field]:
            raise RuntimeError('CUMULATIVE_DESIGN_PROTOCOL_BYTES')
    prior = previous.authorize()
    if (c['data_sha256'] != prior['data_sha256'] or c['cost_sha256'] != prior['cost_sha256']
            or c['period_data_sha256'] != prior['period_data_sha256']):
        raise RuntimeError('CUMULATIVE_DATA_COST_AUTHORITY')
    return c


def charge(raw, symbol, stage, policy, costs, rows):
    value = previous.charge_result(raw, symbol, LANE, stage, policy, costs, rows)
    for key, seal in (('trades', 'trade_sha256'), ('open_observations', 'observation_sha256')):
        for row in value[key]:
            row.pop(seal, None)
            row.update(candidate_id=CANDIDATE, evidence_type='REUSED_DEV_ENTRY_REPAIR',
                       comparison_type='ENTRY_FILTER', base_exit='PR1196_D_UNCHANGED')
            row[seal] = old.digest(row)
    return value


def replay(rows_by, bundles, costs, policy, start, end, stage, common=None, enabled=True):
    result = {k: [] for k in ('trades', 'open_observations', 'events', 'trace')}
    result['admission'] = {}
    for symbol, rows in sorted(rows_by.items()):
        raw = adapter.replay(rows, bundles[symbol], eval_start_ms=start, eval_end_ms=end,
                             enabled=enabled, common_signal_indices=None if common is None else common[symbol])
        value = charge(raw, symbol, stage, policy, costs, rows)
        for key in result:
            if key != 'admission':
                result[key].extend(value[key])
        result['admission'][symbol] = value['audit']
    return result


def assert_D_parity(actual, expected):
    fields = ('signal_index', 'entry_index', 'entry_ts', 'entry_price', 'hold_ms', 'side')
    for key, extra in (('trades', ('exit_index', 'exit_ts', 'exit_price', 'gross_bps', 'net_bps',
                                  'cost_bps', 'funding_bps', 'cost2x_net_bps')),
                       ('open_observations', ('mark_index', 'mark_ts', 'mark_price', 'gross_mark_bps',
                        'hypothetical_liquidation_net_mark_bps', 'hypothetical_liquidation_cost_bps'))):
        aa, bb = ({t['origin_key']: t for t in view[key]} for view in (actual, expected))
        if len(aa) != len(actual[key]) or set(aa) != set(bb):
            raise RuntimeError('CUMULATIVE_DISABLED_ORIGIN_PARITY:' + key)
        for origin in aa:
            for field in fields + extra:
                if aa[origin][field] != bb[origin][field]:
                    raise RuntimeError('CUMULATIVE_DISABLED_ECONOMIC_PARITY:' + field)
    if [(e['symbol'], e['signal_ts'], e['status'], e.get('exclusion_reason')) for e in actual['events']] != [
            (e['symbol'], e['signal_ts'], e['status'], e.get('exclusion_reason')) for e in expected['events']]:
        raise RuntimeError('CUMULATIVE_DISABLED_OPPORTUNITY_PARITY')


def artifact(name, value, verify_only=False):
    path = ROOT / OUTPUT / name; raw = old.probe.canonical(value)
    payload = path.read_bytes() if path.exists() else gzip.compress(raw, mtime=0)
    if gzip.decompress(payload) != raw:
        raise RuntimeError('CUMULATIVE_REPRODUCTION_DRIFT:' + name)
    old.probe.write_immutable(path, payload, verify_only=verify_only)
    return {'path': str(path.relative_to(ROOT)), 'file_sha256': old.file_sha(path)}


def run(data_dir, verify_only=False):
    c = authorize(); out = ROOT / OUTPUT
    if (out / 'receipt.json').exists() != verify_only:
        raise RuntimeError('CUMULATIVE_CONSUMED_OR_MISSING_USE_REPRODUCTION')
    prior, stored = load_stored()
    base, costs, periods, access = previous.load_inputs(Path(data_dir), prior)
    for period, document in stored.items():
        if ({s: old.digest(rows) for s, rows in periods[period].items()} !=
                document['record']['economic_rows_sha256_by_symbol']):
            raise RuntimeError('CUMULATIVE_ORIGINAL_PERIOD_ROWS_PARITY')
    analysis = diagnose(stored, periods)
    if old.digest(analysis) != c['diagnosis_content_sha256'] or not analysis['qualified']:
        raise RuntimeError('CUMULATIVE_CONDITIONAL_EVIDENCE_NOT_MET_OR_DRIFT')
    artifacts = {'diagnosis': artifact('DIAGNOSIS.json.gz', analysis, verify_only)}
    results = {}
    for period, (start, end) in c['calendars'].items():
        rows_by = periods[period]; previous_views = stored[period]['views']
        policy = {**base, 'batch_id': c['batch_id'], 'receipt_sha256': c['receipt_sha256'],
                  'code_files_sha256': c['code_files_sha256'],
                  'combined_data_sha256': c['period_data_sha256'][period],
                  'development_interval_ms': [start, end]}
        with old.probe.io_boundary([], out):
            bundles = {s: adapter.build_bundle(rows, previous.kexit.PARENT_SPEC,
                        eval_start_ms=start, eval_end_ms=end) for s, rows in rows_by.items()}
            disabled = replay(rows_by, bundles, costs, policy, start, end, 'DISABLED', enabled=False)
            assert_D_parity(disabled, previous_views['FULL'])
            common = {s: {t['signal_index'] for t in previous_views['FULL']['trades'] + previous_views['FULL']['open_observations']
                          if t['symbol'] == s} for s in rows_by}
            common_view = replay(rows_by, bundles, costs, policy, start, end, 'N_COMMON_D', common)
            full = replay(rows_by, bundles, costs, policy, start, end, 'N_FULL')
            views = {'P': previous_views['P'], 'D': previous_views['FULL'], 'N_COMMON_D': common_view, 'N': full}
            stages = {'P': stored[period]['record']['stages']['P'],
                      'D': stored[period]['record']['stages']['FULL']}
            for stage in ('N_COMMON_D', 'N'):
                v = views[stage]
                stages[stage] = previous.metrics.build_stage(v['trades'], v['open_observations'],
                    v['events'], rows_by, costs, policy, c['symbols'], start, end)
            comparisons = {}
            for b, n in (('D', 'N_COMMON_D'), ('D', 'N'), ('P', 'N')):
                bv, nv = views[b], views[n]
                comparisons[b + '_to_' + n] = metrics.compare(stages[b], stages[n], bv['trades'],
                    bv['open_observations'], nv['trades'], nv['open_observations'], rows_by, costs, start, end)
            questions = metrics.summarize_cumulative(stages['P'], stages['D'], stages['N'], period)
            questions['original_P_opportunity_effects'] = metrics.original_entry_effects(
                previous_views['P']['trades'], previous_views['P']['open_observations'],
                previous_views['FIXED']['trades'], previous_views['FIXED']['open_observations'],
                full['trades'], full['open_observations'])
            table = metrics.cumulative_table(stages['P'], stages['D'], stages['N'],
                stored[period]['record']['comparisons']['FULL'],
                comparisons['P_to_N'], comparisons['D_to_N'])
        record = {'period': period, 'calendar_ms': [start, end], 'candidate_id': CANDIDATE,
                  'comparison_type': 'ENTRY_FILTER', 'independent': False,
                  'disabled_D_parity': 'EXACT_FILL_COST_OPEN_AND_OPPORTUNITY_PARITY',
                  'stages': stages, 'comparisons': comparisons, 'questions': questions, 'table': table}
        artifacts[period] = artifact(period + '.json.gz', {'record': record, 'views': views}, verify_only)
        summary = deepcopy(record)
        for value in summary['stages'].values():
            value.pop('daily', None)
        for value in summary['comparisons'].values():
            value.pop('same_calendar_windows', None)
        results[period] = summary
    decision = metrics.candidate_decision({period: {name: value for name, value in record['comparisons'].items()
        if name in ('P_to_N', 'D_to_N')} for period, record in results.items()})
    result = old.seal({**AUTH, 'schema': 'keltner.cumulative.entry.result.v1', 'batch_id': c['batch_id'],
        'decision': decision,
        'contract_sha256': c['receipt_sha256'], 'candidate_id': CANDIDATE, 'results': results,
        'candidate_cumulative_before': 28, 'candidate_cumulative_after': 29,
        'new_candidates_measured': 1, 'remaining_allocated_candidates': 0,
        'candidate_period_evaluations': 2, 'common_full_evaluation_views': 4,
        'source_access': access, 'decoded_after_20260905_00UTC': 0, 'artifacts': artifacts,
        'prior_seen_evaluation': '1/1_PRESERVED', 'prior_independent_comparison': c['prior_independent_comparison'],
        'preserved_states': c['preserved_states'], 'previous_result_seal': PRIOR_RESULT,
        'data_reuse_history': c['data_reuse_history'], 'Gemini_actual_video': 'NOT_RUN'})
    old.probe.write_immutable(out / 'receipt.json', old.probe.canonical(result), verify_only=verify_only)
    old.probe.write_immutable(out / 'RESULTS.md', report(result), verify_only=verify_only)
    paths = [SPEC, DESIGN, PROTOCOL, OUTPUT + '/receipt.json', OUTPUT + '/RESULTS.md']
    paths += [a['path'] for a in artifacts.values()]
    durable = old.seal({**AUTH, 'result_receipt_sha256': result['receipt_sha256'],
        'files_sha256': {path: old.file_sha(ROOT / path) for path in paths},
        'code_files_sha256': c['code_files_sha256'], 'preserved_files_sha256': c['preserved_files_sha256']})
    old.probe.write_immutable(out / 'durable_receipt.json', old.probe.canonical(durable), verify_only=verify_only)
    return result


def report(r):
    f = lambda v: 'NA' if v is None else f'{v:,.4f}' if isinstance(v, (int, float)) else str(v)
    lines = ['# Keltner cumulative entry repair: P / D / N', '',
             'P is the unchanged original control. D is the unadopted PR1196 workcopy. N retains D exits and only admits original signal closes in the upper half of their own high-low range. All periods are reused development evidence; independent=false. Units: equal nominal trade-bps, never account returns.', '']
    for period, record in r['results'].items():
        lines += ['| Period / metric | P | D | N | N-D | N-P |', '|---|---:|---:|---:|---:|---:|']
        for row in record['table']:
            lines.append('| ' + period + ' / ' + row['metric'] + ' | ' + ' | '.join(f(row[key]) for key in ('P', 'D', 'N', 'N_minus_D', 'N_minus_P')) + ' |')
        lines += ['', 'D→N: `' + json.dumps(record['comparisons']['D_to_N']['decision'], ensure_ascii=False) + '`', '']
        questions = deepcopy(record['questions'])
        origins = questions.pop('original_P_opportunity_effects')
        concise = {key: value for key, value in origins.items() if key not in
                   ('per_original_origin', 'original_origin_change_attribution', 'original_origin_net_decomposition')}
        lines += ['Cumulative gain and remaining deficits:', '', '```json',
                  json.dumps(questions, indent=2), '```', '',
                  'Original P opportunity bridge (row detail is in the period ledger):', '',
                  '```json', json.dumps(concise, indent=2), '```', '']
        for name, comparison in record['comparisons'].items():
            lines += [name + ' — complete net contribution and uncertainty:', '', '```json',
                      json.dumps({'net_decomposition': comparison['net_decomposition'],
                                  'uncertainty': comparison['uncertainty']}, indent=2), '```', '']
    lines += ['## Interpretation and complete accounting', '',
        'Common-original-opportunity view applies the new eligibility to D admitted origins. Full N independently replays the complete original signal pool and occupancy. Vetoes remain explicit events; removed entries are not zero-PnL wins. Retained common origins keep D exit geometry; changed aggregate performance includes lost winners, avoided losers, newly admitted and displaced entries.', '',
        'The2026 new SOL profit from PR1196 is not added as a constant; its origin must survive actual N replay. Original P winners/losers and prior D fixed effects are diagnostic labels only. Per-period gzip ledgers contain every event/fill/trigger/openmark, UTC path, same-calendar loss/DD windows, common/removed/new origin bridges and block uncertainty.', '',
        'N-D and N-P retention use each reference’s completed winners and capped original profit; topdecile winner definition is unchanged. Existing 90% large-profit preservation is a research comparison prior, not a new formal gate. No P/D verdict is rewritten. Partial improvements and absolute cost-stressed profitability are separate.', '',
        '2025 native interval2024-12-19T08Z–2025-12-29T08Z;2026 interval2026-05-08T00Z–2026-09-05T00Z. The exact original EMA warmup/seed and cost authority are preserved. No input afterSep5T00Z is decoded. Original seen-prefix split labels remain in source_access, not independent validation.', '',
        'Parent P/D unfinished tails remain separate hypothetical full-roundtrip-cost marks; no end-price fabricated fill. D has no separate SL in the original Keltner model. Research cost/funding assumptions remain distinct from production signed funding/fills and account sizing.', '',
        '28 old candidates preserved;1new candidate ordinal29,2period applications,4common/full views,0remaining. Same-result reproduction consumes no new trial. Old seen1/1 and independent0/1 NOT_RUN preserved. No numeric sweep, alternative filter scan, additional candidate, B2, externalpaidAI or operating deployment.', '',
        '| Top5 | This work |', '|---|---|', '| Primary | Preserved |', '| Broad | Preserved |',
        '| Break / Q0 | Research/future observer preserved |', '| Keltner | P fixed; D retained; one N entry repair measured |',
        '| Supertrend | Preserved |', '',
        'PR1195 observer code/spec/period/schedule/data never used for development. G5B/operating code unchanged; execution=NONE/order=BLOCKED/live=BLOCKED, formal credit0. A separate future child freeze/boundary/authorization would be required for unused validation.', '']
    return '\n'.join(lines).encode()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--verify-only', action='store_true'); parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.check_only:
        c = authorize(); print(json.dumps({'status': 'FROZEN_CHECK_PASS', 'spec_sha256': c['receipt_sha256']}))
    else:
        if args.data_dir is None:
            parser.error('--data-dir required')
        r = run(args.data_dir.resolve(), args.verify_only)
        print(json.dumps({'receipt_sha256': r['receipt_sha256'],
              'period_decisions': {k: v['comparisons']['D_to_N']['decision'] for k, v in r['results'].items()}}, indent=2))


if __name__ == '__main__':
    main()
