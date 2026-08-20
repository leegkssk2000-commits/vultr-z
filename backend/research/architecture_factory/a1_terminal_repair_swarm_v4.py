#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import EVIDENCE, LEDGER, base_score, dedup, evidence_compact, read_json, safe_error, validate_candidates
from backend.research.architecture_factory.a1_terminal_repair_swarm_v2 import TERMINAL, canonical, fingerprint, prompt_for, sha
from backend.research.architecture_factory.gemini_provider_v1 import call_gemini_generator, economic_rebuild_enabled
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import evaluate_queue
from backend.research.architecture_factory.a1_failure_economics_v1 import analyze as analyze_failure_economics
from backend.research.architecture_factory.a1_alpha_primitive_miner_v1 import mine as mine_primitives, compact as compact_primitives

NATIVE_SOURCES={"ohlcv","volume","funding","basis","open_interest","l2_order_book","trade_flow"}
EXEC_KEYS={"bar_interval","features","entry_rule","side_rule","exit_rule","max_hold_bars","entry_timing","cost_model","development_data_rule","parameter_provenance"}
P3_COVERAGE_URL="https://raw.githubusercontent.com/leegkssk2000-commits/vultr-z/zel-p3-prospective-data/research/data/p3_prospective/latest_coverage.json"
SINGLE_REPAIR_BUDGET=3

def _gemini_enabled()->bool:
    x=os.environ.get("GEMINI_ECONOMIC_REBUILD_ENABLED","").strip().lower()
    return x not in {"0","false","no","off"} and bool(os.environ.get("GEMINI_API_KEY","").strip())

def _history_readiness()->dict[str,Any]:
    out:dict[str,Any]={
        "ohlcv":{"ready":True,"reason":"BINGX_KLINE_PRE_BOUNDARY_PULL_AVAILABLE"},
        "volume":{"ready":True,"reason":"BINGX_KLINE_PRE_BOUNDARY_PULL_AVAILABLE"},
        "basis":{"ready":False,"reason":"P3_COVERAGE_UNVERIFIED"},
        "funding":{"ready":False,"reason":"P3_COVERAGE_UNVERIFIED"},
        "open_interest":{"ready":False,"reason":"P3_COVERAGE_UNVERIFIED"},
        "l2_order_book":{"ready":False,"reason":"NO_DEVELOPMENT_HISTORY_BOUND"},
        "trade_flow":{"ready":False,"reason":"NO_DEVELOPMENT_HISTORY_BOUND"},
    }
    try:
        with urllib.request.urlopen(P3_COVERAGE_URL,timeout=15) as r:
            cov=json.loads(r.read().decode("utf-8"))
        gate=bool(cov.get("basis_oi_duration_gate_pass")) and bool(cov.get("historical_coverage_claim"))
        ratio=float(cov.get("minimum_coverage_progress_ratio") or 0.0); state=str(cov.get("state") or "")
        for s in ("basis","funding","open_interest"):
            out[s]={"ready":gate,"reason":"P3_FROZEN_HISTORY_GATE_PASS" if gate else "P3_FROZEN_HISTORY_GATE_PENDING","coverage_progress_ratio":ratio,"coverage_state":state,"coverage_receipt":cov.get("receipt_sha256")}
    except Exception as exc:
        err=f"{type(exc).__name__}:{str(exc)[:160]}"
        for s in ("basis","funding","open_interest"): out[s]={"ready":False,"reason":"P3_COVERAGE_FETCH_FAILED","error":err}
    return out

def _allowed_sources(readiness:Mapping[str,Any])->set[str]:
    return {k for k,v in readiness.items() if isinstance(v,Mapping) and v.get("ready") is True}

def _exec_valid(spec:Any)->bool:
    if not isinstance(spec,Mapping) or not EXEC_KEYS.issubset(spec): return False
    if str(spec.get("bar_interval")) not in {"5m","15m","30m","1h","4h","1d"}: return False
    fs=spec.get("features")
    if not isinstance(fs,list) or not fs or not all(isinstance(x,Mapping) and str(x.get("name") or "").strip() and str(x.get("formula") or "").strip() for x in fs): return False
    try: h=int(spec.get("max_hold_bars"))
    except Exception: return False
    if not 1<=h<=720: return False
    return all(str(spec.get(k) or "").strip() for k in ("entry_rule","side_rule","exit_rule","entry_timing","cost_model","development_data_rule","parameter_provenance"))

