"""Two allocated daily CB1 adaptations over preserved DEV data and accounting.

This adapter never edits a parent, old receipt, formal gate, or operating owner.
"""
from __future__ import annotations
import argparse
import gzip
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.research.rebuild import supertrend_flip_ab_v1 as prior
from backend.research.rebuild import top5_external_repair_v1 as inputs
from backend.research.rebuild import break_channel_structure_v1 as structure
from backend.research.rebuild import break_channel_metrics_v1 as accounting

old=prior.old
ROOT=old.ROOT
LANE='break_and_continue_main'
DAY=86_400_000
BAR=14_400_000
OUTPUT='research/development_evidence/BREAK_CHANNEL_SOURCE_20260906_V1'
CONTRACT=OUTPUT+'/SPEC.json'
SOURCE=OUTPUT+'/SOURCE_AND_SPEC.md'
BUDGET={'previous_applications':22,'allocated_new_trials':2,'Q':1,'Q_minus':1,
        'cumulative_after':24,'automatic_extension':False,'paid_external_AI_calls':0}
CELL={'j_days':2,'d_days':2,'x_percent':0.0,'c_percent':0.5}
RULES={
 'source':'Hudson-Urquhart Appendix5 CB1 pp217-218; literal percent; parameter/menu contradictions remain,not repaired from best-return table.',
 'selection_order':'DailyCB1(no fixedk); smallest listedj2; smallest listedd2; x0(no added hurdle/unit ambiguity); largest explicitly listedc0.5percent for shortDEV applicability. No DEV signal count or return consulted.',
 'daily':'UTC six contiguous4h bars; no synthetic partialdays. Previous2 daily CLOSE extrema only. H/L-1<=0.005 prepares channel,U=L*1.005,D=H*0.995.',
 'confirmation':'DESIGN_PRIOR freeze bands at first breakout,2 consecutive closes strictly beyond band; either close below latchedD rejects/cancels UP even without confirmedDOWN; DOWNmaycontinue. Cancel failed attempt,do not restart same day; may rearm followingday. Qminus removes only bullish preparation.',
 'exit':'DESIGN_PRIOR common bearish2-close confirmation has no preparation gate; hold until next-open bearish exit or fixed initialchannelD protective stop. No fixedhold/TP/trailing/short.',
 'orders':'DESIGN_PRIOR confirmed dailyclose to nextopen once,no queue; conflicting directions cancel cashentry,bear priority whilelong. Gap entry at/below protectiveD cancels. Existing SL gap first,next-open exit second,entry third,intrabarSL afterward. One long per symbol.',
 'protection':'DESIGN_PRIOR fixed latched initiallowerD. GapSL fills observedopen; intrabarSL fillsD with exit timestamp at4hclose upperbound. Fullstopbar excursions diagnostic may includepoststop path. No leverage/account-risk claim.',
 'calendar':'Freshflat P/Q/Qminus; start UTCceil(DEVstart+240*4h); end UTCfloor(DEVend). Signals/entries<end; completed held bars and terminalmark<=end. Warmup only earlierDEV. Parent native4h rules unchanged; oldfullP results preserved.',
 'cost':'Existing shared roundtrip fee/spread/impact/slippage/funding and20bpsfloor; RESEARCH_COST_MODEL; entry<8hsettlement<=exit/mark,stop timestamp conservativeupperbound. Cost2 doubles wholecost. No signedfunding/actualfill claim.',
 'terminal':'No forcedfill. Open grossmark,modeledelapsedfunding,unboundentrysidecost and hypothetical fullcost liquidatingmark separate; same dailyhypotheticalmark convention forclosed/open positions.',
 'comparison':'P->Q,P->Qminus mechanismreplacement; Qminus->Q preparationablation. Origin coincidence only descriptive; absolute positive economics distinct fromlossreduction; cashzero reference consumes0.',
 'uncertainty':'Paired daily marked-equity deltas on fullcalendar includingzeros; moving30day noncircularblocks1000 seed1178. No independence claim forblocks/longholds/reusedDEV. Shared closedweeklybootstrap descriptiveonly.',
 'decision':'Minimumclosed6,positiveclosednet/E,PF>1,payoff>=1,cost2positive. DEVpromising additionally calendarincrement lower95>0 and inherited groupedlossrun/DD nonworse. Exposure/winrate tradeoffs separate,not universalveto. Censoring inconclusive; formal/adoptionalwaysblocked.',
}


