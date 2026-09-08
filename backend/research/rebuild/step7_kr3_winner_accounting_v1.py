"""Stored-ledger arithmetic only; never runs a strategy or reads market rows.

Winner labels use original completed net profit, with top ceil(10%) inherited
from break_channel_q1_metrics_v1. Open marks remain hypothetical and excluded
from winner labels. Attribution is descriptive, not a counterfactual replay.
"""
from collections import Counter, defaultdict
from copy import deepcopy

from backend.research.rebuild import break_channel_q1_metrics_v1 as owner


def index(result):
    return owner._index(result['trades'], result.get('open_observations', []))


def normalize_kr3(document):
    result = deepcopy(document['views']['FULL'])
    stage = document['stages']['FULL']
    m = stage['metrics']
    result['metrics'] = {
        'base_cost': m['base_cost'], 'cost2x': m['cost2x'],
        'closed_T': len(result['trades']), 'open_T': len(result['open_observations']),
        'terminal_net_bps': m['terminal_totals_bps']['net_bps'],
        'terminal_cost2x_net_bps': m['terminal_totals_bps']['cost2x_net_bps'],
        'open_hypothetical_net_mark_bps': m['open_observations']['hypothetical_liquidation_net_mark_bps'],
        'marked_DD_trade_sum_bps': stage['marked_diagnostics']['marked_DD_trade_sum_bps'],
        'closed_loss_groups': stage['diagnostics']['lane_simultaneous_close_group_streaks'],
        'exposure': m['exposure'], 'daily': stage['daily'],
    }
    return result


def snapshot(result):
    m = result['metrics']; base = m['base_cost']
    events = result.get('events', [])
    if isinstance(events, dict):
        events = list(events.values())
    return {
        'raw': len(events), 'admitted': len(result['trades']) + len(result.get('open_observations', [])),
        'closed': len(result['trades']), 'open': len(result.get('open_observations', [])),
        **{k: base[k] for k in ('win_rate', 'average_win_bps', 'average_loss_bps',
            'realized_payoff', 'PF', 'expectancy_bps_per_trade', 'net_bps',
            'completed_trade_rate_per_day')},
        'open_mark_bps': m['open_hypothetical_net_mark_bps'],
        'terminal_net_bps': m['terminal_net_bps'],
        'terminal_cost2x_net_bps': m['terminal_cost2x_net_bps'],
        'marked_DD_trade_sum_bps': m['marked_DD_trade_sum_bps'],
        'closed_loss_groups': m['closed_loss_groups'], 'exposure': m['exposure'],
        'exclusions': dict(Counter(e.get('exclusion_reason') for e in events if e.get('exclusion_reason'))),
        'waiting_at_end': sum(e.get('exclusion_reason') == 'PENDING_WAIT_AT_END' for e in events),
        'risk_R': None, 'protective_SL': None, 'TP': None,
        'formal_pass': False, 'independent': False,
    }


def _sign(item):
    if item is None: return 'ABSENT'
    if item[0] == 'O': return 'OPEN'
    value = item[1]['net_bps']
    return 'WIN' if value > 0 else 'LOSS' if value < 0 else 'FLAT'


def _net(item):
    return owner._values(item)['net_bps']


def _risk(daily):
    if not daily: return {'status': 'NO_STORED_DAILY_MARKS'}
    peak = equity = 0.; peak_ts = daily[0]['interval_start_ms']
    worst = {'drawdown_bps': 0., 'peak_ts': peak_ts, 'trough_ts': peak_ts}
    for row in daily:
        equity += row['value']
        if equity >= peak:
            peak = equity; peak_ts = row['mark_ts']
        if peak - equity > worst['drawdown_bps']:
            worst = {'drawdown_bps': peak - equity, 'peak_ts': peak_ts,
                     'trough_ts': row['mark_ts'], 'peak_value_bps': peak}
    recovery = next((r['mark_ts'] for r in daily
        if r['mark_ts'] > worst['trough_ts'] and
        r['cumulative_net_mark_bps'] >= worst.get('peak_value_bps', 0.)), None)
    worst.update(recovery_ts=recovery, recovered=recovery is not None,
                 terminal_underwater_bps=peak-equity)
    return worst


