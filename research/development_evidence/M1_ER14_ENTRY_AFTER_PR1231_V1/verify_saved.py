"""Independent ER, first-exit, raw-cost and all-origin saved verification.
No strategy/evaluator imports, network or alternative strategy replay.
"""
import argparse,fnmatch,gzip,hashlib,importlib.util,json,math,re
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
OLD='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1'
PRIOR='research/development_evidence/C54_PRICE_RETRACEMENT_M1_DIAG_AFTER_PR1230_V1'
C54='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1'
C51='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1'
PERIODS=('DEV2025','SEEN2026');KEY='m1_er14_entry_allocation';BAR=14400000

def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def checker(repo):
    s=importlib.util.spec_from_file_location('m1_saved_costs',repo/C51/'verify_saved.py');v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v

def feature(e,source,v):
    x=e['er_context'];i=e['signal_index'];ts=e['signal_ts']
    need(x['signal_index']==i and x['available_at']==ts and x['previous_available_at']==ts-BAR,'ER_CLOCK')
    rows=x['source_closes'];need(len(rows)==16,'ER_WINDOW_LENGTH')
    for j,r in enumerate(rows,i-15):
        need(type(r['index']) is int and r['index']==j and r['ts']==ts-(i-j)*BAR,'ER_SOURCE_CLOCK')
        need(r['close']==source[str(j)]['close'] and r['ts']==source[str(j)]['bar_close_ts'],'ER_SOURCE_PRICE')
    def one(rows,start,end):
        xs=[r['close'] for r in rows];distance=abs(xs[-1]-xs[0]);path=math.fsum(abs(b-a) for a,b in zip(xs,xs[1:]))
        return dict(displacement=distance,path_length=path,value=distance/path if path else 0.,start_index=start,end_index=end)
    now,prev=one(rows[1:],i-14,i),one(rows[:-1],i-15,i-1)
    v.same(x['current'],now,'ER_CURRENT');v.same(x['previous'],prev,'ER_PREVIOUS')
    allowed=now['value']>prev['value']
    need(x['eligible'] is allowed and x['reason']==(None if allowed else 'ER14_NOT_INCREASING'),'ER_DECISION')
    return allowed

