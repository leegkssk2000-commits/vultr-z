"""Two explicitly allocated Supertrend DEV adaptations, never operating policy."""
from __future__ import annotations
import argparse
import copy
import gzip
import json
import math
from pathlib import Path
from backend.research.rebuild import top5_diverse_batch_execution_v1 as previous
from backend.research.rebuild import top5_external_features_v1 as features
from backend.research.rebuild import supertrend_flip_direction_dev_v1 as direction

old=previous.old
ROOT=old.ROOT
CONTRACT='backend/research/contracts/supertrend_flip_ab_v1.json'
OUTPUT='research/development_evidence/SUPERTREND_FLIP_AB_20260906_V1'
PROPOSAL='research/development_evidence/TOP5_PRIMARY_SOURCE_20260906_V1/EXPERIMENT_BUNDLE.json'
LANE=previous.prep.SUPERTREND
INTERVAL=14_400_000
BUDGET={'previous_applications':20,'allocated_new_trials':2,'A':1,'B':1,'cumulative_after':22,
        'automatic_extension':False,'paid_external_AI_calls':0}
RULES={
 'calculation':'Existing top5_external_features_v1.supertrend, ATR RMA length10 multiplier3; initial down; no changed seed or parameter search.',
 'signals':'Closed i>=239; up flip is direction[i-1]=-1,direction[i]=+1. Down flip is inverse. Only close<DEV end is a signal.',
 'entry':'A/B same enrolled up flips; next bar open once, long only; no initial-state entry, confirmation, delay or queued re-entry.',
 'A_exit':'Existing 12 actual bars: signal i,entry open[i+1],exit close[i+12]. Shared exit-bar ownership unchanged.',
 'B_exit':'First down flip after entry, exit at next open<DEV end including observed price gaps. Missing time bars fail integrity. No short or fixed holding limit.',
 'B_ownership':'One long per symbol; fills at open before observing that bar close; new up flip at exit-bar close may schedule a later entry. Fixed A origins are independent diagnostic positions.',
 'risk':'Current frozen V2 has no separately specified native SL. No new SL,TP,pyramiding or notional sizing; equal-notional trade-bps research only.',
 'tail':'Both A/B enroll only if hypothetical unchanged hold12 close[i+12]<DEV end. Time-only criterion, independent of actual B exit.',
 'terminal':'Last usable signal/mark close<DEV end. A scheduled exit may use final-row open<end even when its close==end; never its later range. Otherwise keep open CENSORED,not WINDOW_END fill.',
 'open_cost':'Inherited modeled funding counts entry_ts<settlement_ts<=exit_or_mark_ts,not actual exchange funding. Entry-side costs NOT_SEPARATELY_BOUND from round-trip binding; no arbitrary halving. Hypothetical liquidation mark uses full shared charge/floor and cost2 separately.',
 'comparisons':'P->A,A->B,P->B full replay; B_FIXED_A on all A completed origins separately, including censored origins; paired completers only diagnostic.',
 'uncertainty':'Existing entry-week paired bootstrap1000 seed1178 on closed trades only; no censoring or long-holding dependence correction; reusedDEV not independent validation.',
 'decision':'Preserve inherited DEV comparison/risk checks as diagnostic,with all origin presences including censored and total exposure. Any censored child makes overall DEV_INCONCLUSIVE; retain closed_screen_decision. No adoption or formal credit.',
}


def flip_signals(rows, split_end_ms=math.inf):
    state=features.supertrend(rows,length=10,multiplier=3.)
    up=[i for i in range(239,len(rows)) if rows[i]['bar_close_ts']<split_end_ms and state['direction'][i-1]==-1 and state['direction'][i]==1]
    down=[i for i in range(1,len(rows)) if rows[i]['bar_close_ts']<split_end_ms and state['direction'][i-1]==1 and state['direction'][i]==-1]
    return up,down,state


def charge_completed(raw, symbol, stage, policy, costs, rows):
    ts=[]
    for value in raw:
        t=old.charge(value,symbol,LANE,stage,policy,costs,rows,INTERVAL)
        t.pop('trade_sha256',None)
        t.update(origin_key=previous.source_key(t),comparison_stage=stage,status='COMPLETED')
        t['trade_sha256']=old.digest(t);ts.append(t)
    return ts


