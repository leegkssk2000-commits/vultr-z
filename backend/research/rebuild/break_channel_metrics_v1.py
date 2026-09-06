"""Pure DEV accounting for one preregistered Break mechanism replacement.

No source loading, trading authority, strategy selection, or parameter search.
Prior sealed evaluators and decisions are imported without modifying them.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import math
import random

from backend.research.rebuild import supertrend_flip_ab_v1 as censored
from backend.research.rebuild import top5_development_repair_v1 as shared
from backend.research.rebuild import top5_external_metrics_v1 as existing_risk

DAY = 86_400_000
COST_FIELDS = ('fee_bps', 'spread_bps', 'impact_bps', 'slippage_bps',
               'funding_bps', 'frozen_floor_reserve_bps')


def exposure_summary(trades, opened, *, start_ms=None, end_ms=None):
    """Sweep half-open holding intervals; same-time exits cannot create overlap."""
    changes = defaultdict(Counter)
    if start_ms is not None and end_ms is not None:
        if end_ms <= start_ms:
            raise ValueError('INVALID_EXPOSURE_CALENDAR')
        changes[start_ms]
        changes[end_ms]
    position_ms = 0
    maximum_hold = 0
    for rows, terminal in ((trades, 'exit_ts'), (opened, 'mark_ts')):
        for t in rows:
            entry, end = t['entry_ts'], t[terminal]
            if end < entry or (start_ms is not None and entry < start_ms) or (end_ms is not None and end > end_ms):
                raise ValueError('EXPOSURE_INTERVAL_OUTSIDE_CALENDAR')
            if t['hold_ms'] != end - entry:
                raise ValueError('EXPOSURE_HOLD_DURATION_MISMATCH')
            position_ms += end - entry
            maximum_hold = max(maximum_hold, end - entry)
            if end > entry:
                changes[entry][t['symbol']] += 1
                changes[end][t['symbol']] -= 1
    active = Counter()
    max_positions = max_symbols = symbol_ms = any_exposure_ms = 0
    by_count_ms = defaultdict(int)
    times = sorted(changes)
    for i, ts in enumerate(times):
        # Apply the whole timestamp, so exit and replacement entry are atomic.
        for symbol, delta in changes[ts].items():
            active[symbol] += delta
            if active[symbol] < 0:
                raise ValueError('NEGATIVE_EXPOSURE_OWNERSHIP')
            if active[symbol] == 0:
                del active[symbol]
        max_positions = max(max_positions, sum(active.values()))
        max_symbols = max(max_symbols, len(active))
        if i + 1 < len(times):
            duration = times[i + 1] - ts
            symbol_ms += duration * len(active)
            if active:
                any_exposure_ms += duration
            by_count_ms[len(active)] += duration
    if active:
        raise ValueError('UNCLOSED_EXPOSURE_SWEEP')
    return {
        'max_simultaneous_positions': max_positions,
        'max_simultaneous_symbols': max_symbols,
        'position_days': position_ms / DAY,
        'symbol_days_union': symbol_ms / DAY,
        'calendar_days_with_any_exposure': any_exposure_ms / DAY,
        'maximum_holding_days_including_open': maximum_hold / DAY,
        'calendar_days_by_simultaneous_symbols': {str(k): v / DAY for k, v in sorted(by_count_ms.items())},
        'semantics': 'ENTRY_INCLUSIVE_EXIT_OR_MARK_EXCLUSIVE; EQUAL_NOTIONAL_SLOTS; NOT_ACCOUNT_EXPOSURE',
    }


def period_metrics(trades, *, start_ms=None, end_ms=None):
    """Realized monthly attribution uses exit month and does not allocate open marks."""
    groups = defaultdict(list)
    if start_ms is not None and end_ms is not None:
        if end_ms <= start_ms:
            raise ValueError('INVALID_MONTHLY_CALENDAR')
        first = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
        last = datetime.fromtimestamp((end_ms - 1) / 1000, timezone.utc)
        year, month = first.year, first.month
        while (year, month) <= (last.year, last.month):
            groups[f'{year:04d}-{month:02d}']
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    for t in trades:
        month = datetime.fromtimestamp(t['exit_ts'] / 1000, timezone.utc).strftime('%Y-%m')
        groups[month].append(t)
    return {month: {
        'closed_T': len(rows), 'gross_bps': sum(t['gross_bps'] for t in rows),
        'net_bps': sum(t['net_bps'] for t in rows),
        'cost2x_net_bps': sum(t['cost2x_net_bps'] for t in rows),
        'cost_bps': sum(t['cost_bps'] for t in rows),
        **{field: sum(t[field] for t in rows) for field in COST_FIELDS},
    } for month, rows in sorted(groups.items())}


def concentration(trades):
    profits = defaultdict(float)
    net = defaultdict(float)
    for t in trades:
        net[t['symbol']] += t['net_bps']
        profits[t['symbol']] += max(0, t['net_bps'])
    winners = sorted((t['net_bps'] for t in trades if t['net_bps'] > 0), reverse=True)
    total = sum(winners)
    top_count = math.ceil(len(winners) * .1)
    top_symbol = min(profits, key=lambda s: (-profits[s], s)) if total else None
    return {
        'by_symbol_closed_net_bps': dict(sorted(net.items())),
        'by_symbol_positive_trade_profit_bps': dict(sorted(profits.items())),
        'total_positive_trade_profit_bps': total,
        'top_one_symbol_by_positive_trade_profit': top_symbol,
        'top_one_symbol_profit_share': profits[top_symbol] / total if total else None,
        'winner_T': len(winners), 'top_decile_winner_T': top_count,
        'top_decile_winners_share': sum(winners[:top_count]) / total if total else None,
        'basis': 'POSITIVE_CLOSED_NET_TRADE_PROFIT; NOT_NET_TOTAL_OR_ACCOUNT_RETURN',
    }


def summarize(trades, opened, events, policy, symbols):
    """Shared completed economics plus explicitly hypothetical terminal valuation."""
    start, end = policy['development_interval_ms']
    if end <= start or not symbols or len(set(symbols)) != len(symbols):
        raise ValueError('INVALID_COMPARISON_CALENDAR_OR_SYMBOLS')
    if any(t['symbol'] not in symbols for t in list(trades) + list(opened)):
        raise ValueError('UNKNOWN_COMPARISON_SYMBOL')
    m = censored.summarize_stage(trades, opened, events, policy, symbols)
    m['closed_cost_totals_bps'] = {field: sum(t[field] for t in trades) for field in COST_FIELDS}
    m['closed_cost_totals_bps']['cost_bps'] = sum(t['cost_bps'] for t in trades)
    m['closed_cost_totals_bps']['funding_settlements_crossed'] = sum(t['funding_settlements_crossed'] for t in trades)
    m['open_observations']['hypothetical_cost_totals_bps'] = {
        field: sum(t['hypothetical_cost_components_bps'][field] for t in opened) for field in COST_FIELDS
    }
    m['open_observations']['funding_settlements_elapsed'] = sum(t['funding_settlements_elapsed'] for t in opened)
    m['open_observations']['entry_side_cost_bps'] = None if opened else 0.0
    m['exposure'] = exposure_summary(trades, opened, start_ms=start, end_ms=end)
    if not math.isclose(m['exposure']['position_days'], m['total_exposure_symbol_days'], abs_tol=1e-10):
        raise ValueError('SHARED_EXPOSURE_PARITY')
    m['by_exit_month'] = period_metrics(trades, start_ms=start, end_ms=end)
    m['concentration'] = concentration(trades)
    m['basis'] = 'RESEARCH_COST_MODEL; EQUAL_NOTIONAL_TRADE_BPS; CLOSED_AND_HYPOTHETICAL_TERMINAL_SEPARATE'
    m['no_account_return_or_equal_risk_claim'] = True
    return m


def diagnostics(trades, start, end):
    """Keep the prior grouped closed-loss and drawdown definitions byte-identical."""
    return existing_risk.diagnostics(trades, start, end)[0]


def attribution(parent, child, open_child):
    """Signal overlap is explanation only for mechanism replacement, not a gate."""
    result = censored.censored_attribution(parent, child, open_child)
    result['comparison_type'] = 'MECHANISM_REPLACEMENT'
    result['source_overlap_is_economic_gate'] = False
    result['retention_limit'] = 'ORIGIN_MATCHED_ORIGINAL_PROFIT_ONLY; DISTINCT_SIGNAL_STRUCTURES_CAN_HAVE_LOW_RETENTION'
    return result


def no_trade_baseline(policy, symbols):
    result = summarize([], [], [], policy, symbols)
    result['baseline_kind'] = 'NO_TRADE'
    result['decision'] = 'REFERENCE_ONLY'
    result['base_cost']['DD_trade_sum_bps'] = 0.0
    result['cost2x']['DD_trade_sum_bps'] = 0.0
    result['hypothesis_allocation_consumed'] = 0
    return result


def _daily_series(series):
    if hasattr(series, 'items'):
        entries = list(series.items())
    else:
        entries = [(row['date'], row['value']) for row in series]
    answer = {}
    for stamp, value in entries:
        day = date.fromisoformat(stamp)
        if day.isoformat() != stamp or stamp in answer or not math.isfinite(value):
            raise ValueError('INVALID_OR_DUPLICATE_DAILY_OBSERVATION')
        answer[stamp] = float(value)
    keys = sorted(answer)
    for a, b in zip(keys, keys[1:]):
        if date.fromisoformat(b) - date.fromisoformat(a) != timedelta(days=1):
            raise ValueError('DAILY_CALENDAR_GAP_PRESERVE_ZERO_DAYS')
    return keys, answer


def paired_daily_uncertainty(parent_daily, child_daily, *, block_days=30, resamples=1000, seed=1178):
    """Paired non-circular moving blocks of daily marked-equity changes.

    Calendar observations and the block length must be frozen before outcomes.
    The caller supplies one consistent full-cost terminal-mark convention.
    """
    keys, parent = _daily_series(parent_daily)
    child_keys, child = _daily_series(child_daily)
    if keys != child_keys:
        raise ValueError('UNPAIRED_DAILY_CALENDAR')
    if isinstance(block_days, bool) or not isinstance(block_days, int) or block_days < 1:
        raise ValueError('INVALID_BLOCK_LENGTH')
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError('INVALID_RESAMPLE_BUDGET')
    n = len(keys)
    delta = [child[k] - parent[k] for k in keys]
    result = {
        'method': 'PAIRED_NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_DAILY_MARKED_EQUITY_DELTAS',
        'calendar_days': n, 'block_days': block_days, 'resamples': resamples, 'seed': seed,
        'approximate_calendar_blocks': n / block_days, 'N_effective': None,
        'calendar_start': keys[0] if keys else None, 'calendar_last_day': keys[-1] if keys else None,
        'parent_marked_delta_sum_bps': sum(parent.values()),
        'child_marked_delta_sum_bps': sum(child.values()),
        'child_minus_parent_marked_delta_sum_bps': sum(delta),
        'child_minus_parent_mean_daily_bps': sum(delta) / n if n else None,
        'child_minus_parent_95pct_interval_bps_per_day': [None, None],
        'child_minus_parent_95pct_interval_calendar_sum_bps': [None, None],
        'status': 'INSUFFICIENT_CALENDAR' if n < block_days else 'COMPUTED',
        'limitations': '30_DAY_BLOCKS_ARE_NOT_PROVEN_INDEPENDENT; LONG_HOLDING_AND_CROSS_SYMBOL_DEPENDENCE_CAN_EXCEED_BLOCK; REUSED_DEV_AND_SELECTION_NOT_CORRECTED; FULL_TERMINAL_MARK_COST_ASSUMPTION; NONCIRCULAR_EDGE_WEIGHTING',
    }
    if n < block_days:
        return result
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        values = []
        while len(values) < n:
            start = rng.randrange(n - block_days + 1)
            values.extend(delta[start:start + block_days])
        draws.append(sum(values[:n]) / n)
    interval = [shared.probe.quantile(draws, .025), shared.probe.quantile(draws, .975)]
    result['child_minus_parent_95pct_interval_bps_per_day'] = interval
    result['child_minus_parent_95pct_interval_calendar_sum_bps'] = [v * n for v in interval]
    return result


def daily_mark_diagnostics(series):
    """Marked drawdown is a sum of equal-notional trade marks, never account MDD."""
    keys, values = _daily_series(series)
    equity = peak = worst = 0.0
    peak_day = date.fromisoformat(keys[0]) - timedelta(days=1) if keys else None
    submerged = False
    recoveries = []
    for key in keys:
        day = date.fromisoformat(key)
        equity += values[key]
        worst = max(worst, peak - equity)
        if equity >= peak:
            if submerged:
                recoveries.append((day - peak_day).days)
            peak = equity
            peak_day = day
            submerged = False
        else:
            submerged = True
    return {
        'marked_DD_trade_sum_bps': worst,
        'max_completed_recovery_days': max(recoveries, default=0),
        'unrecovered_at_end': submerged,
        'open_underwater_days': (date.fromisoformat(keys[-1]) - peak_day).days if submerged else 0,
        'basis': 'DAILY_MARKED_EQUAL_NOTIONAL_TRADE_BPS_WITH_CALLER_COST_CONVENTION; NOT_ACCOUNT_MDD',
    }


def decide(parent_metrics, child_metrics, diagnostics_parent, diagnostics_child, uncertainty, minimum_closed_T=6):
    """New mechanism-screen interpretation; old sealed decisions remain unchanged."""
    p = parent_metrics['base_cost']
    c = child_metrics['base_cost']
    result = {
        'comparison_type': 'MECHANISM_REPLACEMENT',
        'source_overlap_is_economic_gate': False,
        'formal_pass': False, 'operating_adoption': False, 'validation': 'NOT_RUN', 'OOS': 'NOT_RUN',
        'code_test_PASS_is_economic_PASS': False,
        'risk_limit_basis': 'EXISTING_GROUPED_LOSS_RUN_AND_DD_NONDETERIORATION_FOR_DEV_PROMISING_ONLY; NO_ACCOUNT_RISK_LIMIT_INVENTED',
    }
    if child_metrics.get('baseline_kind') == 'NO_TRADE':
        return {**result, 'decision': 'REFERENCE_ONLY', 'closed_screen_decision': 'REFERENCE_ONLY',
                'economic_interpretation': 'ZERO_TRADE_REFERENCE_NOT_A_STRATEGY_HYPOTHESIS', 'failed_checks': []}
    if not isinstance(minimum_closed_T, int) or isinstance(minimum_closed_T, bool) or minimum_closed_T < 1:
        raise ValueError('INVALID_MINIMUM_CLOSED_SAMPLE')
    delta = c['net_bps'] - p['net_bps']
    result['closed_calendar_net_delta_bps'] = delta
    result['expectancy_delta_bps_per_trade'] = (
        c['expectancy_bps_per_trade'] - p['expectancy_bps_per_trade']
        if c['expectancy_bps_per_trade'] is not None and p['expectancy_bps_per_trade'] is not None else None)
    result['economic_interpretation'] = (
        'POSITIVE_CLOSED_ECONOMICS' if c['net_bps'] > 0
        else 'LOSS_REDUCTION' if c['net_bps'] < 0 and delta > 0
        else 'NO_CLOSED_NET_IMPROVEMENT' if delta <= 0
        else 'ZERO_CLOSED_NET')
    loss_key = 'lane_simultaneous_close_group_streaks'
    dd_key = 'drawdown_recovery'
    parent_loss = diagnostics_parent[loss_key]['max_loss_trade_sum_bps']
    child_loss = diagnostics_child[loss_key]['max_loss_trade_sum_bps']
    parent_dd = diagnostics_parent[dd_key]['closed_group_DD_trade_sum_bps']
    child_dd = diagnostics_child[dd_key]['closed_group_DD_trade_sum_bps']
    parent_exposure = parent_metrics['total_exposure_symbol_days']
    child_exposure = child_metrics['total_exposure_symbol_days']
    risk_checks = {'grouped_loss_run_not_worse': child_loss <= parent_loss,
                   'grouped_DD_not_worse': child_dd <= parent_dd}
    result['risk_checks'] = risk_checks
    result['risk_tradeoffs'] = {
        'grouped_loss_run_delta_bps': child_loss - parent_loss,
        'grouped_DD_delta_bps': child_dd - parent_dd,
        'exposure_delta_symbol_days': child_exposure - parent_exposure,
        'exposure_increased': child_exposure > parent_exposure,
        'exposure_increase_is_automatic_reject': False,
        'win_rate_decline_is_automatic_reject': False,
    }
    interval = uncertainty['child_minus_parent_95pct_interval_bps_per_day']
    increment_supported = interval[0] is not None and interval[0] > 0
    result['calendar_increment_positive_lower_95pct'] = increment_supported
    result['calendar_marked_delta_95pct_bps_per_day'] = interval
    enough = (c['completed_T'] >= minimum_closed_T and c['PF'] is not None
              and c['realized_payoff'] is not None and c['expectancy_bps_per_trade'] is not None)
    checks = {
        'positive_closed_net': c['net_bps'] > 0,
        'positive_closed_expectancy': c['expectancy_bps_per_trade'] is not None and c['expectancy_bps_per_trade'] > 0,
        'PF_above_one': c['PF'] is not None and c['PF'] > 1,
        'payoff_at_least_one': c['realized_payoff'] is not None and c['realized_payoff'] >= 1,
        'positive_cost2x_net': child_metrics['cost2x']['net_bps'] > 0,
    }
    result['absolute_economic_checks'] = checks
    if not enough:
        state, failed = 'INSUFFICIENT', ['SAMPLE_OR_PF_OR_PAYOFF_UNDEFINED']
    elif not all(checks.values()):
        state, failed = 'DEV_REJECT', [name for name, passed in checks.items() if not passed]
    elif not increment_supported or not all(risk_checks.values()):
        state = 'DEV_INCONCLUSIVE'
        failed = ([] if increment_supported else ['CALENDAR_INCREMENT_NOT_ESTABLISHED']) + [name for name, passed in risk_checks.items() if not passed]
    else:
        state, failed = 'DEV_PROMISING', []
    result['closed_screen_decision'] = state
    result['closed_screen_scope'] = 'CLOSED_ABSOLUTE_ECONOMICS; CALENDAR_MARKED_INCREMENT; GROUPED_CLOSED_RISK'
    result['decision'] = state
    result['failed_checks'] = failed
    if child_metrics['open_observations']['T']:
        result['decision'] = 'DEV_INCONCLUSIVE'
        result['overall_blocker'] = 'UNRESOLVED_TERMINAL_POSITIONS'
    return result