def _attach(raw:Mapping[str,Any],rows:list[dict[str,Any]],allowed:set[str])->list[dict[str,Any]]:
    specs={str(x.get("candidate_id") or ""):x.get("executable_spec") for x in raw.get("candidates",[]) if isinstance(x,Mapping)}; out=[]
    for row in rows:
        spec=specs.get(str(row.get("candidate_id") or "")); req=set(row.get("required_sources") or [])
        if _exec_valid(spec) and req and req.issubset(NATIVE_SOURCES) and req.issubset(allowed):
            out.append({**row,"executable_spec":dict(spec),"machine_replayable":True,"source_ready":True,"score":round(base_score(row),4),"alpha_proof_candidate_ready":False,"economic_next":"AUTO_DEVELOPMENT_REPLAY"})
    return out

def _source_contract(readiness:Mapping[str,Any])->str:
    allowed=sorted(_allowed_sources(readiness)); blocked=sorted(k for k in readiness if k not in allowed)
    return (
        "SOURCE_HISTORY_CONTRACT="+canonical(readiness)+"\n"
        "HARD RULE: required_sources MUST be a non-empty subset of REPLAY_READY_SOURCES="+canonical(allowed)+". "
        "Do not emit candidates requiring BLOCKED_SOURCES="+canonical(blocked)+". Native ownership without sufficient history is NOT source-ready. "
    )

def _primitive_contract(primitives:list[dict[str,Any]])->str:
    if primitives:
        return (
            "ALPHA_PRIMITIVES="+canonical(primitives)+"\n"
            "HARD RULE: these primitives were mined from fixed pre-boundary tests with 14bps cost and minimum event count. Prefer mechanisms that preserve or causally combine these observed effects. "
            "Do NOT retune their thresholds/horizons from outcomes. If you use one, name its primitive_id in why_distinct or mechanism. "
        )
    return (
        "ALPHA_PRIMITIVES=[]\nHARD RULE: no fixed OHLCV/volume primitive currently clears Net>0 and PF>1 at 14bps. "
        "Do not fabricate an OHLCV edge. Emit only a genuinely distinct replacement rationale that can later use a newly-ready source, or zero candidates. "
    )

def _batch_prompt(fps:list[dict[str,Any]],evidence:list[dict[str,Any]],readiness:Mapping[str,Any],primitives:list[dict[str,Any]])->str:
    return (
      "You are the quota-limited senior ECONOMIC strategy builder. Analyze ALL terminal failures in ONE call. "
      "Produce at most one best single-axis REPAIR per terminal failure and at most three distinct NEW_ARCHITECTURE replacements total. "
      +_source_contract(readiness)+_primitive_contract(primitives)+
      "Every candidate must include a deterministic executable_spec under EXECUTABLE_DSL_V1. Cite supplied evidence_ids. Never invent evidence. "
      "No critic work, threshold sweep, or outcome tuning. Next gate is automatic development economics at 14bps; Net<=0 or PF<=1 dies before any critic.\nFAILURES="+canonical(fps)+"\nEVIDENCE="+canonical(evidence[:30])
    )

def _single_repair_prompt(fail:Mapping[str,Any],evidence:list[dict[str,Any]],readiness:Mapping[str,Any],primitives:list[dict[str,Any]])->str:
    return (
        "You are an economic repair engineer. This candidate already FAILED deterministic development replay. You get exactly ONE causal repair attempt; no sweep or variants. "
        "Preserve the payer/mechanism and alter exactly one causal axis that can plausibly exceed REQUIRED_NET_IMPROVEMENT_BPS_PER_TRADE. If not plausible, emit zero candidates. "
        +_source_contract(readiness)+_primitive_contract(primitives)+
        "Return at most ONE REPAIR with deterministic executable_spec and evidence_ids. Same development-only authority and 14bps cost. "
        "FAILED_CANDIDATE_ECONOMICS="+canonical(fail)+"\nEVIDENCE="+canonical(evidence[:30])
    )

