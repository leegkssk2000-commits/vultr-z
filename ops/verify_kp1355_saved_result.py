"""Verify the already-completed K.P recorded-price run; never invoke a model.

Independent stdlib arithmetic over immutable saved trades and lifecycle trace.
The ZIP pin identifies a completed run, not new execution authority or OOS proof.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

ARCHIVE_SHA = 'f5811b647afcf3f6d352aed5b875a43c23a754be8845dc9bfb44a5af1598cef7'
RESULT_SHA = '42091eced2860b8d301df92d51c0a6e4693d409cdcc617422ccda788afb9f087'
INPUT_SHA = '3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3'
CONTRACT_SHA = 'e2e02b9013b91c92411741791535746e671e9b146eca82c8e0ce3a19176e3e1c'
CANDIDATE = 'scalp7_keltner_hg_parent_utc30m_v2'
RUN_ID = 'KP30_CONNECTED_RECORDED_PRICE_20261004_V1'
WINDOW = {'start_ms': 1789502400000, 'end_exclusive_ms': 1791075300000}
NAMES = {'PREEXEC_FAILURE_PRESERVED.json','execution-tests.log','input-tests.log',
         *('validation/'+n+'.json' for n in ('STARTED','COMPLETED','RESULT','EXECUTION','SIGNALS',
                                           'LIFECYCLE_TRACE','FRAME_MANIFEST','INDEPENDENT_AMOUNT_AUDIT'))}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def strict(raw):
    def pairs(items):
        obj={}
        for k,v in items:
            require(k not in obj,'DUPLICATE_JSON_KEY')
            obj[k]=v
        return obj
    def bad(_):
        raise ValueError('NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def near(a,b):
    require(type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b),'NONFINITE_NUMBER')
    require(abs(a-b)<=1e-7,'ARITHMETIC_MISMATCH')


def signal_key(s):
    return f"{s['identity']}|{s['symbol']}|{s['signal_ts_ms']}"


def summarize(rows, multiplier):
    ordered=sorted(rows,key=lambda t:(t['outcome_available_ts_ms'],t['exit_ts_ms'],t['symbol'],t['identity'],t['signal_ts_ms']))
    vals=[t['gross_bps']-multiplier*t['cost_bps'] for t in ordered]
    wins=math.fsum(v for v in vals if v>0); losses=-math.fsum(v for v in vals if v<0)
    groups=defaultdict(list); streak=maximum=0
    for t,v in zip(ordered,vals):
        streak=streak+1 if v<0 else 0;maximum=max(maximum,streak)
        groups[t['outcome_available_ts_ms']].append(v)
    nav=peak=dd=0.0
    for stamp in sorted(groups):
        nav+=math.fsum(groups[stamp]);peak=max(peak,nav);dd=max(dd,peak-nav)
    return {'T':len(rows),'WR_pct':100*sum(v>0 for v in vals)/len(vals),
            'Gross_bps':math.fsum(t['gross_bps'] for t in rows),
            'Cost_bps':multiplier*math.fsum(t['cost_bps'] for t in rows),
            'Net_bps':math.fsum(vals),'NetExp_bps_T':math.fsum(vals)/len(vals),
            'PF':wins/losses,'DD_bps':dd,'MaxLossStreak':maximum}


def verify(archive):
    raw=Path(archive).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==ARCHIVE_SHA,'WRONG_COMPLETED_ARCHIVE')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        require(len(z.infolist())==len(NAMES) and set(z.namelist())==NAMES,'WRONG_ARCHIVE_MEMBERS')
        require(all(i.file_size<=2*1024*1024 for i in z.infolist()),'MEMBER_SIZE')
        blobs={n:z.read(n) for n in NAMES}
    documents={n:strict(v) for n,v in blobs.items() if n.endswith('.json')}
    get=lambda n:documents['validation/'+n+'.json']
    r,e,ss,tr=get('RESULT'),get('EXECUTION'),get('SIGNALS'),get('LIFECYCLE_TRACE')
    require(hashlib.sha256(blobs['validation/RESULT.json']).hexdigest()==RESULT_SHA==get('COMPLETED')['result_sha256'],'RESULT_HASH')
    require(r['run_id']==get('STARTED')['run_id']==get('COMPLETED')['run_id']==RUN_ID,'RUN_ID')
    require(get('STARTED')['contract_sha256']==CONTRACT_SHA and get('STARTED')['input_sha256']==r['input_sha256']==INPUT_SHA,'INPUT_OR_CONTRACT_HASH')
    require(r['window']==WINDOW and r['candidate']==CANDIDATE and r['economic_replay_count']==get('COMPLETED')['economic_replays']==1,'FIXED_RUN')
    require(r['evidence_class']=='RECORDED_PRICE_HISTORICAL_BAR_BOUNDARY_MODEL','EVIDENCE_CLASS')
    for key in ('unused_oos_certified','g5a_shortlist','g5b_terminal','g6','live','deployed_runtime_repaired','historical_funding_settled'):
        require(r[key] is False,'FALSE_PROMOTION_OR_EXECUTION_CLAIM:'+key)
    for key in ('genuine_fresh_trades','reparameterizations','shared_state_writes','actual_exchange_orders'):
        require(type(r[key]) is int and r[key]==0,'UNEXPECTED_AUTHORITY:'+key)
    require(r['account_dd'] is None and r['account_return'] is None and r['leverage'] is None,'ACCOUNT_CLAIM')
    require(e['order_authority']==e['live_authority']=='BLOCKED' and e['unresolved']==[] and r['unresolved_count']==0,'EXECUTION_BOUNDARY')
    signals={signal_key(s):s for s in ss};require(len(signals)==len(ss)==32,'SIGNAL_DUPLICATE_OR_COUNT')
    trades=e['trades'];require(len(trades)==e['closed_trade_count']==20,'TRADE_COUNT')
    require(e['rejections']==r['rejections']=={'ENTRY_ATR_COST_GATE':11,'POSITION_ALREADY_OWNED':1},'REJECTIONS')
    require(len(trades)+sum(e['rejections'].values())==len(ss),'SIGNAL_FUNNEL')
    partials=defaultdict(list)
    for t in tr:
        require(t['signal_key'] in signals,'TRACE_UNKNOWN_SIGNAL')
        require(t['modeled_decision_ms']==t['bar_open_ms']+1800000,'TRACE_CLOCK')
        if t['partial_fraction']:
            partials[t['signal_key']].append(t)
    require(len(tr)==r['lifecycle_trace_rows']==146 and len(partials)==3,'TRACE_COUNTS')
    keys=set();max_residual=0.0
    for t in trades:
        k=signal_key(t['signal']);require(k in signals and k not in keys,'TRADE_IDENTITY');keys.add(k)
        require(t['signal']==signals[k] and t['identity']==CANDIDATE and t['timeframe_min']==30,'FROZEN_SIGNAL')
        require(WINDOW['start_ms']<=t['signal_ts_ms']<=t['entry_ts_ms']<=t['exit_ts_ms']<=t['outcome_available_ts_ms']<WINDOW['end_exclusive_ms'],'TRADE_CLOCK')
        entry=t['entry_prices'][t['symbol']];exit=t['exit_prices'][t['symbol']];side=t['side']
        require(entry>0 and exit>0 and side in (-1,1),'PRICE_SIDE')
        part=partials[k];require(len(part)<=1,'MULTIPLE_PARTIALS')
        fraction=0.0;gross=0.0
        for p in part:
            near(p['entry_price'],entry);near(p['partial_fraction'],0.1)
            near(p['partial_price'],entry+side*2*p['initial_risk'])
            require(t['entry_ts_ms']<=p['modeled_decision_ms']<=t['outcome_available_ts_ms'],'PARTIAL_CLOCK')
            fraction+=p['partial_fraction'];gross+=p['partial_fraction']*side*(p['partial_price']/entry-1)*10000
        gross+=(1-fraction)*side*(exit/entry-1)*10000
        max_residual=max(max_residual,abs(gross-t['gross_bps']));near(gross,t['gross_bps'])
        near(gross-t['cost_bps'],t['net_bps']);near(t['cost_bps'],t['signal']['meta']['frozen_cost_bps'])
    costs={}
    for mult in (1,2):
        calc=summarize(trades,mult)
        for key,value in calc.items():near(value,r[f'reference_cost_{mult}x'][key])
        costs[str(mult)]=calc
    witness=r['receipt_clock_witness'];require({w['signal_key'] for w in witness}==set(signals) and len(witness)==32,'WITNESS_IDS')
    delays=[w['recorded_constituent_available_ms']-w['decision_close_ms'] for w in witness]
    require(all(d>0 for d in delays) and all(w['historical_next_open_available_in_realtime'] is False for w in witness),'TIMING_CLAIM')
    exit_groups={reason:{str(m):{'T':len(group),'Net_bps':math.fsum(t['gross_bps']-m*t['cost_bps'] for t in group)} for m in (1,2)}
                 for reason in sorted({t['reason'] for t in trades})
                 for group in [[t for t in trades if t['reason']==reason]]}
    return {'schema':'kp30.saved_result_closeout.v1','status':'PASS_SAVED_RESULT_AUDIT',
            'run_id':RUN_ID,'original_run_id':37208749237,'original_artifact_id':11305329406,
            'archive_sha256':ARCHIVE_SHA,'result_sha256':RESULT_SHA,'input_sha256':INPUT_SHA,
            'member_sha256':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(blobs.items())},
            'new_economic_replays':0,'existing_completed_replays':1,'signal_count':32,'trade_count':20,
            'partial_trade_count':3,'gross_max_residual_bps':max_residual,'cost_scenarios':costs,
            'exit_attribution':exit_groups,'all_signal_receipts_late':True,
            'signal_receipt_lateness_ms':{'min':min(delays),'median':sorted(delays)[len(delays)//2-1]/2+sorted(delays)[len(delays)//2]/2,'max':max(delays)},
            'model_economics':'NEGATIVE_AT_1X_AND_2X','formal_g5_failure':False,'promotion_granted':False,
            'unused_oos_certified':False,'actual_realtime_fills_certified':False,'account_economics_certified':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=verify(a.archive)
    with a.output.open('x') as f:json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='member_sha256'},indent=2))


if __name__=='__main__':main()