def check_raw(raw,result,parent_raw,costs,calendar,witness,v):
    expected={k:[] for k in ('trades','open_observations','events','trace')};n=0;signal_count=0
    for symbol,r in sorted(raw.items()):
        source=witness[symbol];old=parent_raw[symbol];old_events={e['signal_index']:e for e in old['events']}
        need(len(old_events)==len(old['events']) and len(r['events'])==len(old_events),'SIGNAL_COUNT')
        need(r['setup_events']==old['setup_events'],'ORIGINAL_SETUP_LOG')
        ci={t['signal_index']:('C',t) for t in r['trades']};ci.update({t['signal_index']:('O',t) for t in r['open_positions']})
        need(len(ci)==len(r['trades'])+len(r['open_positions']),'DUPLICATE_POSITION')
        traces=defaultdict(list)
        for t in r['trace']:traces[t['signal_index']].append(t)
        last_exit=-1;tail=False;pending=[];seen=set()
        for e in r['events']:
            i=e['signal_index'];ts=e['signal_ts'];seen.add(i);signal_count+=1
            need(i in old_events,'NEW_RAW_SIGNAL')
            for k,value in old_events[i].items():
                if k not in ('admission','status','exclusion_reason'):v.same(e[k],value,'ORIGINAL_SIGNAL_'+k)
            good=feature(e,source,v)
            q=e['episode_start'];floor=min(source[str(j)]['low'] for j in range(q,i+1))
            need(floor==e['floor'],'ORIGINAL_FLOOR_SOURCE')
            if tail or ts<=last_exit:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif e['expiry'] is not None and ts>=e['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not good:reason='ER14_NOT_INCREASING'
            elif ts>=calendar['runoff_end_ms'] or str(i+1) not in source:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
            elif source[str(i+1)]['open']<=floor:reason='GAP_INVALIDATES_FIXED_SETUP'
            else:reason=None
            need(e['exclusion_reason']==reason and e['admission']==(reason is None),'ENTRY_PRECEDENCE')
            if reason:
                need(e['status']=='EXCLUDED' and i not in ci and i not in traces,'VETO_NOT_A_TRADE')
                if reason=='NO_NEXT_OPEN_IN_APPROVED_WINDOW':pending.append(e)
                continue
            need(i in ci,'MISSING_ALLOWED_POSITION');kind,t=ci[i];path=traces[i]
            need(t['entry_index']==i+1 and t['entry_ts']==ts and t['entry_price']==source[str(i+1)]['open'],'REAL_NEXT_OPEN_ENTRY')
            need(t['original_protective_sl'] is None and t['exchange_resident_stop'] is False,'FALSE_RESIDENT_SL')
            held=[x for x in path if x['kind']=='HELD_CLOSE_OBSERVATION'];need(held,'NO_HOLDING_TRACE')
            triggered=None
            for k,z in enumerate(held,1):
                j=i+k;b=source[str(j)];momentum=b['close']-source[str(j-14)]['close']
                need(z['index']==j and z['ts']==b['bar_close_ts'] and z['close']==b['close'] and z['held_bars']==k,'HELD_SOURCE_CLOCK')
                v.same(z['momentum'],momentum,'HELD_MOMENTUM')
                reason='FIXED_FLOOR_CLOSE' if b['close']<=floor else 'MOMENTUM_NONPOSITIVE_CLOSE' if momentum<=0 else 'FIXED_TIME_CLOSE' if k>=20 else None
                need(z['exit_reason']==reason and triggered is None,'MISSING_OR_LATE_FIRST_EXIT')
                if reason:triggered=(j,b['bar_close_ts'],reason)
            if kind=='C':
                need(triggered is not None,'CLOSED_WITHOUT_TRIGGER');j,ts1,reason=triggered
                need(t['exit_index']==j+1 and t['exit_ts']==ts1<calendar['runoff_end_ms'] and t['exit_price']==source[str(j+1)]['open'],'EXIT_NEXT_OPEN')
                need(t['exit_reason']==reason+'_NEXT_OPEN','EXIT_REASON');last_exit=t['exit_ts']
            else:
                j=held[-1]['index'];need(t['mark_ts']==calendar['runoff_end_ms'] and t['mark_price']==source[str(j)]['close'],'OPEN_MARK_SOURCE')
                need(not triggered or triggered[1]>=calendar['runoff_end_ms'],'EXIT_OMITTED_IN_WINDOW');tail=True
            n+=1
        need(seen==set(old_events) and r['pending_entries']==pending,'ALL_ORIGINAL_SIGNALS_ACCOUNTED')
        for src,dst in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:
            expected[dst].extend(dict(row,symbol=symbol) for row in r[src])
    need(result['reference_states']=={},'UNEXPECTED_REFERENCE_CLOCK')
    for key in ('events','trace'):
        need(len(expected[key])==len(result[key]),'CHARGED_TRACE_COUNT')
        for a,b in zip(expected[key],result[key]):v.subset(b,a,'CHARGED_SOURCE')
    for key in ('trades','open_observations'):
        rawidx,charged=v.index(expected[key]),v.index(result[key]);need(set(rawidx)==set(charged),'CHARGED_ORIGINS')
        for idx,src in rawidx.items():
            t=charged[idx];v.subset(t,src,'RAW_GEOMETRY');closed=key=='trades'
            end=t['exit_ts'] if closed else t['mark_ts'];price=t['exit_price'] if closed else t['mark_price']
            gross=(price/t['entry_price']-1)*10000;parts,cost,num=v.costs_for(costs[t['symbol']],t['entry_ts'],end)
            need(calendar['start_ms']<=t['entry_ts']<end<=calendar['runoff_end_ms'],'POSITION_CALENDAR')
            v.same(t['hold_ms'],end-t['entry_ts'],'HOLD_DURATION')
            if closed:
                v.subset(t,parts,'COST_PARTS');v.same(t['cost_bps'],cost,'COST_TOTAL');v.same(t['gross_bps'],gross,'GROSS')
                v.same(t['net_bps'],gross-cost,'NET');v.same(t['cost2x_net_bps'],gross-2*cost,'COST2')
            else:
                need(not t['actual_exit'] and not t['terminal_liquidation'],'FAKE_CLOSED_TAIL')
                v.same(t['hypothetical_cost_components_bps'],parts,'OPEN_COST')
                v.same(t['hypothetical_liquidation_net_mark_bps'],gross-cost,'OPEN_NET');v.same(t['hypothetical_liquidation_cost2x_net_mark_bps'],gross-2*cost,'OPEN_COST2')
            need(t['formal_credit']==0 and not t['independent'] and not t['exchange_order_submitted'],'AUTHORITY_CHANGE')
    return n,signal_count


def check_preserved(raw,result,parent_raw,parent,costs,calendar,proof,v):
    # Actual output contains no new origins. This is an observed-result check,
    # never an entry rule. Future differing outputs must not silently pass it.
    pi,ci=v.complete_index(parent),v.complete_index(result)
    need(set(ci)<=set(pi),'UNVALIDATED_NEW_ORIGIN')
    projection=sorted([[e['symbol'],e['signal_index'],e['er_context']['source_closes']] for e in result['events']],key=lambda x:(x[0],x[1]))
    need(hashlib.sha256(canon(projection)).hexdigest()==proof['source_projection_sha256'],'ORIGINAL_PRICE_PROJECTION')
    expected={k:[] for k in ('trades','open_observations','events','trace')};signals=0
    for symbol,r in sorted(raw.items()):
        original=parent_raw[symbol];parents={e['signal_index']:e for e in original['events']}
        need(r['setup_events']==original['setup_events'],'ORIGINAL_SETUP_CHANGED')
        need([e['signal_index'] for e in r['events']]==[e['signal_index'] for e in original['events']],'ORIGINAL_SIGNAL_POOL')
        admitted={t['signal_index'] for key in ('trades','open_positions') for t in r[key]}
        for e in r['events']:
            i=e['signal_index'];signals+=1
            source={str(z['index']):dict(close=z['close'],bar_close_ts=z['ts']) for z in e['er_context']['source_closes']}
            good=feature(e,source,v)
            for k,value in parents[i].items():
                if k not in ('admission','status','exclusion_reason'):v.same(e[k],value,'ORIGINAL_SIGNAL_'+k)
            need(e['admission']==(i in admitted),'RAW_EVENT_POSITION')
            if i in admitted:need(good,'DISALLOWED_ENTRY')
            if e['exclusion_reason']=='ER14_NOT_INCREASING':need(not good,'FALSE_VETO')
        for key in ('trades','open_positions'):
            prior={t['signal_index']:t for t in original[key]}
            for t in r[key]:need(t==prior.get(t['signal_index']),'ORIGINAL_PATH_CHANGED')
        need(r['trace']==[t for t in original['trace'] if t['signal_index'] in admitted],'ORIGINAL_TRACE_CHANGED')
        for src,dst in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:
            expected[dst].extend(dict(t,symbol=symbol) for t in r[src])
    need(result['reference_states']=={},'UNEXPECTED_REFERENCE')
    for key in ('events','trace'):
        need(len(expected[key])==len(result[key]),'RAW_COUNT')
        for rawrow,t in zip(expected[key],result[key]):v.subset(t,rawrow,'RAW_TRACE')
    for key in ('trades','open_observations'):
        rawidx,charged=v.index(expected[key]),v.index(result[key]);need(set(rawidx)==set(charged),'RAW_CHARGED_ORIGINS')
        for k,r in rawidx.items():
            t=charged[k];v.subset(t,r,'RAW_GEOMETRY');closed=key=='trades';end=t['exit_ts'] if closed else t['mark_ts'];price=t['exit_price'] if closed else t['mark_price']
            need(calendar['start_ms']<=t['entry_ts']<end<=calendar['runoff_end_ms'],'POSITION_CALENDAR')
            gross=(price/t['entry_price']-1)*10000;parts,cost,count=v.costs_for(costs[t['symbol']],t['entry_ts'],end)
            if closed:
                v.subset(t,parts,'COST_COMPONENTS');v.same(t['cost_bps'],cost,'COST_TOTAL');v.same(t['gross_bps'],gross,'GROSS')
                v.same(t['net_bps'],gross-cost,'NET');v.same(t['cost2x_net_bps'],gross-2*cost,'COST2')
            else:
                need(not t['actual_exit'] and not t['terminal_liquidation'],'FALSE_CLOSED_TAIL')
                v.same(t['hypothetical_cost_components_bps'],parts,'OPEN_COMPONENTS');v.same(t['hypothetical_liquidation_net_mark_bps'],gross-cost,'OPEN_NET')
                v.same(t['hypothetical_liquidation_cost2x_net_mark_bps'],gross-2*cost,'OPEN_COST2')
            need(t['formal_credit']==0 and not t['independent'] and not t['exchange_order_submitted'],'AUTHORITY_DRIFT')
    return len(ci),signals


def detail(parent,child,v):
    p,c=v.complete_index(parent),v.complete_index(child);removed=[t for k,t in p.items() if k not in c]
    deltas=[];symbols=defaultdict(float)
    for k in p.keys()|c.keys():
        row=c.get(k,p.get(k))[1];d=v.values(c.get(k))['net_bps']-v.values(p.get(k))['net_bps']
        deltas.append(dict(symbol=k[0],signal_ts=k[2],origin=row['origin_key'],net_delta_bps=d));symbols[k[0]]+=d
    wins=sorted([t for t in p.values() if t[0]=='C' and t[1]['net_bps']>0],key=lambda t:(-t[1]['net_bps'],t[1]['origin_key']))
    def retention(items):return sum(min(t[1]['net_bps'],max(0,v.values(c.get(v.identity(t[1])))['net_bps'])) for t in items)/sum(t[1]['net_bps'] for t in items)
    dn=child['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps'];largest=max(deltas,key=lambda z:(z['net_delta_bps'],z['origin']))
    return dict(net_delta_bps=dn,cost2_delta_bps=child['metrics']['terminal_cost2x_net_bps']-parent['metrics']['terminal_cost2x_net_bps'],
        avoided_closed_loss_bps=-sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']<0),
        foregone_closed_win_bps=sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']>0),
        removed_open_mark_delta_bps=-sum(v.values(t)['net_bps'] for t in removed if t[0]=='O'),
        original_positive_profit_retention=retention(wins),topdecile_profit_retention=retention(wins[:math.ceil(len(wins)/10)]),
        by_symbol=dict(symbols),largest_positive_contribution=largest,delta_without_largest_contribution_bps=dn-largest['net_delta_bps'])

def checks(parent,child,v):
    def up(a,b):return a is not None and b is not None and a>b and not v.near(a,b)
    p,c=parent['metrics'],child['metrics']
    return dict(WR_up=up(c['base_cost']['win_rate'],p['base_cost']['win_rate']),net_up=up(c['terminal_net_bps'],p['terminal_net_bps']),cost2_up=up(c['terminal_cost2x_net_bps'],p['terminal_cost2x_net_bps']),DD_down=up(p['marked_DD_trade_sum_bps'],c['marked_DD_trade_sum_bps']))

def verify(root=HERE,pin=None):
    root=Path(root);repo=root.parents[2];v=checker(repo)
    if pin:need(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    for name,d in read(root/'FINAL_HASHES.json').items():need(sha(root/name)==d,'ARTIFACT_DRIFT:'+name)
    spec=read(root/'SPEC.json');budget=read(root/'BUDGET.json');projection=deepcopy(budget);slot=projection.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'INCOMPLETE_SCOPE')
    need((projection['cumulative_actual'],projection['cumulative_actual_evaluations'])==(62,104),'COUNTS')
    need(projection['candidate_trials'][-1]['ordinal']==62 and [t['actual_experiment_ordinal'] for t in projection['trials'][-2:]]==[103,104],'ORDINALS')
    projection['candidate_trials']=projection['candidate_trials'][:-1];projection['trials']=projection['trials'][:-2]
    projection['cumulative_actual']-=1;projection['cumulative_actual_evaluations']-=2;projection['new_candidate_runs']-=1
    need(projection==read(repo/PRIOR/'BUDGET.json') and projection['chart_allocation']['remaining']==6,'OLD_HISTORY_CHANGED')
    need(sha(repo/PRIOR/'BUDGET.json')==spec['prior_budget_sha256'] and sha(repo/PRIOR/'SPEC.json')==spec['prior_spec_sha256'],'OLD_BYTE_DRIFT')
    for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'SOURCE_DRIFT:'+name)
    costs=read(repo/C51/'COSTS.json');summary=read(root/'SUMMARY.json');details=read(root/'DETAILS.json');count=signals=0;statuses=[]
    proof=read(root/'SOURCE_PROOF.json')
    app=read(root/'APPLICABILITY.json')
    for per in PERIODS:
        d=root/per;r=gz(d/'RESULT.json.gz');raw=gz(d/'RAW.json.gz');parent=gz(repo/OLD/'M1'/per/'RESULT.json.gz');original=gz(repo/OLD/'M1'/per/'RAW.json.gz')
        for name,digest in spec['parent_results_sha256'][per].items():need(sha(repo/OLD/'M1'/per/name)==digest,'M1_PARENT_DRIFT')
        need(sha(repo/C54/'B'/per/'RESULT.json.gz')==spec['saved_c54_sha256'][per],'C54_DRIFT')
        at,start,receipt=[read(d/n) for n in ('ATTEMPT.json','EXECUTION_STARTED.json','RECEIPT.json')]
        need(receipt['status']=='COMPLETED' and receipt['result_sha256']==sha(d/'RESULT.json.gz') and receipt['raw_sha256']==sha(d/'RAW.json.gz'),'RESULT_RECEIPT')
        need(at['spec_sha256']==receipt['spec_sha256']==sha(root/'SPEC.json'),'SPEC_BINDING')
        need(start['claim_commit']==start['remote_readback_sha']==receipt['claim_commit'] and at['owner_run']==start['owner_run'],'REMOTE_CLAIM')
        need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PREFREEZE_ORDER')
        need(proof[per]['original_input_sha256']==spec['input_packet_sha256'][per] and proof[per]['raw_sha256']==sha(d/'RAW.json.gz') and proof[per]['result_sha256']==sha(d/'RESULT.json.gz'),'SOURCE_PROOF_BINDING')
        n,ns=check_preserved(raw,r,original,parent,costs,spec['periods'][per],proof[per],v);count+=n;signals+=ns
        contexts={(x['symbol'],x['signal_index']):x['context'] for x in app['periods'][per]['records']}
        need(len(contexts)==ns and all(e['er_context']==contexts[(e['symbol'],e['signal_index'])] for e in r['events']),'PREFLIGHT_EXECUTION_CONTEXT')
        v.check_metrics(r);v.compare_parent(parent,r,read(d/'ACCOUNTING_M1.json'))
        pi,ci=v.complete_index(parent),v.complete_index(r)
        for k in pi.keys()&ci.keys():
            need(pi[k][0]==ci[k][0],'COMMON_STATE_CHANGED');v.same(v.values(pi[k]),v.values(ci[k]),'COMMON_ECONOMICS')
            for field in ('entry_index','entry_ts','entry_price','exit_index','exit_ts','exit_price','exit_reason','mark_ts','mark_price','hold_ms'):
                need(pi[k][1].get(field)==ci[k][1].get(field),'COMMON_PATH_CHANGED')
        v.same(details[per],detail(parent,r,v),'DETAILS');flags=checks(parent,r,v);statuses.append(flags)
        need(summary['periods'][per]['checks']==flags,'SUMMARY_FLAGS')
        for label,z in [('parent',parent),('child',r)]:
            snap=summary['periods'][per][label];m=z['metrics'];b=m['base_cost']
            v.subset(snap,{k:b[k] for k in ('win_rate','average_win_bps','average_loss_bps','realized_payoff','PF')},'SUMMARY_METRICS')
            v.subset(snap,{k:m[k] for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')},'SUMMARY_TOTALS')
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            row='|'+ '|'.join([per,'M1' if label=='parent' else 'ER14',f"{len(z['trades'])}/{len(z['open_observations'])}",fmt(None if b['win_rate'] is None else b['win_rate']*100)]+[fmt(b[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
            need(row in (root/'REPORT.md').read_text(),'REPORT_TABLE')
    status='DEVELOPMENT_GOAL_MET' if all(all(x.values()) for x in statuses) else 'PARTIAL_IMPROVEMENT' if all(x['net_up'] and x['cost2_up'] for x in statuses) else 'REJECT_KEEP_M1_AND_C54'
    need(summary['status']==status,'GOAL_ADJUDICATION')
    wf=(repo/'.github/workflows/m1-er14-entry-v1.yml').read_text();patterns=re.findall(r"^\s+- '([^']+)'\s*$",wf,re.M)
    for name in set(spec['source_files_sha256'])|{C51+'/COSTS.json',C51+'/verify_saved.py',PRIOR+'/BUDGET.json'}:
        need(any(fnmatch.fnmatchcase(name,p) for p in patterns),'UNTRIGGERED_DEPENDENCY')
    return dict(status=status,raw_positions=count,original_signals=signals,candidates=62,evaluations=104,new_economic_replay=0)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--manifest-sha256',required=True);x=q.parse_args();print(json.dumps(verify(pin=x.manifest_sha256),indent=2))
