#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[3]
SPEND = ROOT / "backend/research/contracts/a1_paid_ai_spend_baseline_v1.json"
ROUTING = ROOT / "backend/research/contracts/a1_paid_ai_routing_policy_v1.json"
A5 = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
SWARM = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v5_latest.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
TERMINAL = ROOT / "backend/research/rebuild/a1_top5_g4_terminal_latest.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_paid_ai_roi_audit_latest.json"
SCHEMA = "zel.a1.paid_ai_roi_audit.v1"
PAID_PROVIDERS = ("gemini", "openai")
ALL_PROVIDERS = ("gemini", "openai", "groq", "workers_ai")
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk(child, (*path, str(idx)))


def _normalize_provider(raw: str) -> str | None:
    text = raw.lower().replace("cloudflare", "workers_ai").replace("workers ai", "workers_ai")
    if "gemini" in text:
        return "gemini"
    if "openai" in text or "chatgpt" in text or "gpt-" in text:
        return "openai"
    if "groq" in text:
        return "groq"
    if "workers_ai" in text or "workers-ai" in text:
        return "workers_ai"
    return None


def _provider_from(path: tuple[str, ...], row: Mapping[str, Any]) -> str | None:
    explicit = _normalize_provider(str(row.get("provider") or ""))
    if explicit:
        return explicit
    return _normalize_provider("/".join(path[-4:]))


