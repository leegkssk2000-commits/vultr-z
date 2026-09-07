"""Stored H12 ledger diagnosis only: no signals, fills, strategy or replay."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

from backend.research.rebuild import parallel_exit_dev_v1 as account

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'research/development_evidence/TOP5_MECHANISM_A_20260907_V1'
OUTPUT = 'research/development_evidence/TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1/SUPERTREND'
CODE = 'backend/research/rebuild/supertrend_h12_timeline_diagnostic_v1.py'
BAR = 14400000
RULES = {
    'population': 'Only stored SR1 views.P completed original long H12 trades. Stored opens listed separately, never winner/loss labels. Both previously used calendars are DEV_USED; SEEN2026 is not independent OOS.',
    'clock': 'k=1..11 held completed native4h closes strictly before stored original exit. Each state becomes observable at that close; earliest action would be next open, but no exit or counterfactual is simulated. Original k12 exit-bar HLC never enters a state.',
    'features': 'At each k: close gross versus actual entry, original frozen model hypothetical roundtrip cost through this timestamp, cost-adjusted close mark, favorable-close-ever, favorable-cost-mark-ever, first favorable k, first later nonpositive-close k. No final MFE, outcome, high/low, future funding, or exit close enters features.',
    'loss_partition': 'Stored net<0: COST_FLIPPED if stored gross>0; otherwise GIVEBACK if any strictly-pre-exit completed close>entry; otherwise NO_FAVORABLE_CLOSE. These are disjoint postoutcome diagnostic labels, not entry/exit rules.',
    'winner_partition': 'Stored net>0 top ceil(10% of period winners), descending net then origin_key, are LARGE_WINNER; remaining are ORDINARY_WINNER. Mirrors existing break_channel_q1_metrics_v1 large-winner convention. Stored net==0 is FLAT.',
    'aggregation': 'Report every k1..11, no searched cutoffs: first-close-nonpositive; no favorable close yet; currently nonpositive; observed favorable then currently nonpositive; ever returned nonpositive after favorable; model cost mark nonpositive. Totals and first occurrence distributions by all final cohorts. No rule selection from these tables.',
    'cost': 'Reuse original cost_components(entry_ts,current_completed_close_ts,binding) and max20bps floor, research proxy only; full roundtrip cost is hypothetical liquidation, not accrued cost or actual signed funding. Stored gross/net/cost identity checked, never altered.',
    'integrity': 'Verify original SPEC and receipt seals and gzip byte SHA, approved account.load_inputs source bindings and bounded decoder. Per trade check long, native4h, entry next-open, H12 indices and timestamps, stored exit close parity. States exclude exit row entirely; strict-end closes only.',
    'authority': 'DIAGNOSTIC_ONLY; new economic replays0; new candidate0; external API0; formal_credit0; no hidden sweep; no strategy or shared controller changes.',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    payload = canonical(value) + b'\n'
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError('IMMUTABLE_DIAGNOSTIC_DRIFT:' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def freeze():
    inputs = [SOURCE + '/SPEC.json', SOURCE + '/SR1/receipt.json'] + [
        SOURCE + '/SR1/' + p + '.json.gz' for p in ('DEV2025', 'SEEN2026')]
    spec = {'schema': 'supertrend.h12.diagnostic.spec.v1', 'rules': RULES,
            'frozen_utc': datetime.now(timezone.utc).isoformat(),
            'new_timeline_outcomes_seen_at_freeze': False,
            'code_sha256': sha(ROOT / CODE),
            'input_paths_and_sha': {p: sha(ROOT / p) for p in inputs},
            'source_reader': 'parallel_exit_dev_v1.load_inputs',
            'source_reader_sha256': sha(Path(account.__file__)),
            'scope_key': Path(OUTPUT).parent.name}
    path = ROOT / OUTPUT / 'SPEC.json'
    if path.exists():
        raise RuntimeError('SPEC_ALREADY_FROZEN')
    write_once(path, spec)
    return spec


def causal_states(trade, held_rows, binding):
    """Only actual entry and fully observed prefix rows are inputs."""
    states = []
    first_positive = first_cost_positive = first_return = None
    for k, row in enumerate(held_rows, 1):
        if row['bar_close_ts'] >= trade['exit_ts']:
            raise RuntimeError('EXIT_ROW_OR_FUTURE_IN_STATE')
        gross = (row['close'] / trade['entry_price'] - 1.) * 10000
        parts = account.old.probe.cost_components(trade['entry_ts'], row['bar_close_ts'], binding)
        cost = max(20., parts['cost_bps'])
        if gross > 0 and first_positive is None:
            first_positive = k
        if gross - cost > 0 and first_cost_positive is None:
            first_cost_positive = k
        if first_positive is not None and k > first_positive and gross <= 0 and first_return is None:
            first_return = k
        states.append({'k': k, 'available_at': row['bar_close_ts'],
                       'close_gross_bps': gross, 'hypothetical_roundtrip_cost_bps': cost,
                       'hypothetical_net_close_mark_bps': gross-cost,
                       'first_favorable_close_k_so_far': first_positive,
                       'first_cost_positive_close_k_so_far': first_cost_positive,
                       'first_return_nonpositive_k_so_far': first_return,
                       'no_favorable_close_yet': first_positive is None,
                       'currently_nonpositive_close': gross <= 0,
                       'observed_favorable_now_nonpositive': first_positive is not None and gross <= 0,
                       'ever_returned_nonpositive_after_favorable': first_return is not None})
    return states


def diagnostic_trade(trade, rows, binding, end, large):
    ei, xi = trade['entry_index'], trade['exit_index']
    if (trade['side'] != 'long' or trade['native_interval_ms'] != BAR or
            trade['signal_index'] + 1 != ei or xi - ei != 11 or
            rows[ei]['bar_open_ts'] != trade['entry_ts'] or
            rows[xi]['bar_close_ts'] != trade['exit_ts'] or trade['exit_ts'] >= end or
            rows[ei]['open'] != trade['entry_price'] or rows[xi]['close'] != trade['exit_price']):
        raise RuntimeError('STORED_H12_SOURCE_PARITY')
    if not math.isclose(trade['gross_bps'] - trade['cost_bps'], trade['net_bps'], abs_tol=1e-9):
        raise RuntimeError('STORED_COST_IDENTITY')
    states = causal_states(trade, rows[ei:xi], binding)
    if trade['net_bps'] < 0:
        label = 'COST_FLIPPED' if trade['gross_bps'] > 0 else (
            'GIVEBACK' if not states[-1]['no_favorable_close_yet'] else 'NO_FAVORABLE_CLOSE')
    else:
        label = ('LARGE_WINNER' if trade['origin_key'] in large else 'ORDINARY_WINNER') if trade['net_bps'] > 0 else 'FLAT'
    return {'origin_key': trade['origin_key'], 'symbol': trade['symbol'],
            'entry_ts': trade['entry_ts'], 'exit_ts': trade['exit_ts'],
            'postoutcome_label': label, 'label_is_causal_feature': False,
            'stored_gross_bps': trade['gross_bps'], 'stored_cost_bps': trade['cost_bps'],
            'stored_net_bps': trade['net_bps'], 'states': states,
            'first_close_nonpositive': states[0]['currently_nonpositive_close']}


def summarize(trades):
    result = {}
    for label in ('NO_FAVORABLE_CLOSE', 'GIVEBACK', 'COST_FLIPPED', 'ORDINARY_WINNER', 'LARGE_WINNER', 'FLAT'):
        selected = [t for t in trades if t['postoutcome_label'] == label]
        value = {'T': len(selected), **{field: sum(t[field] for t in selected) for field in
                 ('stored_gross_bps', 'stored_cost_bps', 'stored_net_bps')},
                 'first_close_nonpositive_T': sum(t['first_close_nonpositive'] for t in selected)}
        for field in ('first_favorable_close_k_so_far', 'first_cost_positive_close_k_so_far', 'first_return_nonpositive_k_so_far'):
            value[field + '_distribution'] = dict(sorted(Counter(str(t['states'][-1][field]) for t in selected).items()))
        value['timeline'] = []
        for k in range(1, 12):
            states = [t['states'][k-1] for t in selected]
            value['timeline'].append({'k': k, **{f + '_T': sum(s[f] for s in states) for f in (
                'no_favorable_close_yet', 'currently_nonpositive_close',
                'observed_favorable_now_nonpositive', 'ever_returned_nonpositive_after_favorable')},
                'hypothetical_net_close_nonpositive_T': sum(s['hypothetical_net_close_mark_bps'] <= 0 for s in states)})
        result[label] = value
    return result


def run(data_dir):
    spec_path = ROOT / OUTPUT / 'SPEC.json'
    spec = json.loads(spec_path.read_text())
    if spec['rules'] != RULES or spec['code_sha256'] != sha(ROOT / CODE):
        raise RuntimeError('DIAGNOSTIC_SPEC_CODE_DRIFT')
    for path, digest in spec['input_paths_and_sha'].items():
        if sha(ROOT / path) != digest:
            raise RuntimeError('DIAGNOSTIC_INPUT_DRIFT:' + path)
    original = account.old.read(SOURCE + '/SPEC.json')
    receipt = account.old.read(SOURCE + '/SR1/receipt.json')
    account.old.probe.verify_seal(original, 'MECHANISM_A_SPEC')
    account.old.probe.verify_seal(receipt, 'SR1_RECEIPT')
    _, costs, periods, access = account.load_inputs(Path(data_dir), original)
    results = {}
    for period, rows in periods.items():
        artifact = receipt['artifacts'][period]
        if sha(ROOT / artifact['path']) != artifact['file_sha256']:
            raise RuntimeError('SR1_ARTIFACT_BYTES')
        doc = json.loads(gzip.decompress((ROOT / artifact['path']).read_bytes()))
        p = doc['views']['P']
        winners = sorted((t for t in p['trades'] if t['net_bps'] > 0), key=lambda t: (-t['net_bps'], t['origin_key']))
        large = {t['origin_key'] for t in winners[:math.ceil(len(winners)*.1)]}
        diagnostics = [diagnostic_trade(t, rows[t['symbol']], costs[t['symbol']], original['calendars'][period][1], large)
                       for t in sorted(p['trades'], key=lambda t: t['origin_key'])]
        result = {'period': period, 'evidence_grade': 'DEV_USED', 'independent': False,
                  'closed_T': len(diagnostics), 'open_T_excluded_from_outcome_labels': len(p['open_observations']),
                  'open_origins': [t['origin_key'] for t in p['open_observations']],
                  'summary': summarize(diagnostics), 'trades': diagnostics}
        write_once(ROOT / OUTPUT / (period + '.json'), result)
        results[period] = {k: v for k, v in result.items() if k != 'trades'}
    report = {'schema': 'supertrend.h12.diagnostic.result.v1', 'spec_sha256': sha(spec_path),
              'code_sha256': sha(ROOT / CODE), 'input_paths_and_sha': spec['input_paths_and_sha'],
              'results': results, 'source_access': access,
              'new_economic_replay_count': 0, 'new_candidate_count': 0, 'paid_API_calls': 0,
              'execution_feature_from_outcome_count': 0, 'formal_credit': 0,
              'uncertainty': 'DESCRIPTIVE_REUSED_DEV_ONLY; overlapping cross-symbol/time dependence; effective_N UNKNOWN; no inferential test, threshold selection or independent validation; 4h intrabar order unknown; model costs are not actual signed funding/fills.'}
    write_once(ROOT / OUTPUT / 'RESULT.json', report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--freeze', action='store_true')
    p.add_argument('--data-dir')
    a = p.parse_args()
    if a.freeze:
        print(json.dumps(freeze(), sort_keys=True))
    elif a.data_dir:
        report = run(a.data_dir)
        print(json.dumps({'status': 'DIAGNOSTIC_COMPLETE', 'results': {
            period: {label: {key: val for key, val in cohort.items() if key in ('T', 'stored_net_bps', 'first_close_nonpositive_T')}
                     for label, cohort in result['summary'].items()} for period, result in report['results'].items()}}, sort_keys=True))
    else:
        p.error('--freeze or --data-dir required')


if __name__ == '__main__':
    main()
