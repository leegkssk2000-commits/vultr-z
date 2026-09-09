"""Stored evidence arithmetic and source binding; imports no strategy or runner.

This verifies saved observations, actual OHLC fills, cost and attribution. It
does not generate signals, place orders, or perform another economic replay.
"""
import argparse, gzip, hashlib, importlib.util, json, math
from collections import defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
PARENT='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/B'
CHECKER='research/development_evidence/KR3_PROFIT_ZONE_PRESERVATION_AFTER_PR1223_V1/verify_saved.py'
VARIANTS=('T1','M1','R1','F1','F0'); PERIODS=('DEV2025','SEEN2026'); BAR=14_400_000
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def checker(repo):
    spec=importlib.util.spec_from_file_location('chart_independent_saved_arithmetic',Path(repo)/CHECKER)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def check_standalone_trace(raw,rows,variant,v):
    """Prove first held-close trigger and no omitted earlier held observations."""
    for t in raw['trades']+raw['open_positions']:
        ei=t['entry_index'];last=t.get('exit_index',len(rows))-1
        observations=[x for x in raw['trace'] if x['signal_index']==t['signal_index'] and x['kind']=='HELD_CLOSE_OBSERVATION']
        need([x['index'] for x in observations]==list(range(ei,last+1)),'HELD_OBSERVATION_OMISSION')
        first=None
        for x in observations:
            j=x['index'];close=rows[j]['close'];momentum=close-rows[j-14]['close'] if variant=='M1' else None
            v.same(x['close'],close,'HELD_SOURCE_CLOSE');v.same(x['momentum'],momentum,'SOURCE_MOM14')
            v.same(x['floor'],t['fixed_floor'],'FIXED_FLOOR');v.same(x['target'],t['fixed_target'],'FIXED_TARGET')
            need(x['ts']==rows[j]['bar_close_ts'] and x['held_bars']==j-ei+1,'HELD_CLOCK')
            reason=('FIXED_FLOOR_CLOSE' if close<=t['fixed_floor'] else
                    'MOMENTUM_NONPOSITIVE_CLOSE' if variant=='M1' and momentum<=0 else
                    'PRIOR_RANGE_MIDPOINT_CLOSE' if variant=='R1' and close>=t['fixed_target'] else
                    'FIXED_TIME_CLOSE' if j-ei+1>=(20 if variant=='M1' else 12) else None)
            v.same(x['exit_reason'],reason,'FIRST_EXIT_REASON')
            if reason is not None:
                need(first is None and x is observations[-1],'DELAYED_EXIT');first=(j,reason)
        if 'exit_index' in t:
            need(first is not None and t['exit_index']==first[0]+1,'EXIT_WITHOUT_FIRST_TRIGGER')
            need(t['exit_reason']==first[1]+'_NEXT_OPEN','EXIT_PRIORITY')
        elif first is not None:need(first[0]==len(rows)-1 and t['pending_exit_signal_ts']==rows[-1]['bar_close_ts'],'PENDING_NOT_AT_WINDOW_END')
    return len(raw['trades'])+len(raw['open_positions'])