def run(output:Path)->dict[str,Any]:
    ledger=read_json(LEDGER); evidence=read_json(EVIDENCE); done=int(ledger.get("done_count") or 0)
    source=evidence_compact(evidence); source_ids={str(x.get("id")) for x in source}
    readiness=_history_readiness(); allowed=_allowed_sources(readiness)
    primitive_result=mine_primitives(); primitives=compact_primitives(primitive_result)
    terminals=[(sid,raw) for sid,raw in (ledger.get("strategies") or {}).items() if isinstance(raw,Mapping) and raw.get("status") in TERMINAL]
    fps=[fingerprint(sid,raw) for sid,raw in terminals]; generated=[]; providers={}
    from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import call_openai_generator
    for fp in fps:
        sid=fp["strategy_id"]; providers[sid]={"groq":{"successful":False,"skipped":True,"reason":"RESERVED_POST_ECONOMICS_ONLY"}}
        try:
            p=prompt_for(fp,source)+"\n"+_source_contract(readiness)+_primitive_contract(primitives)
            model,raw,lineage=call_openai_generator(p); rows=_attach(raw,validate_candidates(raw,"openai",source_ids,{sid}),allowed); generated+=rows
            providers[sid]["openai"]={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows)}
        except Exception as exc: providers[sid]["openai"]={"successful":False,"error":safe_error(exc),"candidate_count":0,"machine_replayable_count":0}
    gemini_batch={"successful":False,"skipped":True,"reason":"DISABLED_OR_NO_KEY","request_count":0}
    if _gemini_enabled() and fps:
        try:
            model,raw,lineage=call_gemini_generator(_batch_prompt(fps,source,readiness,primitives)); rows=_attach(raw,validate_candidates(raw,"gemini",source_ids,{sid for sid,_ in terminals}),allowed); generated+=rows
            gemini_batch={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows),"request_count":1}
        except Exception as exc: gemini_batch={"successful":False,"error":safe_error(exc),"candidate_count":0,"machine_replayable_count":0,"request_count":1}
    queue=dedup(sorted(generated,key=lambda x:-base_score(x)),0.85); queue.sort(key=lambda x:(-float(x.get("score") or 0),str(x.get("candidate_id") or "")))
    dev=evaluate_queue(queue); failure_econ=analyze_failure_economics(dev,queue,SINGLE_REPAIR_BUDGET)
    causal_repairs:list[dict[str,Any]]=[]; causal_repair_calls=[]
    for fail in failure_econ.get("selected_for_single_repair") or []:
        sid=str(fail.get("strategy_id") or ""); call_state={"parent_candidate_id":fail.get("candidate_id"),"strategy_id":sid,"required_net_improvement_bps_per_trade":fail.get("required_net_improvement_bps_per_trade")}
        try:
            model,raw,lineage=call_openai_generator(_single_repair_prompt(fail,source,readiness,primitives)); rows=_attach(raw,validate_candidates(raw,"openai",source_ids,{sid}),allowed)[:1]
            for x in rows: x["parent_candidate_id"]=fail.get("candidate_id"); x["repair_iteration"]=1; x["repair_axis_budget_exhausted_after_this"]=True
            causal_repairs.extend(rows); call_state.update({"successful":bool(rows),"model":model,"candidate_count":len(rows),**lineage})
        except Exception as exc: call_state.update({"successful":False,"candidate_count":0,"error":safe_error(exc)})
        causal_repair_calls.append(call_state)
    causal_repairs=dedup(causal_repairs,0.85)
    causal_repair_dev=evaluate_queue(causal_repairs) if causal_repairs else {"economic_pass_count":0,"economic_fail_count":0,"source_skip_count":0,"spec_reject_count":0,"passes":[],"rows":[]}
    passed_ids={str(x.get("candidate_id")) for x in dev.get("passes",[])}
    for x in queue:
        x["development_economic_pass"]=str(x.get("candidate_id")) in passed_ids; x["economic_next"]="POST_ECONOMICS_CRITIC" if x["development_economic_pass"] else "REJECT_OR_SINGLE_REPAIR_ONLY_IF_SELECTED"
    repair_pass_ids={str(x.get("candidate_id")) for x in causal_repair_dev.get("passes",[])}
    for x in causal_repairs:
        x["development_economic_pass"]=str(x.get("candidate_id")) in repair_pass_ids; x["economic_next"]="POST_ECONOMICS_CRITIC" if x["development_economic_pass"] else "TERMINAL_REPAIR_FAIL_NO_MORE_AI"
    by={}
    for fp in fps:
        sid=fp["strategy_id"]; rows=[x for x in queue if x.get("strategy_id")==sid]; by[sid]={"fingerprint":fp,"repair_top3":[x for x in rows if x.get("mode")=="REPAIR"][:3],"new_architecture":[x for x in rows if x.get("mode")=="NEW_ARCHITECTURE"][:2]}
    cov=evidence.get("coverage") if isinstance(evidence.get("coverage"),Mapping) else {}; total_pass=int(dev.get("economic_pass_count") or 0)+int(causal_repair_dev.get("economic_pass_count") or 0)
    result={"schema_version":"zel.a1_terminal_repair_swarm.v4","ledger_done_count":done,"survivor_count":int(ledger.get("survivor_count") or 0),"terminal_count":len(terminals),"terminal_strategy_ids":[sid for sid,_ in terminals],"source_history_readiness":readiness,"replay_ready_sources":sorted(allowed),"alpha_primitive_mining":primitive_result,"machine_replayable_count":len(queue),"queued_repair_count":sum(len(v["repair_top3"]) for v in by.values()),"queued_new_arch_count":sum(len(v["new_architecture"]) for v in by.values()),"development_economics":dev,"failure_economics":failure_econ,"causal_repair_calls":causal_repair_calls,"causal_repairs":causal_repairs,"causal_repair_development_economics":causal_repair_dev,"development_economic_pass_count":total_pass,"alpha_proof_ready_count":0,"eligible_count":0,"provider_state":providers,"gemini_batch":gemini_batch,"evidence_summary":{"peer_reviewed":int(cov.get("peer_reviewed") or 0),"working_paper":int(cov.get("working_paper") or 0),"primary_preprint":int(cov.get("primary_preprint") or 0),"verified_youtube":int(cov.get("verified_youtube") or 0),"youtube_preferred_100k_plus":int(cov.get("youtube_preferred_100k_plus") or 0),"youtube_fallback_30k_plus":int(cov.get("youtube_fallback_30k_plus") or 0)},"strategies":by,"global_queue":queue,"api_economics_policy":{"objective":"validated_net_improvement_per_api_cost","source_history_gate":"BEFORE_CANDIDATE_ACCEPTANCE","alpha_primitive_gate":"FIXED_LIBRARY_COST_ADJUSTED_BEFORE_AI","builder_requires":"COST_POSITIVE_PRIMITIVE_OR_DISTINCT_REPLACEMENT","gemini_generation":"ONE_BATCH_PER_SWARM","groq_generation":"DISABLED","all_pre_economics_critics":"DISABLED","development_economics":"AUTOMATIC_SAME_RUN","failure_economics":"MANDATORY_BEFORE_REPAIR_API","single_causal_repair_budget":SINGLE_REPAIR_BUDGET,"gross_nonpositive":"NO_REPAIR_API_REPLACE_ARCHITECTURE","post_economics_critics":"ONLY_NET_GT_0_AND_PF_GT_1","reject_after_replay":"NET_LE_0_OR_PF_LE_1"},"phase":"GEN1_PARALLEL_GEN2_PREP" if done<25 else "POST25_ECONOMIC_REBUILD","prep_only":done<25,"research_only":True,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0,"launch":{"state":"BLOCKED_GEN1_INCOMPLETE" if done<25 else "BLOCKED_UNTIL_PASS_ALPHA_PROOF_RECEIPT"}}
    result["receipt_sha256"]=sha(result); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); return result