def charge_open(raw, symbol, stage, policy, costs, rows):
    answer=[]
    for value in raw:
        # A temporary mark calculation only; never persisted as a completed fill.
        mark={**value,'gross_bps':value['gross_mark_bps'],'exit_ts':value['mark_ts'],'exit_price':value['mark_price']}
        hypot=old.charge(mark,symbol,LANE,stage,policy,costs,rows,INTERVAL)
        t={**value,'lane_id':LANE,'symbol':symbol,'comparison_stage':stage,'scenario':stage,
           'status':'CENSORED','split':'REUSED_DEVELOPMENT','modeled_funding_accrued_bps':hypot['funding_bps'],
           'funding_settlements_elapsed':hypot['funding_settlements_crossed'],
           'entry_side_cost_bps':None,'entry_side_cost_status':'NOT_SEPARATELY_BOUND',
           'hypothetical_liquidation_cost_bps':hypot['cost_bps'],
           'hypothetical_liquidation_net_mark_bps':hypot['net_bps'],
           'hypothetical_liquidation_cost2x_net_mark_bps':hypot['cost2x_net_bps'],
           'hypothetical_cost_components_bps':{k:hypot[k] for k in ('fee_bps','spread_bps','impact_bps','slippage_bps','funding_bps','frozen_floor_reserve_bps')},
           'data_sha256':policy['combined_data_sha256'],'cost_sha256':policy['cost_binding_sha256'],
           'config_sha256':policy['receipt_sha256'],'code_sha256':old.digest(policy['code_files_sha256']),
           'actual_exit':False,'account_return_claimed':False,**old.probe.DEV_AUTH}
        t['origin_key']=previous.source_key(t);t['observation_sha256']=old.digest(t);answer.append(t)
    return answer


def censored_attribution(parent, child, open_child):
    p={previous.source_key(t):t for t in parent};c={previous.source_key(t):t for t in child};o={previous.source_key(t):t for t in open_child}
    if len(p)!=len(parent) or len(c)!=len(child) or len(o)!=len(open_child) or c.keys()&o.keys():raise RuntimeError('DUPLICATE_OR_RESOLVED_CENSORED_ORIGIN')
    common=sorted(p.keys()&c.keys());unresolved=sorted(p.keys()&o.keys());removed=sorted(p.keys()-(c.keys()|o.keys()));new=sorted(c.keys()-p.keys());new_open=sorted(o.keys()-p.keys())
    net=lambda seq:sum(t['net_bps'] for t in seq)
    a={'common_completed_T':len(common),'common_censored_T':len(unresolved),'removed_T':len(removed),'new_completed_T':len(new),'new_censored_T':len(new_open),
       'common_completed_delta_bps':sum(c[k]['net_bps']-p[k]['net_bps'] for k in common),
       'removed_parent_net_bps':net([p[k] for k in removed]),
       'parent_net_on_censored_origins_bps':net([p[k] for k in unresolved]),
       'new_completed_net_bps':net([c[k] for k in new]),
       'closed_net_delta_bps':net(child)-net(parent),
       'unfilled_parent_loss_bps':-sum(min(0,p[k]['net_bps']) for k in removed),
       'unfilled_parent_winner_bps':sum(max(0,p[k]['net_bps']) for k in removed),
       'closed_delta_semantics':'Common delta minus truly unfilled parent net minus parent net on still-open child origins plus new completed net; censoring is not avoided loss or missed profit.',
       'terminal_hypothetical_mark_bps':sum(t['hypothetical_liquidation_net_mark_bps'] for t in open_child),
       'marked_delta_bps_not_realized':net(child)+sum(t['hypothetical_liquidation_net_mark_bps'] for t in open_child)-net(parent),
       'origins':{'common_completed':sorted(common),'common_censored':sorted(unresolved),'removed':sorted(removed),'new_completed':sorted(new),'new_censored':sorted(new_open)}}
    bridge=a['common_completed_delta_bps']-a['removed_parent_net_bps']-a['parent_net_on_censored_origins_bps']+a['new_completed_net_bps']
    if abs(bridge-a['closed_net_delta_bps'])>1e-7:raise RuntimeError('CENSORED_ACCOUNTING_BRIDGE')
    winners=sorted([k for k in p if p[k]['net_bps']>0],key=lambda k:(-p[k]['net_bps'],k))
    for label,keys in [('winner',winners),('large_winner',winners[:math.ceil(len(winners)*.1)])]:
        total=sum(p[k]['net_bps'] for k in keys)
        retained=sum(min(p[k]['net_bps'],max(0,c[k]['net_bps'])) for k in keys if k in c)
        uncertain=sum(p[k]['net_bps'] for k in keys if k in o)
        a[label]={'parent_T':len(keys),'parent_positive_bps':total,'resolved_preserved_bps':retained,'unresolved_parent_positive_bps':uncertain,
                  'amount_retention_lower':retained/total if total else None,'amount_retention_upper':(retained+uncertain)/total if total else None,
                  'bound_semantics':'Bounds on capped retained original profit,not bounds on total future PnL.'}
    # Resolved common losses/profits can use the immutable common attribution helper.
    a['resolved_common_effects']=previous.attribute([p[k] for k in sorted(common)],[c[k] for k in sorted(common)])
    return a


