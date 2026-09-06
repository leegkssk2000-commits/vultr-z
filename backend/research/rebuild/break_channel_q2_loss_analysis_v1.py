"""Existing Q0 losing-run diagnosis only; no policy generation or new replay.

Inputs are previously sealed DEV trades, events, complete daily bars and marked
paths. UTC prices from those daily bars bridge original native4h mark prices;
no market-data partition is opened by this pure analysis module. Outcome labels
and shuffled order are descriptive and never become execution features.
"""
from __future__ import annotations
import collections
import math
import random
from datetime import datetime, timezone

from backend.research.rebuild import break_channel_source_v1 as source
from backend.research.rebuild import break_channel_q1_metrics_v1 as bridge

DAY = 86_400_000
PERMUTATION_SEED = 1192
PERMUTATION_COUNT = 20_000

def iso(t): return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
def quantiles(v):
 s=sorted(v)
 return {str(q):s[round((len(s)-1)*q)] for q in [0,.1,.25,.5,.75,.9,1]} if s else {}
def csum(ts):
 return {'T':len(ts),'wins_T':sum(t['net_bps']>0 for t in ts),'losses_T':sum(t['net_bps']<0 for t in ts),
         **{k:sum(t[k] for t in ts) for k in ['gross_bps','net_bps','cost_bps','funding_bps']},
         'exit_reason_counts':dict(collections.Counter(t.get('exit_reason','P_NATIVE') for t in ts))}
def grouped(trades):
 d=collections.defaultdict(list)
 for t in trades:d[t['exit_ts']].append(t)
 return [dict(exit_ts=t,exit_utc=iso(t),net_bps=sum(x['net_bps'] for x in v),trades=v) for t,v in sorted(d.items())]
def sign_runs(groups):
 out=[]
 for g in groups:
  sign='LOSS' if g['net_bps']<0 else 'WIN' if g['net_bps']>0 else 'ZERO'
  if not out or out[-1]['sign']!=sign:out.append({'sign':sign,'groups':[]})
  out[-1]['groups'].append(g)
 return out

