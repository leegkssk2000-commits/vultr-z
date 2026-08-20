#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import EVIDENCE, LEDGER, base_score, dedup, evidence_compact, read_json, safe_error, validate_candidates
from backend.research.architecture_factory.a1_terminal_repair_swarm_v2 import TERMINAL, canonical, fingerprint, prompt_for, sha
from backend.research.architecture_factory.gemini_provider_v1 import call_gemini_generator, economic_rebuild_enabled
from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import evaluate_queue

NATIVE_SOURCES={"ohlcv","volume","funding","basis","open_interest","l2_order_book","trade_flow"}
EXEC_KEYS={"bar_interval","features","entry_rule","side_rule","exit_rule","max_hold_bars","entry_timing","cost_model","development_data_rule","parameter_provenance"}

def _gemini_enabled()->bool:
    x=os.environ.get("GEMINI_ECONOMIC_REBUILD_ENABLED","").strip().lower()
    return x not in {"0","false","no","off"} and bool(os.environ.get("GEMINI_API_KEY","").strip())

def _exec_valid(spec:Any)->bool:
    if not isinstance(spec,Mapping) or not EXEC_KEYS.issubset(spec): return False
    if str(spec.get("bar_interval")) not in {"5m","15m","30m","1h","4h","1d"}: return False
    fs=spec.get("features")
    if not isinstance(fs,list) or not fs or not all(isinstance(x,Mapping) and str(x.get("name") or "").strip() and str(x.get("formula") or "").strip() for x in fs): return False
    try: h=int(spec.get("max_hold_bars"))
    except Exception: return False
    if not 1<=h<=720: return False
    return all(str(spec.get(k) or "").strip() for k in ("entry_rule","side_rule","exit_rule","entry_timing","cost_model","development_data_rule","parameter_provenance"))

def _attach(raw:Mapping[str,Any], rows:list[dict[str,Any]])->list[dict[str,Any]]:
    specs={str(x.get("candidate_id") or ""):x.get("executable_spec") for x in raw.get("candidates",[]) if isinstance(x,Mapping)}
    out=[]
    for row in rows:
        spec=specs.get(str(row.get("candidate_id") or "")); req=set(row.get("required_sources") or [])
        if _exec_valid(spec) and req and req.issubset(NATIVE_SOURCES):
            out.append({**row,"executable_spec":dict(spec),"machine_replayable":True,"source_ready":True,"score":round(base_score(row),4),"alpha_proof_candidate_ready":False,"economic_next":"AUTO_DEVELOPMENT_REPLAY"})
    return out

def _batch_prompt(fps:list[dict[str,Any]], evidence:list[dict[str,Any]])->str:
    return (
      "You are the quota-limited senior ECONOMIC strategy builder. Analyze ALL terminal failures in ONE call. "
      "Produce at most one best single-axis REPAIR per terminal failure and at most three distinct NEW_ARCHITECTURE replacements total. "
      "Every candidate must include a deterministic executable_spec. Prefer OHLCV/volume candidates when mechanism evidence supports them because those can be replayed immediately; use funding/basis/OI/flow only when causally necessary. "
      "Cite supplied evidence_ids, including verified YouTube only as hypothesis evidence and papers as mechanism evidence. Never invent evidence. "
      "No critic work, no threshold sweep, no outcome tuning. Next gate is automatic development economics at 14bps realistic cost; Net<=0 or PF<=1 dies before any critic.\nFAILURES="+canonical(fps)+"\nEVIDENCE="+canonical(evidence[:30])
    )

