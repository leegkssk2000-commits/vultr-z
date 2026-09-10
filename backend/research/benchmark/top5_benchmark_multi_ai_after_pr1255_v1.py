from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCOPE_KEY = "TOP5_TRADER_BENCHMARK_MULTI_AI_AFTER_PR1255_V1"
OUT = Path("backend/research/benchmark/top5_benchmark_multi_ai_after_pr1255_latest.json")
DECISION = Path("backend/research/benchmark/BENCHMARK_DECISION.json")
LANES = {
    "trend_rider_primary": ["trend_rider", "primary"],
    "trend_rider_broad": ["trend_rider", "broad"],
    "break": ["break", "q0", "br"],
    "keltner": ["keltner", "kr3"],
    "supertrend": ["supertrend", "sr"],
}
SOURCES = {
    "parker": "breakout entry/exit + stop; entry-day volatility sizing; small losses and let profits run; avoid over-optimization",
    "qullamaggie": "prior expansion -> orderly pullback/tightening -> breakout/range expansion; day/ATR risk; partial after several days; moving-average trail",
    "basso": "rule-based Keltner trend signal and normalized risk",
    "raschke": "strong-trend state -> 20EMA pullback -> re-entry trigger; Keltner context",
    "kell": "cycle-of-price-action: wedge pop, EMA crossback, base-and-break",
    "minervini": "trend/quality selection and contraction concepts; analogous unless direct rule support exists",
    "carter": "Squeeze/Keltner components as source-fidelity reference only; not Top5 candidate authority",
}

def sanitize_secret(name: str) -> str:
    raw = os.environ.get(name, "")
    trimmed = raw.strip(" \t\r\n")
    if not trimmed:
        raise RuntimeError(f"{name}_MISSING")
    for ch in trimmed:
        o = ord(ch)
        if o > 127 or o == 0 or o == 127 or o < 32 or ch.isspace():
            raise RuntimeError(f"{name}_UNSAFE_HEADER_VALUE")
    return trimmed

def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: Any = None, timeout: int = 60) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return int(r.status), json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body[:1000]}
        return int(e.code), parsed

def compact(obj: Any, limit: int) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))[:limit]

def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def summarize(path: Path, obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path)}
    if not isinstance(obj, dict):
        out["parse"] = "FAILED"
        return out
    keep = ["state", "candidate_id", "strategy", "strategy_id", "verdict", "status", "completed_trades", "trades", "sample_size", "sample_gap_to_25", "metrics", "economic", "economics", "parent_metrics", "child_metrics", "reason", "selection_authority", "promotion_authority", "execution_authority", "order_authority", "live_trade_authority", "strategy_parameters_changed", "thresholds_changed", "canonical_exact25_ledger_mutation"]
    for k in keep:
        if k in obj:
            out[k] = obj[k]
    return out

def discover() -> dict[str, list[dict[str, Any]]]:
    files = sorted(Path("backend/research").rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in LANES}
    for p in files:
        name = p.name.lower()
        if not any(x in name for x in ("latest", "forward", "economic", "full")):
            continue
        obj = None
        for lane, needles in LANES.items():
            if len(out[lane]) >= 8:
                continue
            if any(n in name for n in needles):
                if obj is None:
                    obj = load_json(p)
                out[lane].append(summarize(p, obj))
    return out