def authorize():
    c=old.read(CONTRACT);old.probe.verify_seal(c,'BREAK_CHANNEL_SOURCE')
    if c['authorization']!='EXPLICIT_USER_BREAK_CHANNEL_Q_QMINUS_AFTER_PR1189':raise RuntimeError('AUTHORIZATION_REQUIRED')
    if c['budget']!=BUDGET or c['cell']!=CELL or c['rules']!=RULES or c['outcomes_seen_at_freeze'] is not False:raise RuntimeError('ALLOCATION_OR_RULE_DRIFT')
    for k,v in old.probe.DEV_AUTH.items():
        if c.get(k)!=v:raise RuntimeError('AUTHORITY_DRIFT:'+k)
    for k in ('validation_access','OOS_access','G5B_changed','G6_authorized','operating_changed'):
        if c.get(k) is not False:raise RuntimeError('PROTECTED_BOUNDARY:'+k)
    previous=old.read(prior.OUTPUT+'/receipt.json')
    if previous['budget']['cumulative_after']!=22:raise RuntimeError('PREVIOUS_ALLOCATION_IDENTITY')
    for p,h in {**c['code_files_sha256'],**c['preserved_files_sha256']}.items():
        if old.file_sha(ROOT/p)!=h:raise RuntimeError('FROZEN_IDENTITY:'+p)
    return c


def parent_replay(rows, parent, start, end):
    """Native hold6 with a common flat start and explicit unfinished ownership."""
    rs=[r for r in rows if r['bar_close_ts']<=end]
    signals=[i for i in prior.previous.prep.causal_signals(rs,parent['executable_spec']) if start<=rs[i]['bar_close_ts']<end]
    kw=dict(split_start_ms=rs[0]['bar_open_ts'],split_end_ms=end+BAR,interval_ms=BAR,side='long')
    raw=old.common.evaluate_development_events(rs,signals,hold_bars=parent['executable_spec']['max_hold_bars'],**kw)
    trades=raw['trades'];closed={t['signal_index']:t for t in trades};opened=[];events=[];occupied=-1;tail_open=False
    for i in signals:
        e={'signal_index':i,'signal_ts':rs[i]['bar_close_ts'],'admission':True}
        if i<=occupied or tail_open:e.update(status='EXCLUDED',exclusion_reason='SIGNAL_DURING_OPEN')
        elif i in closed:
            t=closed[i];occupied=t['exit_index'];e.update(status='COMPLETED',exclusion_reason=None)
        elif i+1<len(rs) and rs[i+1]['bar_open_ts']<end:
            t=old.common.evaluate_development_events(rs,[i],hold_bars=len(rs)-1-i,**kw)['trades'][0]
            for a,b in [('exit_index','mark_index'),('exit_ts','mark_ts'),('exit_price','mark_price'),('gross_bps','gross_mark_bps')]:t[b]=t.pop(a)
            t.update(status='CENSORED',terminal_liquidation=False,exit_reason=None,native_hold_bars=6)
            opened.append(t);tail_open=True;e.update(status='CENSORED',exclusion_reason=None,censor_reason='NATIVE_HOLD_UNFINISHED')
        else:e.update(status='EXCLUDED',exclusion_reason='NO_NEXT_OPEN_IN_CALENDAR')
        events.append(e)
    return {'trades':trades,'open_positions':opened,'events':events,'trace':[],
            'audit':{'native_rule_preserved':True,'freshflat_common_start':True,'raw_signals':len(signals),'closed_shared_evaluator_parity':True}}


def charge(raw, symbol, stage, policy, costs, rows):
    t=old.charge(raw,symbol,LANE,stage,policy,costs,rows,BAR)
    t.pop('trade_sha256',None)
    t.update(comparison_stage=stage,status='COMPLETED',origin_key=prior.previous.source_key(t))
    t['trade_sha256']=old.digest(t)
    return t


def charge_open(raw, symbol, stage, policy, costs, rows):
    # Reuse the prior censor-cost adapter; only its explicit lane label changes.
    t=prior.charge_open([raw],symbol,stage,policy,costs,rows)[0]
    t.pop('observation_sha256',None);t['lane_id']=LANE;t['origin_key']=prior.previous.source_key(t)
    t['observation_sha256']=old.digest(t)
    return t


