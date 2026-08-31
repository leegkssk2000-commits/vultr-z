#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_paid_ai_target_gate_v1 as paid_gate
from backend.research.architecture_factory import gemini_provider_v1 as gemini
from backend.research.prep import g5_trendrider_preentry_interaction_child_v1 as screen
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_policy_batch_v1 as parent
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
PRODUCT = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
FORENSIC = ROOT / "backend/research/prep/g5_trendrider_w2_forensic_latest.json"
SCREEN = ROOT / "backend/research/prep/g5_trendrider_preentry_interaction_child_latest.json"
MATCHED = ROOT / "backend/research/rebuild/a1_top5_matched_exit_attribution_latest.json"
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
DEFAULT_CURRENT = ROOT / "backend/research/prep/g5_trendrider_causal_web_research_latest.json"

SCHEMA = "zel.g5.trendrider.causal_web_research.v1"
LANE_ID = "trend_rider_broad_wr7000"
STRATEGY_ID = "trend_rider"
TARGET_GATE = "W2_FORENSIC_CAUSAL_MECHANISM_RESELECT"
HOUR_MS = 3_600_000
MIN_GROUNDED_SOURCES = 2
MAX_HYPOTHESES = 3
DEFAULT_MODEL = "gemini-3.7-flash"

MECHANISMS: dict[str, str] = {
    "ST_GAP_NONDECAY": "Require current Supertrend distance in ATR units to be >= its immediately prior-bar value.",
    "CHASE_NONACCEL": "Require current EMA50 chase distance in ATR units to be <= its immediately prior-bar value.",
    "ATR_EXPANSION_CONFIRM": "Require current ATR percent to be >= its immediately prior-bar ATR percent.",
    "VOL_EXPANSION_REQUIRES_ST_GAP": "If ATR percent is expanding versus the prior bar, require Supertrend distance not to decay; otherwise allow the parent signal.",
    "VOL_COOLING_REQUIRES_TRANSITION_FRESH": "If ATR percent is cooling versus the prior bar, require the existing parent transition-fresh reconfirmation; otherwise allow the parent signal.",
    "ST_GAP_AND_CHASE_RECONFIRM": "Require both non-decaying Supertrend distance and non-accelerating EMA50 chase distance.",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def maybe_read(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return read(path)


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def next_hour_boundary_ms(now_ms: int) -> int:
    return ((int(now_ms) // HOUR_MS) + 1) * HOUR_MS


def _atr_pct_at(bars: list[dict[str, Any]], idx: int) -> float:
    prefix = bars[: idx + 1]
    return float(atr(prefix, 14)) / max(float(prefix[-1]["close"]), 1e-12) * 100.0


def augment_prior_features(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        by_ts = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for row in [x for x in rows if str(x["symbol"]) == symbol]:
            signal_ts = int(row.get("signal_ts") or 0)
            idx = by_ts.get(signal_ts)
            if idx is None or idx < 65:
                raise RuntimeError(f"RESEARCH_PREENTRY_FEATURE_SOURCE_MISSING:{symbol}:{signal_ts}")
            prev_ts = int(bars[idx - 1]["ts_ms"])
            prev = parent.compute_trend_rider_feature(bars[:idx], symbol=symbol, now_ts_ms=prev_ts)
            prior_atr_pct = _atr_pct_at(bars, idx - 1)
            prior_st_gap = float(prev.values.get("st_gap_atr"))
            prior_chase = float(prev.values.get("chase_atr"))
            current_atr = float(row.get("atr_pct"))
            current_st_gap = float(row.get("st_gap_atr"))
            current_chase = float(row.get("chase_atr"))
            row.update({
                "prior_atr_pct": prior_atr_pct,
                "prior_st_gap_atr": prior_st_gap,
                "prior_chase_atr": prior_chase,
                "atr_expanding_vs_prior": current_atr >= prior_atr_pct,
                "st_gap_nondecay_vs_prior": current_st_gap >= prior_st_gap,
                "chase_nonaccel_vs_prior": current_chase <= prior_chase,
            })


def mechanism_keep(row: Mapping[str, Any], mechanism_id: str) -> bool:
    atr_expand = bool(row.get("atr_expanding_vs_prior"))
    st_nondecay = bool(row.get("st_gap_nondecay_vs_prior"))
    chase_nonaccel = bool(row.get("chase_nonaccel_vs_prior"))
    transition_fresh = bool(row.get("transition_fresh"))
    if mechanism_id == "ST_GAP_NONDECAY":
        return st_nondecay
    if mechanism_id == "CHASE_NONACCEL":
        return chase_nonaccel
    if mechanism_id == "ATR_EXPANSION_CONFIRM":
        return atr_expand
    if mechanism_id == "VOL_EXPANSION_REQUIRES_ST_GAP":
        return (not atr_expand) or st_nondecay
    if mechanism_id == "VOL_COOLING_REQUIRES_TRANSITION_FRESH":
        return atr_expand or transition_fresh
    if mechanism_id == "ST_GAP_AND_CHASE_RECONFIRM":
        return st_nondecay and chase_nonaccel
    raise RuntimeError(f"UNKNOWN_RESEARCH_MECHANISM:{mechanism_id}")


def filter_rows(rows: list[dict[str, Any]], mechanism_id: str) -> list[dict[str, Any]]:
    return [dict(x) for x in rows if mechanism_keep(x, mechanism_id)]


def _pf_ok(value: Any) -> bool:
    return value == "INF" or (isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 1.0)


def evaluate_candidate(reference: list[dict[str, Any]], w2: list[dict[str, Any]], mechanism_id: str) -> dict[str, Any]:
    kept = filter_rows(reference, mechanism_id)
    blocked = [x for x in reference if not mechanism_keep(x, mechanism_id)]
    w2_kept = filter_rows(w2, mechanism_id)
    w2_blocked = [x for x in w2 if not mechanism_keep(x, mechanism_id)]
    base = screen.metrics(reference)
    child = screen.metrics(kept)
    w2_child = screen.metrics(w2_kept)
    w2_blocked_losses = sum(1 for x in w2_blocked if float(x.get("net_bps") or 0.0) <= 0.0)
    w2_blocked_wins = len(w2_blocked) - w2_blocked_losses
    retention = 100.0 * len(kept) / len(reference) if reference else 0.0
    dev_ok = bool(
        retention >= 50.0
        and float(child.get("net_pnl_bps") or 0.0) > 0.0
        and float(child.get("net_expectancy_bps") or 0.0) > 0.0
        and _pf_ok(child.get("profit_factor"))
        and w2_blocked_losses >= 2
    )
    return {
        "mechanism_id": mechanism_id,
        "mechanism": MECHANISMS[mechanism_id],
        "development_viable": dev_ok,
        "reference": {
            "base": base,
            "child": child,
            "retention_pct": retention,
            "blocked_T": len(blocked),
            "blocked_wins": sum(1 for x in blocked if float(x.get("net_bps") or 0.0) > 0.0),
            "blocked_losses": sum(1 for x in blocked if float(x.get("net_bps") or 0.0) <= 0.0),
        },
        "w2_diagnostic_zero_formal_credit": {
            "base": screen.metrics(w2),
            "child": w2_child,
            "blocked_T": len(w2_blocked),
            "blocked_wins": w2_blocked_wins,
            "blocked_losses": w2_blocked_losses,
            "formal_credit": 0,
        },
    }


def load_context() -> tuple[list[dict[str, Any]], list[dict[str, Any]], Mapping[str, Any]]:
    manifest = read(MANIFEST)
    receipt = screen.current_parent_receipt()
    parent_post = screen.dedup_post_boundary(receipt, int(manifest["prospective_boundary_ms"]))
    target = int(manifest["windows"]["W2"]["target_closed_trades"])
    w2 = [dict(x) for x in parent_post[:target]]

    matched = read(MATCHED)
    broad = next((x for x in (matched.get("lanes") or []) if x.get("lane") == "trend_rider_broad"), None)
    if not isinstance(broad, Mapping):
        raise RuntimeError("RESEARCH_G4_REFERENCE_MISSING")
    reference = [dict(x) for x in (broad.get("rows") or [])]
    screen.enrich(reference)
    screen.enrich(w2)
    augment_prior_features(reference)
    augment_prior_features(w2)
    return reference, w2, receipt


def input_signature(product: Mapping[str, Any], forensic: Mapping[str, Any], child: Mapping[str, Any], prior: Mapping[str, Any] | None) -> str:
    econ = product.get("economic_ssot") or {}
    history = []
    if isinstance(prior, Mapping):
        for row in prior.get("reselection_history") or []:
            if isinstance(row, Mapping):
                history.append({"mechanism_id": row.get("mechanism_id"), "result": row.get("result")})
        selected = prior.get("selected_candidate")
        if isinstance(selected, Mapping) and str(prior.get("state") or "").endswith("FALSIFIED_RESEARCH_NEXT_BOUNDARY"):
            history.append({"mechanism_id": selected.get("mechanism_id"), "result": "FALSIFIED_12T"})
    core = {
        "lane_id": LANE_ID,
        "runtime_trade_set_sha256": econ.get("runtime_trade_set_sha256"),
        "runtime_T": econ.get("runtime_trade_count"),
        "product_receipt": product.get("receipt_sha256"),
        "forensic_receipt": forensic.get("receipt_sha256"),
        "forensic_T": forensic.get("w2_observed_T"),
        "selected_causal_axis": forensic.get("selected_causal_axis"),
        "screen_receipt": child.get("receipt_sha256"),
        "screen_state": child.get("state"),
        "screen_prior_candidate_falsified": child.get("prior_candidate_falsified"),
        "prior_failures": history,
    }
    return sha(core)


def _research_prompt(product: Mapping[str, Any], forensic: Mapping[str, Any], child: Mapping[str, Any], forbidden: set[str]) -> str:
    w2 = ((product.get("windows") or {}).get("W2") or {}).get("metrics") or {}
    hypotheses = forensic.get("preentry_ranked_hypotheses") or []
    allowed = [{"mechanism_id": k, "definition": v} for k, v in MECHANISMS.items() if k not in forbidden]
    contract = {
        "task": "Internet-grounded causal mechanism reselection for one frozen G5 TrendRider lane after bounded pre-entry child development failed.",
        "lane_id": LANE_ID,
        "strategy_id": STRATEGY_ID,
        "stage": "G5",
        "gate": TARGET_GATE,
        "observed_W2": {
            "T": w2.get("trades"), "wins": w2.get("wins"), "net_pnl_bps": w2.get("net_pnl_bps"),
            "net_expectancy_bps": w2.get("net_expectancy_bps"), "profit_factor": w2.get("profit_factor"),
        },
        "deterministic_forensic": {
            "selected_axis": forensic.get("selected_causal_axis"),
            "ranked_preentry_hypotheses": hypotheses[:6],
        },
        "already_failed_screen": {
            "state": child.get("state"),
            "causal_hypothesis": child.get("causal_hypothesis"),
            "prior_candidate_falsified": child.get("prior_candidate_falsified"),
            "children": [
                {"id": k, "development_viable": v.get("development_viable")}
                for k, v in (child.get("children") or {}).items() if isinstance(v, Mapping)
            ],
        },
        "allowed_mechanisms": allowed,
        "forbidden_mechanism_ids": sorted(forbidden),
        "hard_constraints": [
            "Use Google Search and ground the recommendation in verifiable web sources.",
            "Prioritize peer-reviewed/academic research, institutional research, exchange/market-microstructure documentation, then high-quality practitioner evidence.",
            "Search broadly enough to resolve the mechanism question, but stop when marginal information value falls; do not perform an unbounded generic sweep.",
            "Choose at most 3 mechanism_id values, ranked BEFORE any deterministic development evaluation is observed.",
            "Only choose from allowed_mechanisms. Do not invent a new feature, numeric cutoff, symbol/session/side filter, exit change, stop change, leverage/risk change, or cost-model change.",
            "All mechanisms are pre-entry and use only current/prior closed-bar information.",
            "Observed W2 outcomes are diagnostic only and grant zero formal child credit.",
            "Do not claim a mechanism works economically; deterministic code will test it after your ranking.",
            "If the literature does not support any allowed mechanism, return an empty hypotheses list.",
        ],
        "output_json": {
            "research_summary": "string <= 1200 chars",
            "hypotheses": [
                {"mechanism_id": "one allowed ID", "why": "causal rationale <= 600 chars", "falsification": "what would refute it <= 400 chars"}
            ],
        },
    }
    return (
        "Act as a market-microstructure and systematic-trend research analyst. Search the public internet, triangulate sources, and return JSON only. "
        "Do not optimize against the supplied trade outcomes and do not output trading instructions.\n"
        + canonical(contract)
    )


def call_grounded_gemini(prompt: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    paid_gate.configure_target(LANE_ID, "G5", TARGET_GATE)
    target = paid_gate.require_target_binding(provider="gemini")
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    model = (os.environ.get("GEMINI_WEB_RESEARCH_MODEL") or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL).strip()
    base = (os.environ.get("GEMINI_API_BASE") or gemini.DEFAULT_GEMINI_API_BASE).strip().rstrip("/")
    bound, _ = paid_gate.bound_prompt(prompt, provider="gemini", purpose="BOUNDED_G4_OR_G5_CAUSAL_REPAIR")
    body = {
        "systemInstruction": {"parts": [{"text": "Use Google Search grounding. Return one compact JSON object and no markdown. Every recommendation must be source-grounded; never infer future/holdout outcomes."}]},
        "contents": [{"role": "user", "parts": [{"text": bound}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 6000, "responseMimeType": "application/json"},
    }
    url = f"{base}/models/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=canonical(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1200]
        raise RuntimeError(f"GEMINI_GROUNDED_RESEARCH_HTTP_{exc.code}:{detail}") from exc
    text = gemini._extract_text(payload)
    parsed = gemini._extract_json(text)
    first = next((x for x in payload.get("candidates") or [] if isinstance(x, Mapping)), {})
    grounding = first.get("groundingMetadata") if isinstance(first, Mapping) else {}
    grounding = grounding if isinstance(grounding, Mapping) else {}
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in grounding.get("groundingChunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        web = chunk.get("web")
        if not isinstance(web, Mapping):
            continue
        uri, title = str(web.get("uri") or "").strip(), str(web.get("title") or "").strip()
        key2 = (uri, title)
        if not (uri or title) or key2 in seen:
            continue
        seen.add(key2)
        sources.append({"uri": uri, "title": title})
    meta = {
        "provider": "gemini",
        "model": model,
        "request_count": 1,
        "prompt_sha256": hashlib.sha256(bound.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "web_search_queries": [str(x) for x in grounding.get("webSearchQueries") or []],
        "sources": sources[:12],
        "source_count": len(sources),
        "grounding_support_count": len(grounding.get("groundingSupports") or []),
        "usage": gemini._usage_meta(payload),
        "target_binding": target,
    }
    return text, parsed, meta


def validate_hypotheses(parsed: Mapping[str, Any], forbidden: set[str]) -> list[dict[str, str]]:
    rows = parsed.get("hypotheses")
    if not isinstance(rows, list):
        raise RuntimeError("WEB_RESEARCH_HYPOTHESES_LIST_REQUIRED")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        mid = str(raw.get("mechanism_id") or "").strip()
        if mid not in MECHANISMS or mid in forbidden or mid in seen:
            continue
        seen.add(mid)
        out.append({
            "mechanism_id": mid,
            "why": str(raw.get("why") or "")[:900],
            "falsification": str(raw.get("falsification") or "")[:600],
        })
        if len(out) >= MAX_HYPOTHESES:
            break
    return out


def current_frozen_candidate(current: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(current, Mapping):
        return None
    selected = current.get("selected_candidate")
    state = str(current.get("state") or "")
    if not isinstance(selected, Mapping):
        return None
    if state in {
        "WAIT_TRUE_FRESH_SELECTED_CHILD_T",
        "SELECTED_CHILD_6T_DIAGNOSTIC",
        "SELECTED_CHILD_12T_BASE_PASS_STRESS_REQUIRED",
    }:
        return selected
    return None


def recompute_fresh(selected: Mapping[str, Any]) -> dict[str, Any]:
    mechanism_id = str(selected["mechanism_id"])
    boundary_ms = int(selected["fresh_boundary_ms"])
    receipt = screen.current_parent_receipt()
    rows = screen.dedup_post_boundary(receipt, boundary_ms)
    screen.enrich(rows)
    augment_prior_features(rows)
    kept = filter_rows(rows, mechanism_id)
    m = screen.metrics(kept)
    base_pass = bool(
        len(kept) >= 12
        and float(m.get("net_pnl_bps") or 0.0) > 0.0
        and float(m.get("net_expectancy_bps") or 0.0) > 0.0
        and _pf_ok(m.get("profit_factor"))
    )
    return {
        "parent_postboundary_closed_T": len(rows),
        "child_closed_T": len(kept),
        "trade_ids": [screen.trade_id(x) for x in kept],
        "metrics": m,
        "checkpoint_6T_ready": len(kept) >= 6,
        "formal_12T_ready": len(kept) >= 12,
        "base_12T_gate_pass": base_pass,
        "formal_credit_before_boundary": 0,
        "production_grade_terminal_pass": False,
    }


def prior_failure_ids(current: Mapping[str, Any] | None) -> set[str]:
    out: set[str] = set()
    if not isinstance(current, Mapping):
        return out
    for row in current.get("reselection_history") or []:
        if isinstance(row, Mapping) and row.get("result") in {"DEVELOPMENT_FAIL", "FALSIFIED_12T"}:
            mid = str(row.get("mechanism_id") or "")
            if mid in MECHANISMS:
                out.add(mid)
    selected = current.get("selected_candidate")
    if isinstance(selected, Mapping) and str(current.get("state") or "") == "SELECTED_CHILD_12T_FALSIFIED_RESEARCH_NEXT_BOUNDARY":
        mid = str(selected.get("mechanism_id") or "")
        if mid in MECHANISMS:
            out.add(mid)
    return out


def run(out: Path, *, forensic_path: Path, screen_path: Path, current_path: Path | None, allow_network: bool) -> dict[str, Any]:
    product = read(PRODUCT)
    forensic = read(forensic_path)
    child = read(screen_path)
    current = maybe_read(current_path)

    if product.get("lane_id") != LANE_ID or product.get("stage") != "G5":
        raise RuntimeError("WEB_RESEARCH_PARENT_IDENTITY_DRIFT")
    if forensic.get("lane_id") != LANE_ID or forensic.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("WEB_RESEARCH_FORENSIC_IDENTITY_DRIFT")
    if child.get("lane_id") != LANE_ID or child.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("WEB_RESEARCH_SCREEN_IDENTITY_DRIFT")
    if int(forensic.get("w2_observed_T") or 0) != int(child.get("parent", {}).get("current_W2_T") or 0):
        raise RuntimeError("WEB_RESEARCH_FORENSIC_SCREEN_T_MISMATCH")

    frozen = current_frozen_candidate(current)
    if frozen is not None:
        result = dict(current)
        fresh = recompute_fresh(frozen)
        result["fresh"] = fresh
        if fresh["formal_12T_ready"]:
            result["state"] = "SELECTED_CHILD_12T_BASE_PASS_STRESS_REQUIRED" if fresh["base_12T_gate_pass"] else "SELECTED_CHILD_12T_FALSIFIED_RESEARCH_NEXT_BOUNDARY"
            result["next"] = "RUN_G5_STRESS_AND_PRODUCTION_PROVENANCE" if fresh["base_12T_gate_pass"] else "RUN_NEW_GROUNDED_RESEARCH_NEXT_CYCLE_WITH_FRESH_BOUNDARY"
        elif fresh["checkpoint_6T_ready"]:
            result["state"] = "SELECTED_CHILD_6T_DIAGNOSTIC"
            result["next"] = "KEEP_FROZEN_TO_12T_NO_RETUNE"
        else:
            result["state"] = "WAIT_TRUE_FRESH_SELECTED_CHILD_T"
            result["next"] = "COLLECT_TRUE_FRESH_SELECTED_CHILD_T"
        result["last_refresh_utc"] = utc(int(time.time() * 1000))
        result["provider_call_this_run"] = False
        result.pop("receipt_sha256", None)
        result["receipt_sha256"] = sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result

    if str(child.get("state") or "") != "FAIL_DEVELOPMENT_MECHANISM_RESELECT":
        result = {
            "schema_version": SCHEMA,
            "state": "NO_WEB_RESEARCH_NEEDED_CHILD_SCREEN_NOT_FAILED",
            "lane_id": LANE_ID, "strategy_id": STRATEGY_ID, "stage": "G5",
            "input_signature_sha256": input_signature(product, forensic, child, current),
            "provider_call_this_run": False,
            "selection_authority": False, "promotion_authority": False,
            "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
            "g6_promotion_eligible": False, "action": "hold", "next": "KEEP_CURRENT_CHILD_PATH",
        }
        result["receipt_sha256"] = sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    sig = input_signature(product, forensic, child, current)
    if isinstance(current, Mapping) and current.get("input_signature_sha256") == sig and not current.get("selected_candidate"):
        result = dict(current)
        result["provider_call_this_run"] = False
        result["cache_hit"] = True
        result["last_refresh_utc"] = utc(int(time.time() * 1000))
        result.pop("receipt_sha256", None)
        result["receipt_sha256"] = sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result

    forbidden = prior_failure_ids(current)
    if len(forbidden) >= len(MECHANISMS):
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_ALL_PREREGISTERED_WEB_MECHANISMS_EXHAUSTED",
            "lane_id": LANE_ID, "strategy_id": STRATEGY_ID, "stage": "G5",
            "input_signature_sha256": sig, "forbidden_mechanism_ids": sorted(forbidden),
            "provider_call_this_run": False,
            "selection_authority": False, "promotion_authority": False,
            "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
            "g6_promotion_eligible": False, "action": "hold", "next": "WAIT_NEW_STRUCTURAL_EVIDENCE_OR_PARENT_TERMINAL",
        }
        result["receipt_sha256"] = sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    if not allow_network:
        raise RuntimeError("WEB_RESEARCH_NETWORK_DISABLED_FOR_NEW_SIGNATURE")

    prompt = _research_prompt(product, forensic, child, forbidden)
    try:
        raw_text, parsed, provider = call_grounded_gemini(prompt)
        hypotheses = validate_hypotheses(parsed, forbidden)
        provider_error = None
    except Exception as exc:
        raw_text, parsed, provider, hypotheses = "", {}, {"provider": "gemini", "request_count": 0, "source_count": 0, "sources": [], "web_search_queries": []}, []
        provider_error = f"{type(exc).__name__}:{exc}"[:1500]

    reference, w2, _ = load_context()
    evaluations: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    if provider_error is None and int(provider.get("source_count") or 0) >= MIN_GROUNDED_SOURCES:
        for rank, h in enumerate(hypotheses, 1):
            evr = evaluate_candidate(reference, w2, h["mechanism_id"])
            evr["research_rank"] = rank
            evr["research_why"] = h["why"]
            evr["research_falsification"] = h["falsification"]
            evaluations.append(evr)
            if selected is None and evr["development_viable"]:
                now_ms = int(time.time() * 1000)
                boundary_ms = next_hour_boundary_ms(now_ms)
                selected = {
                    "mechanism_id": h["mechanism_id"],
                    "mechanism": MECHANISMS[h["mechanism_id"]],
                    "research_rank": rank,
                    "frozen_from_input_signature_sha256": sig,
                    "freeze_generated_at_utc": utc(now_ms),
                    "fresh_boundary_ms": boundary_ms,
                    "fresh_boundary_utc": utc(boundary_ms),
                    "boundary_rule": "STRICT_SIGNAL_AND_EXIT_AFTER_BOUNDARY",
                    "historical_or_existing_W2_formal_credit": 0,
                    "development": evr,
                }
                break

    history = []
    if isinstance(current, Mapping):
        history = [dict(x) for x in current.get("reselection_history") or [] if isinstance(x, Mapping)]
        old_sel = current.get("selected_candidate")
        if isinstance(old_sel, Mapping) and str(current.get("state") or "") == "SELECTED_CHILD_12T_FALSIFIED_RESEARCH_NEXT_BOUNDARY":
            history.append({
                "mechanism_id": old_sel.get("mechanism_id"),
                "result": "FALSIFIED_12T",
                "fresh_boundary_ms": old_sel.get("fresh_boundary_ms"),
                "source_receipt_sha256": current.get("receipt_sha256"),
            })
    for evr in evaluations:
        if not evr["development_viable"]:
            history.append({"mechanism_id": evr["mechanism_id"], "result": "DEVELOPMENT_FAIL", "input_signature_sha256": sig})

    source_ok = provider_error is None and int(provider.get("source_count") or 0) >= MIN_GROUNDED_SOURCES
    if selected is not None:
        state, nxt = "WAIT_TRUE_FRESH_SELECTED_CHILD_T", "COLLECT_TRUE_FRESH_SELECTED_CHILD_T"
        fresh = recompute_fresh(selected)
    elif provider_error is not None:
        state, nxt, fresh = "HOLD_WEB_RESEARCH_PROVIDER_ERROR", "RETRY_ONLY_AFTER_PROVIDER_RECOVERY_OR_NEW_SIGNATURE", None
    elif not source_ok:
        state, nxt, fresh = "HOLD_WEB_RESEARCH_INSUFFICIENT_GROUNDING", "WAIT_NEW_GROUNDED_EVIDENCE", None
    elif not hypotheses:
        state, nxt, fresh = "HOLD_WEB_RESEARCH_NO_SUPPORTED_ALLOWED_MECHANISM", "WAIT_NEW_STRUCTURAL_EVIDENCE_OR_PARENT_T", None
    else:
        state, nxt, fresh = "NO_VIABLE_WEB_GROUNDED_MECHANISM_WAIT_NEW_T", "WAIT_NEW_PARENT_T_THEN_RESEARCH_ONCE", None

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "lane_id": LANE_ID, "strategy_id": STRATEGY_ID, "stage": "G5",
        "target_gate": TARGET_GATE,
        "input_signature_sha256": sig,
        "parent_product_receipt_sha256": product.get("receipt_sha256"),
        "parent_runtime_trade_set_sha256": (product.get("economic_ssot") or {}).get("runtime_trade_set_sha256"),
        "parent_W2_T": int(((product.get("windows") or {}).get("W2") or {}).get("metrics", {}).get("trades") or 0),
        "forensic_receipt_sha256": forensic.get("receipt_sha256"),
        "forensic_selected_causal_axis": forensic.get("selected_causal_axis"),
        "failed_screen_receipt_sha256": child.get("receipt_sha256"),
        "failed_screen_state": child.get("state"),
        "research_summary": str(parsed.get("research_summary") or "")[:1600] if isinstance(parsed, Mapping) else "",
        "hypotheses_ranked_pre_evaluation": hypotheses,
        "deterministic_evaluations_in_research_order": evaluations,
        "selected_candidate": selected,
        "fresh": fresh,
        "reselection_history": history,
        "provider": provider,
        "provider_error": provider_error,
        "provider_call_this_run": provider_error is None,
        "cache_hit": False,
        "raw_response_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else None,
        "grounding_min_sources_required": MIN_GROUNDED_SOURCES,
        "source_grounding_pass": source_ok,
        "numeric_threshold_sweep": False,
        "symbol_session_side_sweep": False,
        "parent_mutation": False,
        "exit_risk_cost_mutation": False,
        "existing_W2_formal_child_credit": 0,
        "selection_authority": False, "promotion_authority": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
        "g6_promotion_eligible": False, "action": "hold", "next": nxt,
    }
    result["receipt_sha256"] = sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert set(MECHANISMS) == {
        "ST_GAP_NONDECAY", "CHASE_NONACCEL", "ATR_EXPANSION_CONFIRM",
        "VOL_EXPANSION_REQUIRES_ST_GAP", "VOL_COOLING_REQUIRES_TRANSITION_FRESH",
        "ST_GAP_AND_CHASE_RECONFIRM",
    }
    row = {
        "atr_expanding_vs_prior": True,
        "st_gap_nondecay_vs_prior": False,
        "chase_nonaccel_vs_prior": True,
        "transition_fresh": False,
    }
    assert not mechanism_keep(row, "ST_GAP_NONDECAY")
    assert mechanism_keep(row, "CHASE_NONACCEL")
    assert mechanism_keep(row, "ATR_EXPANSION_CONFIRM")
    assert not mechanism_keep(row, "VOL_EXPANSION_REQUIRES_ST_GAP")
    assert mechanism_keep(row, "VOL_COOLING_REQUIRES_TRANSITION_FRESH")
    assert not mechanism_keep(row, "ST_GAP_AND_CHASE_RECONFIRM")
    assert next_hour_boundary_ms(HOUR_MS + 1) == 2 * HOUR_MS
    parsed = {"hypotheses": [
        {"mechanism_id": "ST_GAP_NONDECAY", "why": "a", "falsification": "b"},
        {"mechanism_id": "BAD", "why": "x", "falsification": "y"},
        {"mechanism_id": "CHASE_NONACCEL", "why": "c", "falsification": "d"},
    ]}
    assert [x["mechanism_id"] for x in validate_hypotheses(parsed, set())] == ["ST_GAP_NONDECAY", "CHASE_NONACCEL"]
    paid_gate.validate_target_binding(LANE_ID, "G5", TARGET_GATE, provider="gemini")
    print("PASS_G5_TRENDRIDER_CAUSAL_WEB_RESEARCH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/g5_trendrider_causal_web_research_latest.json"))
    ap.add_argument("--forensic", type=Path, default=FORENSIC)
    ap.add_argument("--screen", type=Path, default=SCREEN)
    ap.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out, forensic_path=args.forensic, screen_path=args.screen, current_path=args.current, allow_network=not args.no_network)
    print(json.dumps({
        "state": r.get("state"),
        "parent_W2_T": r.get("parent_W2_T"),
        "provider_call": r.get("provider_call_this_run"),
        "source_count": (r.get("provider") or {}).get("source_count"),
        "selected": (r.get("selected_candidate") or {}).get("mechanism_id"),
        "fresh_T": (r.get("fresh") or {}).get("child_closed_T"),
        "next": r.get("next"),
        "receipt": r.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
