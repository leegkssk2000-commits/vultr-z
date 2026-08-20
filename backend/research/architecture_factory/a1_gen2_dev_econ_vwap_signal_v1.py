#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

KLINE_API='https://open-api.bingx.com/openApi/swap/v3/quote/klines'
BOUNDARY='2026-08-16T18:45:01Z'
SYMBOLS=('BTC-USDT','ETH-USDT')
INTERVAL='15m'
COST_BPS=14.0
MAX_HOLD_BARS=12


def req(params):
    with urllib.request.urlopen(KLINE_API+'?'+urllib.parse.urlencode(params), timeout=30) as r:
        x=json.loads(r.read().decode())
    if isinstance(x,dict) and x.get('code') not in (None,0):
        raise RuntimeError(f"BINGX:{x.get('code')}:{x.get('msg')}")
    return x


def bars(symbol):
    x=req({'symbol':symbol,'interval':INTERVAL,'limit':1000})
    rows=x.get('data',x if isinstance(x,list) else [])
    out=[]
    for r in rows:
        if isinstance(r,dict):
            ts=int(r.get('time') or r.get('openTime') or r.get('timestamp'))
            out.append({'ts':ts,'open':float(r['open']),'high':float(r['high']),'low':float(r['low']),
                        'close':float(r['close']),'volume':float(r.get('volume') or r.get('vol') or 0)})
        else:
            out.append({'ts':int(r[0]),'open':float(r[1]),'high':float(r[2]),'low':float(r[3]),
                        'close':float(r[4]),'volume':float(r[5] if len(r)>5 else 0)})
    cutoff=int(datetime.fromisoformat(BOUNDARY.replace('Z','+00:00')).timestamp()*1000)
    return sorted([r for r in out if r['ts'] < cutoff], key=lambda z:z['ts'])


def enrich(rs):
    day_num=defaultdict(float); day_den=defaultdict(float)
    vols=[]; out=[]
    for r in rs:
        d=datetime.fromtimestamp(r['ts']/1000,tz=timezone.utc).date().isoformat()
        tp=(r['high']+r['low']+r['close'])/3.0
        day_num[d]+=tp*r['volume']; day_den[d]+=r['volume']
        vwap=day_num[d]/day_den[d] if day_den[d] else r['close']
        vols.append(r['volume'])
        vsma=sum(vols[-20:])/len(vols[-20:])
        out.append({**r,'vwap':vwap,'vol_sma20':vsma})
    return out


def evaluate_symbol(symbol):
    rs=enrich(bars(symbol)); trades=[]; i=21
    while i < len(rs)-1:
        p,r=rs[i-1],rs[i]
        side=None
        if r['close']>r['vwap'] and p['close']<=p['vwap'] and r['volume']>r['vol_sma20']: side='long'
        elif r['close']<r['vwap'] and p['close']>=p['vwap'] and r['volume']>r['vol_sma20']: side='short'
        if not side:
            i+=1; continue
        entry_i=i+1; entry=rs[entry_i]['open']; exit_i=min(entry_i+MAX_HOLD_BARS-1,len(rs)-1)
        for j in range(entry_i, min(entry_i+MAX_HOLD_BARS,len(rs))):
            x=rs[j]
            if (side=='long' and x['close']<x['vwap']) or (side=='short' and x['close']>x['vwap']):
                exit_i=j; break
        exit_=rs[exit_i]['close']
        gross=((exit_/entry)-1.0)*10000*(1 if side=='long' else -1)
        trades.append({'symbol':symbol,'entry_ts':rs[entry_i]['ts'],'exit_ts':rs[exit_i]['ts'],'side':side,
                       'gross_bps':gross,'cost_bps':COST_BPS,'net_bps':gross-COST_BPS,'hold_bars':exit_i-entry_i+1})
        i=max(i+1,exit_i+1)
    return trades,len(rs)


def pf(xs):
    gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0)
    return None if gl<=0 else gp/gl

def payoff(xs):
    w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]
    return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))
def dd(xs):
    eq=peak=mx=0.0
    for x in xs:
        eq+=x; peak=max(peak,eq); mx=max(mx,peak-eq)
    return mx


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='out/a1_gen2_dev_econ_vwap_signal_v1.json'); args=ap.parse_args()
    alltr=[]; src={}
    for s in SYMBOLS:
        t,n=evaluate_symbol(s); alltr+=t; src[s]={'bars':n,'trades':len(t)}
    gross=[t['gross_bps'] for t in alltr]; net=[t['net_bps'] for t in alltr]
    new={'trades':len(net),'gross_expectancy_bps':sum(gross)/len(gross) if gross else None,
         'net_expectancy_bps':sum(net)/len(net) if net else None,'net_pnl_bps':sum(net),
         'profit_factor':pf(net),'payoff':payoff(net),'win_rate':sum(1 for x in net if x>0)/len(net) if net else None,
         'drawdown_bps':dd(net) if net else 0.0,'cost_bps_per_trade':COST_BPS}
    economic_pass=bool(len(net)>=12 and (new['net_expectancy_bps'] or 0)>0 and (new['profit_factor'] or 0)>1.0)
    r={'schema_version':'zel.a1_gen2_dev_econ.vwap_signal.v1','candidate_id':'repair_axis_signal_source_vwap',
       'source_strategy_id':'anchor_vwap_trend','development_only':True,'prospective':False,'heavy':False,
       'uses_data_strictly_before_gen1_boundary':True,'gen1_boundary_utc':BOUNDARY,
       'old':{'trades':0,'net_pnl_bps':0.0,'status':'A1_SPARSE_EVENT_FUTILITY'},'new':new,
       'source_summary':src,'economic_pass':economic_pass,
       'event_spec':{'bar_interval':INTERVAL,'entry':'VWAP crossover + volume>SMA20; next-bar open','exit':'opposite VWAP cross or 12 bars','side':'both'},
       'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED',
       'live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0,'trades':alltr}
    body=dict(r); body.pop('trades',None); r['receipt_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    Path(args.out).parent.mkdir(parents=True,exist_ok=True); Path(args.out).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'trades':new['trades'],'gross_exp':new['gross_expectancy_bps'],'net_exp':new['net_expectancy_bps'],
                      'net_pnl':new['net_pnl_bps'],'pf':new['profit_factor'],'payoff':new['payoff'],'wr':new['win_rate'],
                      'dd':new['drawdown_bps'],'economic_pass':economic_pass},sort_keys=True))

if __name__=='__main__': main()
