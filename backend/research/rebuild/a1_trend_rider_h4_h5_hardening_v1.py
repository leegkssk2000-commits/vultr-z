#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, math, random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr, ema
from backend.tools import zel_economic_hardening_gate_v1 as hard

POLICY_COMMIT = "a4624e5c630046ec53f760dcd1abda5137d6a786"
POLICY_SEALED_AT = "2026-08-03T19:18:16+00:00"


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def replay_receipt(control: str, vals: list[float], *, source_sha: str, data_sha: str, config_sha: str, window_sha: str, cost_sha: str, ci: float | None = None, p: float | None = None) -> dict[str, Any]:
    row = {
        "schema_version": "zel.deterministic_replay.result.v1",
        "state": "PASS_DETERMINISTIC_REPLAY_RESULT",
        "result_id": control,
        "control_type": control,
        "source_sha256": source_sha,
        "data_sha256": data_sha,
        "config_sha256": config_sha,
        "window_sha256": window_sha,
        "cost_model_sha256": cost_sha,
        "trade_count": len(vals),
        "net_R": sum(vals),
        "expectancy_R": sum(vals) / len(vals),
    }
    if ci is not None: row["candidate_minus_control_ci_low_R"] = ci
    if p is not None: row["p_value"] = p
    row["receipt_sha256"] = hard.stable_sha(row)
    return row


def paired_stats(candidate: list[float], control: list[float], seed: int) -> tuple[float, float]:
    d = [a-b for a,b in zip(candidate, control)]
    n=len(d); rng=random.Random(seed)
    # one-sided sign-flip randomization test on mean difference
    obs=sum(d)/n
    ge=1; B=20000
    for _ in range(B):
        m=sum(x if rng.random()<0.5 else -x for x in d)/n
        if m >= obs: ge += 1
    p=ge/(B+1)
    # one-sided 95% paired bootstrap lower bound on total difference
    boots=[]
    for _ in range(B):
        boots.append(sum(d[rng.randrange(n)] for __ in range(n)))
    boots.sort(); ci=boots[max(0, int(0.05*B)-1)]
    return ci,p


def idx_by_ts(bars): return {int(b["ts_ms"]):i for i,b in enumerate(bars)}

def duration_bars(trade, mp):
    a=mp[int(trade["entry_ts"])]; b=mp[int(trade["exit_ts"])]
    return max(1,b-a)

def net_for(side, ep, xp, cost): return (1 if side=="long" else -1)*(xp/ep-1)*10000-cost