def self_test()->int:
    assert economic_rebuild_enabled(24) is False
    assert _exec_valid({"bar_interval":"1h","features":[{"name":"r","formula":"close/open-1"}],"entry_rule":"r>0","side_rule":"long","exit_rule":"time_stop","max_hold_bars":4,"entry_timing":"next_bar_open","cost_model":"14bps","development_data_rule":"pre_boundary","parameter_provenance":"evidence"})
    assert _allowed_sources({"ohlcv":{"ready":True},"basis":{"ready":False}})=={"ohlcv"}
    x=analyze_failure_economics({"cost_bps_per_trade":14,"rows":[{"candidate_id":"a","state":"FAIL_DEVELOPMENT_ECONOMICS","metrics":{"trades":20,"gross_expectancy_bps":8,"net_expectancy_bps":-6,"profit_factor":0.7}}]},[{"candidate_id":"a"}],3)
    assert x["selected_for_single_repair"][0]["candidate_id"]=="a"
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V4_SELF_TEST"); return 0

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path("out/a1_terminal_repair_swarm_v4.json")); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.output); print(canonical({"done":r["ledger_done_count"],"terminal":r["terminal_count"],"ready_sources":r["replay_ready_sources"],"primitive_usable":r["alpha_primitive_mining"]["economically_usable_count"],"machine":r["machine_replayable_count"],"dev_pass":r["development_economic_pass_count"],"failure_economics":r["failure_economics"],"causal_repair_dev":r["causal_repair_development_economics"],"gemini_batch":r["gemini_batch"],"evidence":r["evidence_summary"]})); return 0
if __name__=="__main__": raise SystemExit(main())
