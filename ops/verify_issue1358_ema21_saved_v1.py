"""Independent saved-result audit; stdlib only, no economic model imports.

Checks the recorded order census against the pinned raw minutes, verifies
adverse touch/gap accounting, and independently recomputes new-trade metrics.
It never generates setups, replays a strategy or re-evaluates the old parent.
"""
import argparse
import base64
import csv
import io
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import lzma
import math
from pathlib import Path
import sys

CHILD='scalp7_squeeze_release_ema21_limit_utc30m_v1'
PARENT='scalp7_squeeze_panic_cost4_parent_utc30m_v2'
START=1789502400000
END=1791075300000
M=60000
TF=1800000
PRICE_SHA='3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3'
BUNDLE_SHA='d8e64b248d25a66ccdd44e403da82284ec7f5f49fcf9ebd5be68e9876c1d6ed1'
PARENT_SHA='a390f985245f32d52681fea688617d01fb6eb597b1269f10a62466075a9edbc9'
EPS=1e-7


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def close(a,b):
    if a is None or b is None:
        assert a is b,(a,b)
    else:
        assert math.isfinite(float(a)) and math.isclose(a,b,abs_tol=EPS,rel_tol=1e-10),(a,b)


def key(row):
    return row['symbol'],row['side'],row['signal_ts_ms']


def metrics(rows,mult):
    selected=[r for r in rows if START<=r['signal_ts_ms']<END and r['outcome_available_ts_ms']<END]
    selected.sort(key=lambda r:(r['outcome_available_ts_ms'],r['exit_ts_ms'],r['symbol'],r['identity'],r['signal_ts_ms']))
    nets=[r['gross_bps']-mult*r['cost_bps'] for r in selected]
    gains=math.fsum(x for x in nets if x>0)
    loss=-math.fsum(x for x in nets if x<0)
    groups=defaultdict(float)
    streak=longest=0
    for row,n in zip(selected,nets):
        groups[row['outcome_available_ts_ms']]+=n
        streak=streak+1 if n<0 else 0
        longest=max(longest,streak)
    equity=peak=dd=0
    for stamp in sorted(groups):
        equity+=groups[stamp]
        peak=max(peak,equity)
        dd=max(dd,peak-equity)
    return dict(T=len(nets),WR_pct=100*sum(n>0 for n in nets)/len(nets) if nets else None,
                Gross_bps=math.fsum(r['gross_bps'] for r in selected),
                Cost_bps=math.fsum(mult*r['cost_bps'] for r in selected),Net_bps=math.fsum(nets),
                NetExp_bps_T=math.fsum(nets)/len(nets) if nets else None,
                PF=gains/loss if loss else None,DD_bps=dd,MaxLossStreak=longest)


