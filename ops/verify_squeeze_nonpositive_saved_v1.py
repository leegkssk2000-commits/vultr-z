"""Saved-only independent arithmetic/timing/accounting; never imports a model."""
import argparse
import hashlib
import json
import lzma
import math
from pathlib import Path
import sys
import tempfile
from collections import defaultdict

PARENT='scalp7_squeeze_panic_cost4_parent_utc30m_v2'
CHILD='scalp7_squeeze_panic_cost4_momentum_nonpositive_utc30m_v1'
START=1789502400000;END=1791075300000;EPS=1e-7
BUNDLE_SHA='d8e64b248d25a66ccdd44e403da82284ec7f5f49fcf9ebd5be68e9876c1d6ed1'
PARENT_SHA='a390f985245f32d52681fea688617d01fb6eb597b1269f10a62466075a9edbc9'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def close(a,b):
    if a is None or b is None:assert a is b,(a,b)
    else:assert math.isfinite(float(a)) and math.isclose(a,b,abs_tol=EPS,rel_tol=1e-10),(a,b)
def key(r):return r['symbol'],r['side'],r['signal_ts_ms']
def scored(rows):return [r for r in rows if START<=r['signal_ts_ms']<END and r['outcome_available_ts_ms']<END]
def unpack(path,expected):
    raw=path.read_bytes();assert sha(raw)==expected,'BUNDLE_HASH'
    d=lzma.LZMADecompressor(memlimit=256*1024*1024)
    payload=d.decompress(raw,max_length=32*1024*1024+1)
    assert d.eof and not d.unused_data and len(payload)<=32*1024*1024,'BUNDLE_BOUND'
    return json.loads(payload)
def metrics(rows,mult):
    rows=sorted(scored(rows),key=lambda r:(r['outcome_available_ts_ms'],r['exit_ts_ms'],r['symbol'],r['identity'],r['signal_ts_ms']))
    nets=[r['gross_bps']-mult*r['cost_bps'] for r in rows]
    gains=math.fsum(x for x in nets if x>0);loss=-math.fsum(x for x in nets if x<0)
    groups=defaultdict(float);streak=longest=0
    for r,n in zip(rows,nets):
        groups[r['outcome_available_ts_ms']]+=n;streak=streak+1 if n<0 else 0;longest=max(longest,streak)
    nav=peak=dd=0
    for t in sorted(groups):nav+=groups[t];peak=max(peak,nav);dd=max(dd,peak-nav)
    return {'T':len(nets),'WR_pct':100*sum(n>0 for n in nets)/len(nets) if nets else None,
            'Gross_bps':math.fsum(r['gross_bps'] for r in rows),'Cost_bps':math.fsum(mult*r['cost_bps'] for r in rows),
            'Net_bps':math.fsum(nets),'NetExp_bps_T':math.fsum(nets)/len(nets) if nets else None,
            'PF':gains/loss if loss else None,'DD_bps':dd,'MaxLossStreak':longest}

