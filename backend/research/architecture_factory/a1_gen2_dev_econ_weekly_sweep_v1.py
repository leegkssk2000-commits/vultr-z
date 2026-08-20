#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math, urllib.parse, urllib.request, hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

KLINE_API='https://open-api.bingx.com/openApi/swap/v3/quote/klines'
FUNDING_API='https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate'
BOUNDARY='2026-08-16T18:45:01Z'
SYMBOLS=('BTC-USDT','ETH-USDT')
FEE_SPREAD_IMPACT_BPS=13.0
FUNDING_SETTLEMENTS_PER_WEEK=21


def req(url, params):
    with urllib.request.urlopen(url+'?'+urllib.parse.urlencode(params), timeout=30) as r:
        x=json.loads(r.read().decode())
    if isinstance(x,dict) and x.get('code') not in (None,0):
        raise RuntimeError(f"BINGX:{x.get('code')}:{x.get('msg')}")
    return x


def daily(symbol):
    x=req(KLINE_API,{'symbol':symbol,'interval':'1d','limit':1000})
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
    return sorted([r for r in out if r['ts'] < cutoff], key=lambda r:r['ts'])


def funding_p95(symbol):
    x=req(FUNDING_API,{'symbol':symbol,'limit':100})
    vals=[]
    for r in x.get('data',[]) if isinstance(x,dict) else []:
        try:
            vals.append(abs(float(r.get('fundingRate') or r.get('rate')))*10000)
        except Exception:
            pass
    if not vals:
        raise RuntimeError('FUNDING_EMPTY')
    vals.sort()
    idx=min(len(vals)-1,max(0,math.ceil(.95*len(vals))-1))
    return vals[idx]


def week_key(ts):
    d=datetime.fromtimestamp(ts/1000,tz=timezone.utc)
    iso=d.isocalendar()
    return (iso.year,iso.week)


def weekly(rows):
    buckets=defaultdict(list)
    for r in rows:
        buckets[week_key(r['ts'])].append(r)
    out=[]
    for k in sorted(buckets):
        rs=sorted(buckets[k],key=lambda x:x['ts'])
        out.append({'week':k,'ts':rs[0]['ts'],'open':rs[0]['open'],'high':max(x['high'] for x in rs),
                    'low':min(x['low'] for x in rs),'close':rs[-1]['close'],'volume':sum(x['volume'] for x in rs)})
    return out


def pf(xs):
    gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0)
    return None if gl<=0 else gp/gl


def payoff(xs):
    wins=[x for x in xs if x>0]; losses=[-x for x in xs if x<0]
    return None if not wins or not losses else (sum(wins)/len(wins))/(sum(losses)/len(losses))


def dd(xs):
    eq=peak=draw=0.0
    for x in xs:
        eq += x; peak=max(peak,eq); draw=max(draw,peak-eq)
    return draw


def evaluate_symbol(symbol):
    ws=weekly(daily(symbol))
    p95=funding_p95(symbol)
    cost=FEE_SPREAD_IMPACT_BPS + FUNDING_SETTLEMENTS_PER_WEEK*p95
    trades=[]
    for i in range(9,len(ws)-3):
        prior=ws[i-1]; br=ws[i]
        direction=None
        if br['close'] > prior['high']:
            direction='short'
        elif br['close'] < prior['low']:
            direction='long'
        if not direction:
            continue
        for j in (i+1,i+2):
            if j>=len(ws)-1:
                break
            r=ws[j]
            inside=prior['low'] < r['close'] < prior['high']
            hist=ws[max(0,j-8):j]
            avgvol=sum(x['volume'] for x in hist)/max(1,len(hist))
            if not (inside and r['volume'] > avgvol):
                continue
            entry=ws[j+1]['open']
            exit_=ws[j+1]['close']
            gross=((exit_/entry)-1)*10000*(1 if direction=='long' else -1)
            net=gross-cost
            trades.append({'symbol':symbol,'break_week':br['week'],'reclaim_week':r['week'],'side':direction,
                           'gross_bps':gross,'cost_bps':cost,'net_bps':net})
            break
    return trades,p95,cost,len(ws)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='a1_gen2_dev_econ_weekly_sweep_v1.json')
    args=ap.parse_args()
    alltr=[]; src={}
    for s in SYMBOLS:
        t,p,c,n=evaluate_symbol(s); alltr.extend(t); src[s]={'weekly_bars':n,'funding_p95_abs_bps':p,'weekly_cost_bps':c,'trades':len(t)}
    gross=[x['gross_bps'] for x in alltr]; net=[x['net_bps'] for x in alltr]
    result={
      'schema_version':'zel.a1_gen2_dev_econ.weekly_sweep.v1',
      'candidate_id':'REPAIR_3_horizon_to_weekly_sweep',
      'source_strategy_id':'session_bias',
      'development_only':True,
      'uses_data_strictly_before_gen1_boundary':True,
      'gen1_boundary_utc':BOUNDARY,
      'fresh_prospective_boundary_created':False,
      'heavy_gen2_launch_started':False,
      'old':{'trades':0,'net_pnl_bps':0.0,'net_expectancy_bps':None,'profit_factor':None,'payoff':None,'win_rate':None,'drawdown_bps':0.0,'status':'A1_SPARSE_EVENT_FUTILITY'},
      'new':{'trades':len(net),'gross_expectancy_bps':(sum(gross)/len(gross) if gross else None),
             'net_expectancy_bps':(sum(net)/len(net) if net else None),'net_pnl_bps':sum(net),
             'profit_factor':pf(net),'payoff':payoff(net),'win_rate':(sum(1 for x in net if x>0)/len(net) if net else None),
             'drawdown_bps':dd(net) if net else 0.0},
      'source_summary':src,
      'event_spec':{'range':'previous completed UTC ISO week','breach':'break week close outside prior range',
                    'reclaim':'close back inside prior range within next 2 weeks','volume':'reclaim weekly volume > trailing 8-week mean',
                    'entry':'next week open','exit':'same week close','direction':'opposite failed break'},
      'cost_model':'13bps fee+spread+impact floors + 21 * current public funding P95 absolute reserve',
      'trades':alltr,
      'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE',
      'order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0
    }
    result['economic_pass']=bool(len(net)>=12 and result['new']['net_expectancy_bps'] is not None and result['new']['net_expectancy_bps']>0 and (result['new']['profit_factor'] or 0)>=1)
    body=dict(result); body.pop('trades',None)
    result['receipt_sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    Path(args.out).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'trades':len(net),'net_pnl_bps':result['new']['net_pnl_bps'],'net_expectancy_bps':result['new']['net_expectancy_bps'],
                      'pf':result['new']['profit_factor'],'payoff':result['new']['payoff'],'wr':result['new']['win_rate'],
                      'dd':result['new']['drawdown_bps'],'economic_pass':result['economic_pass']},sort_keys=True))

if __name__=='__main__':
    main()