def daily_valuation(trades, opened, rows_by_symbol, costs, start, end):
    """Descriptive portfolio path; no valuation value enters signal generation."""
    prices={s:{r['bar_close_ts']:r['close'] for r in rs if start<r['bar_close_ts']<=end} for s,rs in rows_by_symbol.items()}
    # Intermediate UTC marks are after that timestamp's next-open orders.
    # At the final boundary there is no eligible next-open order or future bar.
    for s,rs in rows_by_symbol.items():
        prices[s].update({r['bar_open_ts']:r['open'] for r in rs if start<r['bar_open_ts']<end})
    out=[];previous_net=previous_gross=0.
    for ts in range(start+DAY,end+1,DAY):
        gross=net=fee=funding=0.;active=0
        for t in trades+opened:
            if t['entry_ts']>ts:continue
            if t.get('exit_ts',math.inf)<=ts:
                gross+=t['gross_bps'];net+=t['net_bps'];fee+=t['cost_bps'];funding+=t['funding_bps']
            else:
                px=prices[t['symbol']].get(ts)
                if px is None:raise RuntimeError('MISSING_DAILY_VALUATION_PRICE')
                g=(px/t['entry_price']-1)*10000
                parts=old.probe.cost_components(t['entry_ts'],ts,costs[t['symbol']])
                cost=max(20.,parts['cost_bps']);gross+=g;net+=g-cost;fee+=cost;funding+=parts['funding_bps'];active+=1
        out.append({'date':datetime.fromtimestamp((ts-DAY)/1000,timezone.utc).date().isoformat(),'mark_ts':ts,
            'value':net-previous_net,'gross_delta_bps':gross-previous_gross,'cumulative_net_mark_bps':net,
            'cumulative_gross_mark_bps':gross,'full_cost_bps_at_valuation':fee,'modeled_funding_bps_at_valuation':funding,
            'active_marked_positions':active,'valuation_phase':'AFTER_OPEN_ORDERS' if ts<end else 'FINAL_CLOSE_NO_FUTURE_OPEN',
            'basis':'HYPOTHETICAL_FULL_ROUNDTRIP_COST_ON_OPEN_MARKS; NOT_REALIZED_ACCOUNT_RETURN'})
        previous_net=net;previous_gross=gross
    return out