def extract_json(text: str) -> dict[str, Any] | None:
    try:
        x = json.loads(text.strip())
        return x if isinstance(x, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        x = json.loads(m.group(0))
        return x if isinstance(x, dict) else None
    except Exception:
        return None

def call_gemini(packet: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {"provider": "google", "attempts": 1, "model": "gemini-3.6-flash", "billing_status": "unknown"}
    try:
        key = sanitize_secret("GEMINI_API_KEY")
        status, inv = http_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=30)
        rec["inventory_http"] = status
        if status != 200:
            rec.update(state="BLOCKED_MODEL_INVENTORY", usable=False)
            return rec
        available = [m.get("name", "") for m in inv.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        if not any(x.endswith("/gemini-3.6-flash") for x in available):
            rec.update(state="BLOCKED_REQUIRED_MODEL_UNAVAILABLE", usable=False, available_models=available[:30])
            return rec
        prompt = "Return STRICT JSON only. You are the source/mechanism mapper for crypto strategy research. No PnL prediction, future-period selection, threshold sweep, or hindsight feature. For each lane trend_rider_primary, trend_rider_broad, break, keltner, supertrend return source_rule, benchmark_type(EXACT|ANALOGOUS), current_rule_gap, causal_hypothesis, no_pnl_conformance_test, candidate_rule, counterexample, duplicate_risk. candidate_rule=null if evidence is insufficient. PACKET=" + compact(packet, 24000)
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json"}}
        status, body = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={key}", method="POST", headers={"Content-Type": "application/json"}, payload=payload, timeout=90)
        rec["http"] = status
        rec["usage"] = body.get("usageMetadata", {}) if isinstance(body, dict) else {}
        if status != 200:
            rec.update(state="REQUEST_FAILED", usable=False)
            return rec
        text = ""
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass
        parsed = extract_json(text)
        rec["response_id"] = body.get("responseId") if isinstance(body, dict) else None
        rec["result"] = parsed
        rec["usable"] = isinstance(parsed, dict)
        rec["state"] = "PASS_STRUCTURED" if rec["usable"] else "PARSE_FAILED"
        return rec
    except Exception as e:
        rec.update(state="SAFE_BLOCK", usable=False, error=type(e).__name__ + ":" + str(e)[:180])
        return rec

def call_openai(packet: dict[str, Any], gemini: dict[str, Any]) -> dict[str, Any]:
    rec: dict[str, Any] = {"provider": "openai", "attempts": 1, "billing_status": "unknown"}
    try:
        key = sanitize_secret("OPENAI_API_KEY")
        model = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5.6"
        rec["model"] = model
        prompt = "Return STRICT JSON only. Adversarially review the Top5 benchmark mapping. Do not invent source facts. Challenge lookahead, execution timing, occupancy, winner damage, cost/incomplete omission, overfitting and duplicate prior experiments. For each lane return decision(APPROVE_FOR_IMPLEMENTATION|REJECT|NEEDS_DATA), reasons[], required_invariants[], candidate_rule_after_redteam or null. If Gemini is unusable, set gemini_unusable=true and independently review evidence; do not impersonate Gemini. PACKET=" + compact(packet, 18000) + " GEMINI=" + compact(gemini.get("result") if gemini.get("usable") else {"usable": False, "state": gemini.get("state")}, 12000)
        payload = {"model": model, "input": prompt}
        status, body = http_json("https://api.openai.com/v1/responses", method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, payload=payload, timeout=90)
        rec["http"] = status
        rec["response_id"] = body.get("id") if isinstance(body, dict) else None
        rec["usage"] = body.get("usage", {}) if isinstance(body, dict) else {}
        if status != 200:
            rec.update(state="REQUEST_FAILED", usable=False)
            return rec
        text = body.get("output_text", "") if isinstance(body, dict) else ""
        if not text and isinstance(body, dict):
            chunks = []
            for item in body.get("output", []):
                for c in item.get("content", []):
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        chunks.append(c["text"])
            text = "\n".join(chunks)
        parsed = extract_json(text)
        rec["result"] = parsed
        rec["usable"] = isinstance(parsed, dict)
        rec["state"] = "PASS_STRUCTURED" if rec["usable"] else "PARSE_FAILED"
        return rec
    except Exception as e:
        rec.update(state="SAFE_BLOCK", usable=False, error=type(e).__name__ + ":" + str(e)[:180])
        return rec

def build_decision(evidence: dict[str, list[dict[str, Any]]], gemini: dict[str, Any], red: dict[str, Any]) -> dict[str, Any]:
    gd = gemini.get("result") if isinstance(gemini.get("result"), dict) else {}
    rd = red.get("result") if isinstance(red.get("result"), dict) else {}
    lanes: dict[str, Any] = {}
    approved = 0
    for lane in LANES:
        g = gd.get(lane, {}) if isinstance(gd, dict) else {}
        r = rd.get(lane, {}) if isinstance(rd, dict) else {}
        cand = r.get("candidate_rule_after_redteam") if isinstance(r, dict) else None
        if not cand and isinstance(g, dict):
            cand = g.get("candidate_rule")
        review = r.get("decision") if isinstance(r, dict) else None
        state = "REJECT_NO_SUPPORTED_CANDIDATE"
        if cand and review == "APPROVE_FOR_IMPLEMENTATION":
            state = "NOT_RUN_IMPLEMENTATION_MAPPING_REQUIRED"
            approved += 1
        lanes[lane] = {"source_support": g.get("source_rule") if isinstance(g, dict) else None, "mechanism_match": g.get("benchmark_type") if isinstance(g, dict) else None, "current_rule_gap": g.get("current_rule_gap") if isinstance(g, dict) else None, "causal_reach": g.get("causal_hypothesis") if isinstance(g, dict) else None, "not_duplicate": None if not isinstance(g, dict) else (g.get("duplicate_risk") in (None, "LOW", "low", False)), "no_lookahead": bool(g.get("no_pnl_conformance_test")) if isinstance(g, dict) else False, "candidate_rule": cand, "openai_decision": review, "economic_state": state, "evidence_files": [x.get("path") for x in evidence.get(lane, [])]}
    return {"schema_version": "zel.top5_benchmark_decision.v1", "scope_key": SCOPE_KEY, "created_at_epoch": int(time.time()), "source_conformance_and_economic_are_separate": True, "ai_generated_code_execution": False, "lanes": lanes, "approved_but_not_executed_count": approved, "economic_replay_count": 0, "terminal": "NEEDS_DETERMINISTIC_IMPLEMENTATION_MAPPING" if approved else "CLOSED_NO_SUPPORTED_CANDIDATE", "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED"}

def main() -> int:
    evidence = discover()
    packet = {"scope_key": SCOPE_KEY, "sources": SOURCES, "native_evidence": evidence}
    gemini = call_gemini(packet)
    red = call_openai(packet, gemini)
    decision = build_decision(evidence, gemini, red)
    report = {"schema_version": "zel.top5_benchmark_multi_ai.v1", "scope_key": SCOPE_KEY, "packet": packet, "gemini": gemini, "openai_redteam": red, "decision": decision, "api_budget": {"max_calls": 2, "gemini_calls": 1, "openai_calls": 1, "reserved_usd_cap": 1.50, "billing_status": "unknown"}, "protected_mutations": 0, "canonical_exact25_ledger_mutation": False, "strategy_parameters_changed": False, "thresholds_changed": False, "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DECISION.write_text(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"gemini": gemini.get("state"), "openai": red.get("state"), "terminal": decision.get("terminal"), "economic_replay_count": 0}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
