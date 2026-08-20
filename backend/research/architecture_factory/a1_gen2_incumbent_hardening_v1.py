#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0
ATR_N=14; ATR_MULT=1.0
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
    n=len(net)
    return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

def _gross(side,ep,px):
    return (px/ep-1)*10000 if side=='long' else (1-px/ep)*10000

def _atr(rs,i,n=14):
    trs=[]
    for j in range(i-n+1,i+1):
        pc=rs[j-1]['close']
        trs.append(max(rs[j]['high']-rs[j]['low'],abs(rs[j]['high']-pc),abs(rs[j]['low']-pc)))
    return sum(trs)/len(trs)

def _trades():
    out=[]
    for symbol in econ.SYMBOLS:
        rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
        while i<len(rs)-1:
            try: fire=bool(eng.eval(ENTRY_RULE,i))
            except Exception: fire=False
            if not fire: i+=1; continue
            side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']
            activated=False; gross=None
            for j in range(ei,xi+1):
                if activated:
                    floor=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
                    if side=='long' and rs[j]['low']<=floor:
                        gross=_gross(side,ep,min(floor,rs[j]['open'])); break
                    if side=='short' and rs[j]['high']>=floor:
                        gross=_gross(side,ep,max(floor,rs[j]['open'])); break
                fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
                if fav>=ACTIVATE_BPS: activated=True
            if gross is None: gross=_gross(side,ep,rs[xi]['close'])
            atr=_atr(rs,i,ATR_N); shock=abs(rs[i]['close']-rs[i-1]['close']); keep=shock>=ATR_MULT*atr
            out.append({"symbol":symbol,"side":side,"net_bps":gross-14.0,"keep":keep,"shock_atr":shock/atr if atr else None})
            i=max(i+1,xi+1)
    return out

def _pareto(a,b):
    return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
    t=_trades(); base=_metrics([x['net_bps'] for x in t]); kept=[x for x in t if x['keep']]; cand=_metrics([x['net_bps'] for x in kept])
    for k,v in EXPECTED.items():
        if k=='trades': assert base[k]==v,(k,base[k],v)
        else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
    removed=[x for x in t if not x['keep']]; accepted=_pareto(base,cand)
    r={"schema_version":"zel.a1_gen2_atr_normalized_shock_gate.v1","development_only":True,"incumbent_metrics":base,"axis":{"name":"fixed_2pct_signal_plus_signal_bar_abs_shock_at_least_1x_atr14","future_information_used":False,"atr_period":ATR_N,"atr_multiple":ATR_MULT,"threshold_sweep":False,"profit_lock_changed":False,"holding_slot_logic_changed":False,"kept_trade_count":len(kept),"removed_trade_count":len(removed),"removed_net_bps":sum(x['net_bps'] for x in removed),"removed_winners":sum(1 for x in removed if x['net_bps']>0),"removed_losers":sum(1 for x in removed if x['net_bps']<0),"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"side_parity_role":"advisory_only","selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('ATR_NORMALIZED_SHOCK_GATE='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
