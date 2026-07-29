from __future__ import annotations

import argparse, hashlib, json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.strategies.bb_revert import BbRevertConfig
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p=replay.p; exact=replay.exact; base=replay.base; repair=replay.repair; prior=replay.prior
STRATEGY_ID='bb_revert'
VERSION='R7A4D_STRATEGY11_BB_REVERT_COMPONENT_TRACE_V1'
SAFETY={'research_only':True,'promotion_authority':False,'protected_mutations':0,'execution_allowed':False,'order_authority':'BLOCKED','runtime_bound':False}

def stable_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def atomic_json(path:Path,v:Mapping[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(v,indent=2,sort_keys=True,allow_nan=False)+'\n')

def verify_source(root:Path,expected_sha:str)->dict[str,Any]:
    path=(root/'backend/strategies/bb_revert.py').resolve(); src=path.read_text(); sha=hashlib.sha256(src.encode()).hexdigest()
    if sha!=expected_sha: raise RuntimeError(f'SOURCE_SHA_MISMATCH:{sha}:{expected_sha}')
    required={
      'long_setup':'    long_setup = (','short_setup':'    short_setup = (','vol_gate':'    if not vol_ok:',
      'late_gate':'    if late_chase_block and (long_setup or short_setup):','long_entry':'    if long_setup and not in_long and not in_short:',
      'short_entry':'    if short_setup and not in_long and not in_short:'}
    counts={k:src.count(v) for k,v in required.items()}
    if any(v!=1 for v in counts.values()): raise RuntimeError('SOURCE_CONTRACT_SHAPE_MISMATCH:'+json.dumps(counts,sort_keys=True))
    order={k:src.index(v) for k,v in required.items()}
    if not(order['long_setup']<order['short_setup']<order['vol_gate']<order['late_gate']<order['long_entry']<order['short_entry']): raise RuntimeError('SOURCE_ORDER_MISMATCH')
    return {'source_path':'backend/strategies/bb_revert.py','source_sha':sha,'required_clause_counts':counts,'entry_order_verified':True,'source_modified':False}

def trace(strategy:Any,symbols:tuple[str,...],frames:Mapping[tuple[str,str],Any],warmup:int,history_bars:int)->dict[str,Any]:
    cfg=BbRevertConfig(); counts=Counter(); per_window=defaultdict(Counter); per_symbol=defaultdict(Counter); samples=[]; calls=0
    def add(name,w,s): counts[name]+=1; per_window[w][name]+=1; per_symbol[s][name]+=1
    for w in repair.FRESH_ROLES:
      for s in symbols:
        frame=frames[(w,s)]
        for i in range(warmup,len(frame)-1):
          hist=frame.iloc[max(0,i-history_bars+1):i+1].copy(); r=exact._call_strategy(strategy,hist,{'position_side':'','position_qty':0.0,'avg_entry':0.0,'add_count':0,'last_add_price':0.0}); calls+=1
          ind=r.get('indicators')
          if not isinstance(ind,Mapping): continue
          price=float(ind['price']); atr=float(ind['atr']); lower=float(ind['bb_lower']); upper=float(ind['bb_upper']); rsi=float(ind['rsi']); atr_pct=float(ind['atr_pct'])
          long_band=price<lower-atr*cfg.band_over_atr; long_rsi=rsi<=cfg.rsi_os; long_reclaim=bool(ind.get('long_reclaim')); long_trend=not bool(ind.get('trend_short'))
          short_band=price>upper+atr*cfg.band_over_atr; short_rsi=rsi>=cfg.rsi_ob; short_reclaim=bool(ind.get('short_reclaim')); short_trend=not bool(ind.get('trend_long'))
          comps={'long_band':long_band,'long_rsi':long_rsi,'long_reclaim':long_reclaim,'long_trend_ok':long_trend,'short_band':short_band,'short_rsi':short_rsi,'short_reclaim':short_reclaim,'short_trend_ok':short_trend}
          for k,v in comps.items():
            if v:add(k+'_true',w,s)
          for side in ('long','short'):
            band=comps[side+'_band']; rr=comps[side+'_rsi']; rec=comps[side+'_reclaim']; tr=comps[side+'_trend_ok']; setup=bool(ind.get(side+'_setup'))
            if band:add(side+'_band_event',w,s)
            if band and rr:add(side+'_band_rsi_joint',w,s)
            if band and rr and rec:add(side+'_band_rsi_reclaim_joint',w,s)
            if setup:add(side+'_setup_true',w,s)
            if not band: blocker='band_condition'
            elif not rr: blocker='rsi_condition'
            elif not rec: blocker='reclaim_condition'
            elif not tr: blocker='trend_condition'
            elif not(cfg.min_atr_pct<=atr_pct<=cfg.max_atr_pct): blocker='volatility_gate'
            elif bool(ind.get('late_chase_block')): blocker='late_chase_gate'
            else: blocker='entry_eligible'
            if band:add(side+'_'+blocker,w,s)
            if band and len(samples)<30:samples.append({'window_id':w,'symbol':s,'side':side,'first_blocker':blocker,'price':price,'bb_lower':lower,'bb_upper':upper,'rsi':rsi,'atr_pct':atr_pct,'reclaim':rec,'trend_ok':tr,'dist_from_mid_atr':ind.get('dist_from_mid_atr')})
          if str(r.get('action') or 'hold').lower()=='enter':add('actual_enter',w,s)
    eligible=counts['long_entry_eligible']+counts['short_entry_eligible']; actual=counts['actual_enter']; band_events=counts['long_band_event']+counts['short_band_event']; band_rsi=counts['long_band_rsi_joint']+counts['short_band_rsi_joint']; setups=counts['long_setup_true']+counts['short_setup_true']
    if eligible!=actual: state='ROUTING_CONTRACT_MISMATCH'; nxt='TRACE_ENTRY_ROUTER'
    elif band_events>=20 and band_rsi==0: state='BAND_AND_RSI_NEVER_INTERSECT'; nxt='WAIT_W1_OR_TEST_TEMPORAL_CONFIRMATION_AXIS'
    elif band_rsi>0 and setups==0: state='POST_RSI_COMPONENT_BLOCKS_ALL'; nxt='DECOMPOSE_RECLAIM_TREND'
    elif setups<5: state='LOW_FREQUENCY_BB_SETUP_HOLD'; nxt='WAIT_W1_NEW_NONOVERLAP'
    else: state='BB_COMPONENTS_DECOMPOSED'; nxt='SOURCE_CAUSAL_REVIEW'
    return {'state':state,'next_action':nxt,'call_count':calls,'counts':dict(sorted(counts.items())),'band_event_count':band_events,'band_rsi_joint_count':band_rsi,'setup_count':setups,'entry_eligible_count':eligible,'actual_enter_count':actual,'eligible_equals_actual_enter':eligible==actual,'per_window':{k:dict(sorted(v.items())) for k,v in sorted(per_window.items())},'per_symbol':{k:dict(sorted(v.items())) for k,v in sorted(per_symbol.items())},'samples':samples}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,default=Path('.')); ap.add_argument('--fresh-root',type=Path,required=True); ap.add_argument('--evidence-root',type=Path,required=True); ap.add_argument('--source-run-id',required=True); ap.add_argument('--source-head-sha',required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args()
    root=a.root.resolve(); baseline=json.loads(prior.find_summary(a.evidence_root.resolve(),STRATEGY_ID).read_text()); symbols=tuple(str(v) for v in baseline.get('symbols',[])); frames,_,_,manifest=p.load_fresh_data(a.fresh_root.resolve()); registry=base._load_registry(root); row=registry[STRATEGY_ID]; source=verify_source(root,str(row['canonical_engine']['source_sha256'])); strategy=base._load_canonical_strategy(root,STRATEGY_ID,row); t=trace(strategy,symbols,frames,int(manifest['warmup_bars']),220)
    result={'schema_version':'strategy11.bb_revert_component_trace.v1','version':VERSION,'state':'PASS_BB_REVERT_COMPONENT_TRACE','strategy_id':STRATEGY_ID,'source_run_id':str(a.source_run_id),'source_head_sha':str(a.source_head_sha),'baseline_summary_sha':stable_sha(baseline),'symbols':list(symbols),'source_contract':source,'trace':t,'canonical_source_modified':False,'registry_modified':False,'thresholds_modified':False,'ai_review_state':'WAIT_GROQ_QUOTA','w1_confirmation_required':True,'new_sealed_required':True,**SAFETY}; result['diagnostic_sha']=stable_sha(result); a.out.mkdir(parents=True,exist_ok=True); atomic_json(a.out/'final.json',result); print(result['state'],t['state'],t['band_event_count'],t['setup_count']); return 0
if __name__=='__main__': raise SystemExit(main())
