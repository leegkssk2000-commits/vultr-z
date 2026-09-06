"""One explicitly authorized seen-period evaluation of unchanged Q0 and B.

Separate evidence admission; original DEV/formal guards and receipts are sealed.
This module orchestrates existing execution and accounting, never an order route.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path

from backend.research.rebuild import q0_risk_entry_v1 as original
from backend.research.rebuild import q0_b_seen_adapter_v1 as adapter
from backend.research.rebuild import q0_b_seen_metrics_v1 as metrics

old = original.old
ROOT = old.ROOT
OUTPUT = 'research/development_evidence/Q0_B_SEEN_2026_V1'
CONTRACT = OUTPUT + '/SPEC.json'
DESIGN = OUTPUT + '/DESIGN.md'
EVIDENCE = 'SEEN_DATA_REPLICATION'
AUTHORIZATION = 'EXPLICIT_USER_Q0_B_SEEN_PERIOD_REPLICATION_ONE_AFTER_INDEPENDENT_NOT_RUN'
ORIGINAL_RESULT = 'edab29b1ca3db8c75c8e29a439f6076e2dd9acd181b32665760c7915976ebb98'
BUDGET = {
    'candidate_cumulative_before': 26, 'candidate_cumulative_after': 26,
    'candidate_remaining': 0, 'new_candidates': 0,
    'independent_comparison_allocated': 1, 'independent_comparison_used': 0,
    'seen_evaluation_allocated': 1, 'seen_evaluation_used_before': 0,
    'exact_reproductions_are_new_evaluations': False,
    'fixed_C_is_new_candidate': False, 'automatic_extension': False,
    'paid_external_AI_calls': 0,
}
CODE = ['backend/research/rebuild/' + name for name in (
    'q0_b_seen_replication_v1.py', 'q0_b_seen_adapter_v1.py', 'q0_b_seen_metrics_v1.py',
    'test_q0_b_seen_replication_v1.py', 'test_q0_b_seen_adapter_v1.py',
    'test_q0_b_seen_metrics_v1.py')]
AUTH = {**old.probe.DEV_AUTH, 'evidence_type': EVIDENCE, 'independent': False,
        'operating_adoption': False, 'G5B_changed': False, 'operating_changed': False,
        'G6_authorized': False, 'G7_formal_authorized': False,
        'G11_formal_authorized': False, 'actual_account_sizing': False}


def authorize():
    c = original.read(CONTRACT)
    old.probe.verify_seal(c, 'SEEN_SPEC')
    base, q0, q1, q2 = original.authorize()
    result = original.read(original.OUTPUT + '/receipt.json')
    old.probe.verify_seal(result, 'ORIGINAL_RISK_RESULT')
    if result['receipt_sha256'] != ORIGINAL_RESULT:
        raise RuntimeError('SEEN_ORIGINAL_B_RESULT_IDENTITY')
    if c['authorization'] != AUTHORIZATION or c['budget'] != BUDGET:
        raise RuntimeError('SEEN_AUTHORIZATION_OR_BUDGET')
    for k, v in AUTH.items():
        if c.get(k) != v:
            raise RuntimeError('SEEN_AUTHORITY:' + k)
    if (c['evaluation_id'] != 'Q0_B_SEEN_2026_V1'
            or c['batch_id'] != c['evaluation_id']
            or c['new_evaluation_outcomes_seen_at_freeze'] is not False
            or c['underlying_market_history_previously_used'] is not True
            or c['evaluation_interval_ms'] != [1778198400000, 1788566400000]
            or c['original_raw_candidate_interval_ms'] != [1778169600000, 1788609600000]):
        raise RuntimeError('SEEN_FROZEN_SCOPE')
    if c['reference'] != base['reference'] or c['goal'] != original.GOAL:
        raise RuntimeError('SEEN_REFERENCE_OR_GOAL_DRIFT')
    if (c['symbols'] != base['symbols'] or c['Q0_receipt_sha256'] != q0['receipt_sha256']
            or c['B_receipt_sha256'] != ORIGINAL_RESULT
            or c['original_DEV_data_sha256'] != base['data_sha256']
            or c['cost_sha256'] != base['cost_sha256']):
        raise RuntimeError('SEEN_FROZEN_PARENT_LINEAGE')
    if set(c['code_files_sha256']) != set(CODE):
        raise RuntimeError('SEEN_CODE_COVERAGE')
    expected = {**base['preserved_files_sha256'], **base['code_files_sha256']}
    expected.update({str(p.relative_to(ROOT)): old.file_sha(p)
                     for p in (ROOT / original.OUTPUT).iterdir() if p.is_file()})
    for path, sha in expected.items():
        if c['preserved_files_sha256'].get(path) != sha:
            raise RuntimeError('SEEN_ORIGINAL_PRESERVATION:' + path)
    for path, sha in {**c['preserved_files_sha256'], **c['code_files_sha256']}.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('SEEN_FROZEN_BYTES:' + path)
    if old.file_sha(ROOT / DESIGN) != c['design_sha256']:
        raise RuntimeError('SEEN_DESIGN_BYTES')
    return c


def artifact(name, value, verify_only):
    path = ROOT / OUTPUT / name
    raw = old.probe.canonical(value)
    payload = path.read_bytes() if path.exists() else gzip.compress(raw, mtime=0)
    if gzip.decompress(payload) != raw:
        raise RuntimeError('SEEN_REPRODUCTION_DRIFT:' + name)
    old.probe.write_immutable(path, payload, verify_only=verify_only)
    return {'path': str(path.relative_to(ROOT)), 'file_sha256': old.file_sha(path)}


def run(data_dir, verify_only=False):
    c = authorize()
    out = ROOT / OUTPUT
    if (out / 'receipt.json').exists() and not verify_only:
        raise RuntimeError('SEEN_EVALUATION_CONSUMED_USE_VERIFY_ONLY')
    if verify_only and not (out / 'receipt.json').exists():
        raise RuntimeError('SEEN_NO_RESULT_TO_REPRODUCE')
    policy, dev, four, access = adapter.load_seen_inputs(data_dir, c)
    start, end = c['evaluation_interval_ms']
    with old.probe.io_boundary([], out):
        market = adapter.frozen_market_state(four, c['symbols'], start, end)
        unit = adapter.replay_q0(four, dev['cost_by_symbol'], policy,
                                 c['symbols'], start, end, evidence_type=EVIDENCE)
        fields = ('lane_id', 'symbol', 'signal_ts', 'entry_ts', 'side')
        causal = lambda rows: [{k: t[k] for k in fields} for t in rows]
        entry = original.weights.entry_weights(market, causal(unit['trades']),
                                                causal(unit['open_observations']))
        measured = metrics.build(unit['trades'], unit['open_observations'], unit['events'],
                                 four, dev['cost_by_symbol'], policy, c['symbols'],
                                 start, end, entry)
    if measured.get('stages'):
        stages = measured['stages']
        measured['economic_questions'] = {
            name: {key: stages[name]['metrics'][field] > 0 for key, field in (
                ('terminal_net_positive', 'terminal_net_amount_bps'),
                ('terminal_cost2_positive', 'terminal_cost2x_net_amount_bps'))}
            for name in ('A_Q0', 'B_RISK')}
        measured['economic_questions']['B_minus_C_terminal_net_bps'] = (
            stages['B_RISK']['metrics']['terminal_net_amount_bps']
            - stages['C_FIXED']['metrics']['terminal_net_amount_bps'])
        measured['economic_questions']['independent_increment_supported'] = False
    artifacts = {
        'unit_execution': artifact('unit_execution.json.gz', unit, verify_only),
        'market_and_entry_weights': artifact('market_and_entry_weights.json.gz',
                                            {'market': market, 'entry_weights': entry}, verify_only),
        'weighted_accounting': artifact('weighted_accounting.json.gz', measured, verify_only),
    }
    summary = deepcopy(measured)
    for stage in summary.get('stages', {}).values():
        stage.pop('daily', None)
        stage.pop('ledger', None)
        stage.get('exposure', {}).pop('holding_intervals', None)
    # Full per-position/window paths remain in the immutable accounting artifact.
    summary.pop('windows', None)
    for row in summary.get('attribution', {}).values():
        row.pop('position_contributions', None)
    ws = [v['weight'] for v in entry.values()]
    r = old.seal({
        **AUTH, 'schema': 'q0.b.seen.replication.result.v1',
        'evaluation_id': c['evaluation_id'], 'contract_sha256': c['receipt_sha256'],
        'Q0_receipt_sha256': c['Q0_receipt_sha256'], 'B_receipt_sha256': ORIGINAL_RESULT,
        'preserved_states': c['preserved_states'], 'prior_independent_comparison': c['prior_independent_comparison'],
        'budget': {**BUDGET, 'seen_evaluation_used': 1},
        'evaluation_interval_ms': c['evaluation_interval_ms'],
        'original_raw_candidate_interval_ms': c['original_raw_candidate_interval_ms'],
        'reference': {**market['reference'], 'sigma_ref': market['sigma_ref']},
        'weight_summary': {'T': len(ws), 'minimum': min(ws, default=None),
                           'maximum': max(ws, default=None),
                           'mean_per_entry': sum(ws) / len(ws) if ws else None,
                           'reduced_entries': sum(w < 1 for w in ws)},
        'accounting': summary, 'artifacts': artifacts, 'source_access': access,
        'data_sha256': c['data_sha256'], 'cost_sha256': c['cost_sha256'],
        'symbols': c['symbols'], 'data_reuse_history': c['data_reuse_history'],
        'future_readiness': c['future_readiness'],
        'paid_external_AI_calls': 0, 'Gemini_actual_video': 'NOT_RUN',
        'warmup_pnl_evaluated': False, 'initial_positions': 'FLAT',
        'continuous_carryover_test': False,
    })
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
    f = lambda v: 'NA' if v is None else f'{v:,.4f}'
    a = r['accounting']
    names = ('A_Q0', 'B_RISK', 'C_FIXED')
    lines = ['# Frozen Q0/B — 2026 seen-period replication', '',
             '**evidence_type=SEEN_DATA_REPLICATION; independent=false; formal_credit=0; operating_adoption=false.**', '',
             'Entries: 2026-05-08 00:00 UTC inclusive to 2026-09-05 00:00 exclusive. Final mark at September5 00UTC uses the last completed4h close. Both start flat. Channel state uses the original full historical prefix, without warmup PnL or carried orders/positions.', '',
             'The whole original raw candidate pool (May7 16UTC–September5 12UTC) was used by prior related research. Different generations/file hashes do not establish unused data. Prior independent comparison stays NOT_RUN, used0/1.', '',
             'All monetary values are weighted fixed-reference-notional amounts in bps units, not account returns or account MDD. C is an ex-post same-average-notional-holding control, not an executable input. Research price-taker cost model only; signed funding/fills and nonlinear impact are unbound.', '',
             '## A/B/C economics and risk', '',
             '| Metric | Q0 A | Entry allocation B | Fixed exposure C |',
             '|---|---:|---:|---:|']
    ss = a.get('stages', {})
    if ss:
        rows = [
            ('Signals', lambda s: s['metrics']['raw_signals']),
            ('Closed / open', lambda s: f"{s['metrics']['base_cost']['completed_T']} / {s['metrics']['open_observations']['T']}"),
            ('Unit win rate %', lambda s: f(100 * s['metrics']['base_cost']['win_rate']) if s['metrics']['base_cost']['win_rate'] is not None else 'NA'),
            ('Closed gross / T', lambda s: f(s['metrics']['base_cost']['gross_expectancy_bps'])),
            ('Closed net / T', lambda s: f(s['metrics']['base_cost']['expectancy_bps_per_trade'])),
            ('Amount PF', lambda s: f(s['metrics']['base_cost']['PF'])),
            ('Mean win / loss', lambda s: f(s['metrics']['base_cost']['average_win_bps']) + ' / ' + f(s['metrics']['base_cost']['average_loss_bps'])),
            ('Realized amount payoff', lambda s: f(s['metrics']['base_cost']['realized_payoff'])),
            ('Closed cost2 net / T', lambda s: f(s['metrics']['cost2x']['expectancy_bps_per_trade'])),
            ('Closed net amount', lambda s: f(s['metrics']['base_cost']['net_bps'])),
            ('Open hypothetical net mark', lambda s: f(s['metrics']['open_observations']['hypothetical_liquidation_net_mark_bps'])),
            ('Terminal net amount', lambda s: f(s['metrics']['terminal_net_amount_bps'])),
            ('Terminal cost2 net amount', lambda s: f(s['metrics']['terminal_cost2x_net_amount_bps'])),
            ('Daily marked drawdown', lambda s: f(s['marked_diagnostics']['marked_DD_trade_sum_bps'])),
            ('Max completed marked recovery days', lambda s: f(s['marked_diagnostics']['max_completed_recovery_days'])),
            ('Unrecovered at end / underwater days', lambda s: str(s['marked_diagnostics']['unrecovered_at_end']) + ' / ' + f(s['marked_diagnostics']['open_underwater_days'])),
            ('Maximum simultaneous-close-group losing run', lambda s: f(s['diagnostics']['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'])),
            ('Notional-weighted position-days', lambda s: f(s['exposure']['nominal_weighted_position_days'])),
            ('Max simultaneous notional slots', lambda s: f(s['exposure']['max_simultaneous_nominal_weighted_open_slots'])),
            ('Original all-winner amount retained', lambda s: f(s['original_profit_retention']['all_winners']['preserved_amount_bps'])),
            ('Current-period A top3 amount retained / %', lambda s: f(s['current_period_top3_winner_retention']['preserved_amount_bps']) + ' / ' + f(100*s['current_period_top3_winner_retention']['amount_retention']) if s['current_period_top3_winner_retention']['amount_retention'] is not None else 'NA'),
            ('Original top-decile winner amount retained / %', lambda s: f(s['original_profit_retention']['original_top_decile_winners']['preserved_amount_bps']) + ' / ' + f(100*s['original_profit_retention']['original_top_decile_winners']['amount_retention']) if s['original_profit_retention']['original_top_decile_winners']['amount_retention'] is not None else 'NA'),
            ('Closed fees / funding / total cost', lambda s: ' / '.join(f(s['metrics']['closed_cost_totals_bps'][k]) for k in ('fee_bps','funding_bps','cost_bps'))),
        ]
        for label, fn in rows:
            lines.append('| ' + label + ' | ' + ' | '.join(str(fn(ss[n])) for n in names) + ' |')
        lines += ['', 'Frozen reference: ' + str(r['reference']) + '.',
                  'Entry weights: ' + str(r['weight_summary']) + '.',
                  'C normalization: ' + str(a['control']) + '.', '',
                  '## Same-trade amount attribution', '',
                  '| Contribution | B minus A | B minus C |', '|---|---:|---:|']
        for label, key in [('Saved original loss amount', 'loss_amount_reduction_bps_signed'),
                           ('Foregone original winner amount', 'foregone_winner_amount_bps_signed'),
                           ('Cost saving already included in net', 'closed_cost_amount_saving_bps_signed')]:
            lines.append('| ' + label + ' | ' + ' | '.join(f(a['attribution'][n][key]) for n in ('B_minus_A','B_minus_C')) + ' |')
        lines += ['', 'No removed/new trades. Cost saving is already included in net. Different stages\' maximum losing-run or DD extrema are not same-trade causal contributions.', '',
                  '## Monthly marked net amounts', '', '| Month | A | B | C | B−C |','|---|---:|---:|---:|---:|']
        for month in sorted(ss['A_Q0']['by_mark_month']):
            values = [ss[n]['by_mark_month'][month]['net_bps'] for n in names]
            lines.append('| ' + month + ' | ' + ' | '.join(f(v) for v in values + [values[1]-values[2]]) + ' |')
        lines += ['', '## Symbol terminal net amounts', '', '| Symbol | A | B | C | B−C |','|---|---:|---:|---:|---:|']
        for symbol in r['symbols']:
            values = [ss[n]['by_symbol_marked'].get(symbol,{}).get('terminal_net_bps',0) for n in names]
            lines.append('| ' + symbol + ' | ' + ' | '.join(f(v) for v in values + [values[1]-values[2]]) + ' |')
    else:
        lines += ['', 'Control undefined: insufficient total holding exposure. Unit results and A/B totals:',
                  '```json', json.dumps({k: a.get(k) for k in ('unit_metrics', 'A_B_monetary_totals', 'control')}, indent=2, sort_keys=True), '```']
    lines += ['', '## Frozen technical decision and dependence', '',
              '```json', json.dumps({k:v for k,v in a.items() if k in ('decision','dependence','uncertainty','sufficiency','economic_questions')}, indent=2, sort_keys=True), '```', '',
              'The unchanged numerical goal does not grant independent validation or adoption. All original sign cohorts, winner retention, per-stage recoveries, same-calendar marked-DD contributions and full paths are in weighted_accounting.json.gz. Outcome-based groups are diagnostics only.', '',
              'Paired noncircular30day/1000draw/seed1178 uncertainty conditions on realized C. Long holds and market clusters may exceed30days; prior data reuse and model selection remain uncorrected. Counts are not independent samples.', '',
              '## Preserved budget and operational boundaries', '',
              'Candidate cumulative26, candidate remaining0, new candidates0. Separate seen-period economic evaluation1/1. Independent comparison0/1 and priorNOT_RUN preserved. Exact result reproduction is not another evaluation. Q0/Q1/Q2/B original states unchanged. No deploy, G5B replacement, account sizing, formal credit or new paid AI.', '',
              'Future collection/validation is not activated by this result. See DESIGN.md and receipt.future_readiness for actual source paths and missing minimal prospective connection. It did not block this authorized replication.', '']
    return '\n'.join(lines).encode()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', type=Path, required=True)
    ap.add_argument('--verify-only', action='store_true')
    ap.add_argument('--check-dev-only', action='store_true')
    args = ap.parse_args()
    if args.check_dev_only:
        print(json.dumps(adapter.verify_dev_parity(args.data_dir.resolve()), indent=2))
    else:
        r = run(args.data_dir.resolve(), args.verify_only)
        print(json.dumps({'receipt': r['receipt_sha256'], 'decision': r['accounting'].get('decision'),
                          'budget': r['budget'], 'evidence_type': EVIDENCE, 'independent': False}, indent=2))
