#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

ENTRY_RULE="ret(1) < -0.02 or (ret(1) > 0.02 and close < sma('close',50))"
SIDE_RULE="long if ret(1) < -0.02 else short"
HOLD=12; ACTIVATE_BPS=300.0; LOCK_GROSS_BPS=14.0
EARLY_DAYS=2; EARLY_MAE_BPS=300.0; EARLY_MFE_FLOOR_BPS=100.0
EXPECTED={"trades":227,"net_pnl_bps":32456.553693428767,"net_expectancy_bps":142.98041274638223,"profit_factor":1.7661077778815002,"drawdown_bps":3222.578836366174}

def _metrics(net):
    n=len(net)
    return {"trades":n,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}

def _gross(side,ep,px):
    return (px/ep-1)*10000 if side=='long' else (1-px/ep)*10000

def _trades():
    out=[]
    for symbol in econ.SYMBOLS:
        rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
        while i<len(rs)-1:
            try: fire=bool(eng.eval(ENTRY_RULE,i))
            except Exception: fire=False
            if not fire: i+=1; continue
            side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']
            activated=False; base_gross=None
            for j in range(ei,xi+1):
                if activated:
                    floor=ep*(1+LOCK_GROSS_BPS/10000) if side=='long' else ep*(1-LOCK_GROSS_BPS/10000)
                    if side=='long' and rs[j]['low']<=floor:
                        base_gross=_gross(side,ep,min(floor,rs[j]['open'])); break
                    if side=='short' and rs[j]['high']>=floor:
                        base_gross=_gross(side,ep,max(floor,rs[j]['open'])); break
                fav=(rs[j]['high']/ep-1)*10000 if side=='long' else (1-rs[j]['low']/ep)*10000
                if fav>=ACTIVATE_BPS: activated=True
            if base_gross is None: base_gross=_gross(side,ep,rs[xi]['close'])
            e2=min(ei+EARLY_DAYS-1,xi)
            highs=[rs[j]['high'] for j in range(ei,e2+1)]; lows=[rs[j]['low'] for j in range(ei,e2+1)]
            early_mfe=(max(highs)/ep-1)*10000 if side=='long' else (1-min(lows)/ep)*10000
            early_mae=(min(lows)/ep-1)*10000 if side=='long' else (1-max(highs)/ep)*10000
            trigger=(early_mae<=-EARLY_MAE_BPS and early_mfe<EARLY_MFE_FLOOR_BPS)
            early_gross=_gross(side,ep,rs[e2]['close']) if trigger else base_gross
            out.append({"symbol":symbol,"side":side,"base_net_bps":base_gross-14.0,"candidate_net_bps":early_gross-14.0,"early_mfe_bps":early_mfe,"early_mae_bps":early_mae,"trigger":trigger})
            i=max(i+1,xi+1)
    return out

def _pareto(a,b):
    return b['net_pnl_bps']>a['net_pnl_bps'] and b['net_expectancy_bps']>a['net_expectancy_bps'] and b['profit_factor']>a['profit_factor'] and b['drawdown_bps']<a['drawdown_bps']

def run(output:Path):
    t=_trades(); base=_metrics([x['base_net_bps'] for x in t]); cand=_metrics([x['candidate_net_bps'] for x in t])
    for k,v in EXPECTED.items():
        if k=='trades': assert base[k]==v,(k,base[k],v)
        else: assert abs(base[k]-v)<1e-6,(k,base[k],v)
    trig=[x for x in t if x['trigger']]
    accepted=_pareto(base,cand)
    r={"schema_version":"zel.a1_gen2_early_path_tail_loser_screen.v1","development_only":True,"incumbent_metrics":base,"axis":{"name":"day2_early_adverse_300bps_without_100bps_recovery_exit_original_slot_preserved","future_information_used":False,"early_days":EARLY_DAYS,"early_mae_trigger_bps":-EARLY_MAE_BPS,"early_mfe_ceiling_bps":EARLY_MFE_FLOOR_BPS,"threshold_sweep":False,"signal_rule_changed":False,"profit_lock_changed":False,"original_12d_entry_slot_preserved":True,"trigger_trade_count":len(trig),"trigger_base_net_bps":sum(x['base_net_bps'] for x in trig),"trigger_candidate_net_bps":sum(x['candidate_net_bps'] for x in trig),"rescued_losers":sum(1 for x in trig if x['base_net_bps']<0 and x['candidate_net_bps']>x['base_net_bps']),"clipped_winners":sum(1 for x in trig if x['base_net_bps']>0 and x['candidate_net_bps']<x['base_net_bps']),"new_metrics":cand,"accepted_pareto":accepted,"state":"PASS_PARETO_IMPROVEMENT" if accepted else "SEALED_FAIL_NO_REUSE"},"side_parity_role":"advisory_only","selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n'); print('EARLY_PATH_TAIL_LOSER_SCREEN='+json.dumps(r,sort_keys=True)); return r
if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