def check_source(raw,rows,variant,v):
    need(all(r['bar_close_ts']==r['bar_open_ts']+BAR for r in rows),'SOURCE_BAR_CLOCK')
    need(all(b['bar_open_ts']-a['bar_open_ts']==BAR for a,b in zip(rows,rows[1:])),'SOURCE_GAP')
    for t in raw['trades']+raw['open_positions']:
        i=t['signal_index'];ei=t['entry_index'];need(ei==i+1,'SOURCE_ENTRY_INDEX')
        need(t['signal_ts']==rows[i]['bar_close_ts'] and t['entry_ts']==rows[ei]['bar_open_ts'],'SOURCE_ENTRY_CLOCK')
        v.same(t['entry_price'],rows[ei]['open'],'SOURCE_ENTRY_OPEN')
        if 'exit_index' in t:
            x=t['exit_index'];need(t['exit_ts']==rows[x]['bar_open_ts'],'SOURCE_EXIT_CLOCK');v.same(t['exit_price'],rows[x]['open'],'SOURCE_EXIT_OPEN')
        else:
            need(t['mark_ts']==rows[-1]['bar_close_ts'],'SOURCE_MARK_CLOCK');v.same(t['mark_price'],rows[-1]['close'],'SOURCE_MARK_CLOSE')
    for e in raw['events']:
        i=e['signal_index'];need(e['signal_ts']==rows[i]['bar_close_ts'],'SOURCE_EVENT_CLOCK')
        obs=e.get('entry_observation')
        if obs:
            for k in ('close','high','low'):v.same(obs['signal_'+k],rows[i][k],'ENTRY_OBSERVATION_'+k)
        ctx=e.get('entry_context',{}).get('chart_context')
        if ctx and ctx.get('anchor'):
            anchor=ctx['anchor'];a=anchor['low']['index'];b=anchor['high']['index'];q=e['entry_context']['trend_index']
            need(a<b<=q and anchor['high']['known_index']<=i-1 and anchor['low']['known_index']<=i-1,'FUTURE_PIVOT')
            for kind,k,key in [('low',a,'low'),('high',b,'high')]:
                v.same(anchor[kind]['price'],rows[k][key],'SOURCE_ANCHOR')
                need(all(rows[k][key]<rows[z][key] if kind=='low' else rows[k][key]>rows[z][key] for z in (k-2,k-1,k+1,k+2)),'NONSTRICT_PIVOT')
            def av(end):
                den=math.fsum(r['volume'] for r in rows[a:end+1])
                return math.fsum((r['high']+r['low']+r['close'])/3*r['volume'] for r in rows[a:end+1])/den if den else None
            v.same(ctx['avwap'],av(i),'SOURCE_AVWAP');v.same(ctx['previous_avwap'],av(i-1),'SOURCE_LAGGED_AVWAP')
            depth=(rows[b]['high']-min(r['low'] for r in rows[q+1:i]))/(rows[b]['high']-rows[a]['low'])
            v.same(ctx['retracement'],depth,'SOURCE_RETRACEMENT')
            allowed=ctx['avwap'] is not None and ctx['previous_avwap'] is not None and rows[i]['close']>ctx['avwap']>ctx['previous_avwap']
            if variant=='F1':allowed=allowed and .382<=depth<=.618
            if variant=='F0':allowed=allowed and .350<=depth<=.586
            need(ctx['eligible']==allowed,'CHART_ADMISSION_PREDICATE')
            if e['admission']:need(allowed and e['entry_context']['B'],'DISALLOWED_ADMISSION')
    if variant in ('M1','R1'):check_standalone_trace(raw,rows,variant,v)

def check_raw(raw,result,costs,calendar,v):
    expected={k:[] for k in ('trades','open_observations','events','trace')}
    for symbol,data in sorted(raw.items()):
        for source,target in [('trades','trades'),('open_positions','open_observations'),('events','events'),('trace','trace')]:
            expected[target].extend(dict(x,symbol=symbol) for x in data[source])
    for key in ('events','trace'):
        need(len(expected[key])==len(result[key]),'RAW_'+key+'_COUNT')
        for x,y in zip(expected[key],result[key]):v.subset(y,x,'RAW_'+key)
    for kind in ('trades','open_observations'):
        source,target=v.index(expected[kind]),v.index(result[kind]);need(source.keys()==target.keys(),'RAW_ORIGINS')
        for key,x in source.items():
            t=target[key];v.subset(t,x,'RAW_GEOMETRY');closed=kind=='trades'
            end=t['exit_ts'] if closed else t['mark_ts'];price=t['exit_price'] if closed else t['mark_price']
            need(calendar['start_ms']<=t['entry_ts']<calendar['runoff_end_ms'] and t['entry_ts']<=end<=calendar['runoff_end_ms'],'TRADE_CALENDAR')
            need(t['side']=='long' and t['entry_price']>0 and price>0,'PRICE_SIDE')
            gross=(price/t['entry_price']-1)*10000;parts,cost,count=v.costs_for(costs[t['symbol']],t['entry_ts'],end)
            v.same(t['hold_ms'],end-t['entry_ts'],'HOLD_TIME');v.same(t['gross_bps' if closed else 'gross_mark_bps'],gross,'GROSS_ARITHMETIC')
            if closed:
                v.subset(t,parts,'COST_PARTS');v.same(t['cost_bps'],cost,'COST');v.same(t['funding_settlements_crossed'],count,'FUNDING')
                v.same(t['net_bps'],gross-cost,'NET');v.same(t['cost2x_net_bps'],gross-2*cost,'COST2')
                need(t['status']=='COMPLETED','CLOSED_STATUS')
            else:
                need(t['status']=='CENSORED' and not t['actual_exit'] and not t['terminal_liquidation'],'FABRICATED_LIQUIDATION')
                v.same(t['hypothetical_cost_components_bps'],parts,'OPEN_COST_PARTS');v.same(t['hypothetical_liquidation_cost_bps'],cost,'OPEN_COST')
                v.same(t['hypothetical_liquidation_net_mark_bps'],gross-cost,'OPEN_NET');v.same(t['hypothetical_liquidation_cost2x_net_mark_bps'],gross-2*cost,'OPEN_COST2')
            need(t['formal_credit']==0 and t['independent'] is False and t['exchange_order_submitted'] is False,'AUTHORITY_DRIFT')
    return len(expected['trades'])+len(expected['open_observations'])

