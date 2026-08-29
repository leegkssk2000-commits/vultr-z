#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_additive_entry_union_v1 as addu
from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import a1_trendma52_top5_salvage_v1 as salvage
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[3]
COST = ROOT / 'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'
SCHEMA = 'zel.a1.trendma.atr_adverse_veto.top5_salvage.v1'
SYMBOLS = salvage.SYMBOLS
FROZEN_DONOR_AXIS = {
    'origin_commit': '051ff7015e6456410073b1a42dc0c201876c1958',
    'name': 'long_above_sma50_and_shock_ge_1x_atr14_veto_only',
    'atr_n': 14,
    'sma_n': 50,
    'shock_atr_floor': 1.0,
    'threshold_sweep': False,
    'future_information_used': False,
}


def read(path: Path) -> dict[str, Any]:
    v=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(v,dict): raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return v


def atr14(bars:list[dict[str,Any]],i:int)->float:
    vals=[]
    for j in range(i-13,i+1):
        pc=float(bars[j-1]['close'])
        vals.append(max(float(bars[j]['high'])-float(bars[j]['low']),abs(float(bars[j]['high'])-pc),abs(float(bars[j]['low'])-pc)))
    return sum(vals)/len(vals)


def replay(*, boundary_ms:int, bars_by:Mapping[str,list[dict[str,Any]]], snapshots:Mapping[str,Mapping[str,Any]], policy_sha:str)->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    cfg=policy.TrendPolicyConfig(); timeframe_ms=3600*1000
    trades=[]; vetoed=[]
    for symbol in SYMBOLS:
        bars=list(bars_by[symbol]); snap=snapshots[symbol]; blocked_until_ts=-1
        for i in range(max(64,50),len(bars)-1):
            if int(bars[i]['ts_ms']) < boundary_ms: continue
            try:
                feature=policy.compute_trend_ma_macd_feature(bars[:i+1],symbol=symbol,now_ts_ms=int(bars[i]['ts_ms']),config=cfg)
                intent=policy.build_trend_ma_macd_intent(feature,policy_source_sha=policy_sha,verified_round_trip_cost_bps=float(snap['pretrade_verified_cost_bps']),config=cfg)
            except ValueError as exc:
                if str(exc).startswith(('WARMUP_','WINDOW_','ATR_')): continue
                raise
            if bool(getattr(intent,'no_trade')): continue
            side_name=str(getattr(intent,'side'))
            if side_name!='long':
                # TRUE_LONG_ONLY: short is suppressed before ownership/cooldown reservation.
                continue
            a=atr14(bars,i)
            shock=abs(float(bars[i]['close'])-float(bars[i-1]['close']))
            shock_atr=shock/max(a,1e-12)
            sma50=sum(float(x['close']) for x in bars[i-49:i+1])/50.0
            above_sma50=float(bars[i]['close'])>=sma50
            if above_sma50 and shock_atr>=1.0:
                vetoed.append({'symbol':symbol,'signal_ts':int(bars[i]['ts_ms']),'side':'long','shock_atr':shock_atr,'above_sma50':True})
                continue
            entry_bar=bars[i+1]; entry_ts=int(entry_bar['ts_ms'])
            owns_position,cooldown_bars=ev.execution_ownership_policy(intent)
            if owns_position and ev.ownership_blocked(entry_ts,blocked_until_ts): continue
            entry=float(entry_bar['open']); sl=getattr(intent,'sl',None); tp=getattr(intent,'tp',None); timeout=getattr(intent,'timeout',{}) or {}; timeout_bars=int(timeout.get('bars',getattr(cfg,'timeout_bars',1)))
            if sl is None and tp is None: raise RuntimeError('EXIT_GEOMETRY_UNSUPPORTED_NO_SL_TP')
            exit_px=exit_ts=reason=None; last_j=min(len(bars)-1,i+1+max(1,timeout_bars))
            for j in range(i+1,last_j+1):
                bar=bars[j]; low=float(bar['low']); high=float(bar['high'])
                if sl is not None and low<=float(sl): exit_px,exit_ts,reason=float(sl),int(bar['ts_ms']),'SL'; break
                if tp is not None and high>=float(tp): exit_px,exit_ts,reason=float(tp),int(bar['ts_ms']),'TP'; break
            if exit_px is None:
                if last_j>=len(bars)-1:
                    if owns_position:
                        blocked_until_ts=max(blocked_until_ts,ev.reserve_position_ownership(exit_ts=None,open_horizon_ts=int(bars[-1]['ts_ms']),cooldown_bars=cooldown_bars,timeframe_ms=timeframe_ms))
                    continue
                exit_px,exit_ts,reason=float(bars[last_j]['close']),int(bars[last_j]['ts_ms']),'TIMEOUT'
            if owns_position:
                blocked_until_ts=max(blocked_until_ts,ev.reserve_position_ownership(exit_ts=int(exit_ts),open_horizon_ts=None,cooldown_bars=cooldown_bars,timeframe_ms=timeframe_ms))
            cost=float(snap['fee_bps'])+float(snap['spread_bps'])+float(snap['impact_bps'])+ev.funding_cost(entry_ts,int(exit_ts),list(snap['funding_rows']))
            gross=(float(exit_px)-entry)/entry*10000
            trades.append({'symbol':symbol,'signal_ts':int(getattr(intent,'signal_ts')),'entry_ts':entry_ts,'exit_ts':int(exit_ts),'side':'long','entry':entry,'exit':float(exit_px),'reason':reason,'gross_bps':gross,'realized_cost_bps':cost,'net_bps':gross-cost,'shock_atr':shock_atr,'above_sma50':above_sma50})
    return trades,vetoed


