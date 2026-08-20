#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, tempfile
from pathlib import Path
from typing import Any, Mapping
from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import EVIDENCE,LEDGER,base_score,critic_payload,dedup,evidence_compact,openai_critic,read_json,safe_error,subprocess_review,validate_candidates
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import harden_candidate
from backend.research.architecture_factory.a1_terminal_repair_swarm_v2 import TERMINAL,canonical,fingerprint,prompt_for,sha
from backend.research.architecture_factory.gemini_provider_v1 import call_gemini_generator,economic_rebuild_enabled
NATIVE_SOURCES={"ohlcv","volume","funding","basis","open_interest","l2_order_book","trade_flow"}
EXEC_KEYS={"bar_interval","features","entry_rule","side_rule","exit_rule","max_hold_bars","entry_timing","cost_model","development_data_rule","parameter_provenance"}

def _gemini_parallel_prep_enabled()->bool:
    explicit=os.environ.get("GEMINI_ECONOMIC_REBUILD_ENABLED","").strip().lower()
    return explicit not in {"0","false","no","off"} and bool(os.environ.get("GEMINI_API_KEY","").strip())
def _exec_valid(spec:Any)->bool:
    if not isinstance(spec,Mapping) or not EXEC_KEYS.issubset(spec): return False
    if str(spec.get("bar_interval")) not in {"5m","15m","30m","1h","4h","1d"}: return False
    if not isinstance(spec.get("features"),list) or not spec.get("features"): return False
    try: hold=int(spec.get("max_hold_bars"))
    except Exception:return False
    return 1<=hold<=720 and all(str(spec.get(k) or "").strip() for k in ("entry_rule","side_rule","exit_rule","entry_timing","cost_model","development_data_rule","parameter_provenance"))
def _attach(raw:Mapping[str,Any],rows:list[dict[str,Any]])->list[dict[str,Any]]:
    specs={str(x.get("candidate_id") or ""):x.get("executable_spec") for x in raw.get("candidates",[]) if isinstance(x,Mapping)}; out=[]
    for r in rows:
        s=specs.get(str(r.get("candidate_id") or ""))
        if _exec_valid(s): out.append({**r,"executable_spec":dict(s),"machine_replayable":True})
    return out
def _source_executable(c:Mapping[str,Any])->bool:
    req=set(c.get("required_sources") or []); return bool(req) and req.issubset(NATIVE_SOURCES) and _exec_valid(c.get("executable_spec"))
def _review(c:Mapping[str,Any],work:Path,env:Mapping[str,str])->dict[str,Any]:
    if not _source_executable(c): return harden_candidate({**c,"source_ready":False,"cross_reviews":{},"independent_passes":0,"independent_rejects":0,"score":round(base_score(c)-20,4),"economic_next":"REJECT_BEFORE_CRITIC"})
    # Quota-safe rule: only cheap/non-Groq critics before economics. Groq and Gemini critic are reserved for Net>0/PF>1 candidates downstream.
    reviews={}
    try: reviews["openai"]=openai_critic(c)
    except Exception as exc: reviews["openai"]={"successful":False,"error":safe_error(exc)}
    reviews["workers_ai"]=subprocess_review("scripts/strategy11_workers_ai_guard.py",c,work,env,"workers")
    passes=sum(1 for r in reviews.values() if r.get("successful") and str(r.get("decision") or "") in {"PASS","PASS_TO_REPLAY","PASS_TO_PREREGISTER"})
    rejects=sum(1 for r in reviews.values() if r.get("successful") and str(r.get("decision") or "")=="REJECT")
    return harden_candidate({**c,"source_ready":True,"cross_reviews":reviews,"independent_passes":passes,"independent_rejects":rejects,"score":round(base_score(c)+passes*2.5-rejects*4,4),"economic_next":"DEVELOPMENT_ECONOMICS_REQUIRED; GROQ_GEMINI_CRITIC_ONLY_IF_NET_POSITIVE_PF_GT_1"})
def _batch_prompt(fps:list[dict[str,Any]],evidence:list[dict[str,Any]])->str:
    return "You are the quota-limited senior research architect. Analyze ALL terminal failures in one call. Return JSON with candidates. Produce at most one best executable single-axis repair per failure and at most three distinct replacement architectures total. Every candidate must follow the same executable_spec contract as the supplied failure prompts, cite evidence_ids, use native sources only, and optimize realistic-cost Net/PF/DD rather than consensus. Do not browse or invent evidence.\nFAILURES="+canonical(fps)+"\nEVIDENCE="+canonical(evidence[:30])