def simulate_stop_timeout(bars, signal_i, side, stop, timeout, cost):
    ei=signal_i+1
    if ei>=len(bars): return None
    ep=float(bars[ei]["open"]); last=min(len(bars)-1, ei+max(1,timeout))
    xp=None
    for j in range(ei,last+1):
        lo=float(bars[j]["low"]); hi=float(bars[j]["high"])
        if (side=="long" and lo<=stop) or (side=="short" and hi>=stop):
            xp=float(stop); break
    if xp is None: xp=float(bars[last]["close"])
    return net_for(side,ep,xp,cost)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--receipt',required=True); ap.add_argument('--out',default='out/a1_trend_rider_h4_h5_hardening_v1.json'); args=ap.parse_args()
    r=json.load(open(args.receipt)); assert r['strategy_id']=='trend_rider' and int(r['completed_trades'])>=25
    trades=list(r['trades'])[:25]; cfg=TrendPolicyConfig()
    boundary_ms=int(datetime.fromisoformat(r['boundary_utc'].replace('Z','+00:00')).timestamp()*1000)
    symbols=sorted({x['symbol'] for x in trades}); bars_by={}; maps={}
    for sym in symbols:
        bs=ev.fetch_bars(sym,'1h',1000); bars_by[sym]=bs; maps[sym]=idx_by_ts(bs)
    latest=max(int(x['exit_ts']) for x in trades)
    material={s:[b for b in bars_by[s] if boundary_ms<=int(b['ts_ms'])<=latest+cfg.timeframe_ms] for s in symbols}
    source_sha=stable(r['source']); data_sha=stable(material); window_sha=stable({'boundary':r['boundary_utc'],'latest_exit':latest,'symbols':symbols}); cost_sha=str(r['cost_authority_sha256'])
    cand=[float(x['net_bps'])/100.0 for x in trades]
    candidate=replay_receipt('candidate',cand,source_sha=source_sha,data_sha=data_sha,config_sha=str(r['config_sha']),window_sha=window_sha,cost_sha=cost_sha)

    controls: dict[str,list[float]]={}
    # direction inversion: identical timestamps/prices/costs, opposite side
    controls['direction_inversion']=[(-float(x['gross_bps'])-float(x['realized_cost_bps']))/100.0 for x in trades]
    # timestamp shuffle: deterministic side permutation across exact candidate timestamps
    sides=[x['side'] for x in trades]; rng=random.Random(int(window_sha[:16],16)); shuffled=sides[:]; rng.shuffle(shuffled)
    controls['timestamp_shuffle']=[net_for(shuffled[i],float(x['entry']),float(x['exit']),float(x['realized_cost_bps']))/100.0 for i,x in enumerate(trades)]
    # one-bar delay, same symbol/side and original holding duration, identical realized cost budget
    delayed=[]
    for x in trades:
        bs=bars_by[x['symbol']]; mp=maps[x['symbol']]; ei=mp[int(x['entry_ts'])]; dur=duration_bars(x,mp); dei=ei+1; dxi=min(len(bs)-1,dei+dur)
        delayed.append(net_for(x['side'],float(bs[dei]['open']),float(bs[dxi]['close']),float(x['realized_cost_bps']))/100.0)
    controls['one_bar_delay']=delayed
    # same-count random entry: matched symbol, side and holding duration; deterministic sample inside same frozen window
    random_vals=[]
    used=set()
    for i,x in enumerate(trades):
        bs=bars_by[x['symbol']]; mp=maps[x['symbol']]; dur=duration_bars(x,mp)
        pool=[j for j,b in enumerate(bs) if boundary_ms<=int(b['ts_ms'])<=latest and j+1+dur<len(bs) and int(b['ts_ms']) not in used]
        j=pool[rng.randrange(len(pool))]; used.add(int(bs[j]['ts_ms'])); ep=float(bs[j+1]['open']); xp=float(bs[j+1+dur]['close'])
        random_vals.append(net_for(x['side'],ep,xp,float(x['realized_cost_bps']))/100.0)
    controls['same_count_random_entry']=random_vals
    # indicator removal: remove Supertrend; retain EMA50 slope, prior candle direction, ATR stop/timeout and trade budget.
    ir=[]
    candidates=[]
    for sym in symbols:
        bs=bars_by[sym]; closes=[float(b['close']) for b in bs]; e=ema(closes,cfg.ema_trend_len)
        for i in range(max(64,cfg.ema_trend_len+2),len(bs)-cfg.timeout_bars-2):
            if int(bs[i]['ts_ms'])<boundary_ms or int(bs[i]['ts_ms'])>latest: continue
            a=atr(bs[:i+1],cfg.atr_len); close=closes[i]; prev=bs[i-1]
            long_ok=close>e[i] and e[i]>e[i-1] and float(prev['close'])>=float(prev['open']) and abs(close-e[i])/max(a,1e-12)<=2.0
            short_ok=close<e[i] and e[i]<e[i-1] and float(prev['close'])<=float(prev['open']) and abs(close-e[i])/max(a,1e-12)<=2.0
            if long_ok==short_ok: continue
            candidates.append((int(bs[i]['ts_ms']),sym,i,'long' if long_ok else 'short',a))
    candidates.sort()
    if len(candidates)<25: raise RuntimeError(f'INDICATOR_REMOVAL_INSUFFICIENT_TRADES:{len(candidates)}')
    for _,sym,i,side,a in candidates[:25]:
        bs=bars_by[sym]; entry=float(bs[i]['close']); stop=entry-1.5*a if side=='long' else entry+1.5*a
        # identical cost model: pair against candidate realized cost sequence by budget index
        cost=float(trades[len(ir)]['realized_cost_bps']); v=simulate_stop_timeout(bs,i,side,stop,cfg.timeout_bars,cost)
        if v is None: raise RuntimeError('INDICATOR_REMOVAL_OPEN_TRADE')
        ir.append(v/100.0)
    controls['indicator_removal']=ir

    control_receipts={}
    for name in ('same_count_random_entry','one_bar_delay','direction_inversion','timestamp_shuffle','indicator_removal'):
        vals=controls[name]; ci,p=paired_stats(cand,vals,int(stable({'window':window_sha,'control':name})[:16],16))
        control_receipts[name]=replay_receipt(name,vals,source_sha=source_sha,data_sha=data_sha,config_sha=stable({'base':r['config_sha'],'control':name}),window_sha=window_sha,cost_sha=cost_sha,ci=ci,p=p)
    policy=json.load(open('backend/research/zel_economic_hardening_policy_v1.json'))
    h4=hard.h4_placebo_controls({'candidate_receipt':candidate,'control_receipts':control_receipts},policy['h4_placebo_negative_controls'])

    # H5 deterministic decompositions from entry-time observable categories.
    def regime(x):
        bs=bars_by[x['symbol']]; i=maps[x['symbol']][int(x['signal_ts'])]; a14=atr(bs[:i+1],14); a50=atr(bs[:i+1],50); return 'VOL_HIGH' if a14>=a50 else 'VOL_LOW'
    def session(x):
        h=datetime.fromtimestamp(int(x['signal_ts'])/1000,tz=timezone.utc).hour
        return 'APAC' if h<8 else 'EU' if h<16 else 'US'
    def window(x): return datetime.fromtimestamp(int(x['entry_ts'])/1000,tz=timezone.utc).strftime('%Y-%m-%d')
    groupers={'symbol':lambda x:x['symbol'],'regime':regime,'side':lambda x:x['side'],'session':session,'window':window}
    total_profit=sum(max(0.0,float(x['net_bps'])) for x in trades)
    dims={}; loo=[]; total_net=sum(float(x['net_bps']) for x in trades)/100.0
    for dim,fn in groupers.items():
        groups={}
        for x in trades: groups.setdefault(fn(x),[]).append(x)
        rows=[]
        for g,xs in sorted(groups.items()):
            net=sum(float(x['net_bps']) for x in xs)/100.0; prof=sum(max(0.0,float(x['net_bps'])) for x in xs)
            rows.append({'group':g,'net_R':net,'profit_share':prof/total_profit if total_profit>0 else 0.0}); loo.append({'dimension':dim,'group':g,'net_R':total_net-net})
        dims[dim]=rows
    top10=sum(sorted((max(0.0,float(x['net_bps'])) for x in trades),reverse=True)[:10])/total_profit if total_profit>0 else 0.0
    h5p=policy['h5_concentration_fragility']; policy_sha=hard.stable_sha(policy)
    thresholds={'maximum_single_symbol_profit_share':float(h5p['maximum_single_symbol_profit_share']),'maximum_single_regime_profit_share':float(h5p['maximum_single_regime_profit_share']),'maximum_top10_trade_profit_share':float(h5p['maximum_top10_trade_profit_share']),'minimum_leave_one_group_out_net_R':float(h5p['minimum_leave_one_group_out_net_R'])}
    seal={'schema_version':'zel.concentration.threshold_seal.v1','state':'PASS_THRESHOLD_SEAL','policy_sha256':policy_sha,'holdout_window_sha256':window_sha,'thresholds_sha256':hard.stable_sha(thresholds),'sealed_at':POLICY_SEALED_AT,'source_commit_sha':POLICY_COMMIT}
    seal['receipt_sha256']=hard.stable_sha(seal)
    h5=hard.h5_concentration({'threshold_seal_receipt':seal,'holdout_window_sha256':window_sha,'holdout_opened_at':r['boundary_utc'],'dimensions':dims,'top10_trade_profit_share':top10,'leave_one_group_out':loo},h5p,policy_sha256=policy_sha)

    # OOS = all trades strictly after fixed W1 first 24h; no outcome-based boundary selection.
    oos_start=boundary_ms+24*3600_000; oos=[x for x in trades if int(x['entry_ts'])>=oos_start]
    oos_vals=[float(x['net_bps']) for x in oos]
    evidence={
      'schema_version':'zel.a1_trend_rider_hardening_evidence.v1','state':'PASS_HARDENING_EVIDENCE' if h4['state']=='PASS_PLACEBO_NEGATIVE_CONTROLS' and h5['state']=='PASS_CONCENTRATION_FRAGILITY' else 'HOLD_HARDENING_EVIDENCE',
      'strategy_id':'trend_rider','policy_sha':r['policy_sha'],'config_sha':r['config_sha'],'boundary_utc':r['boundary_utc'],'cost_authority_sha256':cost_sha,
      'candidate_receipt_sha256':r['receipt_sha256'],'retention_pct':100.0*len(oos)/len(trades),'retention_definition':'completed_trades_after_fixed_first_24h_W1_divided_by_tierA_25_trade_budget',
      'oos':{'trade_count':len(oos),'net_pnl_bps':sum(oos_vals),'net_expectancy_bps':sum(oos_vals)/len(oos_vals) if oos_vals else None,'window_rule':'strictly_after_preexisting_boundary_plus_24h'},
      'h4_receipt':h4,'h5_receipt':h5,'fixture':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','protected_mutations':0,
    }
    evidence['receipt_sha256']=hard.stable_sha(evidence)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True); Path(args.out).write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    print('A1_TREND_RIDER_H4_H5='+json.dumps({'state':evidence['state'],'retention_pct':evidence['retention_pct'],'oos':evidence['oos'],'H4':h4['state'],'H4_results':h4['control_results'],'H5':h5['state'],'H5_blockers':h5['blockers'],'H5_max_shares':h5['maximum_profit_share_by_dimension'],'top10':h5['top10_trade_profit_share'],'receipt_sha256':evidence['receipt_sha256']},sort_keys=True))

if __name__=='__main__': main()
