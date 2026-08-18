from __future__ import annotations
import argparse, json, math
from datetime import datetime
from pathlib import Path
from typing import Any
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import fetch_bars, fetch_execution_snapshot, funding_cost, git_blob_sha, load_json, max_drawdown, stable_sha
from backend.production.zel_production_a1_jump_liquidity_economic_v1 import _source_complete

ROOT=Path(__file__).resolve().parents[3]
POLICY=ROOT/'backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_policy_v1.json'
PREREG=ROOT/'backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_prereg_v1.json'
COST=ROOT/'backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json'

def _load_jsonl(path:Path)->list[dict[str,Any]]:
    if not path.is_file(): raise RuntimeError(f'MICRO_HISTORY_MISSING:{path}')
    out=[]
    for n,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip(): continue
        try:r=json.loads(line)
        except json.JSONDecodeError as exc: raise RuntimeError(f'MICRO_HISTORY_JSON_INVALID:{n}') from exc
        if isinstance(r,dict):out.append(r)
    return out

def _sign(v:float)->int:return 1 if v>0 else (-1 if v<0 else 0)

def feature_for_index(bars:list[dict[str,Any]],i:int,cfg:dict[str,Any],cost_bps:float)->dict[str,Any]:
    ml=int(cfg['momentum_lookback_bars']); rr=int(cfg['participation_recent_bars']); pp=int(cfg['participation_prior_bars']); rl=int(cfg['range_lookback_bars'])
    warm=max(ml,rr+pp,rl+1)
    if i<warm: return {'pass':False,'reason':'WARMUP'}
    close=float(bars[i]['close']); past=float(bars[i-ml]['close']); mom=(close/past-1.0)*10000.0
    if _sign(mom)==0:return {'pass':False,'reason':'ZERO_MOMENTUM'}
    recent=sum(float(x['volume']) for x in bars[i-rr+1:i+1])/rr
    prior=sum(float(x['volume']) for x in bars[i-rr-pp+1:i-rr+1])/pp
    if recent<prior:return {'pass':False,'reason':'PARTICIPATION_NOT_SUPPORTIVE'}
    cur_range=float(bars[i]['high'])-float(bars[i]['low'])
    prev_ranges=[float(x['high'])-float(x['low']) for x in bars[i-rl:i]]
    if prev_ranges and cur_range>max(prev_ranges):return {'pass':False,'reason':'NEW_RANGE_EXTREME_NO_TRADE'}
    window=bars[i-rl+1:i+1]; hi=max(float(x['high']) for x in window); lo=min(float(x['low']) for x in window)
    range_bps=(hi-lo)/close*10000.0 if close>0 else 0.0
    if range_bps<float(cfg['expected_move_cost_multiple_floor'])*float(cost_bps):return {'pass':False,'reason':'MOVE_BUDGET_BELOW_COST_FLOOR'}
    return {'pass':True,'reason':'BAR_REGIME_READY','side':'long' if mom>0 else 'short','momentum_bps':mom,'recent_volume_mean':recent,'prior_volume_mean':prior,'range_bps':range_bps,'signal_ts_ms':int(bars[i]['ts_ms'])}

def micro_confirmation(rows:list[dict[str,Any]],symbol:str,entry_ts_ms:int,side:str,cfg:dict[str,Any])->dict[str,Any]:
    floor=entry_ts_ms-int(cfg['micro_confirm_window_ms']); eligible=[]
    for r in rows:
        if str(r.get('symbol') or '')!=symbol:continue
        end=int(r.get('bucket_end_ms') or 0)
        if end>entry_ts_ms or end<floor:continue
        if not _source_complete(r):continue
        eligible.append(r)
    eligible.sort(key=lambda r:int(r.get('bucket_end_ms') or 0))
    if len(eligible)<int(cfg['minimum_complete_micro_buckets']):return {'pass':False,'reason':'MICRO_WINDOW_INCOMPLETE','count':len(eligible)}
    last=int(eligible[-1].get('bucket_end_ms') or 0)
    if entry_ts_ms-last>int(cfg['maximum_micro_staleness_ms']):return {'pass':False,'reason':'MICRO_WINDOW_STALE','count':len(eligible)}
    flow=sum(float(r.get('trade_imbalance') or 0.0) for r in eligible)/len(eligible)
    book=sum(float(r.get('imbalance_top20_mean') or 0.0) for r in eligible)/len(eligible)
    want=1 if side=='long' else -1
    passed=_sign(flow)==want and _sign(book)==want
    return {'pass':passed,'reason':'FLOW_BOOK_ALIGNED' if passed else 'FLOW_BOOK_NOT_ALIGNED','count':len(eligible),'flow_mean':flow,'book_mean':book,'latest_bucket_end_ms':last}

