#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import (
    EVIDENCE, LEDGER, base_score, call_groq_generator, call_openai_generator, dedup,
    evidence_compact, openai_critic, read_json, safe_error, subprocess_review, validate_candidates,
)

TERMINAL = {"A1_ECONOMIC_FAIL","A1_COST_FUTILITY","A1_CAUSAL_CONTROL_FAIL","A1_SPARSE_EVENT_FUTILITY"}

def canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
def sha(v: Any) -> str:
    return hashlib.sha256(canonical(v).encode()).hexdigest()

def fingerprint(sid: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    gross=raw.get("gross_expectancy_bps"); net=raw.get("net_expectancy_bps"); status=str(raw.get("status") or ""); cost=float(raw.get("verified_pretrade_cost_bps") or 14.0)
    if status=="A1_SPARSE_EVENT_FUTILITY": primary="STRUCTURAL_EVENT_RATE_TOO_LOW"; diagnosis="Frozen mechanism exhausted its prospective resource budget with too few decisions; threshold loosening is forbidden."
    elif isinstance(gross,(int,float)) and float(gross)<=0: primary="NEGATIVE_GROSS_EDGE"; diagnosis="Frozen mechanism loses before costs; payer/direction/horizon thesis requires redesign rather than fee or threshold rescue."
    elif isinstance(gross,(int,float)) and float(gross)<cost: primary="POSITIVE_GROSS_EDGE_BELOW_COST"; diagnosis="Frozen mechanism shows raw edge but natural move is below verified round-trip cost geometry."
    else: primary="TERMINAL_ECONOMIC_OR_CAUSAL_FAIL"; diagnosis="Frozen mechanism failed its terminal gate and may only be tested through a fresh single-axis repair or distinct replacement architecture."
    return {"strategy_id":sid,"terminal_status":status,"terminal_reason":raw.get("terminal_reason"),"primary":primary,"diagnosis":diagnosis,"baseline":{"receipt_sha":raw.get("receipt_sha"),"config_sha":raw.get("config_sha"),"policy_sha":raw.get("policy_sha"),"evidence_sha":raw.get("evidence_sha"),"trades":int(raw.get("completed_trades") or 0),"intents":int(raw.get("intent_count") or 0),"gross_expectancy_bps":gross,"net_expectancy_bps":net,"profit_factor":raw.get("profit_factor"),"payoff":raw.get("payoff"),"win_rate":raw.get("win_rate"),"drawdown_bps":raw.get("drawdown_bps"),"verified_pretrade_cost_bps":cost}}

def prompt_for(fp: Mapping[str, Any], evidence: list[dict[str, Any]]) -> str:
    shape={"candidates":[{
        "candidate_id":"string","mode":"REPAIR|NEW_ARCHITECTURE","strategy_id":fp["strategy_id"],"architecture_family":"string","changed_axis":"exactly_one_axis","mechanism":"why money exists/who pays","payer":"participant/inefficiency","entry_event":"entry-time observable event","direction_rule":"long|short|both","native_horizon":"natural holding horizon","regime_owner":"when it should/should not trade","invalidation":"causal invalidation","exit_logic":"exit rationale","time_stop_rationale":"why horizon fits mechanism","turnover_cost_budget":"why expected move can dominate cost","required_sources":["ohlcv|volume"],"evidence_ids":["F1"],"expected_move_cost_multiple_target":2.0,"falsification":"bounded prospective kill test","forbidden_changes":["fees","threshold sweep","best-horizon selection","post-outcome loss deletion"],"why_distinct":"why distinct",
        "executable_spec":{"bar_interval":"5m|15m|30m|1h|4h|1d","features":[{"name":"feature_name","formula":"ONE DSL expression only"}],"entry_rule":"ONE DSL boolean expression only","side_rule":"long OR short OR 'long if <DSL boolean> else short'","exit_rule":"time_stop OR ONE DSL boolean expression only","max_hold_bars":12,"entry_timing":"next_bar_open","cost_model":"verified_14bps_or_more","development_data_rule":"strictly_before_GEN1_boundary","parameter_provenance":"design_prior_or_primary_evidence_only"}
    }]}
    dsl=(
      "EXECUTABLE_DSL_V1 HARD CONTRACT: expressions are Python-like scalar expressions only. "
      "Allowed raw names: open,high,low,close,volume and previously defined feature names. "
      "Allowed functions ONLY: abs(x),min(a,b),max(a,b),sma(series,n),ema(series,n),std(series,n),lag(series,n),ret(n),atr(n),vwap(n),zscore(series,n),highest(series,n),lowest(series,n). "
      "For series arguments use bare names, e.g. ema(close,20), sma(volume,20), lowest(low,20). "
      "Allowed operators: + - * / **, > >= < <= == !=, and/or/not. "
      "FORBIDDEN: assignment '=' inside formulas, prose, SQL, array indexing like close[-1], subscripts, attributes, comprehensions, strings/regime labels, position, entry_price, hold_bars, bar_index, return_since_entry, numpy/pandas, custom functions, cumulative_sum, sqrt, if-then prose. "
      "Feature formula examples: ema(close,20); volume/sma(volume,20); (close-lag(close,1))/lag(close,1); zscore(close,20). "
      "Entry example: close > ema20 and volume_ratio > 1.8. Side examples: long ; short ; long if close > ema20 else short. "
      "Prefer exit_rule=time_stop for the first development test. If using a causal exit, it may reference ONLY current OHLCV and named features. "
    )
    return (
      "You are an ECONOMIC strategy builder, not an idea writer. For THIS terminal strategy return exactly 4 candidates: exactly 3 REPAIR and exactly 1 NEW_ARCHITECTURE. "
      "Every candidate MUST include executable_spec that a deterministic Python replay can implement without interpretation. If you cannot express a candidate under EXECUTABLE_DSL_V1, do not emit it. "
      "Each REPAIR changes exactly one causal axis. NEW_ARCHITECTURE replaces payer/mechanism. Never loosen thresholds, sweep parameters, reduce fees, delete losers, inspect future outcomes, or choose best horizon after outcomes. "
      "Use only sources explicitly permitted by the caller's source-history contract. The next gate is development economics; prose quality and AI consensus have zero value without Net>0 and PF>1 after realistic cost. Return JSON only. "
      +dsl+
      f"SCHEMA={canonical(shape)}\nFAILURE={canonical(fp)}\nEVIDENCE={canonical(evidence[:20])}"
    )

def review_candidates(candidates:list[dict[str,Any]])->list[dict[str,Any]]:
    env=os.environ.copy(); out=[]
    with tempfile.TemporaryDirectory(prefix="a1-terminal-swarm-v2-") as td:
      root=Path(td)
      for i,c in enumerate(candidates):
        work=root/str(i); work.mkdir(); reviews={}
        try: reviews["openai"]=openai_critic(c)
        except Exception as exc: reviews["openai"]={"successful":False,"error":safe_error(exc)}
        reviews["groq"]=subprocess_review("scripts/strategy11_groq_redteam.py",c,work,env,"groq")
        reviews["workers_ai"]=subprocess_review("scripts/strategy11_workers_ai_guard.py",c,work,env,"workers")
        passes=rejects=0
        for name,r in reviews.items():
          if name==c.get("provider"): continue
          decision=str(r.get("decision") or "")
          if r.get("successful") and decision in {"PASS","PASS_TO_REPLAY"}: passes+=1
          if r.get("successful") and decision=="REJECT": rejects+=1
        source_ready=all(s in {"ohlcv","volume","funding","basis","open_interest","l2_order_book","trade_flow"} for s in (c.get("required_sources") or [])); score=base_score(c)+passes*2.5-rejects*4.0
        out.append({**c,"source_ready":source_ready,"cross_reviews":reviews,"independent_passes":passes,"independent_rejects":rejects,"score":round(score,4),"eligible_for_preregistration":source_ready and passes>=2 and rejects==0})
    out.sort(key=lambda x:(-float(x["score"]),x["candidate_id"])); return out

def run(output:Path)->dict[str,Any]:
    ledger,evidence=read_json(LEDGER),read_json(EVIDENCE); source_rows=evidence_compact(evidence); source_ids={str(x.get("id")) for x in source_rows}
    terminals=[(sid,raw) for sid,raw in (ledger.get("strategies") or {}).items() if isinstance(raw,Mapping) and raw.get("status") in TERMINAL]; fps=[fingerprint(sid,raw) for sid,raw in terminals]; generated=[]; providers={}
    for fp in fps:
      sid=fp["strategy_id"]; p=prompt_for(fp,source_rows); providers[sid]={}
      for provider,fn in (("openai",call_openai_generator),("groq",call_groq_generator)):
        try:
          model,raw,lineage=fn(p); rows=validate_candidates(raw,provider,source_ids,{sid}); providers[sid][provider]={"successful":True,"model":model,**lineage,"candidate_count":len(rows)}; generated.extend(rows)
        except Exception as exc: providers[sid][provider]={"successful":False,"error":safe_error(exc)}
    generated=dedup(sorted(generated,key=lambda x:-base_score(x)),0.85); reviewed=review_candidates(generated); by_strategy={}
    for fp in fps:
      sid=fp["strategy_id"]; rows=[x for x in reviewed if x.get("strategy_id")==sid]; by_strategy[sid]={"fingerprint":fp,"repair_top3":[x for x in rows if x.get("mode")=="REPAIR"][:3],"new_architecture":[x for x in rows if x.get("mode")=="NEW_ARCHITECTURE"][:2]}
    result={"schema_version":"zel.a1_terminal_repair_swarm.v2","baseline_ledger_sha256":hashlib.sha256(LEDGER.read_bytes()).hexdigest(),"evidence_sweep_sha256":hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),"ledger_done_count":int(ledger.get("done_count") or 0),"survivor_count":int(ledger.get("survivor_count") or 0),"terminal_count":len(terminals),"terminal_strategy_ids":[sid for sid,_ in terminals],"queued_repair_count":sum(len(v["repair_top3"]) for v in by_strategy.values()),"queued_new_arch_count":sum(len(v["new_architecture"]) for v in by_strategy.values()),"eligible_count":sum(1 for x in reviewed if x.get("eligible_for_preregistration")),"dedup_cosine_threshold":0.85,"provider_state":providers,"strategies":by_strategy,"global_queue":reviewed,"launch":{"state":"DEFER_TO_GLOBAL_ONE_HEAVY_OWNER","candidate":None},"research_only":True,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0}; result["receipt_sha256"]=sha(result); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"); return result

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path("out/a1_terminal_repair_swarm_v2.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test:
      f=fingerprint("x",{"status":"A1_COST_FUTILITY","gross_expectancy_bps":2.0,"net_expectancy_bps":-10.0,"verified_pretrade_cost_bps":14.0,"receipt_sha":"r"}); assert f["primary"]=="POSITIVE_GROSS_EDGE_BELOW_COST"; print("PASS_A1_TERMINAL_REPAIR_SWARM_V2_SELF_TEST"); return 0
    r=run(args.output); print(canonical({"terminal_count":r["terminal_count"],"queued_repair_count":r["queued_repair_count"],"queued_new_arch_count":r["queued_new_arch_count"],"eligible_count":r["eligible_count"]})); return 0
if __name__=="__main__": raise SystemExit(main())
