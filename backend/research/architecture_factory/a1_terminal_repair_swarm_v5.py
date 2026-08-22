#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, urllib.request
from pathlib import Path
from typing import Any

from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as v4
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v3 as econ
from backend.research.architecture_factory import a1_gen2_post_econ_alpha_intake_v1 as alpha_intake

CONTRACT=Path('backend/research/contracts/p3_carry_flow_prospective_native_v1.json')
SUBAXIS_CONTRACT=Path('backend/research/contracts/a1_basis_funding_oi_subaxis_replay_v1.json')
CACHE=Path('backend/research/architecture_factory/a1_terminal_repair_swarm_v5_latest.json')
P3_COVERAGE_URL=v4.P3_COVERAGE_URL
CACHE_POLICY='API_ROI_PERSISTENT_CACHE_V1'
CODE_PATHS=[
  Path('backend/research/architecture_factory/a1_terminal_repair_swarm_v4.py'),
  Path('backend/research/architecture_factory/a1_terminal_repair_swarm_v5.py'),
  Path('backend/research/architecture_factory/a1_gen2_generic_dev_econ_v3.py'),
  Path('backend/research/architecture_factory/a1_gen2_post_econ_alpha_intake_v1.py'),
  Path('backend/research/architecture_factory/a1_strategy_architecture_factory_v1.py'),
  Path('backend/research/architecture_factory/gemini_provider_v1.py'),
]

def _history_readiness()->dict[str,Any]:
    out={
      'ohlcv':{'ready':True,'reason':'BINGX_KLINE_PRE_BOUNDARY_PULL_AVAILABLE'},
      'volume':{'ready':True,'reason':'BINGX_KLINE_PRE_BOUNDARY_PULL_AVAILABLE'},
      'funding':{'ready':False,'reason':'P3_CONTRACT_UNVERIFIED'},
      'basis':{'ready':False,'reason':'P3_COVERAGE_UNVERIFIED'},
      'open_interest':{'ready':False,'reason':'P3_COVERAGE_UNVERIFIED'},
      'l2_order_book':{'ready':False,'reason':'NO_DEVELOPMENT_HISTORY_BOUND'},
      'trade_flow':{'ready':False,'reason':'NO_DEVELOPMENT_HISTORY_BOUND'},
    }
    try:
        c=json.loads(CONTRACT.read_text(encoding='utf-8'))
        funding=(c.get('native_sources') or {}).get('funding') or {}
        fready=str(funding.get('status') or '')=='HISTORICAL_W1_W2_BOUND' and bool(funding.get('endpoint'))
        out['funding']={'ready':fready,'reason':'P3_CONTRACT_HISTORICAL_W1_W2_BOUND' if fready else 'P3_FUNDING_HISTORY_NOT_BOUND','endpoint':funding.get('endpoint')}
    except Exception as exc:
        out['funding']={'ready':False,'reason':'P3_CONTRACT_READ_FAILED','error':f'{type(exc).__name__}:{str(exc)[:160]}'}; fready=False
    try:
        s=json.loads(SUBAXIS_CONTRACT.read_text(encoding='utf-8')); inv=s.get('separation_invariant') or {}
        subaxis_ok=(s.get('schema_version')=='zel.a1.basis_funding_oi_subaxis_replay.v1' and s.get('state')=='FROZEN_SUBAXIS_REPLAY_CONTRACT' and inv.get('duration_gate_lowered') is False and inv.get('historical_backfill_fabricated') is False and inv.get('basis_funding_oi_subaxis_does_not_require_flow') is True)
    except Exception as exc:
        subaxis_ok=False; out['basis']={'ready':False,'reason':'P3_SUBAXIS_CONTRACT_READ_FAILED','error':f'{type(exc).__name__}:{str(exc)[:160]}'}; out['open_interest']=dict(out['basis'])
    try:
        with urllib.request.urlopen(P3_COVERAGE_URL,timeout=15) as r: cov=json.loads(r.read().decode('utf-8'))
        duration_gate=bool(cov.get('basis_oi_duration_gate_pass')); gate=bool(duration_gate and subaxis_ok and fready)
        ratio=float(cov.get('minimum_coverage_progress_ratio') or 0.0); state=str(cov.get('state') or '')
        required=int(cov.get('required_capture_span_ms') or 0); spans=[int(x.get('capture_span_ms') or 0) for x in cov.get('results') or [] if isinstance(x,dict)]
        captured=min(spans) if spans else int(required*ratio); remaining=max(0,required-captured)
        common={'coverage_progress_ratio':ratio,'coverage_state':state,'coverage_receipt':cov.get('receipt_sha256'),'required_capture_span_ms':required,'captured_min_span_ms':captured,'remaining_span_ms':remaining,'remaining_days':remaining/86_400_000 if required else None,'prospective_only':True,'historical_coverage_claim':bool(cov.get('historical_coverage_claim')),'historical_coverage_claim_required':False,'historical_backfill_allowed':False,'full_carry_flow_replay_allowed':bool(cov.get('replay_allowed')),'flow_source_bound':bool(cov.get('flow_source_bound')),'subaxis_contract_verified':subaxis_ok}
        for source in ('basis','open_interest'): out[source]={'ready':gate,'reason':'P3_SUBAXIS_FROZEN_21D_DURATION_GATE_PASS' if gate else 'P3_SUBAXIS_FROZEN_21D_DURATION_GATE_PENDING',**common}
        out['basis_oi_combined_gate']={'source_ready':gate,'reason':'BASIS_FUNDING_OI_SUBAXIS_21D_PLUS_FUNDING_REQUIRED','coverage_progress_ratio':ratio,'remaining_days':common['remaining_days'],'duration_gate_pass':duration_gate,'subaxis_contract_verified':subaxis_ok}
    except Exception as exc:
        err=f'{type(exc).__name__}:{str(exc)[:160]}'
        for source in ('basis','open_interest'): out[source]={'ready':False,'reason':'P3_COVERAGE_FETCH_FAILED','error':err}
        out['basis_oi_combined_gate']={'source_ready':False,'reason':'P3_COVERAGE_FETCH_FAILED','error':err}
    return out