def enclosing_calendar(first_exit, last_exit, start, end):
    """Include midnight fills: left boundary is strictly before first exit."""
    ws = max(start, ((first_exit - 1) // DAY) * DAY)
    we = min(end, max(ws + DAY, ((last_exit + DAY - 1) // DAY) * DAY))
    if not start <= ws < we <= end:
        raise ValueError('INVALID_LOSS_RUN_CALENDAR')
    return ws, we


def ordering_sensitivity(groups):
    """Fixed descriptive null; preserves simultaneous groups, changes only order."""
    runs = sign_runs(groups)
    observed_n = max((len(r['groups']) for r in runs if r['sign'] == 'LOSS'), default=0)
    observed_loss = max((-sum(g['net_bps'] for g in r['groups'])
                         for r in runs if r['sign'] == 'LOSS'), default=0)
    rng = random.Random(PERMUTATION_SEED)
    values = [g['net_bps'] for g in groups]
    null_n, null_loss = [], []
    for _ in range(PERMUTATION_COUNT):
        shuffled = values[:]
        rng.shuffle(shuffled)
        n = loss = mn = ml = 0
        for value in shuffled:
            if value < 0:
                n += 1
                loss -= value
                mn, ml = max(mn, n), max(ml, loss)
            else:
                n = loss = 0
        null_n.append(mn)
        null_loss.append(ml)
    return {'seed': PERMUTATION_SEED, 'permutations': PERMUTATION_COUNT,
            'observed_max_loss_groups': observed_n,
            'observed_max_loss_bps': observed_loss,
            'max_length_quantiles': quantiles(null_n),
            'max_loss_quantiles': quantiles(null_loss),
            'exchangeable_shuffle_fraction_max_length_at_least_observed':
                sum(n >= observed_n for n in null_n) / len(null_n),
            'exchangeable_shuffle_fraction_max_loss_at_least_observed':
                sum(v >= observed_loss for v in null_loss) / len(null_loss),
            'simultaneous_group_values_preserved': True,
            'new_strategy_economics_computed': False,
            'not_formal_p_value': True,
            'exchangeability_assumption_verified': False}


def build(trades_by_stage, opens_by_stage, daily_bars_by_symbol,
          daily_valuation_by_stage, cost_by_symbol, start, end, *, events_by_stage=None):
    """Analyze existing P/Q0 only; root runner owns seals, I/O and source metadata."""
    ts=trades_by_stage;os=opens_by_stage;rows=daily_bars_by_symbol;daily=daily_valuation_by_stage;costs=cost_by_symbol
    if set(ts)!={'P','Q0'} or set(os)!=set(ts) or set(daily)!=set(ts): raise ValueError('P_Q0_ONLY')
    if start>=end or start%DAY or end%DAY: raise ValueError('INVALID_CALENDAR')
    if events_by_stage is not None and set(events_by_stage)!=set(ts): raise ValueError('P_Q0_EVENTS_ONLY')
    for s in ts:
     replay=source.daily_valuation(ts[s],os[s],rows,costs,start,end)
     assert len(replay)==len(daily[s])
     for a,b in zip(replay,daily[s]):
      for k,v in a.items():
       if isinstance(v,(int,float)): assert abs(v-b[k])<1e-7,(s,k,v,b[k])
       else: assert v==b[k]
    q=ts['Q0'];gs=grouped(q);runs=sign_runs(gs)
    top_winners=sorted([t for t in q if t['net_bps']>0],key=lambda t:t['net_bps'],reverse=True)[:math.ceil(sum(t['net_bps']>0 for t in q)*.1)]
    top_losses=sorted([t for t in q if t['net_bps']<0],key=lambda t:t['net_bps'])[:math.ceil(sum(t['net_bps']<0 for t in q)*.1)]
    top_loss_ids={t['origin_key'] for t in top_losses}
    label_rows=[];run_details=[]
    def window(ws,we):
     result={}
     for s in ['P','Q0']:
      w=bridge.window_contributions(ts[s],os[s],rows,costs,start,end,ws,we,daily=daily[s])
      active=[x for x in w['position_contributions'] if any(abs(x['delta'][k])>1e-12 for k in ['net_bps','gross_bps','cost_bps'])]
      result[s]={'totals':w['totals'],'parity':w['parity'],'contributing_positions':active}
     return {'window_start_ms':ws,'window_start_utc':iso(ws),'window_end_ms':we,'window_end_utc':iso(we),'stages':result}
    for i,r in enumerate(runs):
     tr=[t for g in r['groups'] for t in g['trades']]
     a=r['groups'][0]['exit_ts'];b=r['groups'][-1]['exit_ts']
     ws,we=enclosing_calendar(a,b,start,end)
     each={'run_id':i,'sign':r['sign'],'groups_n':len(r['groups']),'group_start_utc':iso(a),'group_end_utc':iso(b),'group_start_ms':a,'group_end_ms':b,
           **csum(tr),'symbols':dict(collections.Counter(t['symbol'] for t in tr)),
           'max_single_loss_bps':max([-t['net_bps'] for t in tr if t['net_bps']<0]+[0]),
           'global_top_decile_loss_T':sum(t['origin_key'] in top_loss_ids for t in tr),
           'global_top_decile_loss_bps':sum(-t['net_bps'] for t in tr if t['origin_key'] in top_loss_ids),
           'origin_keys':[t['origin_key'] for t in tr],
           'same_exit_multisymbol_groups':[{'exit_utc':g['exit_utc'],'net_bps':g['net_bps'],'symbols':[t['symbol'] for t in g['trades']]} for g in r['groups'] if len(g['trades'])>1],
           'daily_enclosing_window':window(ws,we)}
     run_details.append(each)
     for t in tr:label_rows.append({'origin_key':t['origin_key'],'symbol':t['symbol'],'entry_ts':t['entry_ts'],'exit_ts':t['exit_ts'],'net_bps':t['net_bps'],'run_id':i,'run_sign':r['sign'],'run_groups_n':len(r['groups']),'post_outcome_label_not_execution_feature':True})
    # Per-symbol daily marks exactly bridge the previously sealed aggregate path.
    sd={s:source.daily_valuation([t for t in q if t['symbol']==s],[t for t in os['Q0'] if t['symbol']==s],{s:rows[s]},costs,start,end) for s in rows}
    simultaneous=[]
    for i,d in enumerate(daily['Q0']):
     sv={s:sd[s][i]['value'] for s in rows}
     assert abs(sum(sv.values())-d['value'])<1e-7
     negatives={s:v for s,v in sv.items() if v<0};positives={s:v for s,v in sv.items() if v>0}
     simultaneous.append({'mark_ts':d['mark_ts'],'date':d['date'],'net_delta_bps':d['value'],'negative_symbols':negatives,'positive_symbols':positives,'negative_symbols_n':len(negatives),'positive_symbols_n':len(positives),'active_marked_positions':d['active_marked_positions']})
    concurrent_summary={}
    for name,selected in [('all',simultaneous),('portfolio_negative',[x for x in simultaneous if x['net_delta_bps']<0]),('portfolio_positive',[x for x in simultaneous if x['net_delta_bps']>0])]:
     by={}
     for count in range(8):
      ss=[x for x in selected if x['negative_symbols_n']==count]
      by[str(count)]={'days':len(ss),'net_delta_bps':sum(x['net_delta_bps'] for x in ss),'sum_negative_symbol_contributions_bps':sum(sum(x['negative_symbols'].values()) for x in ss),'sum_positive_symbol_contributions_bps':sum(sum(x['positive_symbols'].values()) for x in ss)}
     concurrent_summary[name]=by
    def window_mark_summary(w):
        ds = [d for d in simultaneous if w['window_start_ms'] < d['mark_ts'] <= w['window_end_ms']]
        negative = [d for d in ds if d['net_delta_bps'] < 0]
        concurrent = [d for d in ds if d['negative_symbols_n'] >= 2]
        negative_concurrent = [d for d in negative if d['negative_symbols_n'] >= 2]
        result = {
            'days': len(ds), 'negative_mark_days': len(negative),
            'multiple_negative_symbol_days': len(concurrent),
            'multiple_negative_symbols_net_delta_bps': sum(d['net_delta_bps'] for d in concurrent),
            'single_negative_symbol_net_delta_bps': sum(d['net_delta_bps'] for d in ds if d['negative_symbols_n'] == 1),
            'no_negative_symbol_net_delta_bps': sum(d['net_delta_bps'] for d in ds if d['negative_symbols_n'] == 0),
            'negative_mark_day_net_sum_bps': sum(d['net_delta_bps'] for d in negative),
            'negative_mark_days_with_multiple_negative_symbols': len(negative_concurrent),
            'negative_mark_days_with_multiple_negative_symbols_net_sum_bps': sum(d['net_delta_bps'] for d in negative_concurrent),
            'definition': 'DAILY_SYMBOL_MARK_DELTAS_IN_SAME_WINDOW; NOT_AN_EX_ANTE_STATE_OR_ACCOUNT_RISK_LIMIT',
        }
        delta = (result['multiple_negative_symbols_net_delta_bps'] +
                 result['single_negative_symbol_net_delta_bps'] +
                 result['no_negative_symbol_net_delta_bps'])
        assert abs(delta - w['stages']['Q0']['totals']['delta']['net_bps']) < 1e-7
        return result
    for run in run_details:
        w = run['daily_enclosing_window']
        w['concurrent_mark_summary'] = window_mark_summary(w)
    # Original marked DD, and all marked underwater episodes; no extrema differences.
    def dd_windows():
     peak=0;pt=start;maxdd=0;worst=None;episodes=[];ep=None
     for d in daily['Q0']:
      v=d['cumulative_net_mark_bps'];t=d['mark_ts']
      if v>=peak:
       if ep:ep['recovery_ms']=t;ep['recovery_utc']=iso(t);episodes.append(ep);ep=None
       peak=v;pt=t
      else:
       dd=peak-v
       if ep is None:ep={'peak_ms':pt,'peak_utc':iso(pt),'peak_bps':peak,'trough_ms':t,'trough_utc':iso(t),'drawdown_bps':dd,'recovery_ms':None}
       if dd>ep['drawdown_bps']:ep.update(trough_ms=t,trough_utc=iso(t),drawdown_bps=dd)
       if dd>maxdd:maxdd=dd;worst=(pt,t)
     if ep:episodes.append(ep)
     w = window(*worst) if worst else None
     if w: w['concurrent_mark_summary'] = window_mark_summary(w)
     return {'worst':w,'drawdown_bps':maxdd,'all_episodes':episodes}
    neg_runs=[r for r in run_details if r['sign']=='LOSS'];win_runs=[r for r in run_details if r['sign']=='WIN']
    by_month={}
    for m in sorted({iso(t['exit_ts'])[:7] for t in q}):by_month[m]=csum([t for t in q if iso(t['exit_ts'])[:7]==m])
    out={'schema':'Q0_ALL_LOSS_RUN_DIAGNOSIS_V1','scope':'EXISTING_SEALED_Q0_P_LEDGER_ANALYSIS_NO_NEW_CANDIDATE_ECONOMICS',
         'evaluation_interval_ms':[start,end],
         'new_hypothesis_trials_consumed':0,'new_candidate_economics_computed':False,'validation_rows_decoded':0,'OOS_rows_decoded':0,'paid_external_AI_calls':0,
         'daily_bar_input':'SEALED_COMPLETE_DEV_DAILY_BARS_ONLY; no raw partitions accessed; shared cost and valuation parity PASS',
         'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','G5B_changed':False,'operating_changed':False,
         'definitions':{'closed_run':'Sort completed trades by exact exit_ts, sum simultaneous exits; contiguous negative-net groups are a losing run. Group-positive individual losses may occur outside these runs.',
          'labels':'Full run extent/final returns/large winners are post-outcome diagnostic labels; never executable features.',
          'calendar':'Daily enclosing window=last UTC midnight strictly before first exit through UTC midnight at-or-after last exit, at least1 day; all P/Q positions are marked, not only run trades. Boundary positions use shared cost authority.',
          'simultaneous':'Negative per-symbol daily marked contribution, includes full-roundtrip cost on newly opened marks; not necessarily synchronized intrabar loss.',
          'large':'Global top decile by count of observed winning or losing trade outcomes, no execution threshold.',
          'randomization':'20,000 seeded permutations of existing simultaneous-exit group totals. Preserves values and same-exit groups, destroys temporal/market/occupancy dependence. Exchangeability assumption is false/unverified; descriptive ordering sensitivity, not causal p-value or strategy trial.'},
         'summary':{'P':csum(ts['P']),'Q0':csum(q),'exit_groups':len(gs),'negative_groups':sum(g['net_bps']<0 for g in gs),'positive_groups':sum(g['net_bps']>0 for g in gs),'loss_runs_n':len(neg_runs),'winning_runs_n':len(win_runs),'loss_run_lengths':dict(collections.Counter(r['groups_n'] for r in neg_runs)),
             'loss_trade_net_magnitude_bps':sum(-t['net_bps'] for t in q if t['net_bps']<0),'loss_inside_positive_group_T':sum(t['net_bps']<0 for g in gs if g['net_bps']>0 for t in g['trades']),'wins_inside_negative_group_T':sum(t['net_bps']>0 for g in gs if g['net_bps']<0 for t in g['trades']), 'positive_group_totals_bps':sorted(g['net_bps'] for g in gs if g['net_bps']>0),
             'wins_cost_below_gross_T':sum(t['gross_bps']>0 and t['net_bps']<=0 for t in q),'wins_cost_below_gross_net_bps':sum(t['net_bps'] for t in q if t['gross_bps']>0 and t['net_bps']<=0),
             'initial_risk_bps_quantiles':quantiles([(t['entry_price']-t['entry_stop_price'])/t['entry_price']*10000 for t in q])},
         'all_closed_sign_runs':run_details,'trade_run_labels':label_rows,'top_decile_winners':[dict(origin_key=t['origin_key'],symbol=t['symbol'],entry_utc=iso(t['entry_ts']),exit_utc=iso(t['exit_ts']),net_bps=t['net_bps']) for t in top_winners],
         'top_decile_losses':[dict(origin_key=t['origin_key'],symbol=t['symbol'],entry_utc=iso(t['entry_ts']),exit_utc=iso(t['exit_ts']),net_bps=t['net_bps'],exit_reason=t['exit_reason'],initial_risk_bps=(t['entry_price']-t['entry_stop_price'])/t['entry_price']*10000) for t in top_losses],
         'all_daily_symbol_contributions':simultaneous,'daily_concurrent_loss_summary':concurrent_summary,
         'marked_drawdown':dd_windows(),'closed_net_by_exit_month':by_month,
         'ordering_sensitivity':ordering_sensitivity(gs),
         'remaining_limits':['No independent OOS: all months/periods reused DEV.', 'Observed exits and daily marks do not locate true intrabar stop execution time.', 'No calibrated account sizing or account drawdown claim.', 'Observed ordering/feature association is not proof that a filter causally improves future economics.', 'Q2 candidate execution/parameter selection absent.']}
    return out
