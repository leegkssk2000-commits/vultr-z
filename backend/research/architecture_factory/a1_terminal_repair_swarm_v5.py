#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, urllib.request
from pathlib import Path
from typing import Any

from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as v4
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v2 as econ

CONTRACT=Path('backend/research/contracts/p3_carry_flow_prospective_native_v1.json')
P3_COVERAGE_URL=v4.P3_COVERAGE_URL


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
        out['funding']={'ready':False,'reason':'P3_CONTRACT_READ_FAILED','error':f'{type(exc).__name__}:{str(exc)[:160]}'}
    try:
        with urllib.request.urlopen(P3_COVERAGE_URL,timeout=15) as r: cov=json.loads(r.read().decode('utf-8'))
        gate=bool(cov.get('basis_oi_duration_gate_pass')) and bool(cov.get('historical_coverage_claim'))
        ratio=float(cov.get('minimum_coverage_progress_ratio') or 0.0); state=str(cov.get('state') or '')
        required=int(cov.get('required_capture_span_ms') or 0)
        spans=[int(x.get('capture_span_ms') or 0) for x in cov.get('results') or [] if isinstance(x,dict)]
        captured=min(spans) if spans else int(required*ratio)
        remaining=max(0,required-captured)
        common={'coverage_progress_ratio':ratio,'coverage_state':state,'coverage_receipt':cov.get('receipt_sha256'),'required_capture_span_ms':required,'captured_min_span_ms':captured,'remaining_span_ms':remaining,'remaining_days':remaining/86_400_000 if required else None,'prospective_only':True,'historical_backfill_allowed':False}
        for s in ('basis','open_interest'):
            out[s]={'ready':gate,'reason':'P3_FROZEN_21D_HISTORY_GATE_PASS' if gate else 'P3_FROZEN_21D_HISTORY_GATE_PENDING',**common}
        out['basis_oi_combined_gate']={'ready':gate,'reason':'ALL_BASIS_OI_STREAMS_21D_REQUIRED','coverage_progress_ratio':ratio,'remaining_days':common['remaining_days']}
    except Exception as exc:
        err=f'{type(exc).__name__}:{str(exc)[:160]}'
        for s in ('basis','open_interest'): out[s]={'ready':False,'reason':'P3_COVERAGE_FETCH_FAILED','error':err}
        out['basis_oi_combined_gate']={'ready':False,'reason':'P3_COVERAGE_FETCH_FAILED','error':err}
    return out


def _funding_probe()->dict[str,Any]:
    return {
      'candidate_id':'fixed_funding_change_mean_reversion_probe_v1','strategy_id':'NEW','provider':'fixed_evidence_probe','required_sources':['funding','ohlcv'],
      'executable_spec':{
        'bar_interval':'1h',
        'features':[{'name':'funding_delta','formula':'funding_rate-lag(funding_rate,1)'}],
        'entry_rule':'funding_delta != 0',
        'side_rule':'short if funding_rate > 0 else long',
        'exit_rule':'time_stop','max_hold_bars':8,'entry_timing':'next_bar_open','cost_model':'verified_14bps_round_trip','development_data_rule':'strictly_pre_GEN1_boundary','parameter_provenance':'natural 8h funding interval; no outcome sweep'
      },
      'evidence_ids':['F18','F3','F17'],'development_only':True,'selection_authority':False,'promotion_authority':False
    }


def run(output:Path)->dict[str,Any]:
    v4._history_readiness=_history_readiness
    v4.evaluate_queue=econ.evaluate_queue
    result=v4.run(output)
    result['funding_axis_probe']=econ.evaluate_candidate(_funding_probe())
    result['source_gate_fix']={
      'funding_decoupled_from_basis_oi':True,
      'funding_replay_supported':True,
      'basis_oi_gate_lowered':False,
      'basis_oi_backfill_fabricated':False,
      'combined_basis_funding_oi_ready':bool((result.get('source_history_readiness') or {}).get('basis',{}).get('ready') and (result.get('source_history_readiness') or {}).get('funding',{}).get('ready') and (result.get('source_history_readiness') or {}).get('open_interest',{}).get('ready')),
    }
    result['schema_version']='zel.a1_terminal_repair_swarm.v5'
    result.pop('receipt_sha256',None); result['receipt_sha256']=v4.sha(result)
    output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return result


def self_test()->int:
    assert 'funding' in econ.SUPPORTED_SOURCES
    probe=_funding_probe(); assert probe['required_sources']==['funding','ohlcv'] and probe['executable_spec']['max_hold_bars']==8
    print('PASS_A1_TERMINAL_REPAIR_SWARM_V5_SELF_TEST'); return 0


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,default=Path('out/a1_terminal_repair_swarm_v5.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.output); print(json.dumps({'done':r['ledger_done_count'],'ready_sources':r['replay_ready_sources'],'history':r['source_history_readiness'],'funding_probe':r['funding_axis_probe'],'evidence':r['evidence_summary'],'receipt':r['receipt_sha256']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