def run(parent_path:Path,trend70:Path,a4_dir:Path,break_dir:Path,out:Path)->dict[str,Any]:
    exact=read(parent_path)
    if str(exact.get('strategy_id'))!='trend_ma_macd' or len(exact.get('trades') or [])!=52: raise RuntimeError('EXACT_TRENDMA_52_PARENT_REQUIRED')
    authority=read(COST); bars_by,maps,fetched=ab.load_shared_inputs(SYMBOLS,authority); public=exact.get('execution_snapshots') or {}
    snaps={s:salvage._snapshot_with_exact_cost(fetched[s],dict(public.get(s) or {})) for s in SYMBOLS}
    rows,vetoed=replay(boundary_ms=ab.parse_boundary(str(exact.get('boundary_utc') or '')),bars_by=bars_by,snapshots=snaps,policy_sha=str(exact.get('policy_sha') or ''))
    base_true_long=salvage.replay_with_side_admission(mode='LONG_ONLY',boundary_ms=ab.parse_boundary(str(exact.get('boundary_utc') or '')),bars_by=bars_by,snapshots=snaps,policy_sha=str(exact.get('policy_sha') or ''))
    base_ids={(x['symbol'],x['signal_ts'],x['entry_ts']) for x in base_true_long}; child_ids={(x['symbol'],x['signal_ts'],x['entry_ts']) for x in rows}
    lanes=salvage.parent_lanes(trend70,a4_dir,break_dir)
    unions={}; strict=[]
    for lane,p in lanes.items():
        u=addu.evaluate(p,{'strategy_id':'trend_ma_macd','trades':rows})
        unions[lane]={'state':u['state'],'parent_T':u['parent_trade_count'],'added_only_T':u['added_only_trade_count'],'overlap_T':u['overlap_trade_count'],'overlap_payload_mutation_T':u['overlap_payload_mutation_count'],'parent_metrics':u['parent_metrics'],'added_metrics':u['added_only_metrics'],'combined_metrics':u['combined_metrics'],'failed_checks':u['failed_checks'],'near_overlap':salvage.near_overlap(p['trades'],rows)}
        if u['state']=='PASS_ADD_ONLY_ENTRY_LANE': strict.append(lane)
    result={'schema_version':SCHEMA,'state':'PASS_TRENDMA_ATR_ADVERSE_VETO_SALVAGE','strategy_id':'trend_ma_macd','frozen_axis':FROZEN_DONOR_AXIS,'base_true_long':{'T':len(base_true_long),'metrics':addu.metrics(base_true_long)},'candidate':{'T':len(rows),'metrics':addu.metrics(rows),'veto_signal_T':len(vetoed),'trade_ids_removed_from_base_T':len(base_ids-child_ids),'trade_ids_added_after_ownership_release_T':len(child_ids-base_ids)},'top5_append_only_unions':unions,'historical_strict_pass_lanes':strict,'historical_strict_pass_count':len(strict),'attachable_now':False,'attachable_now_reason':'TRANSFER_TO_TRENDMA_WAS_NOT_PREREGISTERED_BEFORE_THIS_SAMPLE','latent_attachable_after_fresh':bool(strict),'next':'FREEZE_THIS_TRANSFER_AND_START_FRESH_PROSPECTIVE' if strict else 'SEALED_FAIL_FOR_TOP5_ATTACHMENT','outcome_selected':False,'threshold_sweep':False,'post_outcome_trade_deletion':False,'parent_rewrite':False,'top5_ssot_mutated':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','protected_mutations':0,'action':'hold'}
    result['receipt_sha256']=stable_sha(result); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8'); return result


def self_test()->int:
    assert FROZEN_DONOR_AXIS['shock_atr_floor']==1.0 and FROZEN_DONOR_AXIS['threshold_sweep'] is False
    print('PASS_A1_TRENDMA_ATR_ADVERSE_VETO_TOP5_SALVAGE_V1_SELF_TEST'); return 0


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--parent',type=Path); ap.add_argument('--trend70-source',type=Path); ap.add_argument('--a4-source-dir',type=Path); ap.add_argument('--break-source-dir',type=Path); ap.add_argument('--out',type=Path,default=Path('out/a1_trendma_atr_adverse_veto_top5_salvage_latest.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:return self_test()
    if not all((a.parent,a.trend70_source,a.a4_source_dir,a.break_source_dir)): raise SystemExit('required paths missing')
    r=run(a.parent,a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out); print(json.dumps({'state':r['state'],'base':r['base_true_long'],'candidate':r['candidate'],'strict':r['historical_strict_pass_lanes'],'latent':r['latent_attachable_after_fresh'],'next':r['next']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