def evaluate(boundary_utc:str,history_path:Path,symbols:list[str])->dict[str,Any]:
    cfg=load_json(POLICY); prereg=load_json(PREREG); authority=load_json(COST)
    if prereg.get('baseline_mutated') is not False or prereg.get('experimental_not_baseline') is not True:raise RuntimeError('PREREG_AUTHORITY_INVALID')
    if cfg.get('fresh_prospective_boundary_utc')!=boundary_utc:raise RuntimeError('BOUNDARY_CONFIG_MISMATCH')
    if cfg.get('parameter_search') is not False or cfg.get('best_horizon_selection') is not False:raise RuntimeError('SEARCH_FORBIDDEN')
    if authority.get('state')!='FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY':raise RuntimeError('COST_AUTHORITY_INVALID')
    boundary_ms=int(datetime.fromisoformat(boundary_utc.replace('Z','+00:00')).timestamp()*1000)
    micro=_load_jsonl(history_path); trades=[]; baseline_events=confirmed=0; defects=[]; source=[]; snapshots={}
    for symbol in symbols:
        snap=fetch_execution_snapshot(symbol,authority); snapshots[symbol]=snap; bars=fetch_bars(symbol,'5m',1000)
        source.append({'symbol':symbol,'bars_post_boundary':sum(1 for b in bars if int(b['ts_ms'])>=boundary_ms),'micro_rows':sum(1 for r in micro if str(r.get('symbol') or '')==symbol)})
        for i in range(max(96,int(cfg['momentum_lookback_bars'])+int(cfg['participation_prior_bars'])+int(cfg['participation_recent_bars'])),len(bars)-2):
            if int(bars[i]['ts_ms'])<boundary_ms:continue
            feat=feature_for_index(bars,i,cfg,float(snap['pretrade_verified_cost_bps']))
            if not feat['pass']:continue
            baseline_events+=1; entry_idx=i+1; entry_ts=int(bars[entry_idx]['ts_ms']); side=str(feat['side'])
            mc=micro_confirmation(micro,symbol,entry_ts,side,cfg)
            if not mc['pass']:continue
            confirmed+=1; key=stable_sha({'symbol':symbol,'signal_ts':feat['signal_ts_ms'],'side':side,'policy':git_blob_sha(POLICY)})
            if any(t['intent_sha']==key for t in trades): defects.append('DUPLICATE:'+key);continue
            sign=1 if side=='long' else -1; entry=float(bars[entry_idx]['open']); max_exit=min(len(bars)-1,entry_idx+int(cfg['horizon_bars']))
            if max_exit<=entry_idx:continue
            exit_px=None;exit_ts=None;reason=None
            ml=int(cfg['momentum_lookback_bars'])
            for j in range(entry_idx+1,max_exit+1):
                if j-ml<0:continue
                m=(float(bars[j]['close'])/float(bars[j-ml]['close'])-1.0)
                if _sign(m) not in (0,sign):
                    if j+1>=len(bars):break
                    exit_px=float(bars[j+1]['open']);exit_ts=int(bars[j+1]['ts_ms']);reason='MOMENTUM_INVALIDATION';break
            if exit_px is None:
                if max_exit>=len(bars)-1:continue
                exit_px=float(bars[max_exit]['close']);exit_ts=int(bars[max_exit]['ts_ms']);reason='TIME_STOP_4H'
            gross=sign*(exit_px-entry)/entry*10000.0; fund=funding_cost(entry_ts,exit_ts,list(snap['funding_rows'])); cost=float(snap['fee_bps'])+float(snap['spread_bps'])+float(snap['impact_bps'])+fund
            trades.append({'symbol':symbol,'side':side,'signal_ts_ms':feat['signal_ts_ms'],'entry_ts_ms':entry_ts,'exit_ts_ms':exit_ts,'entry_px':entry,'exit_px':exit_px,'exit_reason':reason,'gross_bps':gross,'realized_cost_bps':cost,'net_bps':gross-cost,'feature':feat,'micro_confirmation':mc,'intent_sha':key})
    net=[float(t['net_bps']) for t in trades];gross=[float(t['gross_bps']) for t in trades];wins=[x for x in net if x>0];losses=[-x for x in net if x<0];gp=sum(wins);gl=sum(losses)
    metrics={'gross_pnl_bps':sum(gross),'gross_expectancy_bps':sum(gross)/len(gross) if gross else None,'net_pnl_bps':sum(net),'net_expectancy_bps':sum(net)/len(net) if net else None,'profit_factor':gp/gl if gl>0 else (math.inf if gp>0 else None),'payoff':(gp/len(wins))/(gl/len(losses)) if wins and losses else None,'win_rate':len(wins)/len(net) if net else None,'max_drawdown_bps':max_drawdown(net)}
    r={'schema_version':'zel.a1.rcfm.economics.v1','state':'HOLD_RCFM_INTEGRITY' if defects else ('WAIT_FRESH_PROSPECTIVE_DATA' if not trades else 'RCFM_ECONOMICS_ACTIVE'),'experiment_id':'regime_conditioned_flow_momentum_v1','candidate_id':'NEW_RCFM_001','boundary_utc':boundary_utc,'source_history_path':str(history_path),'source_rows':source,'baseline_event_count':baseline_events,'confirmed_intent_count':confirmed,'completed_trades':len(trades),'metrics':metrics,'trades':trades,'snapshots':snapshots,'integrity_defects':defects,'leakage_lookahead':0,'duplicate_count':len(defects),'policy_sha':git_blob_sha(POLICY),'prereg_sha':git_blob_sha(PREREG),'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
    r['receipt_sha256']=stable_sha(r);return r

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--boundary',required=True);ap.add_argument('--history',default='/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl');ap.add_argument('--symbols',default='BTC-USDT,ETH-USDT');ap.add_argument('--out',default='out/a1_rcfm_economics.json');a=ap.parse_args();r=evaluate(a.boundary,Path(a.history),[x.strip() for x in a.symbols.split(',') if x.strip()]);Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(r,sort_keys=True,indent=2,default=str)+'\n');print(json.dumps({'state':r['state'],'trades':r['completed_trades'],'metrics':r['metrics']},sort_keys=True,default=str))
if __name__=='__main__':main()