def receipt_clock(data):
    # Independently aggregate receipt times only, not strategy features/signals.
    per={}
    for symbol,rows in data['minutes'].items():
        groups=defaultdict(list)
        for row in rows:
            groups[row[0]//TF*TF].append(row)
        per[symbol]={t:max(r[6] for r in rs) for t,rs in groups.items()
                     if len(rs)==30 and rs[0][0]==t and rs[-1][0]+M==t+TF}
    grid=sorted(next(iter(per.values())))
    assert all(sorted(v)==grid for v in per.values()),'ALL_SIX_GRID'
    out={};latest=0
    for t in grid:
        latest=max(latest,max(values[t] for values in per.values()))
        out[t]=latest
    return out


def raw_bars(data,symbol):
    """Only saved position management is audited; no setup stream generated."""
    bars=[]
    if symbol in data.get('context',{}):
        seed=data['context'][symbol]
        raw=base64.b64decode(seed['gzip_base64'],validate=True)
        assert sha(raw)==seed['sha256'],'SEED_HASH'
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            body=gz.read(4*1024*1024+1)
        assert len(body)<=4*1024*1024
        for r in csv.DictReader(io.StringIO(body.decode())):
            bars.append(dict(open_ts_ms=int(r['open_ts_ms']),high=float(r['high']),low=float(r['low']),close=float(r['close'])))
    groups=defaultdict(list)
    for r in data['minutes'][symbol]:groups[r[0]//TF*TF].append(r)
    for t,rs in sorted(groups.items()):
        if len(rs)==30 and rs[0][0]==t and rs[-1][0]+M==t+TF:
            bars.append(dict(open_ts_ms=t,high=max(float(r[2]) for r in rs),
                             low=min(float(r[3]) for r in rs),close=float(rs[-1][4])))
    assert all(bars[i]['open_ts_ms']+TF==bars[i+1]['open_ts_ms'] for i in range(len(bars)-1)),'BAR_GAP'
    return bars


def expected_update(history,entered):
    update=dict(exit_next_open=False,reason='POSITIVE_LIFECYCLE_HOLD')
    if len(history)<41 or history[-2]['open_ts_ms']<entered:return update
    x=history[-41:];delta=[]
    for i in range(19,41):
        part=x[i-19:i+1]
        mean=math.fsum(r['close'] for r in part)/20
        middle=(max(r['high'] for r in part)+min(r['low'] for r in part))/2
        delta.append(x[i]['close']-(middle+mean)/2)
    momenta=[]
    centered=[i-9.5 for i in range(20)];den=math.fsum(c*c for c in centered)
    for i in range(3):
        y=delta[i:i+20]
        momenta.append(math.fsum(y)/20+math.fsum(a*b for a,b in zip(y,centered))/den*9.5)
    if momenta[2]>0 and momenta[1]>0 and momenta[2]<momenta[1]<momenta[0]:
        update.update(exit_next_open=True,reason='SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN')
    return update


def terminal_path(s,fill,data,ready,trace):
    """Independent raw-path oracle for every exit or unresolved position."""
    assert s['identity']==PARENT and s['side']==1 and s['max_hold_bars']==11
    assert s['meta']['be_arm_r'] is None,'STATIC_NATIVE_STOP_PROFILE'
    symbol=s['symbol'];entered=fill['minute_open_ms'];stop=float(s['stop_price'])
    anchor=float(fill['price']);risk=anchor-stop
    assert risk>0,'AUDIT_RISK'
    bars=raw_bars(data,symbol)
    decisions=[((ready[b['open_ts_ms']]//M+1)*M,i) for i,b in enumerate(bars)
               if b['open_ts_ms']>=entered+M and b['open_ts_ms'] in ready]
    actual=[e for e in trace if e['kind']=='MANAGEMENT'];exits=[e for e in trace if e['kind']=='EXIT']
    raw=data['minutes'][symbol]
    offset=next(i for i,r in enumerate(raw) if r[0]==entered)
    di=hold=0;mfe=mae=0.0
    for mi,r in enumerate(raw):
        t=r[0]
        if t<entered:continue
        while di<len(decisions) and decisions[di][0]<=t:
            activation,i=decisions[di];b=bars[i]
            assert di<len(actual),'MISSING_MANAGEMENT_DECISION'
            e=actual[di];update=expected_update(bars[:i+1],entered)
            assert e['bar_open_ms']==b['open_ts_ms'] and e['input_ready_ms']==ready[b['open_ts_ms']]
            assert e['order_effective_ms']==activation and e['update']==update,'MANAGEMENT_RULE'
            known=[x for x in raw[offset+1:mi] if x[6]<activation]
            assert known,'NO_POST_FILL_RECEIVED_PREFIX'
            mfe=max(0.0,(max(float(x[2]) for x in known)-anchor)/risk)
            mae=max(0.0,(anchor-min(float(x[3]) for x in known))/risk)
            hold+=1;di+=1
            if update['exit_next_open'] or hold>=11:
                reason=update['reason'] if update['exit_next_open'] else 'MAX_HOLD_CLOCKED_OPEN'
                terminal=(float(r[1]),t,max(t,fill['witness_ms']),reason,hold,mfe,mae)
                assert di==len(actual),'POST_EXIT_MANAGEMENT'
                assert len(exits)==1,'EXIT_EVENT_COUNT'
                return terminal,exits[0]
        if float(r[3])<=stop:
            gap=float(r[1])<stop
            terminal=(float(r[1]) if gap else stop,t if gap else t+M,
                      max(t+M,r[6],fill['witness_ms']),
                      'ADVERSE_OPEN_GAP_STOP' if gap else 'MINUTE_ENTRY_STOP_FIRST',hold,mfe,mae)
            assert di==len(actual),'POST_EXIT_MANAGEMENT'
            assert len(exits)==1,'EXIT_EVENT_COUNT'
            return terminal,exits[0]
    assert di==len(actual) and not exits,'FABRICATED_TERMINAL_EVENT'
    return None,None,(hold,mfe,mae)


def audit(result,summary,data,parent,contract):
    assert result['identity']==CHILD and summary['identity']==CHILD
    assert summary['economic_lane_executions']==1 and summary['parent_replays']==0
    assert summary['order_authority']=='BLOCKED' and summary['live_orders']==0
    assert not summary['unused_oos_certified'] and not summary['g5_promotion']
    assert not summary['realtime_fill_certified'] and summary['account_nav'] is None
    assert result['signals']==parent['signals'],'UNCHANGED_SETUP_STREAM'
    signals={f"{CHILD}|{s['symbol']}|{s['signal_ts_ms']}":s for s in result['signals']}
    assert len(signals)==len(result['signals'])==len(result['census'])
    census={r['key']:r for r in result['census']}
    assert len(census)==len(signals) and set(census)==set(signals),'CENSUS_KEYS'
    assert Counter(c['status'] for c in census.values())==result['status_counts']
    rows={key(r):r for r in result['trades']}
    unresolved={key(r['signal']):r for r in result['unresolved']}
    assert len(rows)==len(result['trades']) and len(unresolved)==len(result['unresolved'])
    assert not rows.keys()&unresolved.keys()
    assert summary['signal_count']==len(signals),'SUMMARY_SIGNAL_COUNT'
    assert summary['trade_count']==len(rows),'SUMMARY_TRADE_COUNT'
    assert summary['unresolved_count']==len(unresolved),'SUMMARY_UNRESOLVED_COUNT'
    assert summary['status_counts']==result['status_counts'],'SUMMARY_STATUS_COUNTS'
    ready=receipt_clock(data)
    owned={};fills=0;nonfills=0
    ordered=sorted(census.values(),key=lambda c:(c['available_ms'],c['symbol']))
    for c in ordered:
        s=signals[c['key']];symbol=s['symbol']
        available=max(ready[s['signal_open_ts_ms']],s['signal_ts_ms'])
        effective=(available//M+1)*M
        expiry=s['signal_open_ts_ms']+2*TF
        assert c['available_ms']==available and c['evidence']=='MODELED_DEVELOPMENT_EVENTS'
        if effective<=owned.get(symbol,-1):
            assert c['status']=='REJECTED_OCCUPIED'
            continue
        assert c['status']!='REJECTED_OCCUPIED','SPURIOUS_OCCUPANCY'
        assert c['effective_ms']==effective and c['expires_ms']==expiry
        if effective>=expiry:
            assert c['status']=='REJECTED_STALE'
            continue
        anchor=float(s['stop_price'])+2*float(s['meta']['atr_price'])
        cost=contract['reference_costs_bps'][symbol]
        if float(s['meta']['atr_price'])/anchor*10000/cost<4:
            assert c['status']=='REJECTED_GATE'
            continue
        assert c['status'] not in ('REJECTED_STALE','REJECTED_GATE')
        candidates=[r for r in data['minutes'][symbol] if effective<=r[0]<expiry and float(r[3])<=anchor]
        if not candidates:
            expired=data['minutes'][symbol][-1][0]+M>=expiry
            assert c['status']==('EXPIRED_UNFILLED' if expired else 'PENDING_END')
            owned[symbol]=expiry-1 if expired else 2**63-1
            nonfills+=1
            continue
        first=candidates[0];fills+=1
        fill=c['order']['fill']
        assert fill['minute_open_ms']==first[0]
        close(fill['price'],anchor)
        assert fill['witness_ms']==max(first[0]+M,first[6])
        assert fill['price_semantics']=='ADVERSE_LIMIT_BOUND_NOT_OBSERVED_TRANSACTION'
        assert fill['intraminute_time_unknown'] is True
        k=key(s)
        path=terminal_path(s,fill,data,ready,[e for e in result['events'] if e['key']==c['key']])
        terminal,exit_event=path[:2]
        if c['status']=='FILLED_UNRESOLVED':
            assert terminal is None,'HIDDEN_TERMINAL_EVENT'
            assert k in unresolved
            hold,mfe,mae=path[2]
            position=unresolved[k]['position']
            assert position['hold_bars']==hold,'UNRESOLVED_HOLD_BARS'
            close(position['mfe_R'],mfe);close(position['mae_R'],mae)
            owned[symbol]=2**63-1
            continue
        assert c['status']=='FILLED_COMPLETED' and k in rows
        assert terminal is not None,'FABRICATED_COMPLETED_POSITION'
        r=rows[k]
        px,stamp,witness,reason,hold,mfe,mae=terminal
        close(r['exit_prices'][symbol],px)
        assert (r['exit_ts_ms'],r['outcome_available_ts_ms'],r['reason'],r['hold_bars'])==(stamp,witness,reason,hold),'TERMINAL_EVENT'
        close(r['mfe_R'],mfe);close(r['mae_R'],mae)
        assert (exit_event['at_ms'],exit_event['witness_ms'],exit_event['reason'])==(stamp,witness,reason),'EXIT_TRACE'
        assert r['identity']==CHILD and r['entry_ts_ms']==first[0]
        assert available<r['entry_ts_ms']<=r['exit_ts_ms']<=r['outcome_available_ts_ms']
        assert r['entry_model']==fill and r['order_authority']=='BLOCKED' and r['fill_is_model_not_exchange']
        close(r['entry_prices'][symbol],anchor)
        close(r['cost_bps'],cost)
        close((r['exit_prices'][symbol]/anchor-1)*10000,r['gross_bps'])
        close(r['gross_bps']-cost,r['net_bps'])
        owned[symbol]=r['outcome_available_ts_ms']
    assert fills==len(rows)+len(unresolved),'FILL_CENSUS'
    event_ids=set()
    for e in result['events']:
        assert e['key'] in signals and e['event_id'] not in event_ids
        event_ids.add(e['event_id'])
        assert e['evidence']=='MODELED_DEVELOPMENT_EVENTS'
        if e['kind']=='MANAGEMENT':
            s=signals[e['key']];r=rows.get(key(s)) or unresolved[key(s)]['position']
            assert e['bar_open_ms']>=r['entry_ts_ms']+M
            assert e['input_ready_ms']==ready[e['bar_open_ms']]
            assert e['order_effective_ms']==(e['input_ready_ms']//M+1)*M
    report=dict(status='PASS_SAVED_CENSUS_AND_ACCOUNTING',new_economic_executions=0,
                signals=len(signals),fills=fills,nonfills=nonfills,status_counts=result['status_counts'],
                completed=len(rows),unresolved=len(unresolved),metrics={},paired={},
                dd_semantics='EQUAL_NOTIONAL_OUTCOME_RECEIPT_COHORT_TRADE_BPS_NOT_ACCOUNT_NAV')
    p={key(r):r for r in parent['trades'] if START<=r['signal_ts_ms']<END and r['outcome_available_ts_ms']<END}
    c={k:r for k,r in rows.items() if START<=r['signal_ts_ms']<END and r['outcome_available_ts_ms']<END}
    for mult in (1,2):
        label=str(mult)+'x'
        new=metrics(result['trades'],mult)
        for name,value in new.items():
            close(value,result['reference'+label][name]);close(value,summary['reference'+label][name])
        # The old parent's already audited metric summary is reused, not rerun.
        old=parent['reference'+label]
        assert summary['baseline_reference'+label]==old
        net=lambda r:r['gross_bps']-mult*r['cost_bps']
        common=sorted(p.keys()&c.keys())
        differences=[net(c[k])-net(p[k]) for k in common]
        added=math.fsum(net(c[k]) for k in c.keys()-p.keys())
        missed=-math.fsum(net(p[k]) for k in p.keys()-c.keys())
        delta=new['Net_bps']-old['Net_bps']
        close(math.fsum(differences)+added+missed,delta)
        check=dict(common_T=len(common),child_only_T=len(c.keys()-p.keys()),parent_only_T=len(p.keys()-c.keys()),
                   harmed_T=sum(d<-EPS for d in differences),improved_T=sum(d>EPS for d in differences),
                   parent_winners_harmed_T=sum(net(p[k])>0 and net(c[k])-net(p[k])<-EPS for k in common),
                   common_delta_bps=math.fsum(differences),new_opportunities_net_bps=added,
                   missing_opportunities_contribution_bps=missed,total_net_delta_bps=delta)
        for name,value in check.items():
            close(value,result['paired'][label][name]);close(value,summary['paired'][label][name])
        report['metrics'][label]=new
        report['paired'][label]=check
    outstanding=bool(unresolved) or any(x['status']=='PENDING_END' for x in census.values())
    profitable=all(report['metrics'][l]['T']>0 and report['metrics'][l]['Net_bps']>0
                   and (report['metrics'][l]['PF'] or 0)>1 for l in ('1x','2x'))
    report['disposition']='HOLD_UNRESOLVED_EXPOSURE' if outstanding else ('DEVELOPMENT_SURVIVOR_NOT_G5' if profitable else 'REJECT_NOT_COST_PROFITABLE')
    return report


def main():
    if sys.flags.optimize:
        raise RuntimeError('ASSERTIONS_REQUIRED')
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('result-dir','input','contract','parent-bundle','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    compressed=a.input.read_bytes();assert len(compressed)<=32*1024*1024
    with gzip.GzipFile(fileobj=__import__('io').BytesIO(compressed)) as gz:
        body=gz.read(64*1024*1024+1)
    assert len(body)<=64*1024*1024 and sha(body)==PRICE_SHA
    data=json.loads(body);contract=json.loads(a.contract.read_bytes())
    raw=a.parent_bundle.read_bytes();assert sha(raw)==BUNDLE_SHA
    dec=lzma.LZMADecompressor(memlimit=256*1024*1024)
    unpacked=dec.decompress(raw,max_length=32*1024*1024+1)
    assert dec.eof and not dec.unused_data and len(unpacked)<=32*1024*1024
    files=json.loads(unpacked);original=files[PARENT+'/RESULT.json'].encode()
    assert sha(original)==PARENT_SHA
    parent=json.loads(original)
    result_raw=(a.result_dir/CHILD/'RESULT.json').read_bytes()
    summary_raw=(a.result_dir/'SUMMARY.json').read_bytes()
    done=json.loads((a.result_dir/'COMPLETED.json').read_bytes())
    reservation=json.loads((a.result_dir/'RESERVATION.json').read_bytes())
    assert done['summary_sha256']==sha(summary_raw) and done['lane_executions']==1
    assert done['claim_commit_sha']==reservation['claim_commit_sha']
    assert reservation['contract_sha256']==sha(a.contract.read_bytes())
    report=audit(json.loads(result_raw),json.loads(summary_raw),data,parent,contract)
    report.update(result_sha256=sha(result_raw),summary_sha256=sha(summary_raw),input_sha256=PRICE_SHA,
                  claim_commit_sha=reservation['claim_commit_sha'])
    with a.output.open('x') as f:
        json.dump(report,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    main()
