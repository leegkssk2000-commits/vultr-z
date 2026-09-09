"""Independent saved arithmetic/causality audit. No strategy/evaluator imports.

Optional --inputs verifies against original packets. Normal CI rechecks pinned
source-bound outputs, every daily witness and unchanged C63 retained path.
"""
import argparse,gzip,hashlib,json,math
from pathlib import Path
from copy import deepcopy
from collections import defaultdict,Counter
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
PARENT='research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
PERIODS=('DEV2025','SEEN2026');BAR=14400000;DAY=86400000;STEP=28800000
KEY='c63_daily_ema21_tip_allocation'
EVIDENCE_SHA='434501a8bd17660130e7367c7d1b2e0772fe278d51be4beb44d4830380776fe7'
VETO='PRICE_NOT_ABOVE_COMPLETED_DAILY_EMA21';MISSING='COMPLETED_DAILY_EMA21_HISTORY_UNAVAILABLE'
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(o):return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def need(ok,reason):
    if not ok:raise ValueError(reason)
def same(a,b,reason):
    if type(a) in (float,int) and type(b) in (float,int):need(math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-7),reason)
    else:need(a==b,reason)
def origin(t):return t['symbol'],t['signal_index'],t['signal_ts']
def index(r):return {origin(t):(k,t) for k,key in [('C','trades'),('O','open_observations')] for t in r[key]}
def val(x,field='net'):
    if x is None:return 0.
    k,t=x
    return t[({'net':'net_bps','cost2':'cost2x_net_bps','gross':'gross_bps'} if k=='C' else {'net':'hypothetical_liquidation_net_mark_bps','cost2':'hypothetical_liquidation_cost2x_net_mark_bps','gross':'gross_mark_bps'})[field]]