def summarize_stage(trades, opened, events, policy, symbols):
    m=old.metrics(trades,[e for e in events if e['status']!='CENSORED'],policy,symbols)
    m.update(raw_signals=len(events),admitted_signals=sum(e['admission'] for e in events),
             censored_signals=sum(e['status']=='CENSORED' for e in events))
    open_days=sum(t['hold_ms'] for t in opened)/86_400_000
    m['open_observations']={'T':len(opened),'exposure_symbol_days':open_days,
        'gross_mark_bps':sum(t['gross_mark_bps'] for t in opened),
        'modeled_funding_accrued_bps':sum(t['modeled_funding_accrued_bps'] for t in opened),
        'entry_side_cost_status':'NOT_SEPARATELY_BOUND',
        'hypothetical_liquidation_cost_bps':sum(t['hypothetical_liquidation_cost_bps'] for t in opened),
        'hypothetical_liquidation_net_mark_bps':sum(t['hypothetical_liquidation_net_mark_bps'] for t in opened),
        'hypothetical_liquidation_cost2x_net_mark_bps':sum(t['hypothetical_liquidation_cost2x_net_mark_bps'] for t in opened)}
    m['entries_including_censored_T']=len(trades)+len(opened)
    m['total_exposure_symbol_days']=m['base_cost']['exposure_symbol_days']+open_days
    m['closed_plus_hypothetical_terminal_mark_bps']=m['base_cost']['net_bps']+m['open_observations']['hypothetical_liquidation_net_mark_bps']
    return m


def compare(p,c,o,pm,cm,pdiag,cdiag,policy,gate):
    unc=old.probe.cluster_uncertainty({'base':p,'child':c},policy)
    adjusted=copy.deepcopy(cm);adjusted['base_cost']['exposure_symbol_days']=cm['total_exposure_symbol_days']
    d=previous.economic_decision(p,c+o,{'parent':pm,'child':adjusted},unc,{'parent':pdiag,'child':cdiag},gate)
    d['origin_presence_retention_including_censored']=d.pop('retention')
    d['parent_winner_origin_presence_not_profit_retention']=d.pop('winner_retention')
    d['closed_screen_decision']=d['decision']
    d['closed_screen_scope']='Closed PnL/PF/payoff,source presence including unresolved,total exposure,closed-group risk. Source-overlap failure is a criterion failure,not proof all mechanisms lack profit.'
    if o:d['decision']='DEV_INCONCLUSIVE';d['overall_blocker']='UNRESOLVED_TERMINAL_POSITIONS'
    return {'decision':d,'uncertainty':unc,'attribution':censored_attribution(p,c,o),
            'uncertainty_limit':'Closed trades clustered by entry-week;does not correct censoring,long-holding dependence or repeatedDEV selection.'}