def build_report(r):
    fmt=lambda v:'NA' if v is None else f'{v:.4f}'
    lines=[(ROOT/SOURCE).read_text().rstrip(),'','## Measured economics','',
      'Same calendar/universe and equal-notional model; not equal risk or account returns. P native4h hold6 is unchanged; Q/Q-minus are daily ZEL adaptations with common4h protection.','',
      '| Stage | Signals | Closed/open | GrossE | NetE | PF | Win% | AvgWin | AvgLoss | Payoff | Cost2E | Net sum |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in ('P','Q','Q_minus','CASH'):
        m=r['metrics'][s];b=m['base_cost']
        values=[b['gross_expectancy_bps'],b['expectancy_bps_per_trade'],b['PF'],None if b['win_rate'] is None else 100*b['win_rate'],b['average_win_bps'],b['average_loss_bps'],b['realized_payoff'],m['cost2x']['expectancy_bps_per_trade'],b['net_bps']]
        lines.append(f"| {s} | {m['raw_signals']} | {b['completed_T']}/{m['open_observations']['T']} | "+' | '.join(fmt(v) for v in values)+' |')
    lines+=['','| Stage | Fee sum | Funding sum | Total cost | Max simultaneous | Exposure days | Max loss-run | Closed DD | Marked DD | Recovery days / unrecovered |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for s in ('P','Q','Q_minus','CASH'):
        m=r['metrics'][s];d=r['diagnostics'][s];md=r['marked_diagnostics'][s];co=m['closed_cost_totals_bps']
        v=[co['fee_bps'],co['funding_bps'],co['cost_bps'],m['exposure']['max_simultaneous_symbols'],m['total_exposure_symbol_days'],d['lane_simultaneous_close_group_streaks']['max_loss_trade_sum_bps'],d['drawdown_recovery']['closed_group_DD_trade_sum_bps'],md['marked_DD_trade_sum_bps']]
        lines.append('| '+s+' | '+' | '.join(fmt(x) for x in v)+f" | {md['max_completed_recovery_days']}/{md['unrecovered_at_end']} ({md['open_underwater_days']} days open underwater) |")
    lines+=['','## Mechanism and preparation comparisons','',
            '| Comparison | Overall / closed screen | Closed net delta | Common closed/censored | Removed/new closed/new open | Original profit retained range | Large profit range | Daily marked delta95% |',
            '|---|---|---:|---|---|---|---|---|']
    for k,v in r['comparisons'].items():
        a=v['attribution'];d=v['decision'];bound=lambda n:[a[n]['amount_retention_lower'],a[n]['amount_retention_upper']]
        lines.append(f"| {k} | {d['decision']}/{d['closed_screen_decision']} | {a['closed_net_delta_bps']:.4f} | {a['common_completed_T']}/{a['common_censored_T']} | {a['removed_T']}/{a['new_completed_T']}/{a['new_censored_T']} | {bound('winner')} | {bound('large_winner')} | {v['uncertainty']['child_minus_parent_95pct_interval_bps_per_day']} |")
    lines+=['','Preparation evidence: **'+r['preparation_evidence']+'**. Origin overlap is explanatory,never a mechanism-quality threshold. Fixed calendar moving blocks and closed weekly intervals are descriptive reusedDEV estimates,not independent validation.','',
            '## Terminal observations and concentration','', '| Stage | OpenT | Gross mark | Funding accrued | Hypothetical cost | Hypothetical net | Cost2 net | Open days | Top symbol profit share | Top-decile winner share |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in ('P','Q','Q_minus'):
        m=r['metrics'][s];o=m['open_observations'];cc=m['concentration']
        values=[o['T'],o['gross_mark_bps'],o['modeled_funding_accrued_bps'],o['hypothetical_liquidation_cost_bps'],o['hypothetical_liquidation_net_mark_bps'],o['hypothetical_liquidation_cost2x_net_mark_bps'],o['exposure_symbol_days'],cc['top_one_symbol_profit_share'],cc['top_decile_winners_share']]
        lines.append('| '+s+' | '+' | '.join(fmt(v) for v in values)+' |')
    lines+=['','Open marks are never forced completed trades. Entry-side cost is NOT_SEPARATELY_BOUND; full roundtrip marks are an explicit valuation convention. Intrabar stop timestamps are4h upperbounds; stopbar MFE/MAE may include postfill movement.','',
            '## Monthly closed gross / net trade-bps','', '| Exit month | P gross/net | Q gross/net | Q-minus gross/net |','|---|---:|---:|---:|']
    months=sorted({k for s in ('P','Q','Q_minus') for k in r['metrics'][s]['by_exit_month']})
    for month in months:
        values=[]
        for s in ('P','Q','Q_minus'):
            d=r['metrics'][s]['by_exit_month'].get(month,{'gross_bps':0,'net_bps':0});values.append(fmt(d['gross_bps'])+'/'+fmt(d['net_bps']))
        lines.append('| '+month+' | '+' | '.join(values)+' |')
    lines+=['','Existing whole-calendar P remains in the original baseline receipt; common-calendar P starts flat after the frozen warmup and reports any full-parent boundary differences in receipt.json.','',
            'Prior22 preserved,exactlyQ23/Q-minus24 consumed,remaining0. New validation/OOS decoded0; Break validationREJECT and G5B collector/intents/boundary retained. executionNONE/orderBLOCKED/liveBLOCKED. No paid externalAI; Gemini actualvideoNOT_RUN. Formal validation readiness staysblocked without separate authorization,unuseddata and production cost/execution lineage.','']
    return '\n'.join(lines).encode()


def run(data_dir,verify_only=False):
    c=authorize();out=ROOT/OUTPUT
    if (out/'receipt.json').exists() and not verify_only:raise RuntimeError('ALLOCATION_CONSUMED_USE_VERIFY_ONLY')
    p,dev,four,_,access=inputs.load_inputs(data_dir)
    if p['combined_data_sha256']!=c['data_sha256'] or p['cost_binding_sha256']!=c['cost_sha256']:raise RuntimeError('DATA_COST_BINDING')
    start,end=c['evaluation_interval_ms'];source_interval=p['development_interval_ms']
    if [math.ceil((source_interval[0]+240*BAR)/DAY)*DAY,source_interval[1]//DAY*DAY]!=[start,end]:raise RuntimeError('CALENDAR_DRIFT')
    if sorted(four)!=c['symbols']:raise RuntimeError('UNIVERSE_DRIFT')
    p={**p,'batch_id':c['batch_id'],'receipt_sha256':c['receipt_sha256'],'development_interval_ms':[start,end],
       'code_files_sha256':{**p['code_files_sha256'],**c['code_files_sha256']}}
    parent=next(t for t in old.read(old.FREEZE)['children'] if t['lane_id']==LANE)
    if old.digest(parent)!=c['parent_sha256']:raise RuntimeError('PARENT_IDENTITY')
    whole=[t for t in inputs.read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz') if t['lane_id']==LANE]
    old_summary=old.read(old.OUTPUT+'/baseline/receipt.json')['lanes'][LANE]['metrics']['base']
    stages={s:[] for s in ('P','Q','Q_minus')};opened={s:[] for s in stages};events={s:[] for s in stages};traces=[];admission={};daily=[]
    with old.probe.io_boundary([],out):
        for symbol,rows in four.items():
            aggregate=structure.aggregate_daily(rows,split_end_ms=end)
            bundles={s:structure.generate_signals(aggregate['daily'],eval_start_ms=start,eval_end_ms=end,require_preparation=s=='Q') for s in ('Q','Q_minus')}
            down=lambda b:[v for v in b['signals'] if v['direction']=='DOWN']
            if down(bundles['Q'])!=down(bundles['Q_minus']):raise RuntimeError('ABLATION_EXIT_SIGNAL_DRIFT')
            raws={'P':parent_replay(rows,parent,start,end),**{s:structure.replay(rows,b,eval_start_ms=start,eval_end_ms=end) for s,b in bundles.items()}}
            admission[symbol]={'aggregation':aggregate['audit'],'stages':{}}
            for s,raw in raws.items():
                stages[s].extend(charge(t,symbol,s,p,dev['cost_by_symbol'],rows) for t in raw['trades'])
                opened[s].extend(charge_open(t,symbol,s,p,dev['cost_by_symbol'],rows) for t in raw['open_positions'])
                events[s].extend(dict(e,symbol=symbol,lane_id=LANE,comparison_stage=s,scenario=s) for e in raw['events'])
                traces.extend(dict(t,symbol=symbol,comparison_stage=s,trace_layer='REPLAY') for t in raw['trace'])
                admission[symbol]['stages'][s]=raw['audit']
                if s in bundles:
                    traces.extend(dict(t,symbol=symbol,comparison_stage=s,trace_layer='SIGNAL') for t in bundles[s]['trace'])
                    admission[symbol]['stages'][s]['signal_audit']=bundles[s]['audit']
                    admission[symbol]['stages'][s]['signal_audit']['common_calendar_reason_counts']=dict(sorted(Counter(t['reason'] for t in bundles[s]['trace'] if t.get('reason') and start<=t['ts']<end).items()))
            daily.extend(dict(d,symbol=symbol) for d in aggregate['daily'])
        metrics={s:accounting.summarize(stages[s],opened[s],events[s],p,list(four)) for s in stages}
        for s in metrics:
            uncertain=[t for t in stages[s] if t.get('intrabar_stop_timing_unknown')]
            metrics[s]['stop_timing_uncertainty']={'completed_intrabar_stop_T':len(uncertain),
                'timestamp_upper_bound_hours':4,'intrabar_path_order_ambiguous_T':0,
                'why_no_competing_intrabar_order':'NO_TP_OR_TRAILING; ENTRY_AT_OPEN_THEN_FIXED_STOP_ONLY',
                'settlement_boundary_inside_stop_bar_T':sum(t['entry_ts']<t['exit_ts'] and t['exit_ts']%(2*BAR)==0 for t in uncertain),
                'alternative_fill_or_cost_result_computed':False}
        metrics['CASH']=accounting.no_trade_baseline(p,list(four))
        di={s:accounting.diagnostics(stages.get(s,[]),start,end) for s in metrics}
        valuation={s:daily_valuation(stages.get(s,[]),opened.get(s,[]),four,dev['cost_by_symbol'],start,end) for s in metrics}
        for s in metrics:
            target=metrics[s]['closed_plus_hypothetical_terminal_mark_bps']
            if not math.isclose(valuation[s][-1]['cumulative_net_mark_bps'],target,abs_tol=1e-7):raise RuntimeError('TERMINAL_VALUATION_BRIDGE:'+s)
        mdi={s:accounting.daily_mark_diagnostics(v) for s,v in valuation.items()}
        comparisons={}
        for name,a,b in [('P_to_Q','P','Q'),('P_to_Q_minus','P','Q_minus'),('Q_minus_to_Q','Q_minus','Q')]:
            unc=accounting.paired_daily_uncertainty(valuation[a],valuation[b])
            comparisons[name]={'decision':accounting.decide(metrics[a],metrics[b],di[a],di[b],unc),
                'uncertainty':unc,'attribution':accounting.attribution(stages[a],stages[b],opened[b]),
                'purpose':'PREPARATION_ABLATION' if name=='Q_minus_to_Q' else 'MECHANISM_REPLACEMENT',
                'closed_weekly_diagnostic':old.probe.cluster_uncertainty({'base':stages[a],'child':stages[b]},p)}
        qtest=comparisons['Q_minus_to_Q']['uncertainty']
        supported=all(metrics[s]['base_cost']['completed_T']>=6 for s in ('Q','Q_minus')) and qtest['child_minus_parent_95pct_interval_bps_per_day'][0] is not None and qtest['child_minus_parent_95pct_interval_bps_per_day'][0]>0 and not opened['Q'] and not opened['Q_minus']
    artifacts={}
    groups={'trades':[t for ts in stages.values() for t in ts],'open_observations':[t for ts in opened.values() for t in ts],
            'events':[t for ts in events.values() for t in ts],'trace':traces,'daily_bars':daily,
            'daily_valuation':[dict(t,comparison_stage=s) for s,vs in valuation.items() for t in vs]}
    for name,items in groups.items():
        raw=b''.join(old.probe.canonical(t) for t in items)
        path=out/(name+'.jsonl.gz');payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
        if gzip.decompress(payload)!=raw:raise RuntimeError('REPRODUCTION_DRIFT:'+name)
        old.probe.write_immutable(path,payload,verify_only=verify_only)
        artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(items),'file_sha256':old.file_sha(path)}
    pfull={prior.previous.source_key(t):t for t in whole};pc={prior.previous.source_key(t):t for t in stages['P']}
    common=sorted(pfull.keys()&pc.keys())
    for k in common:
        for f in ('entry_ts','entry_price','exit_ts','exit_price','gross_bps','net_bps','cost_bps'):
            if pfull[k][f]!=pc[k][f]:raise RuntimeError('NATIVE_COMMON_PARENT_GEOMETRY:'+f)
    r=old.seal({'batch_id':c['batch_id'],'contract_sha256':c['receipt_sha256'],'metrics':metrics,'diagnostics':di,'marked_diagnostics':mdi,
        'comparisons':comparisons,'preparation_evidence':'SUPPORTED_REUSED_DEV_ONLY' if supported else 'NOT_ESTABLISHED',
        'admission':admission,'artifacts':artifacts,'source_access':access,'budget':{**BUDGET,'new_trials_consumed':2,'remaining_allocated_trials':0},
        'data_reuse_history':c['data_reuse_history'],'evaluation_interval_ms':[start,end],'source_interval_ms':source_interval,
        'whole_parent_preserved':{'source':old.OUTPUT+'/baseline/receipt.json','metrics':old_summary,'common_T':len(common),
            'outside_or_initial_ownership_T':len(pfull.keys()-pc.keys()),'common_calendar_new_due_flat_start_T':len(pc.keys()-pfull.keys()),'matching_economics_parity':'PASS'},
        'data_sha256':c['data_sha256'],'cost_sha256':c['cost_sha256'],'Q_minus_only_removes_bullish_preparation':True,
        'validation_rows_decoded':0,'OOS_rows_decoded':0,'paid_external_AI_calls':0,'Gemini_actual_video':'NOT_RUN',
        'G5B_changed':False,'operating_changed':False,'formal_validation_readiness':'BLOCKED_PENDING_SEPARATE_AUTHORITY_UNUSED_DATA_PRODUCTION_COST_AND_EXECUTION_LINEAGE',**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(r),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',build_report(r),verify_only=verify_only)
    paths=[CONTRACT,SOURCE,OUTPUT+'/receipt.json',OUTPUT+'/RESULTS.md']+[a['path'] for a in artifacts.values()]
    durable=old.seal({'result_receipt_sha256':r['receipt_sha256'],'files_sha256':{p:old.file_sha(ROOT/p) for p in paths},
        'code_files_sha256':c['code_files_sha256'],'preserved_files_sha256':c['preserved_files_sha256'],**old.probe.DEV_AUTH})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    return r


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt':r['receipt_sha256'],'preparation':r['preparation_evidence'],'decisions':{k:v['decision']['decision'] for k,v in r['comparisons'].items()}},indent=2))
