#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TERMINAL = {
    "A1_ECONOMIC_FAIL",
    "A1_COST_FUTILITY",
    "A1_CAUSAL_CONTROL_FAIL",
    "A1_SPARSE_EVENT_FUTILITY",
}
NATIVE_SOURCES = {
    "ohlcv", "volume", "funding", "basis", "open_interest",
    "l2_order_book", "trade_flow",
}
AUTHORITY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def canon(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(v: Any) -> str:
    return hashlib.sha256(canon(v).encode()).hexdigest()


def toks(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", s.lower()))


def cosine(a: dict[str, Any], b: dict[str, Any]) -> float:
    ta = toks(" ".join(str(a.get(k, "")) for k in ("architecture_family", "changed_axis", "mechanism", "entry_event", "horizon")))
    tb = toks(" ".join(str(b.get(k, "")) for k in ("architecture_family", "changed_axis", "mechanism", "entry_event", "horizon")))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / math.sqrt(len(ta) * len(tb))


def fingerprint(strategy_id: str, s: dict[str, Any]) -> dict[str, Any]:
    status = s.get("status")
    gross = s.get("gross_expectancy_bps")
    net = s.get("net_expectancy_bps")
    trades = int(s.get("completed_trades") or 0)
    intents = int(s.get("intent_count") or 0)
    cost = float(s.get("verified_pretrade_cost_bps") or 14.0)
    if status == "A1_SPARSE_EVENT_FUTILITY":
        primary = "STRUCTURAL_EVENT_RATE_TOO_LOW"
        diagnosis = "The frozen mechanism cannot produce enough prospective decisions under its bounded resource budget; threshold loosening is forbidden."
    elif gross is not None and float(gross) <= 0:
        primary = "NEGATIVE_GROSS_EDGE"
        diagnosis = "The frozen mechanism loses before transaction costs, so the payer/direction/horizon thesis is structurally weak."
    elif gross is not None and float(gross) < cost:
        primary = "POSITIVE_GROSS_EDGE_BELOW_COST"
        diagnosis = "The frozen mechanism has some raw edge but expected move is too small for the verified cost budget."
    else:
        primary = "TERMINAL_ECONOMIC_FAILURE"
        diagnosis = "The frozen mechanism failed its economic or causal gate and must be repaired without mutating its control."
    return {
        "strategy_id": strategy_id,
        "terminal_status": status,
        "terminal_reason": s.get("terminal_reason"),
        "primary": primary,
        "diagnosis": diagnosis,
        "baseline": {
            "receipt_sha": s.get("receipt_sha"),
            "config_sha": s.get("config_sha"),
            "policy_sha": s.get("policy_sha"),
            "evidence_sha": s.get("evidence_sha"),
            "trades": trades,
            "intents": intents,
            "gross_expectancy_bps": gross,
            "net_expectancy_bps": net,
            "profit_factor": s.get("profit_factor"),
            "payoff": s.get("payoff"),
            "win_rate": s.get("win_rate"),
            "drawdown_bps": s.get("drawdown_bps"),
            "verified_pretrade_cost_bps": cost,
        },
    }


def contract() -> dict[str, Any]:
    return {
        "candidates": [{
            "mode": "REPAIR|NEW_ARCHITECTURE",
            "architecture_family": "string",
            "changed_axis": "single_axis_or_none",
            "mechanism": "string",
            "entry_event": "string",
            "horizon": "string",
            "required_sources": ["ohlcv"],
            "expected_move_cost_multiple_target": 2.0,
            "falsification": "string",
            "evidence_ids": ["string"],
            "why_distinct": "string",
        }]
    }


def build_prompt(fp: dict[str, Any], evidence_context: list[dict[str, Any]]) -> str:
    return (
        "You are a research-only crypto strategy architect. Return JSON only. "
        "Generate exactly 4 candidates for the terminal strategy: 3 bounded REPAIR candidates, each changing exactly ONE causal axis, and 1 NEW_ARCHITECTURE replacement if the original mechanism is weak. "
        "Never loosen thresholds, sweep parameters, reduce fees, delete losers, choose best horizon post-hoc, or use future information. "
        "Prefer mechanisms whose natural expected move can plausibly exceed 2x the verified round-trip cost. "
        "Allowed sources only: ohlcv, volume, funding, basis, open_interest, l2_order_book, trade_flow. "
        "For sparse-event failures, redesign source/context or replace the architecture instead of relaxing entry thresholds. "
        "Every REPAIR changed_axis must be one concrete axis; NEW_ARCHITECTURE changed_axis must be 'none'. "
        f"Schema={canon(contract())}\nFailure={canon(fp)}\nEvidence={canon(evidence_context[:12])}"
    )


def parse_obj(raw: str) -> dict[str, Any]:
    t = raw.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```$", "", t)
    try:
        v = json.loads(t)
    except Exception:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("JSON_MISSING")
        v = json.loads(t[i:j+1])
    if not isinstance(v, dict):
        raise ValueError("JSON_NOT_OBJECT")
    return v


def normalize_candidates(provider: str, fp: dict[str, Any], value: dict[str, Any]) -> list[dict[str, Any]]:
    rows = value.get("candidates")
    if not isinstance(rows, list):
        return []
    out = []
    repair_count = 0
    new_count = 0
    for idx, x in enumerate(rows[:8]):
        if not isinstance(x, dict):
            continue
        mode = str(x.get("mode") or "").upper()
        if mode not in {"REPAIR", "NEW_ARCHITECTURE"}:
            continue
        axis = str(x.get("changed_axis") or "").strip()
        if mode == "REPAIR":
            if not axis or axis.lower() == "none":
                continue
            repair_count += 1
        else:
            axis = "none"
            new_count += 1
        src = [str(s).strip() for s in (x.get("required_sources") or []) if str(s).strip()]
        source_ready = bool(src) and set(src).issubset(NATIVE_SOURCES)
        row = {
            "candidate_id": f"{fp['strategy_id']}:{provider}:{idx+1}",
            "strategy_id": fp["strategy_id"],
            "provider": provider,
            "mode": mode,
            "architecture_family": str(x.get("architecture_family") or fp["strategy_id"]),
            "changed_axis": axis,
            "mechanism": str(x.get("mechanism") or "").strip(),
            "entry_event": str(x.get("entry_event") or "").strip(),
            "horizon": str(x.get("horizon") or "").strip(),
            "required_sources": src,
            "source_ready": source_ready,
            "expected_move_cost_multiple_target": float(x.get("expected_move_cost_multiple_target") or 2.0),
            "falsification": str(x.get("falsification") or "").strip(),
            "evidence_ids": [str(e) for e in (x.get("evidence_ids") or [])],
            "why_distinct": str(x.get("why_distinct") or "").strip(),
            "baseline_receipt_sha": fp["baseline"]["receipt_sha"],
            "threshold_sweep": False,
            "best_horizon_selection": False,
            "fee_reduction": False,
        }
        if row["mechanism"] and row["entry_event"] and row["falsification"]:
            out.append(row)
    # Fail closed if provider ignored requested composition.
    if repair_count < 1 and new_count < 1:
        return []
    return out


def openai_generate(prompt: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    if not key:
        return [], {"successful": False, "blocker": "OPENAI_API_KEY_MISSING"}
    body = {"model": model, "input": prompt, "temperature": 0.1, "max_output_tokens": 2200}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=canon(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            j = json.loads(r.read().decode())
        text = j.get("output_text") or ""
        if not text:
            parts=[]
            for o in j.get("output") or []:
                for c in o.get("content") or []:
                    if isinstance(c, dict) and isinstance(c.get("text"), str): parts.append(c["text"])
            text="\n".join(parts)
        return [parse_obj(text)], {"successful": True, "model": model, "response_sha": hashlib.sha256(text.encode()).hexdigest()}
    except Exception as e:
        return [], {"successful": False, "blocker": type(e).__name__}


def groq_generate(prompt: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
    if not key:
        return [], {"successful": False, "blocker": "GROQ_API_KEY_MISSING"}
    body = {"model": model, "messages": [{"role":"user","content":prompt}], "temperature":0.1, "max_tokens":2200}
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=canon(body).encode(), headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            j=json.loads(r.read().decode())
        text=str(j["choices"][0]["message"]["content"] or "")
        return [parse_obj(text)], {"successful": True, "model": model, "response_sha": hashlib.sha256(text.encode()).hexdigest()}
    except Exception as e:
        return [], {"successful": False, "blocker": type(e).__name__}


def workers_review(candidate: dict[str, Any]) -> dict[str, Any]:
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_WORKERS_AI_TOKEN", "").strip()
    model = os.getenv("WORKERS_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct").strip() or "@cf/meta/llama-3.1-8b-instruct"
    if not account or not token:
        return {"decision":"HOLD","blocker":"WORKERS_AI_CREDENTIAL_MISSING"}
    p=("Return JSON only: {\"decision\":\"PASS_TO_PREREGISTER|HOLD|REJECT\",\"reason\":\"...\"}. "
       "Research-only. PASS only if one-axis repair or genuinely distinct new architecture, source list is native, expected-move/cost target >=2, explicit falsification, no threshold sweep, no fee reduction, no leakage. Candidate="+canon(candidate))
    body={"messages":[{"role":"user","content":p}],"temperature":0,"max_tokens":250}
    req=urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",data=canon(body).encode(),headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=60) as r: j=json.loads(r.read().decode())
        result=j.get("result")
        text=result if isinstance(result,str) else (result or {}).get("response") or (result or {}).get("text") or ""
        v=parse_obj(str(text))
        return {"decision":str(v.get("decision") or "HOLD"),"reason":str(v.get("reason") or "")}
    except Exception as e:
        return {"decision":"HOLD","blocker":type(e).__name__}


def evidence_context() -> list[dict[str, Any]]:
    out=[]
    for p in [
        Path("backend/research/architecture_factory/a1_free_evidence_sweep_v1.json"),
        Path("backend/research/early_ai_prep/a1_early_negative_ai_prep_scalp_snap_v1.json"),
        Path("backend/research/early_ai_prep/a1_early_negative_ai_prep_range_fade_v1.json"),
    ]:
        if not p.is_file(): continue
        try:
            j=json.loads(p.read_text())
        except Exception:
            continue
        for s in j.get("sources") or j.get("external_sources") or []:
            if isinstance(s,dict): out.append({k:s.get(k) for k in ("id","tier","title","identifier","claim")})
    return out


def main() -> int:
    if "--self-test" in sys.argv:
        fp=fingerprint("x", {"status":"A1_COST_FUTILITY","gross_expectancy_bps":2,"net_expectancy_bps":-10,"completed_trades":10,"verified_pretrade_cost_bps":14,"receipt_sha":"r"})
        assert fp["primary"]=="POSITIVE_GROSS_EDGE_BELOW_COST"
        a={"architecture_family":"a","changed_axis":"x","mechanism":"flow momentum","entry_event":"trade flow reversal","horizon":"2h"}
        assert 0<=cosine(a,a)<=1 and cosine(a,a)==1
        print("PASS_A1_TERMINAL_REPAIR_SWARM_SELF_TEST")
        return 0

    ledger_path=Path("backend/research/rebuild/a1_exact25_disposition_ledger_v1.json")
    output=Path(os.getenv("A1_TERMINAL_SWARM_OUTPUT","out/a1_terminal_repair_swarm_v1.json"))
    ledger=json.loads(ledger_path.read_text())
    terminals=[(sid,s) for sid,s in (ledger.get("strategies") or {}).items() if s.get("status") in TERMINAL]
    ev=evidence_context()
    all_candidates=[]
    fps=[]
    provider_state={"openai":{},"groq":{},"workers_ai":{"reviewed":0}}
    for sid,s in terminals:
        fp=fingerprint(sid,s); fps.append(fp)
        prompt=build_prompt(fp,ev)
        for name, fn in (("openai",openai_generate),("groq",groq_generate)):
            vals, meta=fn(prompt); provider_state[name][sid]=meta
            for value in vals:
                all_candidates += normalize_candidates(name,fp,value)
    # Structural dedup across all terminal families.
    ranked=[]
    for c in all_candidates:
        if any(cosine(c,x)>0.85 for x in ranked):
            continue
        c["workers_ai_review"]=workers_review(c)
        provider_state["workers_ai"]["reviewed"] += 1
        c["eligible_for_preregistration"]=(
            c["source_ready"] and c["expected_move_cost_multiple_target"]>=2.0 and
            c["workers_ai_review"].get("decision")=="PASS_TO_PREREGISTER"
        )
        c["priority_score"]=(3 if c["eligible_for_preregistration"] else 0)+(2 if c["mode"]=="NEW_ARCHITECTURE" else 1)+(1 if c["source_ready"] else 0)
        ranked.append(c)
    ranked.sort(key=lambda x:(x["priority_score"],x["expected_move_cost_multiple_target"]),reverse=True)
    by_strategy={}
    for fp in fps:
        sid=fp["strategy_id"]
        cs=[c for c in ranked if c["strategy_id"]==sid]
        repairs=[c for c in cs if c["mode"]=="REPAIR"][:3]
        news=[c for c in cs if c["mode"]=="NEW_ARCHITECTURE"][:2]
        by_strategy[sid]={"fingerprint":fp,"repair_top3":repairs,"new_architecture":news}
    artifact={
        "schema_version":"zel.a1_terminal_repair_swarm.v1",
        "created_at_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
        "ledger_sha":sha(ledger),
        "ledger_done_count":ledger.get("done_count"),
        "survivor_count":ledger.get("survivor_count"),
        "terminal_count":len(terminals),
        "terminal_strategy_ids":[sid for sid,_ in terminals],
        "queued_repair_count":sum(len(v["repair_top3"]) for v in by_strategy.values()),
        "queued_new_arch_count":sum(len(v["new_architecture"]) for v in by_strategy.values()),
        "dedup_cosine_threshold":0.85,
        "provider_state":provider_state,
        "strategies":by_strategy,
        "global_queue":ranked,
        "launch":{
            "state":"DEFER_TO_GLOBAL_ONE_HEAVY_OWNER",
            "candidate":None,
            "reason":"This lightweight swarm never starts a heavy replay itself; current heavy-owner state must be checked by the controller before preregistration/launch."
        },
        **AUTHORITY,
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(artifact,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(canon({"terminal_count":artifact["terminal_count"],"queued_repair_count":artifact["queued_repair_count"],"queued_new_arch_count":artifact["queued_new_arch_count"],"eligible":sum(1 for x in ranked if x["eligible_for_preregistration"])}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
