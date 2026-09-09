"""Independent source/receipt arithmetic; no candidate or evaluator imports/calls."""
import argparse,gzip,hashlib,json,math
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
INPUTS='research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1/INPUTS'
PIN='24951e4613ed505632171f00e5627f03c1bc572035d8964dcefb947e59bbb658'
BAR=14400000;DAY=86400000
COMP=('fee_bps','spread_bps','impact_bps','slippage_bps','funding_bps','frozen_floor_reserve_bps')
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def need(x,name):
    if not x:raise ValueError(name)
def same(a,b,name):
    if isinstance(a,dict) and isinstance(b,dict):
        need(a.keys()==b.keys(),name+':KEYS')
        for k in a:same(a[k],b[k],name+'.'+k)
    elif isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        need(len(a)==len(b),name+':LENGTH')
        for i,(x,y) in enumerate(zip(a,b)):same(x,y,name+str(i))
    elif type(a) in (int,float) and type(b) in (int,float):need(math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-7),name)
    else:need(a==b,name)
def cost(binding,entry,end):
    n=max(0,end//28800000-entry//28800000)
    parts={k:binding[k] for k in ('fee_bps','spread_bps','impact_bps')};parts.update(slippage_bps=0.,funding_bps=n*binding['funding_p95_per_settlement_bps']);parts['frozen_floor_reserve_bps']=max(0.,20.-sum(parts.values()))
    return parts,sum(parts.values())
def val(state,t):
    return t['net_bps'] if state=='C' else t['hypothetical_liquidation_net_mark_bps']
def index(r):
    result={}
    for state,key in [('C','trades'),('O','open_observations')]:
        for t in r[key]:
            k=t['symbol']+'|'+t['setup_id'];need(k not in result,'DUPLICATE_EPISODE');result[k]=(state,t)
    return result

def averages(xs,n,alpha):
    out=[None]*len(xs)
    if len(xs)>=n:
        out[n-1]=math.fsum(xs[:n])/n
        for i in range(n,len(xs)):out[i]=alpha*xs[i]+(1-alpha)*out[i-1]
    return out

def setup_audit(rows,start,end):
    cs=[x['close'] for x in rows];ema=averages(cs,21,2/22);center=averages(cs,20,2/21)
    tr=[max(rows[i]['high']-rows[i]['low'],abs(rows[i]['high']-cs[i-1]),abs(rows[i]['low']-cs[i-1])) for i in range(1,len(rows))];atr=[None]+averages(tr,20,1/20)
    flags=[False]*len(rows)
    for i in range(20,len(rows)):
        m=math.fsum(cs[i-19:i+1])/20;sd=math.sqrt(math.fsum((x-m)**2 for x in cs[i-19:i+1])/20)
        flags[i]=(m-2*sd>center[i]-1.5*atr[i] and m+2*sd<center[i]+1.5*atr[i])
    groups=[];q=None
    for i,on in enumerate(flags+[False]):
        if on and q is None:q=i
        elif not on and q is not None:groups.append((q,i));q=None
    prepared=[];signals=[];wait=[];cancel=[];observed=[]
    for q,stop in groups:
        for i in range(q,stop):
            ts=rows[i]['bar_close_ts']
            if start<=ts<=end:observed.append(i)
        eligible=[i for i in range(q+2,stop) if start<=rows[i]['bar_close_ts']<=end and cs[i]>ema[i] and cs[i]-cs[i-14]>0 and min(z['low'] for z in rows[q:i+1])<ema[i]]
        if not eligible:continue
        j=eligible[0];level=ema[j];floor=min(z['low'] for z in rows[q:j+1]);context=dict(prep_index=j,available_at=rows[j]['bar_close_ts'],level=level,floor=floor,episode_start=q,squeeze_count=j-q+1,ema_period=21);prepared.append(context)
        for i in range(j+1,stop):
            if rows[i]['bar_close_ts']>end:break
            kind='WAIT_PULLBACK'
            if cs[i]<=floor:kind='CANCEL_FLOOR_CLOSE'
            elif rows[i]['low']<=level and cs[i]>level and cs[i]-cs[i-14]>0:kind='PULLBACK_CONFIRMED'
            wait.append((i,kind))
            if kind=='CANCEL_FLOOR_CLOSE':cancel.append(i);break
            if kind=='PULLBACK_CONFIRMED':signals.append((i,context));break
    return dict(signals=signals,prepared=prepared,wait=wait,observed=observed,flags=flags,ema=ema)

def check_core(raw,result,packet,cal):
    positions=0;held_count=0;setup_count=0;expected_events=[];raw_positions={}
    for symbol,x in sorted(raw.items()):
        rows=packet['rows_by'][symbol];seen=setup_audit(rows,cal['start_ms'],cal['runoff_end_ms']);setup_count+=len(seen['prepared'])
        need([e['signal_index'] for e in x['events']]==[i for i,c in seen['signals']],'COMPLETE_SIGNAL_POOL')
        actualprep=[{k:e[k] for k in c} for e,c in zip([z for z in x['setup_events'] if z['kind']=='PREPARED'],seen['prepared'])]
        same(actualprep,seen['prepared'],'PREPARED_SOURCE')
        need(sum(z['kind']=='PREPARED' for z in x['setup_events'])==len(seen['prepared']),'PREPARED_COUNT')
        need([(z['index'],z['kind']) for z in x['setup_events'] if z['kind'] in ('WAIT_PULLBACK','PULLBACK_CONFIRMED','CANCEL_FLOOR_CLOSE')]==seen['wait'],'WAIT_FIRST_ACTION')
        need([z['index'] for z in x['setup_events'] if z['kind']=='SQUEEZE_OBSERVATION']==seen['observed'],'ALL_SQUEEZE_OBSERVATIONS')
        pos={t['signal_index']:t for k in ('trades','open_positions') for t in x[k]};need(len(pos)==len(x['trades'])+len(x['open_positions']),'DUPLICATE_POSITION')
        last=-1;tail=False;pending=[]
        for e,(i,ctx) in zip(x['events'],seen['signals']):
            same(e['entry_context'],ctx,'ENTRY_CONTEXT');same(e['floor'],ctx['floor'],'PREPARATION_FLOOR')
            need(e['signal_ts']==rows[i]['bar_close_ts'] and e['setup_available_at']==ctx['available_at']<e['signal_ts'],'PREPARATION_BEFORE_SIGNAL')
            need(e['setup_id']=='M1:'+str(rows[ctx['episode_start']]['bar_open_ts']),'EPISODE_ID')
            reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION' if tail or e['signal_ts']<=last else 'NO_NEXT_OPEN_IN_APPROVED_WINDOW' if i+1>=len(rows) or rows[i+1]['bar_open_ts']>=cal['runoff_end_ms'] else 'GAP_INVALIDATES_FIXED_SETUP' if rows[i+1]['open']<=ctx['floor'] else None
            need(e['exclusion_reason']==reason and e['admission']==(reason is None) and (i in pos)==e['admission'],'ADMISSION_OCCUPANCY')
            if reason=='NO_NEXT_OPEN_IN_APPROVED_WINDOW':pending.append(e)
            expected_events.append(dict(e,symbol=symbol,lane_id='source_squeeze_momentum_long',comparison_stage='SQUEEZE_PRE_RELEASE_FROZEN_EMA21_PULLBACK_V1',scenario='SQUEEZE_PRE_RELEASE_FROZEN_EMA21_PULLBACK_V1'))
            if i not in pos:continue
            t=pos[i];ei=i+1;entry=rows[ei]['open'];need(t['entry_index']==ei and t['entry_ts']==rows[ei]['bar_open_ts']==e['signal_ts'] and t['entry_price']==entry,'NEXT_ACTUAL_OPEN')
            need(t['fixed_floor']==ctx['floor'] and t['fixed_target'] is None and t['original_protective_sl'] is None and t['exchange_resident_stop'] is False,'NATIVE_RISK_RULE')
            hs=[h for h in x['trace'] if h['signal_index']==i and h['kind']=='HELD_CLOSE_OBSERVATION'];need(hs,'NO_HELD_OBSERVATION');first=None
            for n,h in enumerate(hs,1):
                j=i+n;bar=rows[j];mom=bar['close']-rows[j-14]['close'];why='FIXED_FLOOR_CLOSE' if bar['close']<=ctx['floor'] else 'MOMENTUM_NONPOSITIVE_CLOSE' if mom<=0 else 'FIXED_TIME_CLOSE' if n>=20 else None
                need(first is None,'MISSED_FIRST_EXIT');need(h['index']==j and h['ts']==bar['bar_close_ts'] and h['held_bars']==n,'HELD_CLOCK');same([h['close'],h['momentum'],h['floor']],[bar['close'],mom,ctx['floor']],'HELD_SOURCE');need(h['exit_reason']==why,'NATIVE_EXIT_REASON')
                if why:first=dict(signal_index=j,signal_ts=bar['bar_close_ts'],observed_close=bar['close'],reason=why)
            closed='exit_ts' in t
            if closed:
                need(first is not None and t['exit_trigger']==first and t['exit_index']==first['signal_index']+1 and t['exit_ts']==first['signal_ts']<cal['runoff_end_ms'],'FIRST_EXIT_NEXT_OPEN');need(t['exit_price']==rows[t['exit_index']]['open'] and t['exit_reason']==first['reason']+'_NEXT_OPEN','EXIT_PRICE');last=t['exit_ts'];price=t['exit_price'];stamp=last
            else:
                need(t['mark_ts']==cal['runoff_end_ms']==hs[-1]['ts'] and t['mark_price']==rows[-1]['close'] and t['pending_exit_trigger']==first,'OPEN_BOUNDARY');need(first is None or first['signal_ts']==cal['runoff_end_ms'],'MISSED_EXECUTABLE_EXIT');need(t['terminal_liquidation'] is False,'FAKE_TAIL_FILL');tail=True;price=t['mark_price'];stamp=t['mark_ts']
            need(t['hold_ms']==stamp-t['entry_ts'],'HOLD');gross=(price/entry-1)*10000
            same(t['mfe_bps'],max(0,gross,max((z['high']/entry-1)*10000 for z in rows[ei:hs[-1]['index']+1])),'MFE_SOURCE');same(t['mae_bps'],min(0,gross,min((z['low']/entry-1)*10000 for z in rows[ei:hs[-1]['index']+1])),'MAE_SOURCE')
            raw_positions[(symbol,i)]=t;positions+=1;held_count+=len(hs)
        same(x['pending_entries'],pending,'PENDING_ENTRY_COVERAGE')
    same(result['events'],expected_events,'CHARGED_EVENT_COVERAGE')
    charged={(t['symbol'],t['signal_index']):t for key in ('trades','open_observations') for t in result[key]};need(charged.keys()==raw_positions.keys(),'CHARGED_ORIGINS')
    for k,t in charged.items():
        for field,v in raw_positions[k].items():same(t[field],v,'RAW_TO_CHARGED.'+field)
    return dict(positions=positions,held_closes=held_count,signals=len(expected_events),prepared_setups=setup_count)

def check_metrics(r,packet,cal):
    idx=index(r);m=r['metrics'];closed=r['trades'];opened=r['open_observations']
    for state,t in idx.values():
        end=t['exit_ts'] if state=='C' else t['mark_ts'];price=t['exit_price'] if state=='C' else t['mark_price'];parts,fee=cost(packet['costs'][t['symbol']],t['entry_ts'],end);gross=(price/t['entry_price']-1)*10000
        if state=='C':same([t['gross_bps'],t['net_bps'],t['cost2x_net_bps'],t['cost_bps']],[gross,gross-fee,gross-2*fee,fee],'CLOSED_COST');same({k:t[k] for k in COMP},parts,'COST_COMPONENTS')
        else:same([t['gross_mark_bps'],t['hypothetical_liquidation_net_mark_bps'],t['hypothetical_liquidation_cost2x_net_mark_bps']],[gross,gross-fee,gross-2*fee],'OPEN_COST');same(t['hypothetical_cost_components_bps'],parts,'OPEN_COMPONENTS')
        check=deepcopy(t);key='trade_sha256' if state=='C' else 'observation_sha256';digest=check.pop(key);need(hashlib.sha256(canonical(check)).hexdigest()==digest,'ROW_HASH')
        need(not t['exchange_order_submitted'] and t['formal_credit']==0 and not t['independent'],'AUTHORITY')
    for label,key in [('base_cost','net_bps'),('cost2x','cost2x_net_bps')]:
        xs=[t[key] for t in closed];win=[x for x in xs if x>0];loss=[x for x in xs if x<0];b=m[label];mw=sum(win)/len(win) if win else None;ml=sum(loss)/len(loss) if loss else None
        same([b['net_bps'],b['win_rate'],b['average_win_bps'],b['average_loss_bps'],b['PF'],b['realized_payoff']],[sum(xs),len(win)/len(xs) if xs else None,mw,ml,sum(win)/-sum(loss) if loss else None,mw/-ml if mw is not None and ml is not None else None],'SUMMARY_ARITHMETIC');need(b['completed_T']==len(xs),'SUMMARY_COUNT')
    same(m['terminal_net_bps'],sum(val(s,t) for s,t in idx.values()),'NET_TOTAL');same(m['terminal_cost2x_net_bps'],sum(t['cost2x_net_bps'] if s=='C' else t['hypothetical_liquidation_cost2x_net_mark_bps'] for s,t in idx.values()),'COST2_TOTAL')
    same(m['open_hypothetical_net_mark_bps'],sum(val('O',t) for t in opened),'OPEN_TOTAL')
    prices={s:{r['bar_close_ts']:r['close'] for r in rows} for s,rows in packet['rows_by'].items()}
    for s,rows in packet['rows_by'].items():prices[s].update({r['bar_open_ts']:r['open'] for r in rows if r['bar_open_ts']<cal['runoff_end_ms']})
    stamps=list(range((cal['start_ms']//DAY+1)*DAY,cal['runoff_end_ms']+1,DAY))
    if not stamps or stamps[-1]!=cal['runoff_end_ms']:stamps.append(cal['runoff_end_ms'])
    need([d['mark_ts'] for d in m['daily']]==stamps,'DAILY_COVERAGE');last=peak=dd=0.
    for d in m['daily']:
        ts=d['mark_ts'];net=gross=twice=0.;active=0
        for state,t in idx.values():
            if t['entry_ts']>ts:continue
            if state=='C' and t['exit_ts']<=ts:net+=t['net_bps'];gross+=t['gross_bps'];twice+=t['cost2x_net_bps'];continue
            active+=1;g=(prices[t['symbol']][ts]/t['entry_price']-1)*10000;c=cost(packet['costs'][t['symbol']],t['entry_ts'],ts)[1];gross+=g;net+=g-c;twice+=g-2*c
        same([d['cumulative_net_mark_bps'],d['cumulative_gross_mark_bps'],d['cumulative_cost2x_mark_bps'],d['value']],[net,gross,twice,net-last],'DAILY_SOURCE_VALUES');need(d['active_marked_positions']==active,'DAILY_ACTIVE');last=net;peak=max(peak,net);dd=max(dd,peak-net)
    same(m['marked_DD_trade_sum_bps'],dd,'MARKED_DD');same(m['exposure']['position_days'],sum(t['hold_ms'] for s,t in idx.values())/DAY,'EXPOSURE')
    return len(stamps)

def check_bridge(parent,result,saved):
    pi,ci=index(parent),index(result);need(len(saved['rows'])==len(pi.keys()|ci.keys()),'BRIDGE_COVERAGE');terms=defaultdict(float);by=defaultdict(float);signs=Counter();lower=higher=0
    for row in saved['rows']:
        k=row['episode'];a,b=pi.get(k),ci.get(k);pn=val(*a) if a else 0.;cn=val(*b) if b else 0.;group='common_'+a[0]+b[0] if a and b else 'removed' if a else 'new'
        same([row['parent_net_bps'],row['candidate_net_bps'],row['delta_bps']],[pn,cn,cn-pn],'EPISODE_ROW');need(row['group']==group,'EPISODE_STATE');terms[group]+=cn-pn;by[k.split('|')[0]]+=cn-pn
        if a and b:
            need(b[1]['entry_ts']<a[1]['entry_ts'],'EARLIER_ENTRY');same([row['parent_entry_price'],row['candidate_entry_price']],[a[1]['entry_price'],b[1]['entry_price']],'EPISODE_PRICES');lower+=b[1]['entry_price']<a[1]['entry_price'];higher+=b[1]['entry_price']>a[1]['entry_price']
            if a[0]==b[0]=='C':signs[('W' if pn>0 else 'L')+'->'+('W' if cn>0 else 'L')]+=1
    for k,x in saved['terms'].items():same(terms[k],x,'TERM_'+k)
    delta=result['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps'];same(sum(terms.values()),delta,'BRIDGE_TOTAL');same(saved['total_delta_bps'],delta,'DELTA');need(saved['counts']==dict(lower_entry=lower,higher_entry=higher),'ENTRY_PRICE_COUNTS')
    winners=sorted([(k,x) for k,x in pi.items() if x[0]=='C' and val(*x)>0],key=lambda x:val(*x[1]),reverse=True)
    for label,items in [('all_winners',winners),('large_winners',winners[:max(1,math.ceil(len(winners)*.1))])]:
        total=sum(val(*x) for k,x in items);kept=sum(min(val(*x),max(0,val(*ci[k]))) if k in ci else 0 for k,x in items);v=saved[label]
        same([v['parent_profit_bps'],v['retained_capped_profit_bps'],v['retention']],[total,kept,kept/total if total else None],'RETENTION')
    return dict(by_symbol_delta=dict(by),common_closed_sign_transitions=dict(signs))

def verify(root=HERE,partial=False):
    root=Path(root);repo=root.parents[2];s=read(root/'SPEC.json');need(sha(root/'EVIDENCE_HASHES.json')==PIN,'MANIFEST_PIN')
    for n,d in read(root/'EVIDENCE_HASHES.json').items():need(sha(root/n)==d,'FROZEN_RESULT:'+n)
    missing=[]
    for n,d in s['source_files_sha256'].items():
        if not (repo/n).exists():missing.append(n);continue
        need(sha(repo/n)==d,'SOURCE_HASH:'+n)
    need(partial or not missing,'INCOMPLETE_SOURCE_CHECKOUT')
    b=deepcopy(read(root/'BUDGET.json'));q=b.pop('c63_pre_release_entry_allocation');need((q['reserved'],q['started'],q['completed'],q['failed'],q['remaining'])==(2,2,2,0,0),'SCOPE_INCOMPLETE');need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(68,120),'COUNTERS');need([x['actual_experiment_ordinal'] for x in b['trials'][-2:]]==[119,120],'ATTEMPT_NUMBERS')
    b['cumulative_actual']-=1;b['cumulative_actual_evaluations']-=2;b['new_candidate_runs']-=1;b['candidate_trials']=b['candidate_trials'][:-1];b['trials']=b['trials'][:-2];need(b==read(root/'HISTORY_PRIOR.json') and b['chart_allocation']['remaining']==6,'HISTORY_PRESERVED');need(sha(root/'HISTORY_PRIOR.json')==s['history_sha256'],'HISTORY_SHA')
    totals={};summary=read(root/'SUMMARY.json');goals=[]
    for per,cal in s['periods'].items():
        path=repo/INPUTS/(per+'.json.gz');need(sha(path)==s['input_packet_sha256'][per],'INPUT_SHA');packet=gz(path)
        for n,d in s['parent_results_sha256'][per].items():need(sha(repo/PARENT/per/n)==d,'PARENT_SHA')
        r=gz(root/per/'RESULT.json.gz');raw=gz(root/per/'RAW.json.gz');parent=gz(repo/PARENT/per/'RESULT.json.gz');rec=read(root/per/'RECEIPT.json');at=read(root/per/'ATTEMPT.json');st=read(root/per/'EXECUTION_STARTED.json')
        need(rec['status']=='COMPLETED' and rec['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'RECEIPT_SPEC');need(st['claim_commit']==st['remote_readback_sha']==rec['claim_commit'] and st['owner_run']==at['owner_run'],'REMOTE_CLAIM');need(s['frozen_ns']<at['time_ns']<st['time_ns'],'FREEZE_ORDER');need(rec['raw_sha256']==sha(root/per/'RAW.json.gz') and rec['result_sha256']==sha(root/per/'RESULT.json.gz'),'RECEIPT_HASH')
        counts=check_core(raw,r,packet,cal);counts['daily_marks']=check_metrics(r,packet,cal);counts.update(check_bridge(parent,r,read(root/per/'EPISODE_BRIDGE.json')));totals[per]=counts
        old=parent['metrics'];new=r['metrics']
        flags=dict(WR_up=new['base_cost']['win_rate']>old['base_cost']['win_rate']+1e-10,net_up=new['terminal_net_bps']>old['terminal_net_bps']+1e-7,cost2_up=new['terminal_cost2x_net_bps']>old['terminal_cost2x_net_bps']+1e-7,DD_down=new['marked_DD_trade_sum_bps']<old['marked_DD_trade_sum_bps']-1e-7)
        need(flags==summary['periods'][per]['checks'],'GOAL_FLAGS');goals.append(flags)
        for label,res in [('C63',parent),('ENTRY',r)]:
            m=res['metrics'];bc=m['base_cost'];snap=summary['periods'][per]['snapshots'][label]
            need(snap['closed']==len(res['trades']) and snap['open']==len(res['open_observations']),'DISPLAY_COUNTS')
            for k in ('win_rate','average_win_bps','average_loss_bps','PF','realized_payoff'):same(snap[k],bc[k],'DISPLAY_'+k)
            for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):same(snap[k],m[k],'DISPLAY_'+k)
            fmt=lambda x:'NA' if x is None else f'{x:.2f}'
            line='|'+ '|'.join([per,label,f"{snap['closed']}/{snap['open']}",fmt(snap['win_rate']*100)]+[fmt(snap[k]) for k in ('average_win_bps','average_loss_bps','PF','realized_payoff','terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'
            need(line in (root/'REPORT.md').read_text(),'REPORT_ROW')
    expected='DEVELOPMENT_GOAL_MET' if all(all(x.values()) for x in goals) else 'PARTIAL_IMPROVEMENT' if all(x['net_up'] and x['cost2_up'] for x in goals) else 'REJECT_KEEP_C63_PAUSE_THIS_BRANCH'
    need(summary['status']==expected,'FALSE_ECONOMIC_VERDICT')
    return dict(status='SAVED_SOURCE_ARITHMETIC_VERIFIED',periods=totals,source_files_missing=missing,partial_source_export=bool(missing),new_economic_replays=0)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--allow-partial-source',action='store_true');args=a.parse_args();print(json.dumps(verify(partial=args.allow_partial_source),indent=2))