def authorize():
    c=old.read(CONTRACT);old.probe.verify_seal(c,'ST_FLIP_AB')
    if c['budget']!=BUDGET or c['rules']!=RULES or c['new_outcomes_seen_at_freeze'] is not False:raise RuntimeError('ALLOCATION_OR_RULE_DRIFT')
    if c['authorization']!='EXPLICIT_USER_SUPERTREND_A_B_TWO_TRIALS_AFTER_PR1188':raise RuntimeError('AUTHORIZATION_REQUIRED')
    for k,v in old.probe.DEV_AUTH.items():
        if c.get(k)!=v:raise RuntimeError('AUTHORITY_DRIFT:'+k)
    for k in ('validation_access','OOS_access','G5B_changed','G6_authorized','operating_changed'):
        if c.get(k) is not False:raise RuntimeError('PROTECTED_BOUNDARY:'+k)
    for p,sha in {**c['code_files_sha256'],**c['preserved_files_sha256']}.items():
        if old.file_sha(ROOT/p)!=sha:raise RuntimeError('FROZEN_IDENTITY:'+p)
    return c


def report(r):
    lines=['# Supertrend A/B: measured ZEL DEV adaptations','',
      'A replaces the impulse trigger by official down-to-up flips and retains hold12. B uses the same flips and exits at the next open after the first opposite flip, long/flat only. Source-complete replication is not claimed.',
      '', 'Prior20 applications preserved;A ordinal21 and B ordinal22 consume exactly2. Reproduction is not another hypothesis. All values are equal-notional modeled trade-bps,not account returns.',
      '', '| Stage | Closed / open T | Gross E | Net E | PF | Payoff | Cost2 E | Closed net sum | Closed loss-run | Total exposure days |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt=lambda v:'NA' if v is None else f'{v:.4f}'
    for s in ('P','A','B','B_FIXED_A'):
        m=r['metrics'][s];b=m['base_cost'];di=r['diagnostics'][s]
        v=[b['gross_expectancy_bps'],b['expectancy_bps_per_trade'],b['PF'],b['realized_payoff'],m['cost2x']['expectancy_bps_per_trade'],b['net_bps'],di['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'],m['total_exposure_symbol_days']]
        lines.append(f"| {s} | {b['completed_T']} / {m['open_observations']['T']} | "+' | '.join(fmt(x) for x in v)+' |')
    lines+=['','Closed E/PF/payoff and loss-run exclude open marks. Exposure includes censored holding. B_FIXED_A is an independent-position diagnostic,not a deployable portfolio.','',
      '| Comparison | Overall / closed screen | Closed delta | Common closed / censored | Unfilled / new closed / new open | Winner amount bounds | Large winner bounds | Delta E95% |',
      '|---|---|---:|---|---|---|---|---|']
    for name,v in r['comparisons'].items():
        d=v['decision'];a=v['attribution'];bounds=lambda k:str([a[k]['amount_retention_lower'],a[k]['amount_retention_upper']])
        lines.append(f"| {name} | {d['decision']} / {d['closed_screen_decision']} | {a['closed_net_delta_bps']:.4f} | {a['common_completed_T']} / {a['common_censored_T']} | {a['removed_T']} / {a['new_completed_T']} / {a['new_censored_T']} | {bounds('winner')} | {bounds('large_winner')} | {d['child_minus_parent_95pct_interval_bps']} |")
    lines+=['','## Unclosed observations: no fabricated liquidation','',
      '| Stage | Open T | Gross mark | Modeled funding accrued | Hypothetical roundtrip liquidation cost | Hypothetical net mark | Cost2 hypothetical net mark | Open exposure days |',
      '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in ('B','B_FIXED_A'):
        o=r['metrics'][s]['open_observations'];lines.append(f"| {s} | {o['T']} | "+' | '.join(fmt(o[k]) for k in ('gross_mark_bps','modeled_funding_accrued_bps','hypothetical_liquidation_cost_bps','hypothetical_liquidation_net_mark_bps','hypothetical_liquidation_cost2x_net_mark_bps','exposure_symbol_days'))+' |')
    lines+=['','Entry-side fee/spread/impact is NOT_SEPARATELY_BOUND by the roundtrip model. Hypothetical liquidation cost includes the full frozen cost/floor; it is not accrued cost or a realized exit. Winner retention bounds concern capped original profit,not total future PnL.',
      '', 'Source-trigger overlap is exact signal-time coincidence only. P→A and P→B are full mechanism comparisons. A→B isolates holding/exit on fixed A origins plus a separate full ownership replay. Paired-completer metrics are in receipt.json; unresolved A origins remain visible.',
      '', 'Weekly bootstrap is closed-only and entry-week clustered;it does not adjust for censoring or long holding dependence. ExistingDEV reuse and prior20 trials remain recorded. No independent significance, operating adoption, validation/OOS, G5B change or live authority is created.',
      '', 'See receipt.json for source admission,events,all three decompositions,fees/funding,risk diagnostics,per-symbol metrics and immutable hashes. New paid externalAI0;actual Gemini video NOT_RUN.', '']
    return '\n'.join(lines).encode()


def run(data_dir,verify_only=False):
    c=authorize();out=ROOT/OUTPUT
    if (out/'receipt.json').exists() and not verify_only:raise RuntimeError('ALLOCATED_TRIALS_CONSUMED_USE_VERIFY_ONLY')
    p,dev,four,one,access=previous.prior.previous.load_inputs(data_dir)
    if p['combined_data_sha256']!=c['data_sha256'] or p['cost_binding_sha256']!=c['cost_sha256']:raise RuntimeError('DATA_COST_BINDING')
    p={**p,'batch_id':c['batch_id'],'receipt_sha256':c['receipt_sha256'],'code_files_sha256':{**p['code_files_sha256'],**c['code_files_sha256']}}
    parent=next(v for v in old.read(old.FREEZE)['children'] if v['lane_id']==LANE)
    if old.digest(parent)!=c['parent_sha256']:raise RuntimeError('PARENT_IDENTITY')
    baseline=previous.prior.previous.read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz')
    stages={k:[] for k in ('P','A','B','B_FIXED_A')};opened={k:[] for k in stages};events={k:[] for k in stages};trace=[];admission={}
    with old.probe.io_boundary([],out):
        for symbol,rows in four.items():
            rawp=previous.prep.causal_signals(rows,parent['executable_spec'])
            end=p['development_interval_ms'][1];up,down,_=flip_signals(rows,end)
            enrolled,tail=previous.eligible_signals(rows,up,12,0,end)
            pt,pe=previous.evaluate(rows,rawp,parent,p,dev['cost_by_symbol'],symbol,'P')
            previous.prior.assert_parent_parity(pt,[t for t in baseline if t['lane_id']==LANE and t['symbol']==symbol])
            at,ae=previous.evaluate(rows,enrolled,parent,p,dev['cost_by_symbol'],symbol,'A')
            stages['P'].extend(pt);stages['A'].extend(at);events['P'].extend(pe);events['A'].extend(ae)
            local={}
            for stage,signals,fixed in [('B',enrolled,False),('B_FIXED_A',[t['signal_index'] for t in at],True)]:
                raw=direction.replay_direction(rows,signals,down,split_start_ms=p['development_interval_ms'][0],split_end_ms=end,interval_ms=INTERVAL,fixed_origins=fixed)
                ts=charge_completed(raw['trades'],symbol,stage,p,dev['cost_by_symbol'],rows)
                os=charge_open(raw['open_positions'],symbol,stage,p,dev['cost_by_symbol'],rows)
                stages[stage].extend(ts);opened[stage].extend(os)
                events[stage].extend(dict(e,lane_id=LANE,symbol=symbol,scenario=stage,admission=True) for e in raw['events'])
                trace.extend(dict(e,lane_id=LANE,symbol=symbol,comparison_stage=stage) for e in raw['trace'])
                local[stage]=(ts,os)
            if len(local['B'][1])>1 or len(local['B'][0])+len(local['B'][1])!=len(enrolled):raise RuntimeError('ALTERNATING_FLIP_OWNERSHIP')
            bm={previous.source_key(t):t for t in local['B'][0]+local['B'][1]}
            for t in local['B_FIXED_A'][0]+local['B_FIXED_A'][1]:
                base=bm[previous.source_key(t)]
                for k in ('status','entry_ts','entry_price','exit_ts','exit_price','net_bps','mark_ts','mark_price','gross_mark_bps'):
                    if t.get(k)!=base.get(k):raise RuntimeError('FIXED_ORIGIN_REPLAY_PARITY:'+k)
            admission[symbol]={'raw_parent_signals':len(rawp),'raw_up_flips':len(up),'enrolled_up_flips':len(enrolled),'time_only_tail_excluded':tail,'raw_down_flips':len(down)}
        metrics={s:summarize_stage(stages[s],opened[s],events[s],p,list(four)) for s in stages}
        diagnostics={s:previous.prior.diagnostic.diagnostics(ts,*p['development_interval_ms'])[0] for s,ts in stages.items()}
        comparisons={name:compare(stages[a],stages[b],opened[b],metrics[a],metrics[b],diagnostics[a],diagnostics[b],p,c['selection_rule']) for name,a,b in [('P_to_A','P','A'),('A_to_B','A','B'),('P_to_B','P','B'),('A_to_B_FIXED','A','B_FIXED_A')]}
        keys={previous.source_key(t) for t in stages['B_FIXED_A']}
        paired_a=[t for t in stages['A'] if previous.source_key(t) in keys]
        paired={'scope':'DIAGNOSTIC_PAIRED_COMPLETERS_ONLY','completed_pairs':len(keys),'unresolved_A_origins':len(opened['B_FIXED_A']),
                'A':old.metrics(paired_a,[],p,list(four)),'B_FIXED_A':old.metrics(stages['B_FIXED_A'],[],p,list(four)),
                'uncertainty':old.probe.cluster_uncertainty({'base':paired_a,'child':stages['B_FIXED_A']},p)}
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    artifacts={};ledger=[];event_rows=[]
    for s in stages:
        for t in stages[s]:
            t=dict(t,comparison_stage=s,scenario=s,status='COMPLETED');t.pop('trade_sha256',None);t['trade_sha256']=old.digest(t);ledger.append(t)
        event_rows.extend(dict(e,comparison_stage=s) for e in events[s])
    for name,items in [('trades',ledger),('open_observations',[t for ts in opened.values() for t in ts]),('events',event_rows),('exit_trace',trace)]:
        raw=b''.join(old.probe.canonical(t) for t in sorted(items,key=lambda t:(t.get('comparison_stage',''),t.get('symbol',''),t.get('ts',t.get('signal_ts',0)),t.get('signal_ts',0))))
        path=out/(name+'.jsonl.gz');payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
        if gzip.decompress(payload)!=raw:raise RuntimeError('REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,payload,verify_only=verify_only);artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(items),'file_sha256':old.file_sha(path)}
    r=old.seal({'batch_id':c['batch_id'],'contract_sha256':c['receipt_sha256'],'metrics':metrics,'diagnostics':diagnostics,'comparisons':comparisons,'paired_completers':paired,'admission':admission,'artifacts':artifacts,
        'budget':{**BUDGET,'new_trials_consumed':2,'remaining_allocated_trials':0},'data_reuse_history':c['data_reuse_history'],'source_access':access,
        'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],'parent_parity':'PASS','B_fixed_origin_subset_parity':'PASS','ZEL_adaptation_not_source_complete_replica':True,
        'validation_rows_decoded':0,'OOS_rows_decoded':0,'paid_external_AI_calls':0,'Gemini_actual_video':'NOT_RUN','G5B_changed':False,'operating_changed':False,**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(r),verify_only=verify_only)
    paths=[CONTRACT]+[str((out/n).relative_to(ROOT)) for n in ('receipt.json','RESULTS.md','trades.jsonl.gz','open_observations.jsonl.gz','events.jsonl.gz','exit_trace.jsonl.gz')]
    durable=old.seal({'result_receipt_sha256':r['receipt_sha256'],'files_sha256':{p:old.file_sha(ROOT/p) for p in paths},'code_files_sha256':c['code_files_sha256'],'preserved_files_sha256':c['preserved_files_sha256'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return r


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt':r['receipt_sha256'],'comparisons':{k:v['decision'] for k,v in r['comparisons'].items()}},indent=2))
