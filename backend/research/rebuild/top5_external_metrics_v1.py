"""Ledger attribution and grouped closed-trade loss diagnostics, never entry inputs."""
from collections import Counter, defaultdict
from math import ceil

DAY = 86_400_000


def streaks(groups):
    runs = []; length = 0; loss = 0.; followers = defaultdict(list); pending = 0
    labels = {}; current_ids = []
    for ts, rows in sorted(groups.items()):
        net = sum(t['net_bps'] for t in rows)
        if pending:
            followers[pending].append(net)
        if net < 0:
            length += 1; loss -= net; current_ids.extend(t['identity'] for t in rows)
        else:
            if length:
                runs.append({'length_groups':length,'loss_trade_sum_bps':loss})
                for k in current_ids: labels[k] = length
            length = 0; loss = 0.; current_ids = []
        pending = length
    if length:
        runs.append({'length_groups':length,'loss_trade_sum_bps':loss})
        for k in current_ids: labels[k] = length
    return {'max_length_groups':max((x['length_groups'] for x in runs),default=0),
            'max_loss_trade_sum_bps':max((x['loss_trade_sum_bps'] for x in runs),default=0),
            'length_distribution':dict(Counter(str(x['length_groups']) for x in runs)),
            'next_closed_group_after_loss_length':{str(k):{'groups':len(v),'mean_net_bps':sum(v)/len(v)} for k,v in sorted(followers.items())}}, labels


def grouped(trades):
    groups = defaultdict(list)
    for t in trades: groups[t['exit_ts']].append(t)
    return groups


def drawdown(trades, start, end):
    equity = peak = worst = 0.; peak_time = start; underwater = False; completed = []
    for ts, rows in sorted(grouped(trades).items()):
        equity += sum(t['net_bps'] for t in rows)
        worst = max(worst, peak-equity)
        if equity >= peak:
            if underwater: completed.append((ts-peak_time)/DAY)
            peak = equity; peak_time = ts; underwater = False
        else:
            underwater = True
    return {'closed_group_DD_trade_sum_bps':worst,
            'max_completed_recovery_days':max(completed,default=0),
            'unrecovered_at_end':underwater,
            'open_underwater_days':(end-peak_time)/DAY if underwater else 0,
            'basis':'SIMULTANEOUS_EXIT_GROUP_NET; NOT_ACCOUNT_OR_INTRATRADE_DRAWDOWN'}


def diagnostics(trades, start, end):
    by_symbol = {}; labels = {}
    for s in sorted({t['symbol'] for t in trades}):
        by_symbol[s], marks = streaks(grouped([t for t in trades if t['symbol']==s])); labels.update(marks)
    lane_groups, _ = streaks(grouped(trades))
    weekly = defaultdict(list)
    for t in trades:
        week = (t['exit_ts']//DAY + 3)//7
        weekly[week].append(t)
    clusters = [{'utc_monday_ms':(w*7-3)*DAY,'T':len(v),'net_trade_sum_bps':sum(t['net_bps'] for t in v)} for w,v in sorted(weekly.items())]
    wins = sorted([t['net_bps'] for t in trades if t['net_bps']>0],reverse=True)
    losses = [t for t in trades if t['net_bps']<0]
    return {'by_symbol_streaks':by_symbol,'lane_simultaneous_close_group_streaks':lane_groups,
            'weekly_clusters':clusters, 'drawdown_recovery':drawdown(trades,start,end),
            'gross_profit_trade_sum_bps':sum(wins),
            'gross_loss_trade_sum_bps':-sum(t['net_bps'] for t in losses),
            'top_decile_winners_share':sum(wins[:ceil(len(wins)*.1)])/sum(wins) if wins else None,
            'losses_with_positive_MFE_bound_T':sum(t['mfe_bps']>0 for t in losses),
            'losses_without_positive_MFE_bound_T':sum(t['mfe_bps']<=0 for t in losses),
            'giveback_semantics':'MFE_DIAGNOSTIC_BOUND; NATIVE_EXIT_BAR_MAY_INCLUDE_POST_STOP_MOVEMENT',
            'no_USD_or_account_return_claim':True}, labels


def attribution(parent, child):
    p = {t['identity']:t for t in parent}; c = {t['identity']:t for t in child}
    shared = set(p)&set(c); removed = set(p)-set(c); added = set(c)-set(p)
    for k in sorted(shared):
        for field in ['entry_price','exit_price','gross_bps','cost_bps','net_bps','side','entry_ts','exit_ts']:
            if p[k][field] != c[k][field]:
                raise RuntimeError('MATCHED_NATIVE_GEOMETRY_OR_COST_CHANGED:'+field)
    winners = {k for k,t in p.items() if t['net_bps']>0}
    loser_removed = [p[k] for k in sorted(removed) if p[k]['net_bps']<0]
    winner_removed = [p[k] for k in sorted(removed) if p[k]['net_bps']>0]
    new = [c[k] for k in sorted(added)]
    gross_delta = sum(t['gross_bps'] for t in child)-sum(t['gross_bps'] for t in parent)
    cost_saving = sum(t['cost_bps'] for t in parent)-sum(t['cost_bps'] for t in child)
    delta = sum(t['net_bps'] for t in child)-sum(t['net_bps'] for t in parent)
    decomposition = -sum(t['net_bps'] for t in loser_removed)-sum(t['net_bps'] for t in winner_removed)+sum(t['net_bps'] for t in new)
    if abs(delta-decomposition)>1e-7 or abs(delta-gross_delta-cost_saving)>1e-7:
        raise RuntimeError('NET_ATTRIBUTION_PARITY')
    return {'common_T':len(shared),'removed_loss_T':len(loser_removed),'removed_loss_bps':-sum(t['net_bps'] for t in loser_removed),
            'missed_win_T':len(winner_removed),'missed_win_bps':sum(t['net_bps'] for t in winner_removed),
            'new_T':len(new),'new_net_bps':sum(t['net_bps'] for t in new),
            'winner_count_retention':len(winners&shared)/len(winners) if winners else None,
            'winner_amount_retention':sum(p[k]['net_bps'] for k in sorted(winners&shared))/sum(p[k]['net_bps'] for k in sorted(winners)) if winners else None,
            'gross_delta_bps':gross_delta,'cost_turnover_saving_bps':cost_saving,'net_delta_bps':delta,
            'identities':{'common':sorted(shared),'removed':sorted(removed),'new':sorted(added)},
            'cash_no_trade_net_bps':0.,'mechanism_ablation':'EXACT_PARENT; NOT_INDEPENDENT_EVIDENCE'}