def compare(parent, child):
    p, c = index(parent), index(child)
    out = owner.symmetric_attribution(parent['trades'], parent.get('open_observations', []),
        child['trades'], child.get('open_observations', []))
    out['comparison_type'] = 'ENTRY_REQUALIFICATION_CHANGE'
    out['large_winner_owner'] = 'break_channel_q1_metrics_v1.symmetric_attribution; ceil(0.1 * completed parent winners), descending original net, origin tie-break'
    out['sign_transitions'] = dict(Counter(_sign(p.get(k))+'->'+_sign(c.get(k)) for k in p.keys() | c.keys()))
    partitions = {
        'common_CC_OO': sum(out['groups'][g]['marked']['delta']['net_bps'] for g in ('CC','OO')),
        'removed': sum(out['groups'][g]['marked']['delta']['net_bps'] for g in ('removed_C','removed_O')),
        'new': sum(out['groups'][g]['marked']['delta']['net_bps'] for g in ('new_C','new_O')),
        'closed_open_transitions': sum(out['groups'][g]['marked']['delta']['net_bps'] for g in ('CO','OC')),
    }
    owner._same(sum(partitions.values()), out['marked_delta_bps_not_realized'], 'FOUR_WAY_TERMINAL_PARITY')
    out['four_way_terminal_delta'] = dict(partitions, parity='PASS', costs_already_in_net=True)
    deltas = []; by_symbol = defaultdict(float); by_signal = defaultdict(float)
    for k in sorted(p.keys() | c.keys()):
        row = (c.get(k) or p[k])[1]; delta = _net(c.get(k)) - _net(p.get(k))
        deltas.append({'origin': k, 'symbol': row['symbol'], 'signal_ts': row['signal_ts'], 'delta_bps': delta})
        by_symbol[row['symbol']] += delta; by_signal[str(row['signal_ts'])] += delta
    total = out['marked_delta_bps_not_realized']; hype = by_symbol.get('HYPE-USDT', 0.)
    positive = sum(max(0., x['delta_bps']) for x in deltas)
    largest = max(deltas, key=lambda x: x['delta_bps'], default=None)
    largest_event = max(by_signal.items(), key=lambda x:x[1], default=None)
    out['concentration'] = {
        'origin_deltas': deltas, 'by_symbol_delta_bps': dict(by_symbol),
        'same_raw_signal_close_event_delta_bps': dict(by_signal),
        'largest_positive_origin': largest, 'largest_signal_close_event': largest_event,
        'positive_delta_denominator_bps': positive,
        'largest_origin_positive_share': max(0., largest['delta_bps'])/positive if largest and positive else None,
        'hype_delta_bps': hype, 'hype_share_of_signed_total': hype/total if total else None,
        'delta_excluding_hype_bps': total-hype,
        'interpretation': 'SAVED_ARITHMETIC_ONLY; EVENT_IS_COMMON_ORIGINAL_SIGNAL_CLOSE; NOT_IDENTIFIED_INDEPENDENT_MARKET_EVENT; NO_SYMBOL_REMOVAL_REPLAY',
    }
    pd = parent['metrics'].get('daily', []); cd = child['metrics'].get('daily', [])
    if [r['mark_ts'] for r in pd] != [r['mark_ts'] for r in cd]:
        raise ValueError('STORED_DAILY_CALENDAR_MISMATCH')
    pr, cr = _risk(pd), _risk(cd); windows = []
    for label, risk in (('PARENT', pr), ('CHILD', cr)):
        if 'peak_ts' not in risk: continue
        lo, hi = risk['peak_ts'], risk['trough_ts']
        pv = sum(r['value'] for r in pd if lo < r['mark_ts'] <= hi)
        cv = sum(r['value'] for r in cd if lo < r['mark_ts'] <= hi)
        windows.append({'owner': label, 'start_ms': lo, 'end_ms': hi,
                        'parent_net_change_bps': pv, 'child_net_change_bps': cv, 'delta_bps': cv-pv})
    out['same_calendar_risk'] = {'parent': pr, 'child': cr, 'worst_drawdown_windows': windows,
        'basis': 'SAVED_DAILY_MARK_INCREMENTS; NO_NEW_PATH; OVERLAPPING_WINDOWS_NOT_SUMMED'}
    return out


def repair_cohorts(kr3, b, child, a=None):
    k, bi, c = map(index, (kr3, b, child))
    harmed = [x for x in k if _sign(k[x]) == 'WIN' and _sign(bi.get(x)) != 'WIN']
    restored = [x for x in harmed if _sign(c.get(x)) == 'WIN']
    capped = lambda x, other: min(k[x][1]['net_bps'], max(0., other[x][1]['net_bps'])) if _sign(other.get(x)) == 'WIN' else 0.
    result = {'harmed_KR3_winners': len(harmed), 'restored_to_completed_win': len(restored),
        'restored_origins': restored, 'restored_KR3_capped_profit_bps': sum(capped(x,c) for x in restored),
        'all_KR3_winner_capped_profit_change_vs_B_bps': sum(capped(x,c)-capped(x,bi) for x in k if _sign(k[x])=='WIN'),
        'restored_actual_child_net_bps': sum(c[x][1]['net_bps'] for x in restored),
        'newly_harmed_B_completed_winners': [x for x in bi if _sign(bi[x])=='WIN' and _sign(c.get(x))!='WIN'],
        'newly_harmed_KR3_preserved_winners': [x for x in k if _sign(k[x])=='WIN' and _sign(bi.get(x))=='WIN' and _sign(c.get(x))!='WIN'],
        'open_child_is_not_restored_win': True}
    if a is None:
        result['A85'] = {'status':'NOT_APPLICABLE_NO_AUTHORIZED_A_PERIOD_REPLAY'}
    else:
        ai = index(a); excluded = ai.keys()-bi.keys(); revived = excluded & c.keys()
        closed = [x for x in revived if c[x][0]=='C']; opened = [x for x in revived if c[x][0]=='O']
        result['A85'] = {'original_cohort_T':len(excluded), 'revived_T':len(revived),
            'revived_closed_T':len(closed), 'revived_open_T':len(opened),
            'revived_wins_T':sum(_sign(c[x])=='WIN' for x in closed),
            'revived_losses_T':sum(_sign(c[x])=='LOSS' for x in closed),
            'actual_child_closed_net_bps':sum(c[x][1]['net_bps'] for x in closed),
            'actual_child_loss_sum_bps':sum(min(0.,c[x][1]['net_bps']) for x in closed),
            'actual_child_win_sum_bps':sum(max(0.,c[x][1]['net_bps']) for x in closed),
            'actual_child_open_mark_bps':sum(_net(c[x]) for x in opened),
            'original_A_net_of_revived_bps':sum(_net(ai[x]) for x in revived),
            'not_reentered_T':len(excluded-revived), 'origins':sorted(revived),
            'old_A_pnl_not_used_as_child_pnl':True}
    return result
