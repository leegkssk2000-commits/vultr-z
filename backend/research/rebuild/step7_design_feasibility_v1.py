"""Finite, already-exposed DEV dependence/power design calculation; never replay.

The CLI consumes a frozen minimal projection once. It does not open market tapes,
recompute old strategy scores, assign formal N, or activate any approval proposal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist, mean, median, stdev

DAY = 86_400_000


def seal(value):
    d = dict(value)
    d['receipt_sha256'] = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return d


def required_n(sigma_bps, *, null_bps, alternative_bps, alpha=.05/7, power=.8):
    """Normal approximation for H0: mu<=null vs one specified alternative.

    Rejecting with lower confidence bound >5 and 80% power at mu=5 is
    mathematically incompatible. Infinity is represented as null + reason.
    """
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError('PROBABILITY_RANGE')
    if alternative_bps <= null_bps:
        return {'N': None, 'reason': 'NO_POSITIVE_ALTERNATIVE_MINUS_NULL_GAP'}
    if sigma_bps is None or not math.isfinite(sigma_bps) or sigma_bps <= 0:
        return {'N': None, 'reason': 'SIGMA_UNAVAILABLE_OR_NONPOSITIVE'}
    z = NormalDist().inv_cdf(1-alpha) + NormalDist().inv_cdf(power)
    n = math.ceil((z*sigma_bps/(alternative_bps-null_bps))**2)
    return {'N': n, 'reason': None, 'null_bps': null_bps,
            'alternative_bps': alternative_bps, 'effect_gap_bps': alternative_bps-null_bps,
            'sigma_component_mean_trade_bps': sigma_bps, 'alpha_one_sided': alpha,
            'power': power, 'method': 'NORMAL_PLANNING_APPROXIMATION_NOT_TERMINAL_TEST'}


def nodes_from_projection(p, include_references):
    nodes = []
    for i, row in enumerate(p['trades'] + p['open_observations']):
        end = row.get('exit_ts')
        if end is not None and end < row['entry_ts']:
            raise ValueError('NEGATIVE_ACTUAL_INTERVAL')
        nodes.append({'id': 'actual-'+str(i), 'kind': 'actual', 'start': row['entry_ts'],
                      'end': end, 'signal_ts': row['signal_ts'], 'symbol': row['symbol'],
                      'net': row.get('net_bps'), 'closed': end is not None})
    if include_references:
        for i, row in enumerate(p['reference_opportunities']):
            end = row.get('release_ts')
            if end is not None and end < row['reservation_ts']:
                raise ValueError('NEGATIVE_REFERENCE_INTERVAL')
            nodes.append({'id': 'reference-'+str(i), 'kind': 'reference',
                          'start': row['reservation_ts'], 'end': end,
                          'signal_ts': row['reservation_ts'], 'symbol': row['symbol'],
                          'net': None, 'closed': end is not None})
    return nodes


def components(nodes, *, same_signal_day):
    """Conservative closed-interval overlaps, across symbols, plus day unions.

    References are dependency edges only, never economic rows or zero returns.
    Null end is infinity: right-censoring remains visible in the output.
    """
    parent = list(range(len(nodes)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[root(i)] = root(j)

    for i, left in enumerate(nodes):
        for j in range(i):
            right = nodes[j]
            overlap = (left['start'] <= (right['end'] if right['end'] is not None else math.inf)
                       and right['start'] <= (left['end'] if left['end'] is not None else math.inf))
            same_day = same_signal_day and left['signal_ts']//DAY == right['signal_ts']//DAY
            if overlap or same_day:
                union(i, j)
    groups = {}
    for i, node in enumerate(nodes):
        groups.setdefault(root(i), []).append(node)
    out = []
    for group in groups.values():
        actual = [n for n in group if n['kind'] == 'actual']
        if not actual:
            continue
        values = [n['net'] for n in actual if n['closed'] and n['net'] is not None]
        complete = all(n['closed'] for n in group) and len(values) == len(actual)
        out.append({'first_signal_ts': min(n['signal_ts'] for n in group),
                    'last_end_ts': max(n['end'] for n in group) if complete else None,
                    'actual_T': len(actual), 'reference_T': len(group)-len(actual),
                    'symbols': sorted({n['symbol'] for n in actual}),
                    'closed_T': sum(n['closed'] for n in actual),
                    'censored_actual_T': sum(not n['closed'] for n in actual),
                    'censored_reference_T': sum(not n['closed'] for n in group if n['kind']=='reference'),
                    'complete': complete,
                    'component_mean_net_trade_bps': mean(values) if complete and values else None})
    return sorted(out, key=lambda c: c['first_signal_ts'])


def summarize_components(groups, start, end):
    complete = [g for g in groups if g['complete']]
    vals = [g['component_mean_net_trade_bps'] for g in complete]
    sizes = [g['actual_T'] for g in groups]
    sigma = stdev(vals) if len(vals) >= 2 else None
    days = (end-start)/DAY
    buckets = []
    for k in range(math.ceil(days/30)):
        lo, hi = start+k*30*DAY, min(end, start+(k+1)*30*DAY)
        if lo >= hi:
            continue
        cohort = [g for g in groups if lo <= g['first_signal_ts'] < hi]
        buckets.append({'start_ms': lo, 'end_ms': hi, 'days': (hi-lo)/DAY,
                        'N_complete_components': sum(g['complete'] for g in cohort),
                        'N_censored_components': sum(not g['complete'] for g in cohort),
                        'actual_T': sum(g['actual_T'] for g in cohort)})
    n = required_n(sigma, null_bps=5, alternative_bps=10)
    rate = len(complete)/days if days else 0
    full_buckets = [b['N_complete_components'] for b in buckets if b['days']==30]
    return {'N_components_with_actual_rows': len(groups), 'N_complete_components': len(complete),
            'N_censored_components': len(groups)-len(complete),
            'actual_T': sum(sizes), 'component_actual_sizes': sizes,
            'largest_component_actual_T': max(sizes, default=0),
            'median_component_actual_T': median(sizes) if sizes else None,
            'sigma_component_mean_trade_bps': sigma, 'DEV_calendar_days': days,
            'complete_components_per_30_days_average': 30*rate,
            'observed_full_30day_component_count_range': [min(full_buckets), max(full_buckets)] if full_buckets else None,
            'calendar_cohort_buckets_without_occupancy_reset': buckets,
            'power_H0_0_H1_5': required_n(sigma, null_bps=0, alternative_bps=5),
            'power_H0_5_H1_10': n,
            'power_H0_5_H1_5': required_n(sigma, null_bps=5, alternative_bps=5),
            'illustrative_required_calendar_days_per_window': n['N']/rate if n['N'] and rate else None,
            'minimum_complete_components_each_W1_W2_W3': dict.fromkeys(('W1','W2','W3'),n['N']),
            'rate_is_future_guarantee': False, 'estimated_components_are_proven_independent': False,
            'final_test': 'STUDENT_T_AND_APPROVED_DEPENDENCE_ASSUMPTIONS_STILL_REQUIRED',
            'control_contrast_sigma': None,
            'control_power_reason': 'CANDIDATE_COMPONENT_SIGMA_IS_NOT_PAIRED_CONTROL_DIFFERENCE_SIGMA'}


def analyze(projection, freeze):
    if projection['freeze_sha256'] != freeze['receipt_sha256']:
        raise ValueError('FREEZE_IDENTITY')
    start, end = freeze['input']['calendar_ms']
    results = {}
    for name, refs, day in (('ACTUAL_INTERVAL_ONLY',False,False),
                             ('ACTUAL_AND_REFERENCE_AND_UTC_SIGNAL_DAY',True,True)):
        groups = components(nodes_from_projection(projection, refs), same_signal_day=day)
        results[name] = {'summary': summarize_components(groups,start,end), 'components': groups}
    return seal({'schema':'step7.design.feasibility.result.v1', 'formal_credit':0,
                 'new_candidate_runs':0, 'old_economic_replays':0, 'status':'DEV_DESIGN_ONLY_NO_FORMAL_ACTIVATION',
                 'freeze_sha256':freeze['receipt_sha256'], 'proposal_activated':False,
                 'created_at':datetime.now(timezone.utc).isoformat(), 'results':results,
                 'estimand_correction':'Original sigma/delta formula plans a gap5, not power80 at the lower-bound5 threshold. Preserve lower>5 only with distinct mu_alt10, still an unapproved design assumption.',
                 'never_interpret_as':'New profitability, formal independent observations, universal no-SL authority, account risk or elapsed future guarantee'})


def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',type=Path,required=True);p.add_argument('--projection',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    # O_EXCL marker before DEV projection I/O: this finite calculation is not a
    # repeated CI economic test. Synthetic tests below exercise the pure methods.
    marker=a.output.with_suffix('.attempt.json')
    with marker.open('x') as f:
        json.dump({'command':'step7_design_feasibility_v1','read_limit':1,'at':datetime.now(timezone.utc).isoformat()},f)
    result=analyze(json.loads(a.projection.read_text()),json.loads(a.freeze.read_text()))
    with a.output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps({'result_sha256':result['receipt_sha256'],'summaries':{k:v['summary'] for k,v in result['results'].items()}},sort_keys=True))


if __name__=='__main__':
    main()