def _funding_probe()->dict[str,Any]:
    return {'candidate_id':'fixed_funding_change_mean_reversion_probe_v1','strategy_id':'NEW','provider':'fixed_evidence_probe','required_sources':['funding','ohlcv'],'executable_spec':{'bar_interval':'1h','features':[{'name':'funding_delta','formula':'funding_rate-lag(funding_rate,1)'}],'entry_rule':'funding_delta != 0','side_rule':'short if funding_rate > 0 else long','exit_rule':'time_stop','max_hold_bars':8,'entry_timing':'next_bar_open','cost_model':'verified_14bps_round_trip','development_data_rule':'strictly_pre_GEN1_boundary','parameter_provenance':'natural 8h funding interval; no outcome sweep'},'evidence_ids':['F18','F3','F17'],'development_only':True,'selection_authority':False,'promotion_authority':False}

def _input_signature(readiness:dict[str,Any])->str:
    h=hashlib.sha256(); h.update(CACHE_POLICY.encode())
    for path in [Path(v4.LEDGER),Path(v4.EVIDENCE),CONTRACT,SUBAXIS_CONTRACT,*CODE_PATHS]:
        h.update(str(path).encode()); h.update(b'\0'); h.update(path.read_bytes() if path.is_file() else b'MISSING'); h.update(b'\0')
    h.update(json.dumps(readiness,sort_keys=True,separators=(',',':')).encode())
    h.update((os.environ.get('OPENAI_MODEL','') or 'gpt-5-mini').encode()); h.update(b'\0')
    h.update((os.environ.get('GEMINI_MODEL','') or 'gemini-3.1-pro-preview').encode())
    return h.hexdigest()

def _cache_hit(signature:str)->dict[str,Any]|None:
    if not CACHE.is_file(): return None
    try: old=json.loads(CACHE.read_text(encoding='utf-8'))
    except Exception: return None
    if old.get('schema_version')!='zel.a1_terminal_repair_swarm.v5' or old.get('input_signature')!=signature:return None
    if not isinstance(old.get('global_queue'),list):return None
    return old