def run(output:Path)->dict[str,Any]:
    ledger,evidence=read_json(LEDGER),read_json(EVIDENCE); done=int(ledger.get("done_count") or 0); source=evidence_compact(evidence); source_ids={str(x.get("id")) for x in source}; terminals=[(sid,r) for sid,r in (ledger.get("strategies") or {}).items() if isinstance(r,Mapping) and r.get("status") in TERMINAL]; fps=[fingerprint(s,r) for s,r in terminals]
    generated=[]; providers={}; from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import call_openai_generator
    # OpenAI remains per-failure builder; Gemini is one batch call; Groq generation is disabled to preserve daily tokens for post-economics red-team.
    for fp in fps:
        sid=fp["strategy_id"]; providers[sid]={"groq":{"successful":False,"skipped":True,"reason":"QUOTA_RESERVED_POST_ECONOMICS"}}
        try:
            model,raw,lineage=call_openai_generator(prompt_for(fp,source)); rows=_attach(raw,validate_candidates(raw,"openai",source_ids,{sid})); providers[sid]["openai"]={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows)}; generated.extend(rows)
        except Exception as exc: providers[sid]["openai"]={"successful":False,"error":safe_error(exc),"candidate_count":0}
    gemini_batch={"successful":False,"skipped":True,"reason":"DISABLED_OR_NO_KEY"}
    if _gemini_parallel_prep_enabled() and fps:
        try:
            model,raw,lineage=call_gemini_generator(_batch_prompt(fps,source)); rows=validate_candidates(raw,"gemini",source_ids,{x[0] for x in terminals}); rows=_attach(raw,rows); generated.extend(rows); gemini_batch={"successful":bool(rows),"model":model,**lineage,"candidate_count":len(rows),"machine_replayable_count":len(rows),"request_count":1}
        except Exception as exc: gemini_batch={"successful":False,"error":safe_error(exc),"candidate_count":0,"request_count":1}
    generated=dedup(sorted(generated,key=lambda x:-base_score(x)),0.85); reviewed=[]; env=os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="a1-v4-") as td:
        for i,c in enumerate(generated):
            w=Path(td)/str(i); w.mkdir(); reviewed.append(_review(c,w,env))
    reviewed.sort(key=lambda x:(-float(x.get("score") or 0),str(x.get("candidate_id") or ""))); by={}
    for fp in fps:
        sid=fp["strategy_id"]; rows=[x for x in reviewed if x.get("strategy_id")==sid]; by[sid]={"fingerprint":fp,"repair_top3":[x for x in rows if x.get("mode")=="REPAIR"][:3],"new_architecture":[x for x in rows if x.get("mode")=="NEW_ARCHITECTURE"][:2]}
    result={"schema_version":"zel.a1_terminal_repair_swarm.v4","ledger_done_count":done,"survivor_count":int(ledger.get("survivor_count") or 0),"terminal_count":len(terminals),"terminal_strategy_ids":[s for s,_ in terminals],"machine_replayable_count":sum(1 for x in reviewed if x.get("machine_replayable")),"queued_repair_count":sum(len(v["repair_top3"]) for v in by.values()),"queued_new_arch_count":sum(len(v["new_architecture"]) for v in by.values()),"alpha_proof_ready_count":sum(1 for x in reviewed if x.get("alpha_proof_candidate_ready")),"eligible_count":0,"provider_state":providers,"gemini_batch":gemini_batch,"strategies":by,"global_queue":reviewed,"api_economics_policy":{"objective":"validated_net_improvement_per_api_cost","gemini_generation":"ONE_BATCH_PER_SWARM","groq_generation":"DISABLED","groq_critic":"ONLY_AFTER_NET_GT_0_AND_PF_GT_1","gemini_critic":"ONLY_AFTER_NET_GT_0_AND_PF_GT_1","development_economics":"BEFORE_EXPENSIVE_CRITICS"},"phase":"GEN1_PARALLEL_GEN2_PREP" if done<25 else "POST25_ECONOMIC_REBUILD","prep_only":done<25,"research_only":True,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0,"launch":{"state":"BLOCKED_GEN1_INCOMPLETE" if done<25 else "BLOCKED_UNTIL_PASS_ALPHA_PROOF_RECEIPT"}}
    result["receipt_sha256"]=sha(result); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"); return result
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path("out/a1_terminal_repair_swarm_v4.json")); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: assert economic_rebuild_enabled(24) is False; print("PASS_A1_TERMINAL_REPAIR_SWARM_V4_SELF_TEST"); return 0
    r=run(a.output); print(canonical({"done_count":r["ledger_done_count"],"terminal_count":r["terminal_count"],"machine_replayable_count":r["machine_replayable_count"],"gemini_batch":r["gemini_batch"]})); return 0
if __name__=="__main__": raise SystemExit(main())