def cost(binding,entry,end):
    n=max(0,end//STEP-entry//STEP);parts={k:binding[k] for k in ('fee_bps','spread_bps','impact_bps')};parts.update(slippage_bps=0.,funding_bps=n*binding['funding_p95_per_settlement_bps']);raw=sum(parts.values());parts['frozen_floor_reserve_bps']=max(0.,20.-raw)
    return max(20.,raw),parts,n

def daily_context(e,rows=None):
    x=e['er_context']['daily_context'];ts=e['signal_ts'];ds=x['daily_closes'];i=e['signal_index']
    need(x['available_at']==ts and x['signal_index']==i and x['period']==21,'DAILY_SIGNAL_CLOCK')
    for j,d in enumerate(ds):
        need(d['open_ts']%DAY==0 and d['available_at']==d['open_ts']+DAY<=ts,'DAILY_AVAILABLE_CLOCK')
        need(math.isfinite(d['close']) and d['close']>0,'DAILY_PRICE')
        if j:need(d['open_ts']==ds[j-1]['available_at'],'DAILY_GAP')
    need(x['completed_days']==len(ds) and x['last_daily_available_at']==(ds[-1]['available_at'] if ds else None),'DAILY_COUNT')
    if ds:need(ds[-1]['available_at']<=ts<ds[-1]['available_at']+DAY,'STALE_DAILY_REFERENCE')
    value=None
    if len(ds)>=21:
        value=math.fsum(d['close'] for d in ds[:21])/21
        for d in ds[21:]:value=(2/22)*d['close']+(1-2/22)*value
    same(x['value'],value,'EMA_ARITHMETIC')
    eligible=value is not None and x['signal_close']>value
    need(x['eligible']==eligible and x['reason']==(None if eligible else MISSING if value is None else VETO),'DAILY_STRICT_PREDICATE')
    if rows is not None:
        prefix=rows[:i+1];first=next((j for j,r in enumerate(prefix) if r['bar_open_ts']%DAY==0),len(prefix));expected=[]
        for start in range(first,len(prefix)-5,6):
            chunk=prefix[start:start+6]
            need(all(r['bar_open_ts']==chunk[0]['bar_open_ts']+j*BAR and r['bar_close_ts']==r['bar_open_ts']+BAR for j,r in enumerate(chunk)),'SOURCE_CONTIGUITY')
            expected.append(dict(open_ts=chunk[0]['bar_open_ts'],available_at=chunk[-1]['bar_close_ts'],close=chunk[-1]['close']))
        need(expected==ds and first==x['leading_partial_bars'],'SOURCE_DAILY_WITNESSES')
        need(x['signal_close']==rows[i]['close'] and ts==rows[i]['bar_close_ts'],'SOURCE_SIGNAL_PRICE')
    return eligible

def metrics(r,packet=None):
    idx=index(r);need(len(idx)==len(r['trades'])+len(r['open_observations']),'DUPLICATE_ORIGINS');m=r['metrics']
    for label,field in [('base_cost','net'),('cost2x','cost2')]:
        t=[val((k,z),field) for k,z in idx.values() if k=='C'];wins=[v for v in t if v>0];loss=[v for v in t if v<0];s=m[label]
        for key,value in [('net_bps',sum(t)),('win_rate',len(wins)/len(t) if t else None),('PF',sum(wins)/-sum(loss) if loss else None),('average_win_bps',sum(wins)/len(wins) if wins else None),('average_loss_bps',sum(loss)/len(loss) if loss else None),('expectancy_bps_per_trade',sum(t)/len(t) if t else None)]:same(s[key],value,'METRIC_'+key)
        need(s['completed_T']==len(t) and s['wins']==len(wins) and s['losses']==len(loss),'METRIC_COUNTS')
        same(s['realized_payoff'],(sum(wins)/len(wins))/(-sum(loss)/len(loss)) if wins and loss else None,'PAYOFF')
    same(m['terminal_net_bps'],sum(val(x) for x in idx.values()),'TERMINAL_NET');same(m['terminal_cost2x_net_bps'],sum(val(x,'cost2') for x in idx.values()),'TERMINAL_COST2')
    same(m['open_hypothetical_net_mark_bps'],sum(val(x) for x in idx.values() if x[0]=='O'),'OPEN_MARK')
    peak=previous=maxdd=0.
    for d in m['daily']:
        current=d['cumulative_net_mark_bps'];same(d['value'],current-previous,'DAILY_INCREMENT');previous=current;peak=max(peak,current);maxdd=max(maxdd,peak-current)
    same(maxdd,m['marked_DD_trade_sum_bps'],'DAILY_DD');same(previous,m['terminal_net_bps'],'DAILY_TERMINAL')
    same(m['exposure']['position_days'],sum(t['hold_ms']/DAY for k,t in idx.values()),'POSITION_EXPOSURE')
    if packet is not None:
        maps={s:{r['bar_close_ts']:r['close'] for r in rows} for s,rows in packet['rows_by'].items()}
        for s,rows in packet['rows_by'].items():maps[s].update({r['bar_open_ts']:r['open'] for r in rows})
        for k,t in idx.values():
            end=t['exit_ts'] if k=='C' else t['mark_ts'];px=t['exit_price'] if k=='C' else t['mark_price'];fee,parts,n=cost(packet['costs'][t['symbol']],t['entry_ts'],end);gross=(px/t['entry_price']-1)*10000
            same(val((k,t),'gross'),gross,'SOURCE_GROSS');same(val((k,t)),gross-fee,'SOURCE_NET');same(val((k,t),'cost2'),gross-2*fee,'SOURCE_COST2')
            stored={p:t[p] for p in parts} if k=='C' else t['hypothetical_cost_components_bps']
            for p,v in parts.items():same(stored[p],v,'COST_COMPONENT_'+p)
        for d in m['daily']:
            stamp=d['mark_ts'];net=net2=gross=0.;active=0
            for k,t in idx.values():
                if t['entry_ts']>stamp:continue
                if k=='C' and t['exit_ts']<=stamp:g,n,n2=val((k,t),'gross'),val((k,t)),val((k,t),'cost2')
                else:
                    active+=1;g=(maps[t['symbol']][stamp]/t['entry_price']-1)*10000;fee=cost(packet['costs'][t['symbol']],t['entry_ts'],stamp)[0];n,n2=g-fee,g-2*fee
                gross+=g;net+=n;net2+=n2
            for field,value in [('cumulative_gross_mark_bps',gross),('cumulative_net_mark_bps',net),('cumulative_cost2x_mark_bps',net2)]:same(d[field],value,'SOURCE_DAILY_'+field)
            need(active==d['active_marked_positions'],'SOURCE_DAILY_ACTIVE')

def details(parent,child):
    pi,ci=index(parent),index(child);events={origin(e):e for e in child['events']};rows=[];terms=defaultdict(float);by_symbol=defaultdict(float);reasons=defaultdict(list)
    for key in sorted(pi.keys()|ci.keys()):
        old,cur=pi.get(key),ci.get(key);group='common_'+old[0]+cur[0] if old and cur else 'removed_'+old[0] if old else 'new_'+cur[0];delta=val(cur)-val(old);terms[group]+=delta;by_symbol[key[0]]+=delta
        reason=events[key]['exclusion_reason'] if cur is None else None
        row=dict(symbol=key[0],signal_index=key[1],signal_ts=key[2],group=group,parent_net=val(old),candidate_net=val(cur),delta=delta,reason=reason)
        if old is None or cur is None or delta!=0:rows.append(row)
        if cur is None:reasons[reason].append(row)
    out={reason:dict(n=len(v),wins=sum(x['parent_net']>0 for x in v),losses=sum(x['parent_net']<0 for x in v),avoided_loss=sum(-min(0,x['parent_net']) for x in v),foregone_profit=sum(max(0,x['parent_net']) for x in v),net_delta=sum(x['delta'] for x in v)) for reason,v in reasons.items()}
    winners=sorted([k for k,x in pi.items() if x[0]=='C' and val(x)>0],key=lambda k:(-val(pi[k]),k))
    ret={}
    for name,keys in [('all_winners',winners),('top_decile',winners[:math.ceil(len(winners)*.1)])]:
        den=sum(val(pi[k]) for k in keys);kept=sum(min(val(pi[k]),max(0,val(ci.get(k)))) for k in keys)
        ret[name]=dict(n=len(keys),origins=[pi[k][1]['origin_key'] for k in keys],parent_profit=den,kept_profit=kept,fraction=kept/den if den else None)
    total=sum(terms.values());same(total,child['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps'],'ATTRIBUTION_TOTAL')
    largest=max(rows,key=lambda x:x['delta']) if rows else None
    return dict(rows=rows,terms=dict(terms),by_symbol=dict(by_symbol),removed_by_reason=out,retention=ret,net_delta=total,largest_positive_contribution=largest,delta_without_largest=total-largest['delta'] if largest else total)

def cell(per,inputs=None,root=HERE):
    root=Path(root);repo=root.parents[2];spec=read(root/'SPEC.json');cal=spec['periods'][per];raw=gz(root/per/'RAW.json.gz');result=gz(root/per/'RESULT.json.gz');par=gz(repo/PARENT/per/'RESULT.json.gz');pr=gz(repo/PARENT/per/'RAW.json.gz')
    packet=None
    if inputs:
        path=Path(inputs)/(per+'.json.gz');need(sha(path)==spec['input_packet_sha256'][per],'ORIGINAL_INPUT_HASH');packet=gz(path)
    pi,ci=index(par),index(result);need(ci.keys()<=pi.keys(),'NEW_ORIGIN_REQUIRES_EXTENDED_CHECK_NOT_SILENT_PASS')
    signals=held=0;expected=[]
    for sym,x in sorted(raw.items()):
        old={e['signal_index']:e for e in pr[sym]['events']};need([e['signal_index'] for e in x['events']]==list(old),'ORIGINAL_SIGNAL_POOL');need(x['setup_events']==pr[sym]['setup_events'],'ORIGINAL_SETUP_POOL')
        rows=packet['rows_by'][sym] if packet else None;last=-1;tail=False;pos={t['signal_index']:t for k in ('trades','open_positions') for t in x[k]};pending=[]
        for e in x['events']:
            i=e['signal_index'];signals+=1;expected.append(dict(e,symbol=sym,scenario=spec['candidate'],comparison_stage=spec['candidate'],lane_id='source_squeeze_momentum_long'));before=old[i];obs=e['er_context'];base=dict(obs)
            for k in ('c63_eligible','c63_reason','daily_context'):base.pop(k)
            base['eligible']=obs['c63_eligible'];base['reason']=obs['c63_reason'];need(base==before['er_context'],'ORIGINAL_C63_CONTEXT')
            for k,v in before.items():
                if k not in ('admission','status','exclusion_reason','er_context'):need(e[k]==v,'ORIGINAL_SIGNAL_GEOMETRY')
            allowed=daily_context(e,rows);need(obs['eligible']==(obs['c63_eligible'] and allowed),'COMBINED_ELIGIBILITY')
            need(obs['reason']==(obs['c63_reason'] if not obs['c63_eligible'] else obs['daily_context']['reason']),'COMBINED_REASON')
            reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION' if tail or e['signal_ts']<=last else 'SETUP_EXPIRED_BEFORE_ENTRY' if e['expiry'] is not None and e['signal_ts']>=e['expiry'] else obs['reason'] if not obs['eligible'] else 'NO_NEXT_OPEN_IN_APPROVED_WINDOW' if e['signal_ts']>=cal['runoff_end_ms'] else 'GAP_INVALIDATES_FIXED_SETUP' if rows is not None and rows[i+1]['open']<=e['floor'] else before['exclusion_reason'] if rows is None and before['exclusion_reason']=='GAP_INVALIDATES_FIXED_SETUP' else None
            need(e['exclusion_reason']==reason and e['admission']==(reason is None),'ACTUAL_OCCUPANCY_PRECEDENCE');need((i in pos)==e['admission'],'ADMISSION_POSITION')
            if reason=='NO_NEXT_OPEN_IN_APPROVED_WINDOW':pending.append(e)
            if i in pos:
                t=pos[i];kind='trades' if 'exit_ts' in t else 'open_positions';source=next(z for z in pr[sym][kind] if z['signal_index']==i);need(t==source,'RETAINED_ORIGINAL_PATH')
                tr=[z for z in x['trace'] if z['signal_index']==i];pt=[z for z in pr[sym]['trace'] if z['signal_index']==i];need(tr==pt,'RETAINED_ORIGINAL_TRACE')
                if rows:
                    need(t['entry_price']==rows[t['entry_index']]['open'] and t['entry_ts']==rows[t['entry_index']]['bar_open_ts'],'SOURCE_ENTRY')
                    need((t['exit_price']==rows[t['exit_index']]['open']) if kind=='trades' else (t['mark_price']==rows[t['mark_index']]['close']),'SOURCE_EXIT_MARK')
                for h in tr:
                    if h['kind']!='HELD_CLOSE_OBSERVATION':continue
                    held+=1
                    if rows:need(h['close']==rows[h['index']]['close'] and h['ts']==rows[h['index']]['bar_close_ts'],'SOURCE_HELD')
                if kind=='trades':last=t['exit_ts']
                else:tail=True
        need(x['pending_entries']==pending,'PENDING_ENTRY')
    need(result['events']==expected,'CHARGED_EVENTS')
    for k in ci:
        need(ci[k][0]==pi[k][0],'RETAINED_STATE')
        for field in ('net','cost2','gross'):same(val(ci[k],field),val(pi[k],field),'RETAINED_COST_GEOMETRY')
    metrics(result,packet);detail=details(par,result);ac=read(root/per/'ACCOUNTING_C63.json')
    same(ac['four_way_terminal_delta']['removed'],detail['terms'].get('removed_C',0)+detail['terms'].get('removed_O',0),'ACCOUNTING_REMOVED')
    need(ac['counts']['new_C']==ac['counts']['new_O']==ac['counts']['CO']==ac['counts']['OC']==0,'ACCOUNTING_TRANSITIONS')
    for name,own in [('winner','all_winners'),('large_winner','top_decile')]:same(ac[name]['amount_retention_lower'],detail['retention'][own]['fraction'],'ACCOUNTING_RETENTION')
    return dict(signals=signals,positions=len(ci),held_closes=held,daily_marks=len(result['metrics']['daily']),details=detail)

def verify(root=HERE,inputs=None,derived_sha=None,full_repository=False):
    root=Path(root);repo=root.parents[2];need(sha(root/'EVIDENCE_HASHES.json')==EVIDENCE_SHA,'MANIFEST_PIN')
    for name,d in read(root/'EVIDENCE_HASHES.json').items():need(sha(root/name)==d,'FROZEN_OUTPUT:'+name)
    spec=read(root/'SPEC.json');b=deepcopy(read(root/'BUDGET.json'));slot=b.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'BUDGET_CLOSED')
    need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(69,122),'COUNTS');need([t['actual_experiment_ordinal'] for t in b['trials'][-2:]]==[121,122],'ORDINALS')
    b['trials']=b['trials'][:-2];b['candidate_trials']=b['candidate_trials'][:-1];b['cumulative_actual']-=1;b['cumulative_actual_evaluations']-=2;b['new_candidate_runs']-=1
    need(b==read(root/'HISTORY_PRIOR.json') and b['chart_allocation']['remaining']==6,'PRIOR_HISTORY')
    if full_repository:
        for name,d in spec['source_files_sha256'].items():need(sha(repo/name)==d,'FROZEN_SOURCE:'+name)
    summary=read(root/'SUMMARY.json');output={};flags=[]
    for per in PERIODS:
        for name,d in spec['parent_results_sha256'][per].items():need(sha(repo/PARENT/per/name)==d,'C63_PARENT_PIN')
        at,start,receipt=[read(root/per/n) for n in ('ATTEMPT.json','EXECUTION_STARTED.json','RECEIPT.json')]
        need(at['spec_sha256']==receipt['spec_sha256']==sha(root/'SPEC.json'),'SPEC_BINDING');need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'PRE_RESULT_FREEZE')
        need(start['claim_commit']==start['remote_readback_sha']==receipt['claim_commit'] and start['owner_run']==at['owner_run'],'REMOTE_CLAIM')
        need(receipt['result_sha256']==sha(root/per/'RESULT.json.gz') and receipt['raw_sha256']==sha(root/per/'RAW.json.gz'),'RESULT_BINDING')
        output[per]=cell(per,inputs,root)
        parent=gz(repo/PARENT/per/'RESULT.json.gz');child=gz(root/per/'RESULT.json.gz');pm,cm=parent['metrics'],child['metrics']
        checks={k:(cv>pv and not math.isclose(cv,pv,rel_tol=1e-12,abs_tol=1e-7)) for k,cv,pv in [('WR_up',cm['base_cost']['win_rate'],pm['base_cost']['win_rate']),('net_up',cm['terminal_net_bps'],pm['terminal_net_bps']),('cost2_up',cm['terminal_cost2x_net_bps'],pm['terminal_cost2x_net_bps']),('DD_down',pm['marked_DD_trade_sum_bps'],cm['marked_DD_trade_sum_bps'])]}
        need(checks==summary['periods'][per]['checks'],'SUMMARY_CHECKS');flags.append(checks)
        for label,result in [('C63',parent),('DAILY21',child)]:
            m=result['metrics'];s=summary['periods'][per]['snapshots'][label];base=m['base_cost']
            need(s['closed']==len(result['trades']) and s['open']==len(result['open_observations']),'SUMMARY_COUNTS')
            for key in ('win_rate','average_win_bps','average_loss_bps','PF','realized_payoff'):same(s[key],base[key],'SUMMARY_BASE')
            for key in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):same(s[key],m[key],'SUMMARY_TOTALS')
            fmt=lambda v:'NA' if v is None else f'{v:.2f}'
            line='|'+ '|'.join([per,label,f"{s['closed']}/{s['open']}",fmt(None if s['win_rate'] is None else s['win_rate']*100)]+[fmt(s[k]) for k in ('average_win_bps','average_loss_bps','PF','realized_payoff','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
            need(line in (root/'REPORT.md').read_text(),'REPORT_TABLE')
    goal=all(all(x.values()) for x in flags);gain=all(x['net_up'] and x['cost2_up'] for x in flags)
    need(summary['status']==('DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'),'VERDICT')
    if derived_sha:
        need(sha(root/'SOURCE_PROOF.json')==derived_sha,'DERIVED_PIN');proof=read(root/'SOURCE_PROOF.json');need(proof['periods_canonical_sha256']==hashlib.sha256(canon(output)).hexdigest(),'DERIVED_ARITHMETIC');need(proof['input_packet_sha256']==spec['input_packet_sha256'],'PROOF_SOURCE')
    return dict(status=summary['status'],periods=output,new_economic_replays=0,original_inputs_checked=inputs is not None,all_frozen_source_files_checked=full_repository)
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--inputs');q.add_argument('--derived-sha256');q.add_argument('--full-repository',action='store_true');x=q.parse_args();r=verify(inputs=x.inputs,derived_sha=x.derived_sha256,full_repository=x.full_repository)
    print(json.dumps({k:v if k!='periods' else {p:{n:c[n] for n in ('signals','positions','held_closes','daily_marks')} for p,c in v.items()} for k,v in r.items()},indent=2))