def verify_event_clock(event):
    """Closed UTC 30m input; order at the FIRST minute strictly after receipt."""
    bar,ready,effective=(event[k] for k in ('bar_open_ms','input_ready_ms','order_effective_ms'))
    assert all(type(t) is int and t>=0 for t in (bar,ready,effective)), 'EVENT_INTEGER_CLOCK'
    assert bar%(30*60000)==0, 'EVENT_UTC_30M_BAR'
    assert ready>=bar+30*60000, 'EVENT_INCOMPLETE_30M_BAR'
    assert effective==(ready//60000+1)*60000, 'EVENT_NOT_FIRST_POST_RECEIPT_MINUTE'

def exit_evidence(parent,child):
    """Cross-index saved callbacks and exact fills; equal PnL is not parity."""
    parent_rows={key(r):r for r in parent['trades']}
    child_rows={key(r):r for r in child['trades']}
    assert len(parent_rows)==len(parent['trades']) and len(child_rows)==len(child['trades'])
    signals={f"{CHILD}|{s['symbol']}|{s['signal_ts_ms']}":key(s) for s in child['signals']}
    assert len(signals)==len(child['signals'])
    linked=defaultdict(list)
    failure_reason='SQUEEZE_OBSERVED_NONPOSITIVE_MOMENTUM_NEXT_OPEN'
    for event in child['events']:
        assert event['signal_key'] in signals,'UNKNOWN_EVENT_SIGNAL'
        if event['update'].get('reason')!=failure_reason:continue
        k=signals[event['signal_key']]
        assert k in child_rows,'FAILURE_EVENT_WITHOUT_COMPLETED_TRADE'
        trade=child_rows[k]
        assert trade['reason']==failure_reason,'FAILURE_EVENT_TRADE_REASON'
        assert event['update'].get('exit_next_open') is True,'FAILURE_EVENT_NOT_EXIT'
        assert event['order_effective_ms']==trade['exit_ts_ms'],'FAILURE_EVENT_EXIT_TIME'
        assert trade['entry_ts_ms']<=event['bar_open_ms']<event['input_ready_ms']<event['order_effective_ms'],'FAILURE_EVENT_CHRONOLOGY'
        verify_event_clock(event)
        momentum=event['update']['observed_momentum']
        assert math.isfinite(momentum) and momentum<=0,'FAILURE_EVENT_MOMENTUM'
        linked[k].append(event)
    links=[]
    for k,trade in child_rows.items():
        if trade['reason']==failure_reason:
            assert len(linked[k])==1,'FAILURE_TRADE_REQUIRES_ONE_EVENT'
            event=linked[k][0]
            links.append({'key':list(k),'event_signal_key':event['signal_key'],
                          'input_ready_ms':event['input_ready_ms'],
                          'order_effective_ms':event['order_effective_ms'],
                          'trade_exit_ts_ms':trade['exit_ts_ms'],'trade_exit_prices':trade['exit_prices'],
                          'reason':trade['reason'],'observed_momentum':event['update']['observed_momentum']})
        else:assert not linked[k],'FAILURE_EVENT_LINKED_TO_OTHER_EXIT'
    fields=('side','entry_ts_ms','exit_ts_ms','outcome_available_ts_ms','entry_prices','exit_prices',
            'reason','gross_bps','cost_bps','net_bps','signal_available_ms')
    compared=[]
    for k in sorted(parent_rows.keys()&child_rows.keys()):
        p,c=parent_rows[k],child_rows[k]
        different=[name for name in fields if p[name]!=c[name]]
        compared.append({'key':list(k),'identical_trade_evidence':not different,
                         'different_fields':different,
                         'equal_net_different_evidence':abs(p['net_bps']-c['net_bps'])<=EPS and bool(different),
                         'parent_exit_ts_ms':p['exit_ts_ms'],'child_exit_ts_ms':c['exit_ts_ms'],
                         'parent_exit_prices':p['exit_prices'],'child_exit_prices':c['exit_prices'],
                         'parent_reason':p['reason'],'child_reason':c['reason']})
    return {'compared_fields':list(fields),'common_T':len(compared),
            'identical_trade_evidence_T':sum(r['identical_trade_evidence'] for r in compared),
            'changed_trade_evidence_T':sum(not r['identical_trade_evidence'] for r in compared),
            'equal_net_different_evidence_T':sum(r['equal_net_different_evidence'] for r in compared),
            'failure_trade_event_links':links,'rows':compared}

def audit(files,parent_files):
    original=parent_files[PARENT+'/RESULT.json'].encode();assert sha(original)==PARENT_SHA
    p=json.loads(original);raw=files[CHILD+'/RESULT.json'].encode();c=json.loads(raw)
    done=json.loads(files[CHILD+'/COMPLETED.json']);assert done['result_sha256']==sha(raw) and done['executions']==1
    s=json.loads(files['SUMMARY.json']);finish=json.loads(files['COMPLETED.json'])
    assert finish['summary_sha256']==sha(files['SUMMARY.json'].encode()) and finish['lane_executions']==1
    assert s['economic_lane_executions']==1 and s['parent_replays']==s['keltner_replays']==s['new_signal_generation_calls']==0
    assert not s['g5_promotion'] and not s['unused_oos_certified'] and not s['realtime_fill_certified'] and s['orders']==0
    assert s['account_nav'] is None and s['account_dd'] is None
    original_signals={key(r):r for r in p['signals']};assert len(original_signals)==15
    assert len(c['signals'])==15 and len(set(map(key,c['signals'])))==15
    for r in c['signals']:
        mapped=dict(r);assert mapped.pop('research_parent_identity')==PARENT and mapped['identity']==CHILD
        mapped['identity']=PARENT;assert mapped==original_signals[key(r)]
    assert len(c['signals'])==len(c['trades'])+len(c['unresolved'])+sum(c['rejections'].values())
    assert len(set(map(key,c['trades'])))==len(c['trades'])
    positions=defaultdict(list)
    for r in c['trades']:
        symbol=r['symbol'];assert r['identity']==CHILD and key(r) in original_signals
        close(r['side']*(r['exit_prices'][symbol]/r['entry_prices'][symbol]-1)*10000,r['gross_bps'])
        close(r['gross_bps']-r['cost_bps'],r['net_bps'])
        close(r['cost_bps'],original_signals[key(r)]['meta']['frozen_cost_bps'])
        assert r['signal_available_ms']<r['entry_ts_ms']<=r['exit_ts_ms']<=r['outcome_available_ts_ms']
        assert r['entry_ts_ms']%60000==0 and r['order_authority']=='BLOCKED' and r['fill_is_model_not_exchange']
        positions[symbol].append(r)
    for rs in positions.values():
        rs.sort(key=lambda r:r['entry_ts_ms'])
        assert all(a['outcome_available_ts_ms']<b['entry_ts_ms'] for a,b in zip(rs,rs[1:])), 'OVERLAP'
    failure_events=[]
    for e in c['events']:
        verify_event_clock(e)
        if e['update'].get('reason')=='SQUEEZE_OBSERVED_NONPOSITIVE_MOMENTUM_NEXT_OPEN':
            assert math.isfinite(e['update']['observed_momentum']) and e['update']['observed_momentum']<=0
            assert e['update']['exit_next_open'];failure_events.append(e)
    output={'status':'PASS_SAVED_ACCOUNTING','new_economic_calls':0,'parent_result_sha256':PARENT_SHA,
            'child_result_sha256':sha(raw),'summary_sha256':sha(files['SUMMARY.json'].encode()),
            'signals':len(c['signals']),'completed':len(c['trades']),'unresolved':len(c['unresolved']),
            'rejections':c['rejections'],'failure_exit_events':len(failure_events),'metrics':{},'paired':{},
            'exit_evidence':exit_evidence(p,c)}
    pr={key(r):r for r in scored(p['trades'])};cr={key(r):r for r in scored(c['trades'])};common=sorted(pr.keys()&cr.keys())
    for mult in (1,2):
        label=str(mult)+'x';pm=metrics(p['trades'],mult);cm=metrics(c['trades'],mult)
        for name,values in (('parent',pm),('child',cm)):
            for k,v in values.items():close(v,s[name+'_reference'+label][k])
        for k,v in cm.items():close(v,c['reference'+label][k])
        output['metrics'][label]={'parent':pm,'child':cm}
        net=lambda r:r['gross_bps']-mult*r['cost_bps']
        rows=[{'key':list(k),'parent_net_bps':net(pr[k]),'child_net_bps':net(cr[k]),'delta_bps':net(cr[k])-net(pr[k])} for k in common]
        delta=math.fsum(r['delta_bps'] for r in rows)
        extra=math.fsum(net(cr[k]) for k in cr.keys()-pr.keys());missing=-math.fsum(net(pr[k]) for k in pr.keys()-cr.keys())
        total=cm['Net_bps']-pm['Net_bps'];close(delta+extra+missing,total)
        check={'common_T':len(common),'child_only_T':len(cr.keys()-pr.keys()),'parent_only_T':len(pr.keys()-cr.keys()),
               'improved_T':sum(r['delta_bps']>EPS for r in rows),'harmed_T':sum(r['delta_bps']<-EPS for r in rows),
               'parent_winners_harmed_T':sum(r['parent_net_bps']>0 and r['delta_bps']<-EPS for r in rows),
               'parent_loss_change_bps':math.fsum(r['delta_bps'] for r in rows if r['parent_net_bps']<0),
               'parent_winner_change_bps':math.fsum(r['delta_bps'] for r in rows if r['parent_net_bps']>0),
               'common_delta_bps':delta,'new_opportunities_net_bps':extra,
               'missing_opportunities_contribution_bps':missing,'total_net_delta_bps':total}
        for k,v in check.items():close(v,c['paired'][label][k]);close(v,s['paired'][label][k])
        output['paired'][label]={**check,'rows':rows}
    return output

def main():
    if sys.flags.optimize:raise RuntimeError('ASSERTIONS_REQUIRED')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--parent-bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=audit(unpack(a.bundle,a.sha256),unpack(a.parent_bundle,BUNDLE_SHA))
    with a.output.open('x') as f:json.dump(report,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k!='paired'},indent=2))

if __name__=='__main__':main()
