"""Read-only Q0 native-state diagnosis; no child replay or economic trial.

Three diagnostic booleans were bounded before observation. All current/future
trade outcomes are joined as labels only after the pre-entry feature builder.
The caller owns DEV-only loading, identity seals, persistence and permissions.
"""
from collections import defaultdict, Counter
from datetime import datetime, timezone
import statistics

from backend.research.rebuild import break_channel_structure_v1 as structure

DAY = 86_400_000
STATES = ('last_down_upper_unreclaimed', 'prepared_up_upper_nonascending',
          'prior_stop_same_or_lower_channel')


def key(row):
    return row['symbol'], row['signal_index']


def iso(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()


def build(rows_by_symbol, trades, events, *, eval_start_ms, eval_end_ms):
    """Diagnose original stage-Q records using approved, already-loaded DEV.

    Returns counts, full causal feature rows, outcome-label cohort/quarter/run
    breakdowns, continuous observations and full signal-prefix checks. No
    strategy economics, input loading, output writing or state mutation.
    """
    trades = [t for t in trades if t.get('comparison_stage') == 'Q']
    events = [e for e in events if e.get('comparison_stage') == 'Q']
    if len({key(t) for t in trades}) != len(trades):
        raise RuntimeError('Q0_DUPLICATE_TRADE_ORIGIN')
    if len({key(e) for e in events}) != len(events):
        raise RuntimeError('Q0_DUPLICATE_EVENT_ORIGIN')
    if not {key(t) for t in trades} <= {key(e) for e in events}:
        raise RuntimeError('Q0_TRADE_WITHOUT_EVENT')
    daily = {s: structure.aggregate_daily(rows, split_end_ms=eval_end_ms)['daily']
             for s, rows in rows_by_symbol.items()}
    signals = {s: structure.generate_signals(ds,
               eval_start_ms=ds[0]['bar_open_ts'], eval_end_ms=eval_end_ms,
               require_preparation=True)['signals'] for s, ds in daily.items()}
    return _build_from_native(daily, signals, trades, events,
                              eval_start_ms, eval_end_ms, check_prefix=True)


def _build_from_native(daily_by_symbol, signals_by_symbol, trades, events,
                       start, end, *, check_prefix=False):
    """Pure classifier seam. Public build supplies and prefix-checks originals."""
    bytrade={key(t):t for t in trades}; byevent={key(e):e for e in events}
    # Build exact-simultaneous-close loss groups and parent loss runs, diagnostic only.
    groups=defaultdict(list)
    for t in trades:groups[t['exit_ts']].append(t)
    runs=[];active=[]
    for ts,tsrows in sorted(groups.items()):
     if sum(t['net_bps'] for t in tsrows)<0:active.append((ts,tsrows))
     elif active:runs.append(active);active=[]
    if active:runs.append(active)
    runof={key(t):i+1 for i,run in enumerate(runs) for _,row in run for t in row}
    worstid=(max(range(len(runs)),key=lambda i:-sum(t['net_bps'] for _,row in runs[i] for t in row))+1) if runs else None
    big=sorted((t for t in trades if t['net_bps']>0),key=lambda t:t['net_bps'],reverse=True)[:3]
    bigkeys={key(t) for t in big}
    features=[]; prefix_checks=0
    for symbol,daily in sorted(daily_by_symbol.items()):
     allsignals=signals_by_symbol[symbol]
     current=[s for s in allsignals if s['direction']=='UP' and start<=s['signal_ts']<end]
     if [(s['signal_index'],s['signal_ts']) for s in current] != [(e['signal_index'],e['signal_ts']) for e in events if e['symbol']==symbol]: raise RuntimeError('Q0_EVENT_SIGNAL_IDENTITY')
     for s in current:
      ts=s['signal_ts'];k=(symbol,s['signal_index'])
      if check_prefix:
       prefix=structure.generate_signals([d for d in daily if d['bar_close_ts']<=ts],eval_start_ms=daily[0]['bar_open_ts'],eval_end_ms=ts+DAY,require_preparation=True)['signals']
       if prefix != [v for v in allsignals if v['signal_ts']<=ts]: raise RuntimeError('Q0_SIGNAL_PREFIX_DRIFT')
       prefix_checks+=1
      pu=[v for v in allsignals if v['direction']=='UP' and v['signal_ts']<ts]
      pd=[v for v in allsignals if v['direction']=='DOWN' and v['signal_ts']<ts]
      closed=[t for t in trades if t['symbol']==symbol and t['exit_ts']<=ts]
      pu=pu[-1] if pu else None;pd=pd[-1] if pd else None
      # Q0 stop-bar upper-bound close equals signal close: stop precedes close signal.
      pt=max(closed,key=lambda t:(t['exit_ts'],t['entry_ts'])) if closed else None
      # Feature construction reads current/past prices and already-realized stop state only.
      states={
       'last_down_upper_unreclaimed':None if pd is None else s['confirmation_close']<=pd['upper'],
       'prepared_up_upper_nonascending':None if pu is None else s['upper']<=pu['upper'],
       'prior_stop_same_or_lower_channel':None if pt is None else pt['exit_reason'].startswith('PROTECTIVE_STOP') and s['upper']<=pt['channel_upper'],
      }
      lineage={'last_down_signal_ts':None if pd is None else pd['signal_ts'],
       'last_down_upper':None if pd is None else pd['upper'],
       'previous_up_signal_ts':None if pu is None else pu['signal_ts'],
       'previous_up_upper':None if pu is None else pu['upper'],
       'prior_position_exit_ts':None if pt is None else pt['exit_ts'],
       'prior_position_exit_reason':None if pt is None else pt['exit_reason'],
       'prior_position_trade_sha256':None if pt is None else pt['trade_sha256'],
       'prior_position_upper':None if pt is None else pt['channel_upper'],
       'max_feature_ts':max([ts]+([pt['exit_ts']] if pt else []))}
      assert lineage['max_feature_ts']<=ts
      month=iso(ts)[:7];dt=datetime.fromtimestamp(ts/1000,timezone.utc)
      r={'symbol':symbol,'signal_index':s['signal_index'],'signal_ts':ts,'signal_utc':iso(ts),'quarter':str(dt.year)+'Q'+str((dt.month-1)//3+1),'month':month,
       'status':byevent[k]['status'],'exclusion_reason':byevent[k]['exclusion_reason'],
       'states':states,'lineage':lineage,'confirmation_close':s['confirmation_close'],'upper':s['upper'],'lower':s['lower'],
       'initial_stop_distance_at_signal_bps':(1-s['lower']/s['confirmation_close'])*10000,
       'channel_width_bps':s['channel_width_fraction']*10000,
       'two_day_confirmation_advance_bps':(s['confirmation_close']/daily[s['anchor_daily_index']]['close']-1)*10000}
      # Only now join diagnostic final outcomes. Never fed to feature builder/replay.
      t=bytrade.get(k)
      r['diagnostic_label']={'closed':t is not None,'net_bps':None if t is None else t['net_bps'],'gross_bps':None if t is None else t['gross_bps'],
        'win':None if t is None else t['net_bps']>0,'parent_loss_run_id':runof.get(k),'worst_run':worstid is not None and runof.get(k)==worstid,'top3_winner':k in bigkeys,
        'exit_reason':None if t is None else t['exit_reason'],
        'exit_group_net_bps':None if t is None else sum(v['net_bps'] for v in groups[t['exit_ts']])}
      features.append(r)

    def count(rows,state):
     vals=Counter('unknown' if x['states'][state] is None else str(x['states'][state]).lower() for x in rows)
     n=len(rows);return {'N':n,'true':vals['true'],'false':vals['false'],'unknown':vals['unknown'],'true_share_all':vals['true']/n if n else None}

    cohorts={
     'all_eligible_UP':features,
     'occupied_excluded_UP':[x for x in features if x['status']=='EXCLUDED' and x['exclusion_reason']=='SIGNAL_DURING_OPEN'],
     'other_excluded_UP':[x for x in features if x['status']=='EXCLUDED' and x['exclusion_reason']!='SIGNAL_DURING_OPEN'],
     'all_closed':[x for x in features if x['diagnostic_label']['closed']],
     'closed_losses':[x for x in features if x['diagnostic_label']['closed'] and x['diagnostic_label']['net_bps'] < 0],
     'closed_wins':[x for x in features if x['diagnostic_label']['win'] is True],
     'closed_zeros':[x for x in features if x['diagnostic_label']['closed'] and x['diagnostic_label']['net_bps']==0],
     'top3_winners':[x for x in features if x['diagnostic_label']['top3_winner']],
     'worst_parent_loss_run':[x for x in features if x['diagnostic_label']['worst_run']],
     'ordinary_losses_outside_worst_run':[x for x in features if x['diagnostic_label']['closed'] and x['diagnostic_label']['net_bps'] < 0 and not x['diagnostic_label']['worst_run']],
     'singleton_parent_loss_runs':[x for x in features if x['diagnostic_label']['parent_loss_run_id'] and len(runs[x['diagnostic_label']['parent_loss_run_id']-1])==1],
     'nonworst_multigroup_parent_loss_runs':[x for x in features if x['diagnostic_label']['parent_loss_run_id'] and len(runs[x['diagnostic_label']['parent_loss_run_id']-1])>1 and not x['diagnostic_label']['worst_run']],
     'other_parent_loss_runs':[x for x in features if x['diagnostic_label']['parent_loss_run_id'] and not x['diagnostic_label']['worst_run']],
     'positive_exit_groups':[x for x in features if x['diagnostic_label']['closed'] and x['diagnostic_label']['exit_group_net_bps']>0],
     'zero_exit_groups':[x for x in features if x['diagnostic_label']['closed'] and x['diagnostic_label']['exit_group_net_bps']==0],
    }
    states=list(STATES)
    summaries={state:{name:count(rows,state) for name,rows in cohorts.items()} for state in states}
    quarter={q:{state:{name:count([x for x in rs if x['quarter']==q],state) for name,rs in cohorts.items()} for state in states} for q in sorted({x['quarter'] for x in features})}
    byrun={str(i+1):{'groups':len(run),'trades':sum(len(rs) for _,rs in run),'start_ms':run[0][0],'end_ms':run[-1][0],
     'net_bps':sum(t['net_bps'] for _,rs in run for t in rs),
     'state_occurrences':{s:count([x for x in features if x['diagnostic_label']['parent_loss_run_id']==i+1],s) for s in states}} for i,run in enumerate(runs)}
    # Continuous distributions, no threshold search or candidate selection.
    continuous={}
    for field in ['initial_stop_distance_at_signal_bps','channel_width_bps','two_day_confirmation_advance_bps']:
     continuous[field]={}
     for name,rs in cohorts.items():
      a=sorted(x[field] for x in rs)
      continuous[field][name]={'N':len(a),'min':min(a) if a else None,'median':statistics.median(a) if a else None,'max':max(a) if a else None}
    result={'purpose':'PARENT_Q0_OBSERVABILITY_ONLY_NO_CANDIDATE_ECONOMICS','bounded_states_chosen_before_first_run':states,
     'definitions':{'last_down_upper_unreclaimed':'At current prepared UP confirmation close <= most recent strictly earlier confirmed DOWN attempt frozen upper. Natural band equality only; no tuned threshold.',
     'prepared_up_upper_nonascending':'Current prepared UP frozen upper <= immediately previous strictly earlier prepared UP frozen upper, including held/excluded signals and DEV warmup history.',
     'prior_stop_same_or_lower_channel':'Previously closed same-symbol Q0 position (exit<=signal) was protective stop AND new prepared UP upper <= previous actual entry channel upper. Current/future trade outcome never input.'},
     'limitations':['The third state conditions on prior observed Q0 lifecycle; a child full replay must recompute its own causal ownership if changed.','All quarters are already-used DEV; no independent validation or causal-performance claim.','No aggregate candidate PnL, sweep, child replay, new strategy measurement, external paid AI, validation/OOS access.','Parent loss-run/top3/final outcomes only diagnostic labels after pre-entry feature construction.'],
     'causality_audit':{'full_signal_prefix_checks':prefix_checks,'checks_passed':check_prefix and prefix_checks==len(events),'last_DOWN_and_UP_history':'Strictly prior signal_ts; full causal generator prefix compared at all eligible current signals. Earlier DEV warmup allowed; no validation/OOS.', 'prior_position':'Stored Q0 exit_ts<=current signal_ts; only realized exit reason/band/time used, never prior/current final PnL in feature computation. At same stop-bar close, stop precedes new signal per existing replay semantics.', 'current_values':'Current complete daily confirmation_close and initial2-close channel upper/lower; next-open fill not presumed known at signal.', 'outcomes':'Final current trade net/win/top3/run labels joined only after feature construction; diagnostic only.', 'event_status':'Final opportunity status is a retrospective cohort label; no state predicate uses completed/censored outcomes.', 'unknown_history':'None retained; unknown counts reported against full denominator; no synthetic false history.', 'child_replay_dependency':'Prior-position state depends on actual Q0 ownership. A hypothetical child must rebuild its own causal ownership; parent state labels cannot be a trade subset strategy.'},
     'evaluation_interval_ms':[start,end],'cohort_state_counts':summaries,'quarter_state_counts':quarter,
     'all_parent_loss_runs':byrun,'continuous_observations_no_thresholds':continuous,
     'top3_parent_winners':[{k:v for k,v in t.items() if k in ('symbol','signal_index','entry_ts','exit_ts','net_bps')} for t in big],
     'feature_rows':features,
     'hypotheses_consumed':0,'future_feature_rows':0}
    return result
