#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af

ROOT = Path(__file__).resolve().parents[3]
MAP = ROOT / "backend/research/architecture_factory/a1_external_research_exact25_map_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
FREE_EVIDENCE = ROOT / "backend/research/architecture_factory/a1_free_evidence_sweep_v1.json"
YOUTUBE = ROOT / "backend/research/architecture_factory/a1_youtube_evidence_latest.json"
PREVIOUS = ROOT / "backend/research/architecture_factory/a1_research_factory_latest.json"
SCHEMA = "zel.a1_research_factory.v1"
DEDUP_THRESHOLD = 0.85
BACKLOG_TOP_K = 5
AI_STRATEGY_LIMIT = 3
COMMON_READY = {"ohlcv", "volume"}
PRIMARY_TIERS = {"peer_reviewed", "primary_preprint", "working_paper", "discovered_primary_abstract"}

AXIS_LIBRARY: dict[str, dict[str, Any]] = {
    "trend": {"axis": "TREND_REGIME_OWNER_ONLY", "required_sources": ["ohlcv"], "mechanism": "Change only entry-time ownership across observable trend states; preserve native signal/risk geometry."},
    "momentum": {"axis": "MOMENTUM_STATE_OWNER_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only ownership of the frozen signal to an observable momentum state."},
    "reversal": {"axis": "REVERSAL_REGIME_OWNER_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only entry-time ownership to a reversal-compatible state; preserve exits and risk."},
    "mean reversion": {"axis": "MEAN_REVERSION_REGIME_OWNER_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only regime ownership of the frozen mean-reversion geometry."},
    "breakout": {"axis": "BREAKOUT_CONFIRMATION_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Keep breakout geometry frozen and change only one entry-time confirmation state."},
    "liquidity": {"axis": "LIQUIDITY_REGIME_OWNER_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only entry eligibility across observable liquidity states."},
    "volatility": {"axis": "VOLATILITY_REGIME_OWNER_ONLY", "required_sources": ["ohlcv"], "mechanism": "Change only ownership across lagged observable volatility states."},
    "volume": {"axis": "RELATIVE_VOLUME_CONFIRMATION_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Keep signal geometry frozen and change only relative-volume confirmation at entry time."},
    "session": {"axis": "SESSION_PRICE_DISCOVERY_OWNER_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only deterministic session ownership using completed bars."},
    "funding": {"axis": "FUNDING_STATE_OWNER_ONLY", "required_sources": ["ohlcv", "funding"], "mechanism": "Change only ownership across timestamp-safe funding states; funding is not a standalone direction oracle."},
    "basis": {"axis": "BASIS_DISLOCATION_OWNER_ONLY", "required_sources": ["ohlcv", "funding", "basis"], "mechanism": "Change only ownership across observable basis-dislocation states with funding context."},
    "open interest": {"axis": "OI_POSITIONING_OWNER_ONLY", "required_sources": ["ohlcv", "open_interest"], "mechanism": "Change only entry-time ownership across open-interest positioning states."},
    "order flow": {"axis": "DEPTH_NORMALIZED_OFI_CONFIRMATION_ONLY", "required_sources": ["l2_order_book", "trade_flow"], "mechanism": "Keep parent geometry frozen and change only depth-normalized pre-entry order-flow confirmation."},
    "vwap": {"axis": "VWAP_TRANSITION_ONLY", "required_sources": ["ohlcv", "volume"], "mechanism": "Change only completed-bar VWAP transition ownership; preserve risk and exit geometry."},
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def toks(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def cosine_text(a: str, b: str) -> float:
    va, vb = toks(a), toks(b)
    if not va or not vb:
        return 0.0
    dot = sum(v * vb.get(k, 0) for k, v in va.items())
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def abstract_from_openalex(inv: Any) -> str:
    if not isinstance(inv, Mapping):
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inv.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int):
                pairs.append((pos, str(word)))
    pairs.sort()
    return " ".join(word for _, word in pairs)


def http_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ZEL-Research-Factory/1.0 (+research-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def discover_openalex(query: str, limit: int = 6) -> tuple[list[dict[str, Any]], str | None]:
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": query, "per-page": limit})
    try:
        payload = http_json(url)
    except Exception as exc:  # noqa: BLE001
        return [], f"OPENALEX:{type(exc).__name__}:{str(exc)[:180]}"
    out = []
    for raw in payload.get("results") or []:
        if not isinstance(raw, Mapping):
            continue
        title = str(raw.get("title") or "").strip()
        abstract = abstract_from_openalex(raw.get("abstract_inverted_index"))
        doi = str(raw.get("doi") or "").replace("https://doi.org/", "").strip()
        if not title:
            continue
        key = doi.lower() if doi else str(raw.get("id") or title)
        out.append({
            "id": "DX:" + hashlib.sha256(key.encode()).hexdigest()[:16],
            "tier": "discovered_primary_abstract" if doi and abstract else "discovered_metadata_only",
            "source_type": "OpenAlex",
            "identifier": f"DOI:{doi}" if doi else str(raw.get("id") or ""),
            "title": title,
            "claim": abstract[:1800] if abstract else title,
            "publication_year": raw.get("publication_year"),
            "citation_count": int(raw.get("cited_by_count") or 0),
            "query": query,
            "limitations": "Fresh external discovery. Metadata/abstract is hypothesis input only; local causal replay and source lineage remain mandatory.",
            "promotion_authority": False,
        })
    return out, None


def discover_crossref(query: str, limit: int = 6) -> tuple[list[dict[str, Any]], str | None]:
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": query, "rows": limit})
    try:
        payload = http_json(url)
    except Exception as exc:  # noqa: BLE001
        return [], f"CROSSREF:{type(exc).__name__}:{str(exc)[:180]}"
    out = []
    for raw in (((payload or {}).get("message") or {}).get("items") or []):
        if not isinstance(raw, Mapping):
            continue
        titles = raw.get("title") or []
        title = str(titles[0] if titles else "").strip()
        doi = str(raw.get("DOI") or "").strip()
        abstract = strip_html(str(raw.get("abstract") or ""))
        if not title:
            continue
        key = doi.lower() if doi else title.lower()
        out.append({
            "id": "DX:" + hashlib.sha256(key.encode()).hexdigest()[:16],
            "tier": "discovered_primary_abstract" if doi and abstract else "discovered_metadata_only",
            "source_type": "Crossref",
            "identifier": f"DOI:{doi}" if doi else str(raw.get("URL") or ""),
            "title": title,
            "claim": abstract[:1800] if abstract else title,
            "publication_year": (((raw.get("published") or {}).get("date-parts") or [[None]])[0] or [None])[0],
            "citation_count": int(raw.get("is-referenced-by-count") or 0),
            "query": query,
            "limitations": "Fresh external discovery. Metadata/abstract is hypothesis input only; local causal replay and source lineage remain mandatory.",
            "promotion_authority": False,
        })
    return out, None


def source_key(row: Mapping[str, Any]) -> str:
    identifier = str(row.get("identifier") or "").lower().strip()
    if identifier:
        return identifier
    return re.sub(r"[^a-z0-9]+", " ", str(row.get("title") or row.get("claim") or "").lower()).strip()


def dedup_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    keys: set[str] = set()
    for row in rows:
        key = source_key(row)
        if key and key in keys:
            continue
        text = f"{row.get('title','')} {row.get('claim','')}"
        if any(cosine_text(text, f"{old.get('title','')} {old.get('claim','')}") > 0.94 for old in kept):
            continue
        if key:
            keys.add(key)
        kept.append(row)
    return kept


def normalize_static_sources(mapping: Mapping[str, Any], free: Mapping[str, Any], youtube: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source_id, raw in (mapping.get("sources") or {}).items():
        if isinstance(raw, Mapping):
            out.append({"id": str(source_id), **dict(raw), "source_origin": "exact25_map"})
    for raw in free.get("sources") or []:
        if isinstance(raw, Mapping) and raw.get("id"):
            out.append({**dict(raw), "source_origin": "free_evidence"})
    for raw in youtube.get("sources") or []:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("view_snapshot_verified") is not True or raw.get("accepted_for_hypothesis_only") is not True:
            continue
        if int(raw.get("view_count_snapshot") or 0) < 30_000:
            continue
        out.append({**dict(raw), "tier": str(raw.get("tier") or "verified_youtube_hypothesis"), "source_origin": "verified_youtube"})
    return dedup_sources(out)


def strategy_context(strategy_id: str, proposal: Mapping[str, Any]) -> str:
    return " ".join([
        strategy_id.replace("_", " "),
        str(proposal.get("axis") or "").replace("_", " "),
        str(proposal.get("mechanism") or ""),
        " ".join(str(x) for x in (proposal.get("required_data") or [])),
        "cryptocurrency perpetual futures bitcoin ethereum",
    ])


def search_query(strategy_id: str, proposal: Mapping[str, Any]) -> str:
    axis = re.sub(r"_+", " ", str(proposal.get("axis") or "")).lower()
    words = " ".join(axis.split()[:7])
    return f"cryptocurrency perpetual futures {strategy_id.replace('_',' ')} {words}"[:240]


def relevance(context: str, row: Mapping[str, Any]) -> float:
    text = f"{row.get('title','')} {row.get('claim','')}"
    return cosine_text(context, text)


def source_weight(row: Mapping[str, Any]) -> float:
    tier = str(row.get("tier") or "")
    if tier == "peer_reviewed": return 5.0
    if tier == "primary_preprint": return 4.4
    if tier == "working_paper": return 4.0
    if tier == "discovered_primary_abstract": return 3.5
    if "youtube" in tier: return 1.2
    if "community" in tier: return 1.0
    return 0.6


def tags_for_source(row: Mapping[str, Any]) -> set[str]:
    text = f"{row.get('title','')} {row.get('claim','')} " + " ".join(str(x) for x in (row.get("extractable_axes") or []))
    low = text.lower()
    tags: set[str] = set()
    patterns = {
        "mean reversion": ["mean reversion", "mean-reversion"],
        "open interest": ["open interest", "positioning"],
        "order flow": ["order flow", "order-flow", "order book", "order-book", "imbalance"],
        "trend": ["trend", "trend-follow"], "momentum": ["momentum"], "reversal": ["reversal", "fade"],
        "breakout": ["breakout", "break out", "trading range"], "liquidity": ["liquidity", "liquid"],
        "volatility": ["volatility", "variance"], "volume": ["volume"], "session": ["intraday", "session", "time-of-day", "price discovery"],
        "funding": ["funding rate", "funding"], "basis": ["basis", "futures premium"], "vwap": ["vwap", "volume weighted average price"],
    }
    for tag, needles in patterns.items():
        if any(n in low for n in needles):
            tags.add(tag)
    return tags


def candidate_text(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get(k) or "") for k in ("axis", "mechanism", "strategy_id"))


def candidate_dedup(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda x: (-float(x.get("score") or 0), str(x.get("axis") or ""))):
        if any(cosine_text(candidate_text(row), candidate_text(old)) > DEDUP_THRESHOLD for old in kept):
            continue
        kept.append(row)
    return kept


def build_axis_backlog(strategy_id: str, proposal: Mapping[str, Any], sources: list[dict[str, Any]], context: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    base_source_ids = [str(x) for x in (proposal.get("source_ids") or [])]
    base_support = [x for x in sources if str(x.get("id")) in set(base_source_ids)]
    candidates.append({
        "strategy_id": strategy_id,
        "axis": str(proposal.get("axis") or ""),
        "mechanism": str(proposal.get("mechanism") or ""),
        "required_sources": list(proposal.get("required_data") or []),
        "source_ids": base_source_ids,
        "source_tiers": sorted({str(x.get("tier") or "") for x in base_support}),
        "score": 20.0 + sum(source_weight(x) for x in base_support),
        "origin": "SEALED_EXACT25_AXIS",
        "status": "EXISTING_PREREG_AXIS",
    })
    tagged: dict[str, list[dict[str, Any]]] = {}
    for src in sources:
        if relevance(context, src) < 0.08:
            continue
        for tag in tags_for_source(src):
            tagged.setdefault(tag, []).append(src)
    for tag, support in tagged.items():
        lib = AXIS_LIBRARY[tag]
        ids = [str(x.get("id")) for x in support[:6] if x.get("id")]
        rel = max((relevance(context, x) for x in support), default=0.0)
        primary = sum(1 for x in support if str(x.get("tier") or "") in PRIMARY_TIERS)
        score = 4.0 + rel * 12.0 + min(len(support), 4) * 1.2 + min(primary, 3) * 1.5
        candidates.append({
            "strategy_id": strategy_id,
            "axis": lib["axis"], "mechanism": lib["mechanism"], "required_sources": lib["required_sources"],
            "source_ids": ids, "source_tiers": sorted({str(x.get("tier") or "") for x in support}),
            "score": round(score, 4), "origin": "CONTINUOUS_EVIDENCE_DISCOVERY", "status": "QUEUED_FOR_AI_SYNTHESIS",
        })
    out = candidate_dedup([x for x in candidates if x.get("axis")])[:BACKLOG_TOP_K]
    for idx, row in enumerate(out, 1):
        row["rank"] = idx
        row["source_gate"] = "READY_COMMON" if set(row.get("required_sources") or []).issubset(COMMON_READY) else "NEEDS_SOURCE_HISTORY_GATE"
        row["candidate_sha256"] = sha({k: v for k, v in row.items() if k not in {"rank", "candidate_sha256"}})
    return out


def priority_targets(ledger: Mapping[str, Any], strategy_ids: list[str], backlogs: Mapping[str, Any], limit: int) -> list[str]:
    rows = []
    states = ledger.get("strategies") or {}
    for sid in strategy_ids:
        raw = states.get(sid) if isinstance(states, Mapping) else {}
        raw = raw if isinstance(raw, Mapping) else {}
        status = str(raw.get("status") or "")
        terminal = status.startswith("A1_") and status not in {"A1_SURVIVOR", "A1_EXACT25_BASELINE_SWEEP_ACTIVE"}
        backlog = backlogs.get(sid) if isinstance(backlogs, Mapping) else []
        backlog_n = len(backlog) if isinstance(backlog, list) else 0
        score = (100 if terminal else 0) + max(0, BACKLOG_TOP_K - backlog_n) * 5 + min(int(raw.get("completed_trades") or 0), 25)
        rows.append((score, sid))
    rows.sort(key=lambda x: (-x[0], x[1]))
    return [sid for _, sid in rows[: max(0, limit)]]


def ai_scout(strategy_id: str, ledger_row: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_ids = {str(x.get("id")) for x in evidence_rows if x.get("id")}
    context = {
        "objective": "Build a persistent one-axis hypothesis backlog for this exact strategy; prefer mechanisms that can survive verified cost and fresh causal controls.",
        "verified_round_trip_cost_bps_reference": float(ledger_row.get("verified_pretrade_cost_bps") or 14.0),
        "available_source_vocabulary": ["ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"],
        "current_failure_targets": [{
            "strategy_id": strategy_id, "status": ledger_row.get("status"), "completed_trades": ledger_row.get("completed_trades"),
            "gross_expectancy_bps": ledger_row.get("gross_expectancy_bps"), "net_expectancy_bps": ledger_row.get("net_expectancy_bps"),
            "profit_factor": ledger_row.get("profit_factor"), "drawdown_bps": ledger_row.get("drawdown_bps"),
        }],
        "external_evidence": evidence_rows[:20],
        "constraints": {"baseline_mutation": False, "threshold_sweep": False, "best_horizon_cherry_pick": False, "fee_reduction": False, "sealed_holdout_visibility": False, "one_axis_per_repair": True},
    }
    prompt = af.generator_prompt(context)
    generated: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}
    for provider, fn in (("openai", af.call_openai_generator), ("groq", af.call_groq_generator)):
        try:
            model, raw, lineage = fn(prompt)
            got = af.validate_candidates(raw, provider, source_ids, {strategy_id})
            providers[provider] = {"successful": True, "model": model, **lineage, "candidate_count": len(got)}
            generated.extend(got)
        except Exception as exc:  # noqa: BLE001
            providers[provider] = {"successful": False, "error": af.safe_error(exc)}
    generated = af.dedup(sorted(generated, key=lambda x: -af.base_score(x)), DEDUP_THRESHOLD)[:3]
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix=f"a1-rf-{strategy_id}-") as td:
        root = Path(td)
        for idx, candidate in enumerate(generated):
            work = root / str(idx); work.mkdir()
            reviews: dict[str, Any] = {}
            try:
                reviews["openai"] = af.openai_critic(candidate)
            except Exception as exc:  # noqa: BLE001
                reviews["openai"] = {"successful": False, "error": af.safe_error(exc)}
            reviews["groq"] = af.subprocess_review("scripts/strategy11_groq_redteam.py", candidate, work, env, "groq")
            reviews["workers_ai"] = af.subprocess_review("scripts/strategy11_workers_ai_guard.py", candidate, work, env, "workers")
            passes = rejects = 0
            for name, review in reviews.items():
                if name == candidate.get("provider"):
                    continue
                decision = str(review.get("decision") or "")
                if review.get("successful") and decision in {"PASS", "PASS_TO_REPLAY"}: passes += 1
                if review.get("successful") and decision == "REJECT": rejects += 1
            score = af.base_score(candidate) + passes * 2.5 - rejects * 4.0
            required = set(candidate.get("required_sources") or [])
            reviewed.append({**candidate, "cross_reviews": reviews, "independent_passes": passes, "independent_rejects": rejects,
                             "score": round(score, 4), "source_gate": "READY_COMMON" if required.issubset(COMMON_READY) else "NEEDS_SOURCE_HISTORY_GATE",
                             "eligible_for_experiment_queue": passes >= 2 and rejects == 0})
    reviewed.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("candidate_id") or "")))
    return {"strategy_id": strategy_id, "providers": providers, "reviewed": reviewed[:3]}


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = AI_STRATEGY_LIMIT) -> dict[str, Any]:
    mapping, ledger, free, youtube, previous = read(MAP), read(LEDGER), read(FREE_EVIDENCE), read(YOUTUBE), read(PREVIOUS)
    strategy_ids = list(ledger.get("strategy_order") or [])
    proposals = mapping.get("strategies") or {}
    if len(strategy_ids) != 25 or len(set(strategy_ids)) != 25 or set(strategy_ids) != set(proposals):
        raise RuntimeError("EXACT25_RESEARCH_FACTORY_IDENTITY_REQUIRED")

    static_sources = normalize_static_sources(mapping, free, youtube)
    discovered: list[dict[str, Any]] = []
    discovery_errors: list[str] = []
    queries: dict[str, str] = {}
    if network:
        for sid in strategy_ids:
            proposal = proposals[sid] if isinstance(proposals[sid], Mapping) else {}
            q = search_query(sid, proposal); queries[sid] = q
            for fn in (discover_openalex, discover_crossref):
                rows, err = fn(q)
                for row in rows:
                    row["applicable_strategy"] = sid
                discovered.extend(rows)
                if err: discovery_errors.append(f"{sid}:{err}")
            time.sleep(0.05)
    discovered = dedup_sources(discovered)
    all_sources = dedup_sources([*static_sources, *discovered])

    strategy_sources: dict[str, list[dict[str, Any]]] = {}
    backlogs: dict[str, list[dict[str, Any]]] = {}
    for sid in strategy_ids:
        proposal = proposals[sid] if isinstance(proposals[sid], Mapping) else {}
        ctx = strategy_context(sid, proposal)
        base_ids = {str(x) for x in (proposal.get("source_ids") or [])}
        ranked = []
        for row in all_sources:
            rel = relevance(ctx, row)
            if str(row.get("id")) in base_ids: rel += 1.0
            if row.get("applicable_strategy") == sid: rel += 0.30
            if rel < 0.08 and str(row.get("id")) not in base_ids:
                continue
            ranked.append((rel + source_weight(row) / 20.0, {**row, "relevance": round(rel, 4)}))
        ranked.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
        strategy_sources[sid] = [row for _, row in ranked[:20]]
        backlogs[sid] = build_axis_backlog(sid, proposal, strategy_sources[sid], ctx)

    priority = priority_targets(ledger, strategy_ids, backlogs, ai_strategy_limit)
    ai_results: dict[str, Any] = {}
    if ai:
        ledger_rows = ledger.get("strategies") or {}
        for sid in priority:
            raw = ledger_rows.get(sid) if isinstance(ledger_rows, Mapping) else {}
            raw = raw if isinstance(raw, Mapping) else {}
            ai_results[sid] = ai_scout(sid, raw, strategy_sources[sid])
            for candidate in ai_results[sid].get("reviewed") or []:
                backlogs[sid].append({
                    "rank": 999, "strategy_id": sid, "axis": candidate.get("changed_axis"), "mechanism": candidate.get("mechanism"),
                    "required_sources": candidate.get("required_sources") or [], "source_ids": candidate.get("evidence_ids") or [],
                    "source_tiers": [], "score": candidate.get("score"), "origin": "MULTI_AI_SCOUT", "status": "AI_REVIEWED",
                    "source_gate": candidate.get("source_gate"), "candidate_sha256": candidate.get("candidate_sha256"),
                    "eligible_for_experiment_queue": bool(candidate.get("eligible_for_experiment_queue")),
                    "provider": candidate.get("provider"), "cross_reviews": candidate.get("cross_reviews"),
                })
            merged = candidate_dedup(backlogs[sid])[:BACKLOG_TOP_K]
            for idx, row in enumerate(merged, 1): row["rank"] = idx
            backlogs[sid] = merged

    experiment_queue = []
    for sid in strategy_ids:
        for row in backlogs[sid]:
            if row.get("origin") == "SEALED_EXACT25_AXIS":
                continue
            experiment_queue.append({**row, "strategy_id": sid})
    experiment_queue.sort(key=lambda x: (x.get("source_gate") != "READY_COMMON", not bool(x.get("eligible_for_experiment_queue")), -float(x.get("score") or 0), x["strategy_id"]))

    prior_sha = previous.get("receipt_sha256") if isinstance(previous, Mapping) else None
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "schema_version": SCHEMA, "state": "PASS_RESEARCH_FACTORY_BACKLOG_READY",
        "created_at_utc": now, "exact25_strategy_count": 25,
        "external_source_count": len(all_sources), "static_source_count": len(static_sources), "new_discovered_source_count": len(discovered),
        "discovered_primary_abstract_count": sum(1 for x in discovered if x.get("tier") == "discovered_primary_abstract"),
        "discovery_query_count": len(queries), "discovery_errors": discovery_errors[:50], "queries": queries,
        "dedup_cosine_threshold": DEDUP_THRESHOLD, "backlog_top_k": BACKLOG_TOP_K,
        "strategy_backlogs": backlogs, "ai_scout_priority_strategy_ids": priority, "ai_scout_results": ai_results,
        "experiment_queue": experiment_queue[:50], "experiment_queue_count": len(experiment_queue),
        "next_experiment_candidate": next((x for x in experiment_queue if x.get("source_gate") == "READY_COMMON" and x.get("eligible_for_experiment_queue") is True), None),
        "previous_receipt_sha256": prior_sha,
        "policy": {
            "continuous_external_discovery": True, "per_strategy_persistent_backlog": True, "min_backlog_target": 3,
            "one_axis_per_experiment": True, "youtube_and_community_hypothesis_only": True,
            "primary_evidence_preferred": True, "no_threshold_sweep": True, "no_holdout_outcome_access": True,
            "failure_advances_to_next_backlog_candidate": True, "promotion_requires_existing_alpha_proof_and_fresh_gates": True,
        },
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "protected_mutations": 0,
    }
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    a = {"axis": "LIQUIDITY_REGIME_OWNER_ONLY", "mechanism": "liquidity owner", "strategy_id": "x", "score": 5.0}
    b = {"axis": "LIQUIDITY_REGIME_OWNER_ONLY", "mechanism": "liquidity owner", "strategy_id": "x", "score": 4.0}
    c = {"axis": "BREAKOUT_CONFIRMATION_ONLY", "mechanism": "breakout volume", "strategy_id": "x", "score": 3.0}
    assert len(candidate_dedup([a, b, c])) == 2
    assert "basis" in tags_for_source({"title": "Perpetual futures basis and funding", "claim": "basis dislocation"})
    assert "funding" in tags_for_source({"title": "Perpetual futures basis and funding", "claim": "basis dislocation"})
    assert search_query("trend_rider", {"axis": "TREND_OWNER_ONLY"}).startswith("cryptocurrency perpetual futures")
    print("PASS_A1_RESEARCH_FACTORY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v1.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-strategy-limit", type=int, default=AI_STRATEGY_LIMIT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, network=not args.no_network, ai=not args.no_ai, ai_strategy_limit=max(0, args.ai_strategy_limit))
    print(json.dumps({
        "state": result["state"], "new_discovered_source_count": result["new_discovered_source_count"],
        "primary_abstract_count": result["discovered_primary_abstract_count"], "experiment_queue_count": result["experiment_queue_count"],
        "ai_scout_priority_strategy_ids": result["ai_scout_priority_strategy_ids"],
        "next_experiment_candidate": result["next_experiment_candidate"], "receipt_sha256": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
