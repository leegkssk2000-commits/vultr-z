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

def _trades():
    out=[]
    for symbol in econ.SYMBOLS:
        rs=econ.bars(symbol,'1d'); eng=econ.Expr(rs,{}); i=30
        while i<len(rs)-1:
            try: fire=bool(eng.eval(ENTRY_RULE,i))
            except Exception: fire=False
            if not fire: i+=1; continue
            side=econ._side(SIDE_RULE,eng,i); ei=i+1; xi=min(ei+HOLD-1,len(rs)-1); ep=rs[ei]['open']
            gross,lock_exit_day,activation_day=_lock_outcome(rs,side,ei,xi,ep)
            prev=rs[i-1]['close']; ret=rs[i]['close']/prev-1 if prev else 0.0
            w=[x['close'] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w)
            out.append({"symbol":symbol,"side":side,"gross_bps":gross,"signal_year":datetime.fromtimestamp(rs[i]['ts']/1000,tz=timezone.utc).year,"signal_regime50":"above_sma50" if rs[i]['close']>=sma50 else "below_sma50","activation_day":activation_day,"lock_exit_day":lock_exit_day})
            i=max(i+1,xi+1)
    return out

def _group(rows,key,cost=14.0):
    d={}
    for r in rows: d.setdefault(str(r[key]),[]).append(r)
    return {k:_metrics([x['gross_bps'] for x in v],cost) for k,v in sorted(d.items())}

def run(output:Path):
    trades=_trades(); base=_metrics([t['gross_bps'] for t in trades],14.0)
    for k,v in EXPECTED.items():
        if k=='trades':
            if int(base[k])!=v: raise RuntimeError(f'PROMOTED_INCUMBENT_MISMATCH:{k}')
        elif abs(float(base[k])-float(v))>1e-6: raise RuntimeError(f'PROMOTED_INCUMBENT_MISMATCH:{k}:{base[k]}:{v}')
    costs={str(c):_metrics([t['gross_bps'] for t in trades],float(c)) for c in (14,20,28,40)}
    by_symbol=_group(trades,'symbol'); by_side=_group(trades,'side'); by_year=_group(trades,'signal_year'); by_regime=_group(trades,'signal_regime50')
    flipped=_metrics([-t['gross_bps'] for t in trades],14.0)
    losses=sorted([t for t in trades if t['gross_bps']-14<0],key=lambda x:x['gross_bps']-14)
    total_loss=-sum(t['gross_bps']-14 for t in losses); top10=-sum(t['gross_bps']-14 for t in losses[:10])
    summary={
      "robust_cost_28":costs['28']['net_expectancy_bps']>0 and costs['28']['profit_factor']>1,
      "robust_cost_40":costs['40']['net_expectancy_bps']>0 and costs['40']['profit_factor']>1,
      "both_symbols_positive":all(x['net_expectancy_bps']>0 and x['profit_factor']>1 for x in by_symbol.values()),
      "negative_control_ok":flipped['net_expectancy_bps']<0 and flipped['profit_factor']<1,
      "year_positive_count":sum(1 for x in by_year.values() if x['net_expectancy_bps']>0 and x['profit_factor']>1),
      "year_total":len(by_year),
      "all_hardening_pass":False
    }
    summary['all_hardening_pass']=bool(summary['robust_cost_28'] and summary['robust_cost_40'] and summary['both_symbols_positive'] and summary['negative_control_ok'])
    result={"schema_version":"zel.a1_gen2_profit_lock_incumbent_hardening.v1","development_only":True,"candidate_id":"repair_short_above_sma50_veto_plus_mfe300_net_be_lock_v1","promoted_from":"repair_short_above_sma50_veto_v1","mechanism":{"entry_rule":ENTRY_RULE,"side_rule":SIDE_RULE,"time_stop_bars":HOLD,"profit_lock_activation_bps":ACTIVATE_BPS,"profit_lock_gross_bps":LOCK_GROSS_BPS,"path_preserved_by_original_12d_slot_cooldown":True,"same_bar_activation_and_stop_forbidden_conservative":True,"gap_model":"worse_of_lock_or_next_bar_open"},"incumbent_metrics":base,"cost_stress":costs,"by_symbol":by_symbol,"by_side":by_side,"by_year":by_year,"by_regime50":by_regime,"negative_controls":{"side_flip_same_events":flipped},"loss_concentration":{"loss_trade_count":len(losses),"total_loss_bps":total_loss,"top10_loss_bps":top10,"top10_share_of_loss":top10/total_loss if total_loss else 0.0},"lock_usage":{"activated_trades":sum(t['activation_day'] is not None for t in trades),"lock_exit_trades":sum(t['lock_exit_day'] is not None for t in trades)},"hardening_summary":summary,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0}
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('PROFIT_LOCK_INCUMBENT_HARDENING='+json.dumps(result,sort_keys=True)); return result

if __name__=='__main__': run(Path('out/a1_gen2_incumbent_hardening_v1.json'))
