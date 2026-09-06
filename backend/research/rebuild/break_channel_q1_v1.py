"""One explicitly allocated Q0 exit continuation; sealed history stays unchanged."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path

from backend.research.rebuild import break_channel_source_v1 as prior
from backend.research.rebuild import break_channel_q1_structure_v1 as execution
from backend.research.rebuild import break_channel_q1_metrics_v1 as bridge

old = prior.old
ROOT = old.ROOT
OUTPUT = 'research/development_evidence/BREAK_CHANNEL_Q1_20260906_V1'
CONTRACT = OUTPUT + '/SPEC.json'
SOURCE = OUTPUT + '/DESIGN.md'
DIAGNOSIS = OUTPUT + '/Q0_DIAGNOSIS.json'
BUDGET = {'previous_applications': 24, 'allocated_new_trials': 1,
          'Q1': 1, 'cumulative_after': 25, 'Q2_authorized': False,
          'automatic_extension': False, 'paid_external_AI_calls': 0}
RULE = {
    'id': 'Q1_CONFIRMED_PREPARED_CHANNEL_LOWER_RATCHET_NEXT_OPEN',
    'entry': 'Exact Q0 prepared UP, initial lower SL, next-open admission and original DOWN conflict priority.',
    'update': 'While held, a strictly post-entry existing Q0 prepared-UP confirmation can raise effective SL to max(currentSL,confirmed lowerD). Never lower, resize or queue entry.',
    'activation': 'Only from the next 4h open after that confirming daily close; no use of the confirming bar low to trigger a newly raised stop.',
    'priority': 'Activate already scheduled higher SL; gap SL at observed open; existing bearish next-open exit; intrabar SL. Original no same-open reversal and close-signal occupancy phases retained.',
    'fill': 'Gap at observed open, intrabar at effective SL with 4h close timing upperbound. Original initial SL remains separately recorded.',
    'terminal': 'No orders at common end, no forced close; symmetric full-cost hypothetical open mark, exact Q0 convention.',
    'cost': 'Unchanged frozen fee/spread/impact/slippage/funding and20bpsfloor; all-cost2x; funding elapsed recomputed.',
    'comparison': 'EXIT_CHANGE: all Q0 completed/open entries fixed, then all original UP opportunities chronological. P/Q0 reused sealed observations; no Q-minus rerun.',
}
GOAL = {
    'primary': 'Reduce total symbol-day exposure in BOTH fixed-entry and full replay while preserving aggregate terminal marked PnL.',
    'aggregate_terminal_retention_min': 1.0,
    'large_winner_capped_retention_min': 0.90,
    'tradeoff': 'DESIGN_PRIOR study-only: up to10% of original top-decile winner amount may be lost only if aggregate terminal PnL is fully preserved in both stages. No full-replay marked-DD or grouped-loss-run deterioration allowed.',
    'minimum_closed_T': 6,
    'research_reference_requires_no_open_positions': True,
    'uncertainty': 'Same paired30day1000draw seed1178 descriptive reusedDEV interval; crossingzero blocks a strong DEV claim, not an observational study-goal reference. Never formal PASS.',
    'official_SSOT_modified': False,
}


def read_local(path):
    return json.loads((ROOT / path).read_text())


def authorize():
    c = read_local(CONTRACT)
    old.probe.verify_seal(c, 'Q1_SPEC')
    if c['authorization'] != 'EXPLICIT_USER_ONE_Q1_AFTER_PR1190':
        raise RuntimeError('Q1_AUTHORIZATION_REQUIRED')
    if c['budget'] != BUDGET or c['rule'] != RULE or c['goal'] != GOAL or c['outcomes_seen_at_freeze'] is not False:
        raise RuntimeError('Q1_FROZEN_RULE_OR_ALLOCATION_DRIFT')
    for k, v in old.probe.DEV_AUTH.items():
        if c.get(k) != v:
            raise RuntimeError('Q1_AUTHORITY_DRIFT:' + k)
    for k in ('validation_access', 'OOS_access', 'G5B_changed', 'G6_authorized', 'operating_changed'):
        if c.get(k) is not False:
            raise RuntimeError('Q1_PROTECTED_BOUNDARY:' + k)
    p = read_local(prior.OUTPUT + '/receipt.json')
    old.probe.verify_seal(p, 'Q0_RECEIPT')
    if p['budget']['cumulative_after'] != 24 or p['receipt_sha256'] != c['Q0_receipt_sha256']:
        raise RuntimeError('Q1_PRIOR_ALLOCATION_IDENTITY')
    if p['comparisons']['P_to_Q']['decision']['decision'] != 'DEV_INCONCLUSIVE':
        raise RuntimeError('Q0_STATUS_DRIFT')
    for path, sha in {**c['code_files_sha256'], **c['preserved_files_sha256']}.items():
        if old.file_sha(ROOT / path) != sha:
            raise RuntimeError('Q1_FROZEN_IDENTITY:' + path)
    return c


def read_lines(path):
    with gzip.open(ROOT / path, 'rt') as f:
        return [json.loads(line) for line in f]


def large_retention(parent, child, opened):
    """Same original top-decile definition; unfinished profit is a bound only."""
    key = prior.prior.previous.source_key
    winners = sorted((t for t in parent if t['net_bps'] > 0), key=lambda t: (-t['net_bps'], key(t)))
    large = winners[:math.ceil(len(winners) * .1)]
    c = {key(t): t for t in child}
    o = {key(t): t for t in opened}
    amount = sum(t['net_bps'] for t in large)
    preserved = sum(min(t['net_bps'], max(0., c[key(t)]['net_bps'])) for t in large if key(t) in c)
    unresolved = sum(t['net_bps'] for t in large if key(t) in o)
    return {'parent_T': len(large), 'parent_positive_bps': amount,
            'preserved_bps': preserved, 'unresolved_parent_positive_bps': unresolved,
            'lower': preserved / amount if amount else None,
            'upper': (preserved + unresolved) / amount if amount else None,
            'original_keys': [key(t) for t in large], 'basis': 'CAPPED_ORIGINAL_COMPLETED_TOP_DECILE_WINNERS'}


def study_decision(metrics, diagnostics, marked, large, uncertainty):
    q0 = metrics['Q0']; checks = {}; absolute = {}
    for s in ('Q1_fixed', 'Q1'):
        m = metrics[s]; b = m['base_cost']
        absolute[s] = {
            'sample': b['completed_T'] >= GOAL['minimum_closed_T'] and all(b[k] is not None for k in ('PF', 'realized_payoff', 'expectancy_bps_per_trade')),
            'positive_net': b['net_bps'] > 0,
            'positive_expectancy': b['expectancy_bps_per_trade'] is not None and b['expectancy_bps_per_trade'] > 0,
            'PF': b['PF'] is not None and b['PF'] > 1,
            'payoff': b['realized_payoff'] is not None and b['realized_payoff'] >= 1,
            'cost2x': m['cost2x']['net_bps'] > 0,
        }
        checks[s + '_exposure_reduced'] = m['total_exposure_symbol_days'] < q0['total_exposure_symbol_days']
        checks[s + '_aggregate_terminal_preserved'] = m['closed_plus_hypothetical_terminal_mark_bps'] >= q0['closed_plus_hypothetical_terminal_mark_bps'] * GOAL['aggregate_terminal_retention_min']
        checks[s + '_large_profit_preserved'] = large[s]['lower'] is not None and large[s]['lower'] >= GOAL['large_winner_capped_retention_min']
        checks[s + '_no_unfinished_positions'] = m['open_observations']['T'] == 0
    checks['full_marked_DD_not_worse'] = marked['Q1']['marked_DD_trade_sum_bps'] <= marked['Q0']['marked_DD_trade_sum_bps']
    loss = lambda s: diagnostics[s]['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps']
    checks['full_grouped_loss_run_not_worse'] = loss('Q1') <= loss('Q0')
    met = all(checks.values()) and all(all(x.values()) for x in absolute.values())
    ci = uncertainty['Q0_to_Q1']['child_minus_parent_95pct_interval_bps_per_day']
    strong = ci[0] is not None and ci[0] > 0
    state = 'DEV_PROMISING_NO_CREDIT' if met and strong else 'DEV_INCONCLUSIVE' if met else 'DEV_REJECT'
    if any(not x['sample'] for x in absolute.values()): state = 'INSUFFICIENT'
    study_screen = state
    closed_screen = ('INSUFFICIENT' if any(not x['sample'] for x in absolute.values()) else
                     'POSITIVE_CLOSED_ECONOMICS' if all(all(x.values()) for x in absolute.values()) else 'DEV_REJECT')
    unresolved = any(metrics[s]['open_observations']['T'] for s in ('Q1_fixed', 'Q1'))
    if unresolved: state = 'DEV_INCONCLUSIVE'
    return {'comparison_type': 'EXIT_CHANGE', 'study_goal_met': met,
            'research_reference': 'Q1' if met else 'Q0', 'Q0_original_status': 'DEV_INCONCLUSIVE',
            'decision': state, 'study_screen_decision': study_screen, 'closed_absolute_screen_decision': closed_screen,
            'overall_blocker': 'UNRESOLVED_TERMINAL_POSITIONS' if unresolved else None,
            'checks': checks, 'absolute_economic_checks': absolute,
            'failed_checks': [k for k, v in checks.items() if not v] + [s + ':' + k for s, items in absolute.items() for k, v in items.items() if not v],
            'increment_lower_95_positive': strong, 'formal_pass': False, 'operating_adoption': False,
            'research_reference_is_operating_promotion': False, 'Q2_authorized': False,
            'code_test_PASS_is_economic_PASS': False}


def report(r):
    f = lambda v: 'NA' if v is None else f'{v:.4f}'
    lines = [(ROOT / SOURCE).read_text().rstrip(), '', '## Measured fixed-entry and lifecycle outcomes', '',
             'Same Q0 calendar, symbols, costs and equal notional. These are trade-bps, not account return/MDD or equal-risk sizing.', '',
             '| Stage | Signals | Closed/open | GrossE | NetE | PF | Win% | AvgWin / AvgLoss | Payoff | Cost2E | Closed net | Terminal net |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in ('P', 'Q0', 'Q1_fixed', 'Q1'):
        m = r['metrics'][s]; b = m['base_cost']
        vals = [b['gross_expectancy_bps'], b['expectancy_bps_per_trade'], b['PF'], None if b['win_rate'] is None else b['win_rate'] * 100]
        lines.append(f"| {s} | {m['raw_signals']} | {b['completed_T']}/{m['open_observations']['T']} | " + ' | '.join(f(v) for v in vals) + f" | {f(b['average_win_bps'])} / {f(b['average_loss_bps'])} | {f(b['realized_payoff'])} | {f(m['cost2x']['expectancy_bps_per_trade'])} | {f(b['net_bps'])} | {f(m['closed_plus_hypothetical_terminal_mark_bps'])} |")
    lines += ['', '| Stage | Marked DD | Grouped loss-run | Exposure days | Max simultaneous | Fees / funding / all costs | Large winner retention |', '|---|---:|---:|---:|---:|---:|---:|']
    for s in ('P', 'Q0', 'Q1_fixed', 'Q1'):
        m = r['metrics'][s]; co = m['closed_cost_totals_bps']; large = r['large_winner_preservation'].get(s)
        lines.append(f"| {s} | {f(r['marked_diagnostics'][s]['marked_DD_trade_sum_bps'])} | {f(r['diagnostics'][s]['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'])} | {f(m['total_exposure_symbol_days'])} | {m['exposure']['max_simultaneous_symbols']} | {f(co['fee_bps'])} / {f(co['funding_bps'])} / {f(co['cost_bps'])} | {f(large['lower'] if large else None)} |")
    lines += ['', '| Comparison | Common CC/CO/OC/OO | Removed C/O | New C/O | Closed net delta | Both-side terminal delta | Added closed costs |', '|---|---|---|---|---:|---:|---:|']
    for name, a in r['comparisons'].items():
        n = a['counts']
        lines.append('| ' + name + ' | ' + '/'.join(str(n[k]) for k in ('CC','CO','OC','OO')) + f" | {n['removed_C']}/{n['removed_O']} | {n['new_C']}/{n['new_O']} | {f(a['closed_net_delta_bps'])} | {f(a['marked_delta_bps_not_realized'])} | {f(a['closed_cost_delta_bps'])} |")
    lines += ['', '| Comparison | Saved common losses | Cut positive winner profit | Worse losses on winners | Removed loss / winner profit | New completed net |', '|---|---:|---:|---:|---:|---:|']
    for name, a in r['comparisons'].items():
        e = a['resolved_common_effects']
        lines.append(f"| {name} | {f(e['saved_common_loss_bps'])} | {f(e['cut_positive_winner_profit_bps'])} | {f(e['additional_loss_on_parent_winners_bps'])} | {f(a['removed_completed_parent_loss_bps'])} / {f(a['removed_completed_parent_winner_bps'])} | {f(a['new_completed_net_bps'])} |")
    lines += ['', 'Decision: **' + r['decision']['decision'] + '**. Study goal met: **' + str(r['decision']['study_goal_met']) + '**. Research reference: **' + r['decision']['research_reference'] + '**. Formal/operating adoption: **false**.', '',
              'Failed study checks: ' + ', '.join(r['decision']['failed_checks']), '',
              '## Same-calendar Q0 drawdown window', '',
              'Window pinned from Q0 before Q1 results. Per-trade starting/ending marks reconcile this calendar change; differences between unrelated extrema are not causal contribution.', '',
              '| Stage | Window gross change | Cost change | Net marked change |', '|---|---:|---:|---:|']
    for s, w in r['same_calendar_windows'].items():
        d = w['totals']['delta']
        lines.append(f"| {s} | {f(d['gross_bps'])} | {f(d['cost_bps'])} | {f(d['net_bps'])} |")
    lines += ['', '| Comparison | Marked daily increment | Paired30day95% interval |', '|---|---:|---|']
    for name, u in r['uncertainty'].items():
        lines.append(f"| {name} | {f(u['child_minus_parent_mean_daily_bps'])} | {u['child_minus_parent_95pct_interval_bps_per_day']} |")
    lines += ['', '| Stage | OpenT | Gross mark | Hypothetical cost/net/cost2net | Open days | Top-symbol / top-decile profit share |', '|---|---:|---:|---|---:|---|']
    for s in ('P', 'Q0', 'Q1_fixed', 'Q1'):
        m = r['metrics'][s]; o = m['open_observations']; cc = m['concentration']
        lines.append(f"| {s} | {o['T']} | {f(o['gross_mark_bps'])} | {f(o['hypothetical_liquidation_cost_bps'])}/{f(o['hypothetical_liquidation_net_mark_bps'])}/{f(o['hypothetical_liquidation_cost2x_net_mark_bps'])} | {f(o['exposure_symbol_days'])} | {f(cc['top_one_symbol_profit_share'])}/{f(cc['top_decile_winners_share'])} |")
    lines += ['', '## Monthly closed gross / net', '', '| Month | P | Q0 | Q1 fixed | Q1 full |', '|---|---:|---:|---:|---:|']
    months = sorted({k for m in r['metrics'].values() for k in m['by_exit_month']})
    for month in months:
        vals = [r['metrics'][s]['by_exit_month'].get(month, {'gross_bps': 0, 'net_bps': 0}) for s in ('P', 'Q0', 'Q1_fixed', 'Q1')]
        lines.append('| ' + month + ' | ' + ' | '.join(f(v['gross_bps']) + ' / ' + f(v['net_bps']) for v in vals) + ' |')
    lines += ['', '## Symbol closed net and concentration', '', '| Symbol | P | Q0 | Q1 fixed | Q1 full |', '|---|---:|---:|---:|---:|']
    for symbol in r['symbols']:
        lines.append('| ' + symbol + ' | ' + ' | '.join(f(r['metrics'][s]['concentration']['by_symbol_closed_net_bps'].get(symbol, 0)) for s in ('P', 'Q0', 'Q1_fixed', 'Q1')) + ' |')
    lines += ['', 'Open observations, symmetric attribution CC/CO/OC/OO, per-trade window contributions, cost/funding, recovery and concentration are in receipt.json and linked ledgers. No open is forced closed. Reused DEV block intervals do not claim independent validation.', '',
              'Prior24 preserved; Q1 consumes ordinal25; remaining0; Q2 unauthorized. P/Q0/Q-minus historical receipts unchanged. Q0 retains DEV_INCONCLUSIVE. validation/OOS decoded0; no G5B/operating change; executionNONE/orderBLOCKED/liveBLOCKED; paid externalAI0.', '']
    return '\n'.join(lines).encode()


def run(data_dir, verify_only=False):
    c = authorize(); out = ROOT / OUTPUT
    if (out / 'receipt.json').exists() and not verify_only:
        raise RuntimeError('Q1_ALLOCATION_CONSUMED_USE_VERIFY_ONLY')
    p, dev, four, _, access = prior.inputs.load_inputs(data_dir)
    if p['combined_data_sha256'] != c['data_sha256'] or p['cost_binding_sha256'] != c['cost_sha256']:
        raise RuntimeError('Q1_DATA_COST_DRIFT')
    if sorted(four) != c['symbols']: raise RuntimeError('Q1_UNIVERSE_DRIFT')
    start, end = c['evaluation_interval_ms']
    oldc = read_local(prior.CONTRACT)
    if [start, end] != oldc['evaluation_interval_ms']: raise RuntimeError('Q1_CALENDAR_DRIFT')
    p = {**p, 'batch_id': c['batch_id'], 'receipt_sha256': c['receipt_sha256'],
         'development_interval_ms': [start, end],
         'code_files_sha256': {**p['code_files_sha256'], **c['code_files_sha256']}}
    original_receipt = read_local(prior.OUTPUT + '/receipt.json')
    original_daily = read_lines(prior.OUTPUT + '/daily_valuation.jsonl.gz')
    stages = ('P', 'Q0', 'Q1_fixed', 'Q1')
    trades = {s: [] for s in stages}; opened = {s: [] for s in stages}; events = {s: [] for s in stages}
    for name, dest in (('trades', trades), ('open_observations', opened), ('events', events)):
        for t in read_lines(prior.OUTPUT + '/' + name + '.jsonl.gz'):
            s = {'P': 'P', 'Q': 'Q0'}.get(t['comparison_stage'])
            if s: dest[s].append(t)
    trace = []; admission = {}
    with old.probe.io_boundary([], out):
        for symbol, rows in four.items():
            daily = prior.structure.aggregate_daily(rows, split_end_ms=end)['daily']
            bundle = prior.structure.generate_signals(daily, eval_start_ms=start, eval_end_ms=end, require_preparation=True)
            expected = [e for e in events['Q0'] if e['symbol'] == symbol]
            actual = [v for v in bundle['signals'] if v['direction'] == 'UP']
            if [(e['signal_ts'], e['signal_index']) for e in expected] != [(e['signal_ts'], e['signal_index']) for e in actual]:
                raise RuntimeError('Q1_ORIGINAL_ENTRY_SIGNAL_DRIFT')
            fixed = [t['signal_index'] for t in trades['Q0'] + opened['Q0'] if t['symbol'] == symbol]
            admission[symbol] = {}
            for s, origins in (('Q1_fixed', fixed), ('Q1', None)):
                raw = execution.replay(rows, bundle, eval_start_ms=start, eval_end_ms=end, fixed_signal_indices=origins)
                trades[s].extend(prior.charge(t, symbol, s, p, dev['cost_by_symbol'], rows) for t in raw['trades'])
                opened[s].extend(prior.charge_open(t, symbol, s, p, dev['cost_by_symbol'], rows) for t in raw['open_positions'])
                events[s].extend(dict(e, symbol=symbol, lane_id=prior.LANE, comparison_stage=s, scenario=s) for e in raw['events'])
                trace.extend(dict(t, symbol=symbol, comparison_stage=s) for t in raw['trace'])
                admission[symbol][s] = raw['audit']
        key = prior.prior.previous.source_key
        if {key(t) for t in trades['Q0'] + opened['Q0']} != {key(t) for t in trades['Q1_fixed'] + opened['Q1_fixed']}:
            raise RuntimeError('Q1_FIXED_ORIGIN_POPULATION_DRIFT')
        originals = {key(t): t for t in trades['Q0'] + opened['Q0']}
        for s in ('Q1_fixed', 'Q1'):
            for t in trades[s] + opened[s]:
                if key(t) in originals:
                    for k in ('entry_ts', 'entry_price', 'entry_stop_price', 'side'):
                        if t[k] != originals[key(t)][k]: raise RuntimeError('Q1_INITIAL_ENTRY_RISK_DRIFT:' + k)
        metrics = {s: prior.accounting.summarize(trades[s], opened[s], events[s], p, list(four)) for s in stages}
        di = {s: prior.accounting.diagnostics(trades[s], start, end) for s in stages}
        valuation = {s: prior.daily_valuation(trades[s], opened[s], four, dev['cost_by_symbol'], start, end) for s in stages}
        mdi = {s: prior.accounting.daily_mark_diagnostics(v) for s, v in valuation.items()}
        for s in stages:
            if not math.isclose(valuation[s][-1]['cumulative_net_mark_bps'], metrics[s]['closed_plus_hypothetical_terminal_mark_bps'], abs_tol=1e-7): raise RuntimeError('Q1_MARK_BRIDGE:' + s)
        for s, label in (('P', 'P'), ('Q0', 'Q')):
            previous_metrics = original_receipt['metrics'][label]
            for k, v in metrics[s].items():
                if previous_metrics[k] != v: raise RuntimeError('Q1_BASELINE_METRIC_PARITY:' + s + ':' + k)
            if di[s] != original_receipt['diagnostics'][label] or mdi[s] != original_receipt['marked_diagnostics'][label]:
                raise RuntimeError('Q1_BASELINE_RISK_PARITY:' + s)
            previous_daily = [{k:v for k,v in row.items() if k != 'comparison_stage'} for row in original_daily if row['comparison_stage'] == label]
            if valuation[s] != previous_daily: raise RuntimeError('Q1_BASELINE_DAILY_PARITY:' + s)
            metrics[s] = previous_metrics
        for s in ('Q1_fixed', 'Q1'):
            uncertain = [t for t in trades[s] if t.get('intrabar_stop_timing_unknown')]
            metrics[s]['stop_timing_uncertainty'] = {'completed_intrabar_stop_T': len(uncertain),
                'timestamp_upper_bound_hours': 4, 'intrabar_path_order_ambiguous_T': 0,
                'settlement_boundary_inside_stop_bar_T': sum(t['entry_ts'] < t['exit_ts'] and t['exit_ts'] % (2*prior.BAR) == 0 for t in uncertain),
                'same_bar_original_and_raised_stop_priority': 'HIGHER_EFFECTIVE_STOP_AFTER_OPEN_ACTIVATION; NO_TP',
                'alternative_fill_or_cost_result_computed': False}
        comparisons = {}; uncertainty = {}
        for name, a, b in (('Q0_to_Q1_fixed', 'Q0', 'Q1_fixed'), ('Q0_to_Q1', 'Q0', 'Q1'), ('P_to_Q1', 'P', 'Q1')):
            comparisons[name] = bridge.symmetric_attribution(trades[a], opened[a], trades[b], opened[b])
            comparisons[name]['comparison_type'] = 'MECHANISM_REPLACEMENT' if a == 'P' else 'EXIT_CHANGE'
            uncertainty[name] = prior.accounting.paired_daily_uncertainty(valuation[a], valuation[b])
        large = {s: large_retention(trades['Q0'], trades[s], opened[s]) for s in ('Q1_fixed', 'Q1')}
        ws, we = c['Q0_drawdown_window_ms']
        windows = {s: bridge.window_contributions(trades[s], opened[s], four, dev['cost_by_symbol'], start, end, ws, we, daily=valuation[s]) for s in stages}
        decision = study_decision(metrics, di, mdi, large, uncertainty)
    artifacts = {}
    # Parent rows remain in their original hashed ledger; copying with a renamed
    # stage would invalidate their existing row digest. Only candidate rows are new.
    groups = {'trades': [t for s in ('Q1_fixed', 'Q1') for t in trades[s]],
              'open_observations': [t for s in ('Q1_fixed', 'Q1') for t in opened[s]],
              'events': [t for s in ('Q1_fixed', 'Q1') for t in events[s]], 'trace': trace,
              'daily_valuation': [dict(t, comparison_stage=s) for s in stages for t in valuation[s]]}
    for name, items in groups.items():
        raw = b''.join(old.probe.canonical(t) for t in items); path = out / (name + '.jsonl.gz')
        payload = path.read_bytes() if path.exists() else gzip.compress(raw, mtime=0)
        if gzip.decompress(payload) != raw: raise RuntimeError('Q1_REPRODUCTION_DRIFT:' + name)
        old.probe.write_immutable(path, payload, verify_only=verify_only)
        artifacts[name] = {'path': str(path.relative_to(ROOT)), 'rows': len(items), 'file_sha256': old.file_sha(path)}
    r = old.seal({'batch_id': c['batch_id'], 'contract_sha256': c['receipt_sha256'],
        'Q0_receipt_sha256': c['Q0_receipt_sha256'], 'Q0_status_preserved': 'DEV_INCONCLUSIVE',
        'baseline_ledger_reference': {'receipt': prior.OUTPUT + '/receipt.json', 'P_stage': 'P', 'Q0_stage': 'Q', 'parent_rows_rewritten': False},
        'baseline_metrics_risk_daily_parity': 'PASS',
        'symbols': c['symbols'], 'evaluation_interval_ms': [start, end], 'data_sha256': c['data_sha256'], 'cost_sha256': c['cost_sha256'],
        'metrics': metrics, 'diagnostics': di, 'marked_diagnostics': mdi, 'comparisons': comparisons,
        'uncertainty': uncertainty, 'large_winner_preservation': large, 'same_calendar_windows': windows,
        'decision': decision, 'admission': admission, 'artifacts': artifacts, 'source_access': access,
        'budget': {**BUDGET, 'new_trials_consumed': 1, 'remaining_allocated_trials': 0},
        'data_reuse_history': c['data_reuse_history'], 'research_lineage': {'parent': 'PR1190_Q0', 'child': 'Q1', 'next_reference': decision['research_reference'], 'Q2_authorized': False},
        'validation_rows_decoded': 0, 'OOS_rows_decoded': 0, 'paid_external_AI_calls': 0,
        'G5B_changed': False, 'operating_changed': False, 'G6_authorized': False, **old.probe.DEV_AUTH})
    old.probe.write_immutable(out / 'receipt.json', old.probe.canonical(r), verify_only=verify_only)
    old.probe.write_immutable(out / 'RESULTS.md', report(r), verify_only=verify_only)
    paths = [CONTRACT, SOURCE, DIAGNOSIS, OUTPUT + '/receipt.json', OUTPUT + '/RESULTS.md'] + [a['path'] for a in artifacts.values()]
    durable = old.seal({'result_receipt_sha256': r['receipt_sha256'], 'files_sha256': {p: old.file_sha(ROOT / p) for p in paths},
                        'code_files_sha256': c['code_files_sha256'], 'preserved_files_sha256': c['preserved_files_sha256'], **old.probe.DEV_AUTH})
    old.probe.write_immutable(out / 'durable_receipt.json', old.probe.canonical(durable), verify_only=verify_only)
    return r


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--data-dir', type=Path, required=True); ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args(); result = run(args.data_dir.resolve(), args.verify_only)
    print(json.dumps({'receipt': result['receipt_sha256'], 'decision': result['decision'], 'budget': result['budget']}, indent=2))