def verify(root=HERE,inputs=None,pin=None):
    root=Path(root);repo=root.parents[2];v=checker(repo);spec=read(root/'SPEC.json');budget=read(root/'BUDGET.json')
    if pin:need(sha(root/'FINAL_HASHES.json')==pin,'MANIFEST_DRIFT')
    if (root/'FINAL_HASHES.json').exists():
        for path,digest in read(root/'FINAL_HASHES.json').items():need(sha(root/path)==digest,'ARTIFACT_DRIFT:'+path)
    for path,digest in spec['source_files_sha256'].items():need(sha(repo/path)==digest,'SOURCE_DRIFT:'+path)
    if spec.get('prior_budget_path'):need(sha(repo/spec['prior_budget_path'])==spec['prior_budget_sha256'],'PRIOR_BUDGET_DRIFT')
    costs=read(root/'COSTS.json') if (root/'COSTS.json').exists() else read(repo/Path(CHECKER).parent/'COSTS.json')
    if spec.get('cost_hash'):need(hashlib.sha256(v.canonical(costs)).hexdigest()==spec['cost_hash'],'COST_DRIFT')
    slot=budget['chart_allocation'];need(slot['reserved']<=10 and slot['started']<=slot['reserved'] and slot['completed']+slot['failed']<=slot['started'],'BUDGET_OVERSPEND')
    records={};completed=0
    for per in PERIODS:
        parent_path=repo/PARENT/per/'RESULT.json.gz';need(sha(parent_path)==spec['parent_results_sha256'][per],'PARENT_DRIFT');parent=gz(parent_path)
        packet=None
        if inputs:
            pp=Path(inputs)/(per+'.json.gz');need(sha(pp)==spec['input_packet_sha256'][per],'INPUT_PACKET_DRIFT');packet=gz(pp)
            v.same(packet['costs'],costs,'PACKET_COSTS')
        for variant in VARIANTS:
            d=root/variant/per
            if not (d/'RECEIPT.json').exists():continue
            receipt=read(d/'RECEIPT.json')
            if receipt['status']!='COMPLETED':continue
            at=read(d/'ATTEMPT.json');started=read(d/'EXECUTION_STARTED.json');raw=gz(d/'RAW.json.gz');result=gz(d/'RESULT.json.gz')
            need(sha(d/'RAW.json.gz')==receipt['raw_sha256'] and sha(d/'RESULT.json.gz')==receipt['result_sha256'],'RECEIPT_DRIFT')
            need(receipt['spec_sha256']==at['spec_sha256']==sha(root/'SPEC.json'),'SPEC_IDENTITY')
            need(started['claim_commit']==started['remote_readback_sha']==receipt['claim_commit'],'REMOTE_CLAIM')
            need(spec['frozen_ns']<at['time_ns']<started['time_ns'],'ATTEMPT_ORDER')
            count=check_raw(raw,result,costs,spec['periods'][per],v);v.check_metrics(result)
            if packet:
                for symbol,data in raw.items():check_source(data,packet['rows_by'][symbol],variant,v)
            comparison=None
            if variant in ('T1','F1','F0'):
                comparison=v.compare_parent(parent,result,read(d/'ACCOUNTING_C54.json'))
                pi,ci=v.complete_index(parent),v.complete_index(result)
                for k in pi.keys()&ci.keys():
                    need(pi[k][0]==ci[k][0],'COMMON_PARENT_STATE_CHANGED');v.same(v.values(pi[k]),v.values(ci[k]),'COMMON_C54_ECONOMICS')
                    for field in ('entry_price','entry_ts','hold_ms'):v.same(pi[k][1][field],ci[k][1][field],'COMMON_C54_'+field)
            records[variant+'/'+per]=dict(raw_rows=count,net=result['metrics']['terminal_net_bps'],attribution=comparison,source_bound=packet is not None);completed+=1
    need(completed==slot['completed'],'COMPLETION_COUNT')
    return dict(status='SAVED_RAW_COST_METRICS_VERIFIED',source_binding=bool(inputs),new_economic_replays=0,results=records)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--manifest-sha256');x=p.parse_args()
    print(json.dumps(verify(inputs=x.inputs,pin=x.manifest_sha256),indent=2))
