"""Read saved Squeeze artifacts; never import an engine or execute a replay.

This verifies successor arithmetic and recorded clocks only. It cannot prove
OHLC fills, parent parity, opportunity completeness or economic acceptance.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

CANDIDATE = 'scalp7_squeeze_trend_signal_low_invalidation_utc30m_v1'
OWNER = 'CLOUD_WORK_COORDINATOR_ISSUE1358_V1'
INVENTORY = '53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2'
CONTEXT = '168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c'
SAVED_S = '8389495e62fb1da211c7b360de621ed782322280552d627dea58909eee6025e8'
ORDERED_K = '4017a6a30628df0de444bcfd3b65a622e765e595f836976729d6c3d868c03ae4'
START, END, DAY = 1768262400000, 1789430400000, 86400000


def require(condition, code):
    if not condition:
        raise ValueError(code)


def unsigned_digest(value):
    unsigned = {k: v for k, v in value.items() if k != 'receipt_sha256'}
    raw = json.dumps(unsigned, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
    return hashlib.sha256(raw.encode()).hexdigest()


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value), 'NONFINITE_OR_MISSING_NUMBER')
    return float(value)


def equal(actual, expected, field):
    if expected is None:
        require(actual is None, 'METRIC_MISMATCH:' + field)
    else:
        require(math.isclose(finite(actual), expected, rel_tol=1e-10, abs_tol=1e-7),
                'METRIC_MISMATCH:' + field)


def event_key(row):
    return row['symbol'], row['signal_ts_ms'], row['signal_open_ts_ms']


def measure(rows, multiplier):
    ordered = sorted(rows, key=lambda r: (r['outcome_available_ts_ms'], r['exit_ts_ms'],
                                         r['symbol'], r['identity'], r['signal_ts_ms']))
    values = [finite(r['gross_bps']) - multiplier * finite(r['cost_bps']) for r in ordered]
    cohorts = defaultdict(list)
    streak = max_streak = 0
    for row, value in zip(ordered, values):
        cohorts[row['outcome_available_ts_ms']].append(value)
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
    equity = peak = drawdown = 0.0
    for timestamp in sorted(cohorts):
        equity += math.fsum(cohorts[timestamp])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    positive = math.fsum(v for v in values if v > 0)
    negative = -math.fsum(v for v in values if v < 0)
    total = math.fsum(values)
    return {'T': len(rows), 'Gross_bps': math.fsum(finite(r['gross_bps']) for r in rows),
            'Cost_bps': multiplier * math.fsum(finite(r['cost_bps']) for r in rows),
            'Net_bps': total, 'Net_bps_per_T': total / len(rows) if rows else None,
            'Net_bps_per_day': total / ((END - START) / DAY),
            'WR_pct': 100 * sum(v > 0 for v in values) / len(rows) if rows else None,
            'PF': positive / negative if negative else None,
            'MaxLossStreak': max_streak, 'DD_bps': drawdown,
            'worst_trade_bps': min(values) if values else None}


def verify(result, freeze):
    for name, body in [('RESULT', result), ('STARTED_FREEZE', freeze)]:
        require(body.get('receipt_sha256') == unsigned_digest(body), 'RECEIPT_MISMATCH:' + name)
    require(result['input_freeze_sha256'] == unsigned_digest(freeze), 'FREEZE_BINDING_MISMATCH')
    require(result['candidate_id'] == freeze['candidate_id'] == CANDIDATE, 'WRONG_CANDIDATE')
    require(freeze['claim_id'] == OWNER, 'WRONG_OWNER')
    require(result['source_inventory_sha256'] == freeze['source_inventory_sha256'] == INVENTORY,
            'WRONG_SOURCE')
    require(freeze['context_fit_sha256'] == CONTEXT, 'WRONG_CONTEXT')
    require(result['saved_rejected_receipt'] == freeze['saved_rejected_receipt'] == SAVED_S,
            'WRONG_SAVED_BASELINE')
    require(freeze['keltner_result_receipt_sha256'] == ORDERED_K, 'WRONG_ORDERED_K')
    require(result['window'] == {'start_ms': START, 'end_exclusive_ms': END}, 'WRONG_WINDOW')
    require(result['used_dev_only'] is True and result['fresh_or_oos'] is False
            and result['account_nav_or_mtm'] is False and result['promotion'] is False,
            'AUTHORITY_OR_CLASSIFICATION_DRIFT')
    require(result['economic_runs'] == 1 and freeze['candidate_comparisons_attempted'] == 1,
            'RUN_COUNT_DRIFT')
    require(result['old_candidate_replayed'] is False, 'OLD_CANDIDATE_REPLAYED')
    require(result['order_paper_live_deploy'] == 'BLOCKED', 'TRADING_AUTHORITY_DRIFT')
    rows = result['trade_rows']
    require(len({event_key(r) for r in rows}) == len(rows), 'DUPLICATE_TRADE_KEY')
    require(rows == [r for r in result['all_partition_trade_rows'] if r['partition'] == 'rolling'],
            'ROLLING_SUBSET_MISMATCH')
    for row in rows:
        require(row['identity'] == CANDIDATE and row['partition'] == 'rolling'
                and row['timeframe_min'] == 30 and row['side'] == 1, 'ROW_IDENTITY_DRIFT')
        times = [row[k] for k in ('signal_open_ts_ms', 'signal_ts_ms', 'entry_ts_ms',
                                 'exit_ts_ms', 'outcome_available_ts_ms')]
        require(all(type(t) is int for t in times), 'NONINTEGER_CLOCK')
        require(times == sorted(times) and START <= times[1] < END and times[-1] < END,
                'UNAVAILABLE_CLOCK_OR_BOUNDARY')
        feature = row['signal']['meta']['feature_available_ts_ms']
        require(type(feature) is int and feature <= row['signal_ts_ms'], 'FUTURE_FEATURE')
        require(finite(row['cost_bps']) > 0, 'NONPOSITIVE_COST')
        equal(row['net_bps'], finite(row['gross_bps']) - finite(row['cost_bps']), 'row_net_bps')
    incomplete = bool(result['unresolved'] or result['boundary_excluded'])
    require(result['comparison_complete'] is (not incomplete), 'INCOMPLETE_COMPARISON_MISLABEL')
    require(result['state'] == ('INCOMPLETE_NO_ADOPTION' if incomplete else
                               'USED_DEV_MEASURED_AWAITING_SSOT_ADJUDICATION'), 'STATE_DRIFT')
    measured = {}
    for multiplier in (1, 2):
        name = f'cost{multiplier}x'
        measured[name] = measure(rows, multiplier)
        view = result['views'][name]
        for field, expected in measured[name].items():
            equal(view['successor'].get(field), expected, name + '.' + field)
        require(view['successor']['DD_kind'] == 'REALIZED_SIMULTANEOUS_OUTCOME_COHORT_TRADE_BPS',
                'DD_KIND_MISMATCH')
        require(view['successor']['completed_subset_only'] is incomplete, 'SUBSET_MISLABEL')
        if incomplete:
            require(view['vs_parent'] is None and view['vs_saved_rejected'] is None,
                    'UNRESOLVED_TREATED_AS_AVOIDED_LOSS')
    entries = [d for d in result['decisions'] if d['partition'] == 'rolling' and d['state'] == 'ACCEPTED']
    require(len({event_key(d) for d in entries}) == len(entries), 'DUPLICATE_ACCEPTED_KEY')
    require(all(START <= d['entry_ts_ms'] < END for d in entries), 'ENTRY_OUTSIDE_WINDOW')
    require({event_key(r) for r in rows} <= {event_key(d) for d in entries}, 'TRADE_WITHOUT_ACCEPTANCE')
    accepted_by_key = {event_key(d): d for d in entries}
    require(all(accepted_by_key[event_key(r)]['entry_ts_ms'] == r['entry_ts_ms'] for r in rows),
            'ACCEPTED_TRADE_ENTRY_CLOCK_MISMATCH')
    if not incomplete:
        require({event_key(r) for r in rows} == {event_key(d) for d in entries}, 'ACCEPTANCE_WITHOUT_TRADE')
    equal(result['accepted_entries'], len(entries), 'accepted_entries')
    equal(result['entries_per_calendar_day'], len(entries) / ((END - START) / DAY), 'entries_per_day')
    return {'state': 'PASS_SAVED_SUCCESSOR_ARITHMETIC_ONLY', 'candidate_id': CANDIDATE,
            'result_receipt_sha256': result['receipt_sha256'], 'views': measured,
            'comparison_complete': not incomplete, 'new_economic_runs': 0,
            'account_nav': None, 'promotion': False,
            'remaining_source_audit': ['parent_and_saved_opportunity_reconciliation',
                'OHLC_stop_first_gap_and_unresolved_paths', 'ten_trigger_causal_attribution',
                'ordinary_large_and_recovery_winner_retention', 'SSOT_economic_adjudication']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    args = parser.parse_args()
    missing = [str(p) for p in (args.result, args.freeze) if not p.is_file()]
    if missing:
        print(json.dumps({'state': 'NOT_RUN_MISSING_FULL_ARTIFACT', 'missing': missing,
                          'new_economic_runs': 0, 'metrics': None}))
        return 2
    try:
        result = verify(json.loads(args.result.read_text()), json.loads(args.freeze.read_text()))
    except (ValueError, KeyError, TypeError) as error:
        print(json.dumps({'state': 'HOLD_INVALID_SAVED_ARTIFACT', 'first_error': str(error),
                          'new_economic_runs': 0, 'metrics': None}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