def run(output:Path)->dict[str,Any]:
    ledger=read_json(LEDGER); evidence=read_json(EVIDENCE); done=int(ledger.get("done_count") or 0)
    source=evidence_compact(evidence); source_ids={str(x.get("id")) for x in source}
    terminals=[(sid,raw) for sid,raw in (ledger.get("strategies") or {}).items() if isinstance(raw,Mapping) and raw.get("status") in TERMINAL]
    fps=[fingerprint(sid,raw) for sid,raw in terminals]; generated=[]; providers={}
    from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import call_openai_generator
    for fp in fps:
        sid=fp["strategy_id"]; providers[sid]={"groq":{"successful":False,"skipped":True,"reason":"RESERVED_POST_ECONOMICS_ONLY"}}
        try:
            model,raw,lineage=call_openai_generator(prompt_for(fp,source)); rows=_attach(raw,validate_candidates(raw,"openai",source_ids,{sid})); generated+=rows
            providers[sid]["openai"]={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows)}
        except Exception as exc:
            providers[sid]["openai"]={"successful":False,"error":safe_error(exc),"candidate_count":0,"machine_replayable_count":0}
    gemini_batch={"successful":False,"skipped":True,"reason":"DISABLED_OR_NO_KEY","request_count":0}
    if _gemini_enabled() and fps:
        try:
            model,raw,lineage=call_gemini_generator(_batch_prompt(fps,source)); rows=_attach(raw,validate_candidates(raw,"gemini",source_ids,{sid for sid,_ in terminals})); generated+=rows
            gemini_batch={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows),"request_count":1}
        except Exception as exc:
            gemini_batch={"successful":False,"error":safe_error(exc),"candidate_count":0,"machine_replayable_count":0,"request_count":1}
    queue=dedup(sorted(generated,key=lambda x:-base_score(x)),0.85); queue.sort(key=lambda x:(-float(x.get("score") or 0),str(x.get("candidate_id") or "")))
    dev=evaluate_queue(queue)
    passed_ids={str(x.get("candidate_id")) for x in dev.get("passes",[])}
    for x in queue:
        x["development_economic_pass"]=str(x.get("candidate_id")) in passed_ids
        x["economic_next"]="POST_ECONOMICS_CRITIC" if x["development_economic_pass"] else "REJECT_OR_SOURCE_WAIT"
    by={}
    for fp in fps:
        sid=fp["strategy_id"]; rows=[x for x in queue if x.get("strategy_id")==sid]
        by[sid]={"fingerprint":fp,"repair_top3":[x for x in rows if x.get("mode")=="REPAIR"][:3],"new_architecture":[x for x in rows if x.get("mode")=="NEW_ARCHITECTURE"][:2]}
    cov=evidence.get("coverage") if isinstance(evidence.get("coverage"),Mapping) else {}
    result={"schema_version":"zel.a1_terminal_repair_swarm.v4","ledger_done_count":done,"survivor_count":int(ledger.get("survivor_count") or 0),"terminal_count":len(terminals),"terminal_strategy_ids":[sid for sid,_ in terminals],"machine_replayable_count":len(queue),"queued_repair_count":sum(len(v["repair_top3"]) for v in by.values()),"queued_new_arch_count":sum(len(v["new_architecture"]) for v in by.values()),"development_economics":dev,"development_economic_pass_count":int(dev.get("economic_pass_count") or 0),"alpha_proof_ready_count":0,"eligible_count":0,"provider_state":providers,"gemini_batch":gemini_batch,"evidence_summary":{"peer_reviewed":int(cov.get("peer_reviewed") or 0),"working_paper":int(cov.get("working_paper") or 0),"primary_preprint":int(cov.get("primary_preprint") or 0),"verified_youtube":int(cov.get("verified_youtube") or 0),"youtube_preferred_100k_plus":int(cov.get("youtube_preferred_100k_plus") or 0),"youtube_fallback_30k_plus":int(cov.get("youtube_fallback_30k_plus") or 0)},"strategies":by,"global_queue":queue,"api_economics_policy":{"objective":"validated_net_improvement_per_api_cost","gemini_generation":"ONE_BATCH_PER_SWARM","groq_generation":"DISABLED","all_pre_economics_critics":"DISABLED","development_economics":"AUTOMATIC_SAME_RUN","post_economics_critics":"ONLY_NET_GT_0_AND_PF_GT_1","reject_after_replay":"NET_LE_0_OR_PF_LE_1"},"phase":"GEN1_PARALLEL_GEN2_PREP" if done<25 else "POST25_ECONOMIC_REBUILD","prep_only":done<25,"research_only":True,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0,"launch":{"state":"BLOCKED_GEN1_INCOMPLETE" if done<25 else "BLOCKED_UNTIL_PASS_ALPHA_PROOF_RECEIPT"}}
    result["receipt_sha256"]=sha(result); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); return result

def self_test()->int:
    assert economic_rebuild_enabled(24) is False
    assert _exec_valid({"bar_interval":"1h","features":[{"name":"r","formula":"close/open-1"}],"entry_rule":"r>0","side_rule":"long","exit_rule":"time_stop","max_hold_bars":4,"entry_timing":"next_bar_open","cost_model":"14bps","development_data_rule":"pre_boundary","parameter_provenance":"evidence"})
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V4_SELF_TEST"); return 0

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path("out/a1_terminal_repair_swarm_v4.json")); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.output); print(canonical({"done":r["ledger_done_count"],"terminal":r["terminal_count"],"machine":r["machine_replayable_count"],"dev_pass":r["development_economic_pass_count"],"gemini_batch":r["gemini_batch"],"evidence":r["evidence_summary"]})); return 0
if __name__=="__main__": raise SystemExit(main())