def _provider_events(doc: Mapping[str, Any], source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    signal_keys = {"request_count", "successful", "candidate_count", "model", "skipped", "error"}
    for path, value in _walk(doc):
        if not isinstance(value, Mapping):
            continue
        provider = _provider_from(path, value)
        if provider not in ALL_PROVIDERS or not (signal_keys & set(value)):
            continue
        events.append({
            "source": source,
            "path": "/".join(path),
            "provider": provider,
            "request_count": int(value.get("request_count") or 0),
            "successful": value.get("successful") is True,
            "candidate_count": int(value.get("candidate_count") or 0),
            "skipped": value.get("skipped") is True,
            "error": bool(value.get("error")),
            "model": str(value.get("model") or value.get("requested_model") or ""),
        })
    return events


def _candidate_rows(doc: Mapping[str, Any], source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, value in _walk(doc):
        if not isinstance(value, Mapping) or not value.get("candidate_id"):
            continue
        provider = _provider_from(path, value)
        if provider not in ALL_PROVIDERS:
            continue
        rows.append({
            "source": source,
            "candidate_id": str(value.get("candidate_id")),
            "provider": provider,
            "strategy_id": str(value.get("strategy_id") or ""),
            "changed_axis": str(value.get("changed_axis") or ""),
            "candidate_sha256": str(value.get("candidate_sha256") or ""),
        })
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        unique[(row["source"], row["provider"], row["candidate_id"])] = row
    return list(unique.values())


def _pass_ids(doc: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for path, value in _walk(doc):
        if not path:
            continue
        key = path[-1]
        if key == "pass_candidate_ids" and isinstance(value, list):
            out.update(str(x) for x in value if str(x))
        elif key == "passes" and isinstance(value, list):
            for row in value:
                if isinstance(row, Mapping) and row.get("candidate_id"):
                    out.add(str(row.get("candidate_id")))
        elif isinstance(value, Mapping) and value.get("candidate_id") and value.get("economic_gate_pass") is True:
            out.add(str(value.get("candidate_id")))
    return out


def _gemini_bridges(doc: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for _, value in _walk(doc):
        if not isinstance(value, Mapping):
            continue
        origin = str(value.get("origin") or "")
        if "GEMINI" not in origin.upper():
            continue
        rows.append({
            "axis": str(value.get("axis") or value.get("changed_axis") or ""),
            "video_id": str(value.get("video_id") or ""),
            "named_channel": str(value.get("named_channel") or ""),
            "origin": origin,
        })
    unique = {(x["axis"], x["video_id"], x["named_channel"], x["origin"]): x for x in rows}
    values = list(unique.values())
    return {
        "unique_bridge_count": len(values),
        "unique_video_count": len({x["video_id"] for x in values if x["video_id"]}),
        "unique_channel_count": len({x["named_channel"] for x in values if x["named_channel"]}),
        "sample": values[:10],
        "economic_pass_claim": False,
    }


def _sum_usage(doc: Mapping[str, Any], provider: str) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for path, value in _walk(doc):
        if not isinstance(value, Mapping):
            continue
        p = _provider_from(path, value)
        if p != provider:
            continue
        for src, dst in (("input_tokens", "input_tokens"), ("prompt_tokens", "input_tokens"), ("output_tokens", "output_tokens"), ("candidate_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
            raw = value.get(src)
            if isinstance(raw, (int, float)) and raw >= 0:
                totals[dst] += int(raw)
    return totals


def _source_receipt(doc: Mapping[str, Any]) -> str | None:
    raw = str(doc.get("receipt_sha256") or "")
    return raw or None


def _economic_attribution(candidates: list[dict[str, Any]], pass_ids: set[str]) -> dict[str, Any]:
    by_provider: dict[str, dict[str, Any]] = {}
    for provider in ALL_PROVIDERS:
        ids = sorted({x["candidate_id"] for x in candidates if x["provider"] == provider})
        passed = sorted(set(ids) & pass_ids)
        by_provider[provider] = {
            "unique_candidate_count": len(ids),
            "provider_attributed_development_economic_pass_count": len(passed),
            "pass_candidate_ids": passed,
        }
    return by_provider


def run(output: Path) -> dict[str, Any]:
    spend = _read(SPEND)
    routing = _read(ROUTING)
    a5 = _read(A5)
    swarm = _read(SWARM)
    top5 = _read(TOP5)
    terminal = _read(TERMINAL)

    if spend.get("schema_version") != "zel.a1.paid_ai_spend_baseline.v1":
        raise RuntimeError("SPEND_BASELINE_SCHEMA_DRIFT")
    if routing.get("schema_version") != "zel.a1.paid_ai_routing_policy.v1":
        raise RuntimeError("ROUTING_POLICY_SCHEMA_DRIFT")
    total_spend = float(spend.get("total_user_reported_spend_eur") or 0.0)
    if total_spend <= 0:
        raise RuntimeError("USER_REPORTED_SPEND_REQUIRED")

    docs = (("a5_latest", a5), ("terminal_repair_swarm_v5_latest", swarm))
    events = [event for source, doc in docs for event in _provider_events(doc, source)]
    candidates = [row for source, doc in docs for row in _candidate_rows(doc, source)]
    pass_ids: set[str] = set()
    for _, doc in docs:
        pass_ids.update(_pass_ids(doc))
    attribution = _economic_attribution(candidates, pass_ids)

    provider_rows: dict[str, Any] = {}
    for provider in ALL_PROVIDERS:
        p_events = [x for x in events if x["provider"] == provider]
        spend_row = (spend.get("providers") or {}).get(provider) if isinstance(spend.get("providers"), Mapping) else None
        spend_eur = float((spend_row or {}).get("user_reported_spend_eur") or 0.0) if isinstance(spend_row, Mapping) else 0.0
        telemetry_verified = bool((spend_row or {}).get("telemetry_verified")) if isinstance(spend_row, Mapping) else False
        econ_pass = int(attribution[provider]["provider_attributed_development_economic_pass_count"])
        research_count = int(attribution[provider]["unique_candidate_count"])
        provider_rows[provider] = {
            "user_reported_spend_eur": spend_eur if provider in PAID_PROVIDERS else None,
            "matched_cost_telemetry_verified": telemetry_verified if provider in PAID_PROVIDERS else None,
            "observed_provider_event_count": len(p_events),
            "observed_request_count": sum(int(x["request_count"]) for x in p_events),
            "observed_success_event_count": sum(1 for x in p_events if x["successful"]),
            "observed_skipped_event_count": sum(1 for x in p_events if x["skipped"]),
            "observed_error_event_count": sum(1 for x in p_events if x["error"]),
            "observed_candidate_count": research_count,
            "provider_attributed_development_economic_pass_count": econ_pass,
            "provider_attributed_pass_candidate_ids": attribution[provider]["pass_candidate_ids"],
            "observed_token_usage_nonbilling_sum": {
                key: sum(_sum_usage(doc, provider)[key] for _, doc in docs)
                for key in ("input_tokens", "output_tokens", "total_tokens")
            },
            "cost_per_economic_pass_eur": (spend_eur / econ_pass) if telemetry_verified and econ_pass > 0 else None,
            "recovered_spend_eur": None,
            "wasted_spend_eur": None,
            "economic_roi_status": "UNPROVEN_SCOPE_UNMATCHED" if provider in PAID_PROVIDERS and not telemetry_verified else ("ECONOMIC_SIGNAL_PRESENT" if econ_pass else "NO_PROVIDER_ATTRIBUTED_ECONOMIC_PASS"),
            "routing": ((routing.get("providers") or {}).get(provider) or {}).get("default_role") if isinstance(routing.get("providers"), Mapping) else None,
        }

    gemini_bridge = _gemini_bridges(a5)
    if gemini_bridge["unique_bridge_count"] > 0:
        provider_rows["gemini"]["research_information_value"] = "PRESENT_EXECUTABLE_BRIDGE_EVIDENCE"
        provider_rows["gemini"]["gemini_named_information_bridge"] = gemini_bridge
    else:
        provider_rows["gemini"]["research_information_value"] = "NOT_OBSERVED_IN_CURRENT_AUDIT_INPUTS"
        provider_rows["gemini"]["gemini_named_information_bridge"] = gemini_bridge
    provider_rows["openai"]["research_information_value"] = "PRESENT_CANDIDATE_LINEAGE" if provider_rows["openai"]["observed_candidate_count"] > 0 else "NOT_PROVEN_BY_CURRENT_AUDIT_INPUTS"

    a5_pass = int(a5.get("development_economic_pass_count") or 0)
    primitive = swarm.get("alpha_primitive_mining") if isinstance(swarm.get("alpha_primitive_mining"), Mapping) else {}
    primitive_usable = int((primitive or {}).get("economically_usable_count") or 0)
    paid_econ_pass = sum(int(provider_rows[p]["provider_attributed_development_economic_pass_count"]) for p in PAID_PROVIDERS)
    any_research_value = gemini_bridge["unique_bridge_count"] > 0 or any(provider_rows[p]["observed_candidate_count"] > 0 for p in PAID_PROVIDERS)
    if paid_econ_pass > 0:
        verdict = "PAID_AI_ECONOMIC_SIGNAL_PRESENT_COST_SCOPE_UNMATCHED"
    elif any_research_value:
        verdict = "PAID_AI_ECONOMIC_ROI_UNPROVEN_RESEARCH_VALUE_PRESENT"
    else:
        verdict = "PAID_AI_ECONOMIC_ROI_UNPROVEN_NO_CURRENT_ATTRIBUTABLE_VALUE"

    terminal_summary = terminal.get("summary") if isinstance(terminal.get("summary"), Mapping) else {}
    canonical_provider_lineage_present = any(
        _normalize_provider(str(value)) in PAID_PROVIDERS
        for _, value in _walk(top5)
        if isinstance(value, str)
    )
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_PAID_AI_ROI_AUDIT_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "REPOSITORY_ATTRIBUTION_PLUS_USER_REPORTED_LIFETIME_SPEND",
        "verdict": verdict,
        "reported_spend": {
            "currency": str(spend.get("currency") or "EUR"),
            "total_eur": total_spend,
            "gemini_eur": float(((spend.get("providers") or {}).get("gemini") or {}).get("user_reported_spend_eur") or 0.0),
            "openai_eur": float(((spend.get("providers") or {}).get("openai") or {}).get("user_reported_spend_eur") or 0.0),
            "api_metered": False,
            "scope_matched_to_repository_events": False,
            "recovered_spend_eur": None,
            "wasted_spend_eur": None,
            "reason": "Lifetime user-reported spend is not request-level billing telemetry and cannot be allocated honestly to individual passes or failures."
        },
        "providers": provider_rows,
        "current_economic_evidence": {
            "a5_development_economic_pass_count": a5_pass,
            "terminal_repair_alpha_primitive_economically_usable_count": primitive_usable,
            "alpha_primitive_provider_attribution": False,
            "alpha_primitive_is_survivor_or_promotion_evidence": False,
            "paid_provider_attributed_development_economic_pass_count": paid_econ_pass,
            "canonical_top5_provider_lineage_present": canonical_provider_lineage_present,
            "canonical_adoption_attribution_available": canonical_provider_lineage_present,
            "g4_terminal_unresolved": int(terminal_summary.get("unresolved") or 0),
        },
        "current_cost_control_evidence": {
            "routing_policy_state": routing.get("state"),
            "identical_input_signature_cache_required": bool((routing.get("mandatory_controls") or {}).get("input_signature_cache")),
            "identical_input_paid_recall": bool((routing.get("mandatory_controls") or {}).get("identical_input_paid_recall")),
            "cosine_dedup_threshold": float((routing.get("mandatory_controls") or {}).get("cosine_dedup_threshold") or 0.0),
            "a5_paid_request_count_latest": int(a5.get("paid_request_count") or 0),
            "a5_paid_request_cap": int(a5.get("paid_request_cap") or 0),
            "terminal_swarm_paid_request_count_latest": int(((swarm.get("api_roi") or {}).get("paid_request_count")) or 0) if isinstance(swarm.get("api_roi"), Mapping) else None,
            "terminal_swarm_cache_hit_latest": ((swarm.get("api_roi") or {}).get("cache_hit")) if isinstance(swarm.get("api_roi"), Mapping) else None,
            "broad_paid_fanout_allowed": False,
        },
        "source_receipts": {
            "a5": _source_receipt(a5),
            "terminal_repair_swarm_v5": _source_receipt(swarm),
            "top5": _source_receipt(top5),
            "g4_terminal": _source_receipt(terminal),
        },
        "required_next": [
            "KEEP_GEMINI_AND_OPENAI_ESCALATION_ONLY",
            "ADD_REQUEST_LEVEL_COST_TELEMETRY_BEFORE_ANY_COST_PER_PASS_OR_WASTE_CLAIM",
            "ATTRIBUTE_PROVIDER_TO_REPLAY_PASS_AND_CANONICAL_ADOPTION",
            "DO_NOT_TRIGGER_PAID_AI_ONLY_BECAUSE_FRESH_T_IS_WAITING"
        ],
        **AUTH,
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake = {
        "providers": {"gemini_rescue": {"successful": True, "request_count": 1, "candidate_count": 2, "model": "gemini-x"}},
        "candidates": [{"candidate_id": "g1", "provider": "gemini", "strategy_id": "s"}],
        "passes": [{"candidate_id": "g1"}],
        "axis": {"axis": "X", "origin": "NAMED_CHANNEL_GEMINI_EXECUTABLE_BRIDGE_V1", "video_id": "v", "named_channel": "c"},
    }
    events = _provider_events(fake, "fake")
    assert len(events) == 1 and events[0]["provider"] == "gemini" and events[0]["request_count"] == 1
    candidates = _candidate_rows(fake, "fake")
    assert len(candidates) == 1 and candidates[0]["provider"] == "gemini"
    assert _pass_ids(fake) == {"g1"}
    assert _gemini_bridges(fake)["unique_bridge_count"] == 1
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED" and AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_PAID_AI_ROI_AUDIT_V1_SELF_TEST")
    print("PASS_NO_FAKE_COST_PER_PASS_WITH_UNMATCHED_LIFETIME_SPEND")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_paid_ai_roi_audit_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result["state"],
        "verdict": result["verdict"],
        "reported_spend_eur": result["reported_spend"]["total_eur"],
        "gemini_bridge_count": result["providers"]["gemini"]["gemini_named_information_bridge"]["unique_bridge_count"],
        "paid_provider_economic_pass": result["current_economic_evidence"]["paid_provider_attributed_development_economic_pass_count"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
