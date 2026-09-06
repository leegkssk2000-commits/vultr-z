"""Two explicitly allocated exit hypotheses; reused DEV only, no observer reads.

This integration calls immutable signal, fill and cost implementations. Neither
prior experiments nor prospective model trades are re-executed by this runner.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path

from backend.research.rebuild import break_channel_source_v1 as source
from backend.research.rebuild import q0_b_seen_adapter_v1 as seen
from backend.research.rebuild import q0_b_seen_replication_v1 as seen_run
from backend.research.rebuild import parallel_exit_q0_v1 as qexit
from backend.research.rebuild import parallel_exit_keltner_v1 as kexit
from backend.research.rebuild import parallel_exit_metrics_v1 as metrics

old, ROOT = source.old, source.ROOT
OUTPUT = 'research/development_evidence/PARALLEL_EXIT_DEV_20260906_V1'
CONTRACT, DESIGN = OUTPUT + '/SPEC.json', OUTPUT + '/DESIGN.md'
AUTHORIZATION = 'EXPLICIT_USER_TWO_PARALLEL_EXIT_DEV_AFTER_PR1195'
CANDIDATES = {'Q0': 'Q0_ENTRY_CHANNEL_LOSS_EXIT_DEV_V1',
              'KELTNER': 'KELTNER_TREND_INVALIDATION_EXIT_DEV_V1'}
CALENDARS = {'Q0': {'DEV2025': [1738108800000, 1766966400000],
                    'SEEN2026': [1778198400000, 1788566400000]},
             'KELTNER': {'DEV2025': [1734595200000, 1766995200000],
                         'SEEN2026': [1778198400000, 1788566400000]}}
AUTH = {**old.probe.DEV_AUTH, 'independent': False, 'formal_credit': 0,
        'operating_adoption': False, 'G5B_changed': False, 'G6_authorized': False,
        'operating_changed': False, 'actual_account_sizing': False,
        'future_observer_inputs_used': False, 'paid_external_AI_calls': 0}
CODE = ['backend/research/rebuild/' + prefix + name + '_v1.py'
        for name in ('parallel_exit_dev', 'parallel_exit_q0',
                     'parallel_exit_keltner', 'parallel_exit_metrics')
        for prefix in ('', 'test_')]
RULES = {
    'Q0': 'Freeze original UP signal channel upper for each entry. First held completed4h close<=upper queues next eligible4h open exit. Original gapSL/original DOWN exit take precedence, then added exit, original occupancy/entry/intrabarSL; no post-stop trigger. No channel update, B, Q1, BE, extra filter or time limit.',
    'KELTNER': 'Original V2 EMA20 reclaim and EMA20>EMA50 entry, original EMA seed/warmup/index239 and max12hold. First held completed4h EMA20<=EMA50 queues next eligible4h open exit, native timeout first. No added SL. Native strict-end completion exclusion retained as explicit open mark, never a forced close.',
    'comparison': 'EXIT_CHANGE; parent admitted entries fixed for direct exit effect, separately full original signal/occupancy replay. No entry change. Same-entry accounting is not an executable portfolio if positions overlap.',
    'fills': 'Only original OHLCV; signal close cannot be fill. Next open must be strictly before calendar end. Existing original SL and timeout precedence; final completed close is valuation only. No future bars decoded.',
    'cost': 'Unchanged common research fee/spread/impact/slippage/funding and20bps floor; entry<8h settlement<=exit/mark; cost2 doubles all components; hypothetical full roundtrip open mark separate from realized closed metrics. Equal nominal amounts, not account returns or equal account risk.',
    'evidence': 'Both periods reused development data. SEEN2026 original partition labels honestly recorded; explicit reuse is not new independent validation. No prospective warmup/archive/cursor/market records loaded.',
    'calendar': 'Lane native2025 boundaries preserved; seen2026 fresh flat with original source-prefix causal warmup. No warmup trades carried. Pair calendars/universe/cost identical; UTC midnight daily marks plus exact partial terminal boundary.',
    'budget': 'Prior26 immutable; exactly2 candidate allocations (ordinals27/28),2 periods each. Fixed/full are views of same hypothesis, not additional candidates. Reproduction does not consume allocation; no outcome-conditioned changes or automatic expansion.',
}


def authorize():
    c = old.read(CONTRACT)
    old.probe.verify_seal(c, 'PARALLEL_EXIT_SPEC')
    if (c['authorization'] != AUTHORIZATION or c['candidates'] != CANDIDATES
            or c['calendars'] != CALENDARS or c['rules'] != RULES
            or c['goal'] != metrics.GOAL or c['new_outcomes_seen_at_freeze'] is not False
            or c['candidate_cumulative_before'] != 26 or c['allocated_new_candidates'] != 2
            or c['symbols'] != list(seen.SYMBOLS)):
        raise RuntimeError('PARALLEL_EXIT_AUTHORIZATION_RULE_BUDGET')
    for key, value in AUTH.items():
        if c.get(key) != value:
            raise RuntimeError('PARALLEL_EXIT_AUTHORITY:' + key)
    if set(c['code_files_sha256']) != set(CODE):
        raise RuntimeError('PARALLEL_EXIT_CODE_COVERAGE')
    for path, sha in {**c['code_files_sha256'], **c['preserved_files_sha256'],
                      **c['ci_files_sha256']}.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('PARALLEL_EXIT_FROZEN_BYTES:' + path)
    if old.file_sha(ROOT / DESIGN) != c['design_sha256']:
        raise RuntimeError('PARALLEL_EXIT_DESIGN_BYTES')
    original = old.read(seen_run.CONTRACT)
    if (c['data_sha256'] != original['data_sha256']
            or c['cost_sha256'] != original['cost_sha256']
            or c['period_data_sha256'] != {'DEV2025': old.read(source.CONTRACT)['data_sha256'],
                                           'SEEN2026': original['data_sha256']}
            or c['prior_independent_comparison'] != original['prior_independent_comparison']):
        raise RuntimeError('PARALLEL_EXIT_DATA_COST_HISTORY')
    return c


def load_inputs(data_dir, c):
    # The bounded, previously authorized reader verifies full-file bytes opaquely
    # and decodes exactly3748 rows through2026-09-05T00Z. No raw archive path.
    policy, dev, four, access = seen.load_seen_inputs(data_dir, old.read(seen_run.CONTRACT))
    if (policy['cost_binding_sha256'] != c['cost_sha256']
            or policy['combined_data_sha256'] != c['data_sha256']):
        raise RuntimeError('PARALLEL_EXIT_INPUT_BINDING')
    dev_end = CALENDARS['KELTNER']['DEV2025'][1]
    original = {s: [r for r in rows if r['bar_close_ts'] <= dev_end]
                for s, rows in four.items()}
    if any(len(rows) != 2250 or rows[-1]['bar_close_ts'] != dev_end
           for rows in original.values()):
        raise RuntimeError('PARALLEL_EXIT_ORIGINAL_DEV_PREFIX')
    return policy, dev['cost_by_symbol'], {'DEV2025': original, 'SEEN2026': four}, access


def charge_result(raw, symbol, lane, stage, policy, costs, rows):
    result = {k: [] for k in ('trades', 'open_observations', 'events', 'trace')}
    for value in raw['trades']:
        t = old.charge(value, symbol, lane, stage, policy, costs, rows, seen.BAR)
        t.pop('trade_sha256', None)
        t.update(comparison_stage=stage, status='COMPLETED', evidence_type='REUSED_DEV_EXIT_COMPARISON',
                 independent=False, formal_credit=0, origin_key=source.prior.previous.source_key(t))
        t['trade_sha256'] = old.digest(t)
        result['trades'].append(t)
    for t in source.prior.charge_open(raw['open_positions'], symbol, stage, policy, costs, rows):
        t.pop('observation_sha256', None)
        t.update(lane_id=lane, evidence_type='REUSED_DEV_EXIT_COMPARISON', independent=False, formal_credit=0)
        t['origin_key'] = source.prior.previous.source_key(t)
        t['observation_sha256'] = old.digest(t)
        result['open_observations'].append(t)
    for key in ('events', 'trace'):
        result[key] = [dict(t, symbol=symbol, lane_id=lane, comparison_stage=stage, scenario=stage)
                       for t in raw[key]]
    result['audit'] = raw['audit']
    return result


def replay_stage(kind, bundles, rows_by, costs, policy, start, end, stage, fixed=None):
    lane = source.LANE if kind == 'Q0' else 'keltner_trend_main'
    result = {k: [] for k in ('trades', 'open_observations', 'events', 'trace')}
    result['admission'] = {}
    engine = qexit if kind == 'Q0' else kexit
    for symbol in sorted(rows_by):
        raw = engine.replay(rows_by[symbol], bundles[symbol], eval_start_ms=start, eval_end_ms=end,
                            enable_change=stage != 'P',
                            fixed_signal_indices=None if fixed is None else fixed[symbol])
        if kind == 'KELTNER' and stage == 'P':
            shared = old.common.evaluate_development_events(rows_by[symbol],
                [s['signal_index'] for s in bundles[symbol]['signals']],
                split_start_ms=rows_by[symbol][0]['bar_open_ts'], split_end_ms=end,
                interval_ms=seen.BAR, hold_bars=12)
            if raw['trades'] != shared['trades']:
                raise RuntimeError('PARALLEL_EXIT_KELTNER_SHARED_BATCH_PARITY')
            raw['audit']['disabled_whole_batch_shared_closed_parity'] = 'PASS'
        charged = charge_result(raw, symbol, lane, stage, policy, costs, rows_by[symbol])
        for key in result:
            if key != 'admission':
                result[key].extend(charged[key])
        result['admission'][symbol] = charged['audit']
    return result


def parent_parity(kind, period, parent):
    if kind == 'Q0':
        if period == 'DEV2025':
            prior = seen_run.original.load_parent(old.read(source.OUTPUT + '/receipt.json'))
        else:
            prior = json.loads(gzip.decompress((ROOT / seen_run.OUTPUT / 'unit_execution.json.gz').read_bytes()))
    elif period == 'DEV2025':
        prior = {'trades': [t for t in source.inputs.read_lines(ROOT / old.OUTPUT / 'baseline/trades.jsonl.gz')
                            if t['lane_id'] == 'keltner_trend_main']}
    else:
        return {'status': 'NATIVE_DISABLED_SHARED_EVALUATOR_PARITY', 'prior_same_calendar_ledger': False}
    fields = ('signal_ts', 'entry_ts', 'entry_price', 'exit_ts', 'exit_price', 'side',
              'gross_bps', 'net_bps', 'cost2x_net_bps', 'cost_bps', 'funding_bps', 'hold_ms')
    key = lambda t: (t['symbol'], t['signal_ts'], t['side'])
    a, b = ({key(t): t for t in v['trades']} for v in (parent, prior))
    if len(a) != len(parent['trades']) or set(a) != set(b):
        raise RuntimeError('PARALLEL_EXIT_PARENT_ORIGINS:' + kind + period)
    for origin in a:
        for field in fields:
            if a[origin][field] != b[origin][field]:
                raise RuntimeError('PARALLEL_EXIT_PARENT_ECONOMICS:' + kind + period + ':' + field)
    if kind == 'Q0':
        af = {key(t): t for t in parent['open_observations']}
        bf = {key(t): t for t in prior['open_observations']}
        if set(af) != set(bf):
            raise RuntimeError('PARALLEL_EXIT_PARENT_OPEN_ORIGINS')
        for origin in af:
            for field in ('entry_ts', 'entry_price', 'mark_ts', 'mark_price', 'gross_mark_bps',
                          'hypothetical_liquidation_net_mark_bps'):
                if af[origin][field] != bf[origin][field]:
                    raise RuntimeError('PARALLEL_EXIT_PARENT_OPEN_PARITY')
    return {'status': 'EXACT_PRESERVED_CLOSED_GEOMETRY_COST_PARITY', 'completed_T': len(a),
            'explicit_open_marks_T': len(parent['open_observations']),
            'old_closed_ledger_changed': False}


def artifact(name, value, verify_only):
    path = ROOT / OUTPUT / name
    raw = old.probe.canonical(value)
    payload = path.read_bytes() if path.exists() else gzip.compress(raw, mtime=0)
    if gzip.decompress(payload) != raw:
        raise RuntimeError('PARALLEL_EXIT_REPRODUCTION_DRIFT:' + name)
    old.probe.write_immutable(path, payload, verify_only=verify_only)
    return {'path': str(path.relative_to(ROOT)), 'file_sha256': old.file_sha(path)}


def run(data_dir, verify_only=False):
    c = authorize()
    out = ROOT / OUTPUT
    if (out / 'receipt.json').exists() and not verify_only:
        raise RuntimeError('PARALLEL_EXIT_ALLOCATIONS_CONSUMED_USE_VERIFY_ONLY')
    if verify_only and not (out / 'receipt.json').exists():
        raise RuntimeError('PARALLEL_EXIT_NO_RESULTS_TO_REPRODUCE')
    base_policy, costs, periods, access = load_inputs(Path(data_dir), c)
    kparent = next(t for t in old.read(old.FREEZE)['children'] if t['lane_id'] == 'keltner_trend_main')
    if old.digest(kparent) != c['keltner_parent_sha256']:
        raise RuntimeError('PARALLEL_EXIT_KELTNER_PARENT')
    results, artifacts = {}, {}
    for kind in CANDIDATES:
        for period, interval in CALENDARS[kind].items():
            start, end = interval
            four = {s: [r for r in rows if r['bar_close_ts'] <= end]
                    for s, rows in periods[period].items()}
            policy = {**base_policy, 'batch_id': c['batch_id'], 'receipt_sha256': c['receipt_sha256'],
                      'combined_data_sha256': c['period_data_sha256'][period],
                      'code_files_sha256': c['code_files_sha256'], 'development_interval_ms': interval}
            bundles = {}
            with old.probe.io_boundary([], out):
                for symbol, rows in four.items():
                    if kind == 'Q0':
                        daily = source.structure.aggregate_daily(rows, split_end_ms=end)
                        bundles[symbol] = source.structure.generate_signals(daily['daily'], eval_start_ms=start,
                                                                           eval_end_ms=end, require_preparation=True)
                    else:
                        bundles[symbol] = kexit.build_bundle(rows, kparent['executable_spec'],
                                                            eval_start_ms=start, eval_end_ms=end)
                parent = replay_stage(kind, bundles, four, costs, policy, start, end, 'P')
            parity = parent_parity(kind, period, parent)
            with old.probe.io_boundary([], out):
                fixed = {s: {t['signal_index'] for t in parent['trades'] + parent['open_observations']
                             if t['symbol'] == s} for s in four}
                direct = replay_stage(kind, bundles, four, costs, policy, start, end, 'FIXED', fixed)
                origins = lambda v: {(t['symbol'], t['signal_ts'], t['entry_ts'], t['entry_price'])
                                     for t in v['trades'] + v['open_observations']}
                if origins(direct) != origins(parent):
                    raise RuntimeError('PARALLEL_EXIT_FIXED_ENTRY_SET_DRIFT')
                full = replay_stage(kind, bundles, four, costs, policy, start, end, 'FULL')
                views = {'P': parent, 'FIXED': direct, 'FULL': full}
                stages = {name: metrics.build_stage(v['trades'], v['open_observations'], v['events'],
                                                    four, costs, policy, c['symbols'], start, end)
                          for name, v in views.items()}
                comparisons = {name: metrics.compare(stages['P'], stages[name], parent['trades'],
                    parent['open_observations'], views[name]['trades'], views[name]['open_observations'],
                    four, costs, start, end) for name in ('FIXED', 'FULL')}
                decision = metrics.candidate_decision(comparisons['FIXED'], comparisons['FULL'])
            name = kind + '_' + period
            record = {'candidate_id': CANDIDATES[kind], 'period': period, 'calendar_ms': interval,
                      'economic_rows_sha256_by_symbol': {s: old.digest(rows) for s, rows in four.items()},
                      'parent_parity': parity, 'stages': stages, 'comparisons': comparisons, 'decision': decision}
            artifacts[name] = artifact(name + '.json.gz', {'record': record, 'views': views}, verify_only)
            summary = deepcopy(record)
            for stage in summary['stages'].values():
                stage.pop('daily', None)
            for comparison in summary['comparisons'].values():
                comparison.pop('same_calendar_windows', None)
            results[name] = summary
    r = old.seal({**AUTH, 'schema': 'parallel.exit.dev.result.v1', 'batch_id': c['batch_id'],
                  'contract_sha256': c['receipt_sha256'], 'results': results, 'artifacts': artifacts,
                  'source_access': access, 'decoded_after_20260905_00UTC': 0,
                  'candidate_cumulative_before': 26, 'new_candidates_measured': 2,
                  'candidate_cumulative_after': 28, 'remaining_allocated_candidates': 0,
                  'candidate_period_evaluations': 4, 'fixed_full_comparison_views': 8,
                  'prior_seen_evaluation': '1/1_PRESERVED', 'prior_independent_comparison': c['prior_independent_comparison'],
                  'preserved_states': c['preserved_states'], 'data_reuse_history': c['data_reuse_history'],
                  'Gemini_actual_video': 'NOT_RUN', 'economic_adoption_automatic': False})
    old.probe.write_immutable(out / 'receipt.json', old.probe.canonical(r), verify_only=verify_only)
    old.probe.write_immutable(out / 'RESULTS.md', report(r), verify_only=verify_only)
    paths = [CONTRACT, DESIGN, OUTPUT + '/receipt.json', OUTPUT + '/RESULTS.md']
    paths += [v['path'] for v in artifacts.values()]
    durable = old.seal({**AUTH, 'result_receipt_sha256': r['receipt_sha256'],
                       'files_sha256': {p: old.file_sha(ROOT / p) for p in paths},
                       'code_files_sha256': c['code_files_sha256'],
                       'preserved_files_sha256': c['preserved_files_sha256']})
    old.probe.write_immutable(out / 'durable_receipt.json', old.probe.canonical(durable), verify_only=verify_only)
    return r


def report(r):
    # Deliberately generated from actual metrics and never source-selected examples.
    lines = ['# Q0 / Keltner exit comparison', '',
             'Both calendars are reused development evidence; independent=false. Equal nominal trade-bps, not account returns. Code PASS does not establish economic adoption.', '',
             '| Candidate / period | View | Closed/open | Net E | PF | Win% | Payoff | Cost2 E | Closed net | Marked DD | Max grouped loss | Exposure days |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    f = lambda v: 'NA' if v is None else f'{v:,.4f}'
    for name, record in r['results'].items():
        for view, value in record['stages'].items():
            m, d = value['metrics'], value['diagnostics']
            b = m['base_cost']
            vals = [b['expectancy_bps_per_trade'], b['PF'], None if b['win_rate'] is None else 100*b['win_rate'],
                    b['realized_payoff'], m['cost2x']['expectancy_bps_per_trade'], b['net_bps'],
                    value['marked_diagnostics']['marked_DD_trade_sum_bps'],
                    d['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'], m['total_exposure_symbol_days']]
            lines.append(f"| {name} | {view} | {b['completed_T']}/{m['open_observations']['T']} | " + ' | '.join(f(v) for v in vals) + ' |')
        lines += ['', name + ' decision: `' + json.dumps(record['decision'], ensure_ascii=False) + '`', '']
    lines += ['## Signals, costs and unfinished positions', '',
              '| Study | View | Signals | Gross E | Avg win/loss | Fee/funding | Total cost | Open gross/net/cost2 | Max simultaneous | Recovery days/open underwater days |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, record in r['results'].items():
        for view, value in record['stages'].items():
            m, md = value['metrics'], value['marked_diagnostics']
            b, o, cost = m['base_cost'], m['open_observations'], m['closed_cost_totals_bps']
            lines.append(f"| {name} | {view} | {m['raw_signals']} | {f(b['gross_expectancy_bps'])} | "
                + f"{f(b['average_win_bps'])}/{f(b['average_loss_bps'])} | {f(cost['fee_bps'])}/{f(cost['funding_bps'])} | "
                + f"{f(cost['cost_bps'])} | {f(o['gross_mark_bps'])}/{f(o['hypothetical_liquidation_net_mark_bps'])}/{f(o['hypothetical_liquidation_cost2x_net_mark_bps'])} | "
                + f"{m['exposure']['max_simultaneous_symbols']} | {f(md['max_completed_recovery_days'])}/{f(md['open_underwater_days'])} |")
    lines += ['', '## Exit effects and preservation', '',
              '| Study | View | Common CC/CO/OC/OO | Removed/new closed/open | Closed net delta | Original win retained | Large win amount retained/parent | Daily delta95 |',
              '|---|---|---|---|---:|---:|---:|---|']
    for name, record in r['results'].items():
        for view, comparison in record['comparisons'].items():
            a = comparison['attribution']; counts = a['counts']
            lines.append(f"| {name} | {view} | " + '/'.join(str(counts[k]) for k in ('CC','CO','OC','OO'))
                + ' | ' + '/'.join(str(counts[k]) for k in ('removed_C','removed_O','new_C','new_O'))
                + f" | {f(a['closed_net_delta_bps'])} | {f(a['winner']['amount_retention_lower'])} | "
                + f"{f(a['large_winner']['resolved_preserved_bps'])}/{f(a['large_winner']['parent_positive_bps'])} | "
                + str(comparison['uncertainty']['child_minus_parent_95pct_interval_bps_per_day']) + ' |')
    lines += ['', '## Closed-net decomposition', '',
              '| Study | View | Common loss improved/worsened | Winner profit cut/flipped loss/added | New net | Removed loss/profit | Cost/funding delta (already in net) |',
              '|---|---|---:|---:|---:|---:|---:|']
    for name, record in r['results'].items():
        for view, comparison in record['comparisons'].items():
            a, d = comparison['attribution'], comparison['net_decomposition']
            lines.append(f"| {name} | {view} | {f(d['common_loser_improvement_bps'])}/{f(d['common_loser_deterioration_bps'])} | "
                + '/'.join(f(d[k]) for k in ('common_winner_profit_cut_bps','common_winner_flipped_loss_bps','common_winner_profit_added_bps'))
                + f" | {f(a['new_completed_net_bps'])} | {f(a['removed_completed_parent_loss_bps'])}/{f(a['removed_completed_parent_winner_bps'])} | "
                + f"{f(a['closed_cost_delta_bps'])}/{f(a['closed_funding_delta_bps'])} |")
    lines += ['## Complete accounting', '',
              'Per-period compressed ledgers include every fill, trigger, event, open mark, UTC marked path, monthly/symbol concentration, paired block uncertainty, same-calendar loss/DD attribution and common/new/removed origin bridge. receipt.json retains all summary metrics.', '',
              'Q0 freezes the original entry channel upper. Keltner preserves original EMA20/50 seed, entry,12-bar maximum and absence of a separate SL. Full replay includes newly available opportunities; FIXED isolates original admitted entries and is a counterfactual accounting view.', '',
              'Native Keltner exact-end excluded horizon remains an explicit open mark. Open marks use the unchanged hypothetical full roundtrip research cost; no terminal forced fill. Original closed ledgers remain unchanged.', '',
              '2025 calendars: Q0 2025-01-29T00Z–2025-12-29T00Z; Keltner 2024-12-19T08Z–2025-12-29T08Z. 2026 both 2026-05-08T00Z–2026-09-05T00Z. Native calendar differences are preserved. No rows after2026-09-05T00Z decoded. Existing split labels in the authorized seen prefix do not confer independent validation.', '',
              '| Top5 | This batch |', '|---|---|',
              '| Primary | Preserved, no new candidate |', '| Broad | Preserved, no new candidate |',
              '| Break / Q0 lineage | Entry-channel-loss exit research child only; Q0 baseline unchanged |',
              '| Keltner V2 | Trend-invalidation exit research child only; parent unchanged |',
              '| Supertrend | Preserved, no new candidate |', '',
              'Candidate count26→28;2new candidates,4candidate-period applications,8fixed/full comparison views;0remaining. Previous26history, seen1/1 and independent0/1 NOT_RUN preserved. No retuning or further candidate.', '',
              'PR1195 observer code/calendar/source/cursor/schedule unchanged and never used as development input. No G5B replacement, G6 formal credit, account sizing, orders/live execution or paid externalAI. New child future validation would need its own prospective freeze/boundary and separate authorization; existing Q0 future data cannot be retroactively unused child evidence.', '']
    return '\n'.join(lines).encode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', type=Path)
    ap.add_argument('--verify-only', action='store_true')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    if args.check_only:
        c = authorize()
        print(json.dumps({'status': 'FROZEN_PREREGISTRATION_PASS', 'spec_sha256': c['receipt_sha256']}))
    else:
        if args.data_dir is None:
            ap.error('--data-dir required for economic evaluation')
        r = run(args.data_dir.resolve(), args.verify_only)
        print(json.dumps({'receipt_sha256': r['receipt_sha256'],
                          'results': {k: v['decision'] for k, v in r['results'].items()}}, indent=2))


if __name__ == '__main__':
    main()
