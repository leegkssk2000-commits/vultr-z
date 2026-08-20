#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12
ACTIVATE_BPS=300.0
LOCK_GROSS_BPS=14.0
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(gross,cost=14.0):
    net=[float(x)-cost for x in gross]; n=len(net)
    return {"trades":n,"cost_bps_per_trade":cost,"gross_expectancy_bps":sum(gross)/n if n else None,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

def _lock_outcome(rs,side,ei,xi,ep):
    activated=False; activation_day=None
    lock_px=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
    for d,j in enumerate(range(ei,xi+1),start=1):
        if activated:
            if side=='long' and rs[j]['low']<=lock_px:
                px=min(lock_px,rs[j]['open']); return (px/ep-1)*10000,d,activation_day
            if side=='short' and rs[j]['high']>=lock_px:
                px=max(lock_px,rs[j]['open']); return (1-px/ep)*10000,d,activation_day
        fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
        if not activated and fav>=ACTIVATE_BPS:
            activated=True; activation_day=d
    xp=rs[xi]['close']
    return (xp/ep-1)*10000*(1 if side=='long' else -1),None,activation_day

def _rejection_ok(r,side):
    o=float(r['open']); c=float(r['close']); h=float(r['high']); l=float(r['low'])
    body=abs(c-o)
    lower=max(0.0,min(o,c)-l)
    upper=max(0.0,h-max(o,c))
    return lower>=body if side=='long' else upper>=body

def _trades(rejection_confirm=False):
    out=[]
    for symbol in econ.SYMBOLS:
        rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
        while i<len(rs)-1:
            try: fire=bool(eng.eval(ENTRY_RULE,i))
            except Exception: fire=False
            if not fire: i+=1; continue
            side=econ._side(SIDE_RULE,eng,i)
            if rejection_confirm and not _rejection_ok(rs[i],side):
                i+=1; continue
            ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']
            gross,lock_exit_day,activation_day=_lock_outcome(rs,side,ei,xi,ep)
            w=[x['close'] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w)
            out.append({"symbol":symbol,"side":side,"gross_bps":gross,"signal_year":datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year,"signal_regime50":"above_sma50" if rs[i]['close']>=sma50 else "below_sma50","activation_day":activation_day,"lock_exit_day":lock_exit_day})
            i=max(i+1,xi+1)
    return out

def _group(rows,key,cost=14.0):
    d={}
    for r in rows: d.setdefault(str(r[key]),[]).append(r)
    return {k:_metrics([x['gross_bps'] for x in v],cost) for k,v in sorted(d.items())}

def _pareto(a,b):
    return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
    trades=_trades(False); base=_metrics([t['gross_bps'] for t in trades],14.0)
    for k,v in EXPECTED.items():
        if k=='trades':
            if int(base[k])!=v: raise RuntimeError(f'PROMOTED_INCUMBENT_MISMATCH:{k}')
        elif abs(float(base[k])-float(v))>1e-6: raise RuntimeError(f'PROMOTED_INCUMBENT_MISMATCH:{k}:{base[k]}:{v}')
    candidate_trades=_trades(True); cand=_metrics([t['gross_bps'] for t in candidate_trades],14.0)
    cand_costs={str(c):_metrics([t['gross_bps'] for t in candidate_trades],float(c)) for c in (14,28,40)}
    cand_symbols=_group(candidate_trades,'symbol'); cand_years=_group(candidate_trades,'signal_year')
    cand_flip=_metrics([-t['gross_bps'] for t in candidate_trades],14.0)
    accepted=_pareto(base,cand)
    result={
      "schema_version":"zel.a1_gen2_independent_axis_candle_rejection.v1",
      "development_only":True,
      "incumbent_id":"repair_short_above_sma50_veto_plus_mfe300_net_be_lock_v1",
      "incumbent_metrics":base,
      "independent_axis":{
        "axis":"shock_day_directional_rejection_wick_ge_real_body_only",
        "threshold_sweep":False,
        "profit_lock_unchanged":True,
        "holding_horizon_unchanged":True,
        "short_sma50_veto_unchanged":True,
        "new_metrics":cand,
        "cost_stress":cand_costs,
        "by_symbol":cand_symbols,
        "by_year":cand_years,
        "negative_control_side_flip":cand_flip,
        "accepted_pareto":accepted,
        "state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"
      },
      "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0
    }
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('INDEPENDENT_CANDLE_REJECTION_AXIS='+json.dumps(result,sort_keys=True)); return result

if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