def run(output:Path)->dict[str,Any]:
    readiness=_history_readiness(); signature=_input_signature(readiness); cached=_cache_hit(signature)
    if cached is not None:
        result=json.loads(json.dumps(cached)); old_receipt=result.get('receipt_sha256')
        roi=result.setdefault('api_roi',{}); roi['cache_hit']=True; roi['cache_policy']=CACHE_POLICY; roi['cache_source_receipt']=old_receipt; roi['paid_request_count']=0; roi['request_counts']={'openai_batch':0,'gemini_rescue_batch':0,'openai_repair_batch':0}; roi['token_usage_this_run']={'openai':{'input_tokens':0,'output_tokens':0,'total_tokens':0},'gemini':{'input_tokens':0,'output_tokens':0,'total_tokens':0}}
        result['run_mode']='CACHE_HIT_NO_PAID_AI'; result['source_history_readiness']=readiness; result.pop('receipt_sha256',None); result['receipt_sha256']=v4.sha(result)
        output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8'); return result

    v4._history_readiness=lambda: readiness
    v4.evaluate_queue=econ.evaluate_queue
    result=v4.run(output)
    result['funding_axis_probe']=econ.evaluate_candidate(_funding_probe())
    result['source_gate_fix']={'funding_decoupled_from_basis_oi':True,'funding_replay_supported':True,'basis_oi_gate_lowered':False,'basis_oi_backfill_fabricated':False,'historical_coverage_claim_required_for_subaxis':False,'basis_funding_oi_subaxis_flow_required':False,'full_carry_flow_contract_unchanged':True,'basis_oi_prospective_replay_supported_after_gate':True,'combined_basis_funding_oi_ready':bool((result.get('source_history_readiness') or {}).get('basis',{}).get('ready') and (result.get('source_history_readiness') or {}).get('funding',{}).get('ready') and (result.get('source_history_readiness') or {}).get('open_interest',{}).get('ready'))}
    if int(result.get('ledger_done_count') or 0)==25 and result.get('prep_only') is False:
        result['post_econ_alpha_intake']=alpha_intake.build(result)
    else:
        result['post_econ_alpha_intake']={'schema_version':alpha_intake.SCHEMA_VERSION,'state':'BLOCKED_UNTIL_EXACT25_COMPLETE','ledger_done_count':int(result.get('ledger_done_count') or 0),'prep_only':result.get('prep_only'),'development_pass_count':0,'intake_count':0,'intake_ready_count':0,'top_ready_candidate_ids':[],'rows':[],'failures':['EXACT25_NOT_COMPLETE'],**alpha_intake.AUTHORITY}; result['post_econ_alpha_intake']['receipt_sha256']=v4.sha(result['post_econ_alpha_intake'])
    result['schema_version']='zel.a1_terminal_repair_swarm.v5'; result['input_signature']=signature; result['run_mode']='PAID_API_BATCH_CASCADE'
    roi=result.setdefault('api_roi',{}); roi['cache_hit']=False; roi['cache_policy']=CACHE_POLICY; roi['duplicate_paid_call_policy']='IDENTICAL_INPUT_SIGNATURE_ZERO_PAID_AI'; roi['fresh_sample_wait_policy']='ZERO_AI_UNLESS_SIGNATURE_CHANGES'
    result.pop('receipt_sha256',None); result['receipt_sha256']=v4.sha(result)
    output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8'); return result

def self_test()->int:
    assert {'basis','funding','open_interest'}.issubset(econ.SUPPORTED_SOURCES)
    probe=_funding_probe(); assert probe['required_sources']==['funding','ohlcv'] and probe['executable_spec']['max_hold_bars']==8
    s=json.loads(SUBAXIS_CONTRACT.read_text(encoding='utf-8')); assert (s.get('separation_invariant') or {}).get('duration_gate_lowered') is False
    assert alpha_intake.self_test()==0
    assert v4.self_test()==0
    print('PASS_A1_TERMINAL_REPAIR_SWARM_V5_API_ROI_SELF_TEST'); return 0

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,default=Path('out/a1_terminal_repair_swarm_v5.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.output); print(json.dumps({'done':r['ledger_done_count'],'run_mode':r['run_mode'],'paid_requests':(r.get('api_roi') or {}).get('paid_request_count'),'cache_hit':(r.get('api_roi') or {}).get('cache_hit'),'ready_sources':r['replay_ready_sources'],'funding_probe':r['funding_axis_probe'],'alpha_intake':r['post_econ_alpha_intake'],'dev_pass':r['development_economic_pass_count'],'receipt':r['receipt_sha256']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
