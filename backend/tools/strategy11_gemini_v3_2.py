from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tools.strategy11_bounded_internal_mutation_v3 import (  # noqa: E402
    mutation_domain,
    native_regimes,
    semantic_role,
    side_scope,
)

VERSION = "STRATEGY11_GEMINI_DIRECT_VIDEO_V3_2"
PROMPT_VERSION = "S11_GEMINI_V3_2_MULTIMODAL_DISTINCT_AXIS"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
PREFERRED_MODELS = (
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
)
REVIEW_ONLY = {"supertrend_pullback", "trend_rider"}
STRONG = {"trend_ma_macd"}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def lane(count: int) -> str:
    if count <= 0:
        return "A_ENTRY_LIVENESS_REPAIR"
    if count <= 4:
        return "B_COVERAGE_EXPANSION"
    if count <= 9:
        return "C_DISCOVERY_OPTIMIZATION"
    return "D_QUALITY_OPTIMIZATION"


def list_models(key: str) -> list[str]:
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    eligible = [
        str(row["name"])
        for row in payload.get("models", [])
        if row.get("name") and "generateContent" in row.get("supportedGenerationMethods", [])
    ]
    ordered = [model for model in PREFERRED_MODELS if model in eligible]
    ordered.extend(model for model in eligible if model not in ordered and "flash" in model.lower())
    return ordered


def call_direct_video(key: str, prompt: str, sources: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    models = list_models(key)
    if not models:
        raise RuntimeError("NO_ELIGIBLE_GEMINI_FLASH_MODEL")
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend({"file_data": {"file_uri": str(row["url"])}} for row in sources)
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": 32768,
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    errors: list[str] = []
    for model in models:
        try:
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=900) as response:
                generated = json.load(response)
            texts: list[str] = []
            for candidate in generated.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part.get("text"), str):
                        texts.append(part["text"])
            text = "\n".join(texts).strip()
            if not text:
                raise RuntimeError("EMPTY_GEMINI_RESPONSE")
            return model, text
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}:HTTP_{exc.code}:{detail[:800]}")
        except Exception as exc:  # pragma: no cover - provider diagnostics
            errors.append(f"{model}:{type(exc).__name__}:{str(exc)[:500]}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def find_results(root: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("**/result.json")):
        try:
            row = read_json(path)
        except Exception:
            continue
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id:
            output[strategy_id] = row
    return output


def metric_view(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": row.get("variant_id"),
        "trade_count": row.get("trade_count"),
        "win_rate_pct": row.get("win_rate_pct"),
        "net_return_pct_sum": row.get("net_return_pct_sum"),
        "net_profit_factor": row.get("net_profit_factor"),
        "payoff_ratio": row.get("payoff_ratio"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "positive_window_count": row.get("positive_window_count"),
        "research_state": row.get("research_state"),
        "short_observer": row.get("short_observer"),
    }


def top_hold_reasons(control: Mapping[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    diagnostics = control.get("opportunity_diagnostics")
    reasons = diagnostics.get("hold_reasons") if isinstance(diagnostics, Mapping) else {}
    if not isinstance(reasons, Mapping):
        return []
    rows = [{"reason": str(key), "count": int(value or 0)} for key, value in reasons.items()]
    rows.sort(key=lambda value: value["count"], reverse=True)
    return rows[:limit]


def tested_map(ledger: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in ledger.get("rows", []):
        if isinstance(row, Mapping) and row.get("strategy_id"):
            result[str(row["strategy_id"])] = {str(value) for value in row.get("tested_candidate_ids", [])}
    return result


def preferred_direction(current_lane: str) -> str:
    return "RELAX" if current_lane in {
        "A_ENTRY_LIVENESS_REPAIR",
        "B_COVERAGE_EXPANSION",
        "C_DISCOVERY_OPTIMIZATION",
    } else "TIGHT"


def candidate_catalog(
    registry_row: Mapping[str, Any],
    current_lane: str,
    tested_ids: set[str],
    max_items: int,
) -> list[dict[str, Any]]:
    strategy_id = str(registry_row["strategy_id"])
    if strategy_id in REVIEW_ONLY or not registry_row.get("config_injectable"):
        return []
    tested_upper = {value.upper() for value in tested_ids}
    fields = [dict(value) for value in registry_row.get("safe_internal_fields", []) if isinstance(value, Mapping)]
    role_order = {
        "A_ENTRY_LIVENESS_REPAIR": ("ENTRY_TRIGGER", "REGIME_GATE", "ENTRY_SUPPORT", "INDICATOR_PERIOD", "BEAM_CONFIRMATION"),
        "B_COVERAGE_EXPANSION": ("ENTRY_TRIGGER", "REGIME_GATE", "ENTRY_SUPPORT", "INDICATOR_PERIOD", "BEAM_CONFIRMATION"),
        "C_DISCOVERY_OPTIMIZATION": ("ENTRY_TRIGGER", "ENTRY_SUPPORT", "REGIME_GATE", "INDICATOR_PERIOD", "BEAM_CONFIRMATION"),
        "D_QUALITY_OPTIMIZATION": ("ENTRY_SUPPORT", "ENTRY_TRIGGER", "REGIME_GATE", "BEAM_CONFIRMATION", "INDICATOR_PERIOD"),
    }[current_lane]
    role_rank = {role: index for index, role in enumerate(role_order)}
    side_rank = {"LONG_ONLY": 0, "NEUTRAL": 1, "SHORT_ONLY": 2}
    eligible: list[dict[str, Any]] = []
    for field in fields:
        name = str(field["field"])
        domain = mutation_domain(name)
        role = semantic_role(name)
        scope = side_scope(name)
        if domain != "ENTRY_LOGIC" or role not in role_rank:
            continue
        marker = f"_{name.upper()}_"
        if any(marker in f"_{candidate_id}_" for candidate_id in tested_upper):
            continue
        if strategy_id == "trend_ma_macd" and name == "max_chase_dist_atr":
            continue
        direction = preferred_direction(current_lane)
        value = field.get("relaxed_value") if direction == "RELAX" else field.get("tightened_value")
        if value is None:
            continue
        candidate_id = f"GEMV32_{name.upper()}_{direction}"
        candidate = {
            "candidate_id": candidate_id,
            "kind": "INTERNAL_MUTATION",
            "axis": f"{field.get('axis')}:{name}",
            "mutation_domain": domain,
            "semantic_role": role,
            "side_scope": scope,
            "field": name,
            "base_value": field.get("base_value"),
            "mutation_value": value,
            "regime_scope": None,
            "family": registry_row.get("family"),
            "one_axis_only": True,
            "same_axis_generation_limit": 2,
            "canonical_mutated": False,
        }
        candidate["candidate_spec_sha256"] = stable_sha(candidate)
        eligible.append(candidate)
    eligible.sort(key=lambda value: (
        side_rank.get(str(value["side_scope"]), 99),
        role_rank.get(str(value["semantic_role"]), 99),
        str(value["field"]),
    ))
    return eligible[:max_items]


def build_profiles(
    registry: Mapping[str, Any],
    ledger: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    max_catalog: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    tested = tested_map(ledger)
    profiles: list[dict[str, Any]] = []
    catalogs: dict[str, dict[str, dict[str, Any]]] = {}
    for registry_row in registry.get("rows", []):
        if not isinstance(registry_row, Mapping):
            continue
        strategy_id = str(registry_row.get("strategy_id") or "")
        if not strategy_id or strategy_id == "alpha_combo":
            continue
        result = results.get(strategy_id)
        if not result:
            raise RuntimeError(f"RESULT_MISSING:{strategy_id}")
        control = result.get("control") if isinstance(result.get("control"), Mapping) else {}
        current_lane = lane(int(control.get("trade_count") or 0))
        catalog_rows = candidate_catalog(registry_row, current_lane, tested.get(strategy_id, set()), max_catalog)
        catalogs[strategy_id] = {str(row["candidate_id"]): row for row in catalog_rows}
        profile = {
            "strategy_id": strategy_id,
            "family": registry_row.get("family"),
            "review_mode": "NEW_CHILD_ONLY" if strategy_id in REVIEW_ONLY else "BOUNDED_REPLAY",
            "priority": "STRONG_SURVIVOR" if strategy_id in STRONG else "FAILED_OR_HOLD_RESCUE",
            "lane": current_lane,
            "control": metric_view(control),
            "tested_variants": [metric_view(row) for row in result.get("variants", []) if isinstance(row, Mapping)],
            "top_hold_reasons": top_hold_reasons(control),
            "available_candidate_ids": sorted(catalogs[strategy_id]),
            "candidate_catalog": catalog_rows,
        }
        profiles.append(profile)
    return profiles, catalogs


def build_prompt(
    profiles: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> str:
    source_rows = [
        {
            "source_index": index + 1,
            "url": row["url"],
            "title": row["title"],
            "channel": row["channel"],
            "topics": row.get("topics", []),
        }
        for index, row in enumerate(sources)
    ]
    schema = {
        "status": "PASS|HOLD",
        "source_assessments": [{
            "source_index": 1,
            "decision": "USE|REJECT_SOURCE",
            "reason": "concise",
            "methodology_risk": "LOW|MEDIUM|HIGH",
        }],
        "strategy_reviews": [{
            "strategy_id": "exact input strategy_id",
            "verdict": "SELECT_REPLAY|NO_ACTION|NEW_CHILD_REQUIRED",
            "selected_candidate_id": "exact available candidate id or null",
            "causal_reason": "single cause only",
            "internal_evidence_refs": ["hold reason or metric"],
            "video_source_indexes": [1, 2],
            "expected_metric_effect": "specific",
            "falsification_test": "specific",
            "overfit_risk": "LOW|MEDIUM|HIGH",
        }],
        "alpha_fresh_only": {
            "strategy_id": "alpha_combo",
            "authority": "TIME54_TIME60_W1_FRESH_ONLY",
            "hypotheses": [{
                "label": "HYPOTHESIS_EXTERNAL_FRESH_ONLY",
                "single_cause_change": "one distinct cause",
                "bounded_test_space": "explicit bounded values",
                "why_distinct_from_TIME54_TIME60": "...",
                "falsification_test": "...",
            }],
        },
        "selected_replay_order": ["strategy_id:candidate_id"],
    }
    return (
        "You are a skeptical quantitative strategy-research reviewer. Analyze every attached public YouTube video directly and compare it with the supplied anonymized V3 evidence. "
        "Videos are hypothesis sources only. Reject marketing, repainting, omitted fees, hidden samples, discretionary rules, and claims without deterministic definitions. "
        "Review every non-Alpha strategy exactly once. You may select at most one existing candidate ID per strategy and at most "
        f"{int(policy['max_selected_replay'])} replay candidates globally. Never invent a candidate ID or alter its value. "
        "Prioritize genuinely distinct axes not already tested. Include the strong trend_ma_macd survivor in the review, but do not repeat max_chase_dist_atr. "
        "For supertrend_pullback and trend_rider, official-basis economics were rejected; select no existing threshold candidate. Use NEW_CHILD_REQUIRED or NO_ACTION only. "
        "Alpha Combo has exhausted same-data generations. Return at most two fresh-W1-only hypotheses; do not select an archive replay candidate for Alpha. "
        "Favor candidates supported jointly by internal hold reasons/metrics and at least two independent video sources. Do not force a replay when evidence is weak. "
        "All outputs remain research-only and must pass Groq red-team, Workers AI guard, deterministic A/B parity, cost stress, W1/W2/W3 and new sealed. "
        "Return strict JSON only matching OUTPUT_SCHEMA.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"PUBLIC_VIDEO_SOURCES={json.dumps(source_rows, ensure_ascii=False, sort_keys=True)}\n"
        f"STRATEGY_PROFILES={json.dumps(list(profiles), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def validate_response(
    response: Mapping[str, Any],
    profiles: Sequence[Mapping[str, Any]],
    catalogs: Mapping[str, Mapping[str, Mapping[str, Any]]],
    max_selected: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {str(row["strategy_id"]) for row in profiles}
    reviews = [dict(row) for row in response.get("strategy_reviews", []) if isinstance(row, Mapping)]
    seen = [str(row.get("strategy_id") or "") for row in reviews]
    if set(seen) != expected or len(seen) != len(expected):
        raise ValueError(f"STRATEGY_REVIEW_COVERAGE_MISMATCH:{len(seen)}:{len(expected)}")
    selected: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    for row in reviews:
        strategy_id = str(row["strategy_id"])
        verdict = str(row.get("verdict") or "NO_ACTION")
        candidate_id = row.get("selected_candidate_id")
        if strategy_id in REVIEW_ONLY and verdict == "SELECT_REPLAY":
            raise ValueError(f"REVIEW_ONLY_REPLAY_FORBIDDEN:{strategy_id}")
        if verdict == "SELECT_REPLAY":
            if not isinstance(candidate_id, str) or candidate_id not in catalogs.get(strategy_id, {}):
                raise ValueError(f"INVALID_SELECTED_CANDIDATE:{strategy_id}:{candidate_id}")
            selected.append({
                "strategy_id": strategy_id,
                "candidate_id": candidate_id,
                "candidate_spec": dict(catalogs[strategy_id][candidate_id]),
                "causal_reason": row.get("causal_reason"),
                "internal_evidence_refs": row.get("internal_evidence_refs", []),
                "video_source_indexes": row.get("video_source_indexes", []),
                "expected_metric_effect": row.get("expected_metric_effect"),
                "falsification_test": row.get("falsification_test"),
                "overfit_risk": row.get("overfit_risk"),
            })
        elif candidate_id not in (None, "", "NO_ACTION"):
            raise ValueError(f"CANDIDATE_PRESENT_WITHOUT_SELECT:{strategy_id}")
        normalized.append(row)
    if len(selected) > max_selected:
        raise ValueError(f"SELECTED_REPLAY_LIMIT_EXCEEDED:{len(selected)}:{max_selected}")
    if len({row["strategy_id"] for row in selected}) != len(selected):
        raise ValueError("MULTIPLE_CANDIDATES_PER_STRATEGY")
    return normalized, selected


def build_plan(
    selected: Sequence[Mapping[str, Any]],
    profiles: Sequence[Mapping[str, Any]],
    input_sha: str,
) -> dict[str, Any]:
    profile_map = {str(row["strategy_id"]): row for row in profiles}
    rows: list[dict[str, Any]] = []
    for selection in selected:
        strategy_id = str(selection["strategy_id"])
        candidate_id = str(selection["candidate_id"])
        spec = dict(selection["candidate_spec"])
        profile = profile_map[strategy_id]
        rows.append({
            "strategy_id": strategy_id,
            "family": profile.get("family"),
            "lane": profile.get("lane"),
            "incumbent_trade_count": int(profile.get("control", {}).get("trade_count") or 0),
            "candidate_ids": [candidate_id],
            "candidate_specs": {candidate_id: spec},
            "selection_reason": "GEMINI_DIRECT_VIDEO_PLUS_INTERNAL_V3_EVIDENCE",
            "gemini_input_sha256": input_sha,
            "cycle_index": 2,
        })
    return {
        "schema_version": "3.2",
        "version": VERSION,
        "state": "PASS_GEMINI_V3_2_PLAN" if rows else "COMPLETE_NO_GEMINI_REPLAY_AXIS",
        "cycle_index": 2,
        "strategy_count_total": 25,
        "active_strategy_count": len(rows),
        "active_strategy_ids": [row["strategy_id"] for row in rows],
        "candidate_count": len(rows),
        "rows": rows,
        "no_action": [],
        "alpha_special_route": "ALPHA_TIME54_TIME60_W1_FRESH_GEMINI_QUEUE",
        "blind_cartesian_product_used": False,
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--video-registry", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--v3-final", required=True)
    parser.add_argument("--previous-summary")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    registry = read_json(Path(args.registry).resolve())
    ledger = read_json(Path(args.ledger).resolve())
    v3_final = read_json(Path(args.v3_final).resolve())
    video_registry = read_json(Path(args.video_registry).resolve())
    policy = read_json(Path(args.policy).resolve())
    results = find_results(Path(args.results_root).resolve())
    blockers: list[str] = []
    if v3_final.get("state") != "PASS_V3_ORGANIC_AUDIT":
        blockers.append("V3_FINAL_AUTHORITY_INVALID")
    if registry.get("strategy_count") != 25:
        blockers.append("REGISTRY_STRATEGY_COUNT_INVALID")
    if len(results) != 24:
        blockers.append(f"RESULT_COUNT_INVALID:{len(results)}")
    sources = [dict(row) for row in video_registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in sources}
    if len(sources) < int(policy["minimum_public_videos"]):
        blockers.append("PUBLIC_VIDEO_COUNT_LOW")
    if len(channels) < int(policy["minimum_independent_channels"]):
        blockers.append("INDEPENDENT_CHANNEL_COUNT_LOW")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        blockers.append("GEMINI_API_KEY_MISSING")
    if blockers:
        write_json(out / "summary.json", {"state": "HOLD", "blockers": blockers, "GEMINI_USED": False, **SAFETY})
        return 0

    profiles, catalogs = build_profiles(registry, ledger, results, int(policy["max_catalog_per_strategy"]))
    input_payload = {
        "v3_final_sha256": v3_final.get("final_sha256"),
        "registry_sha256": registry.get("registry_sha256"),
        "ledger_sha256": stable_sha(ledger),
        "video_registry_sha256": stable_sha(video_registry),
        "policy_sha256": stable_sha(policy),
        "prompt_version": PROMPT_VERSION,
        "tool_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "profiles": profiles,
    }
    input_sha = stable_sha(input_payload)
    previous = read_json(Path(args.previous_summary).resolve()) if args.previous_summary and Path(args.previous_summary).exists() else {}
    if previous.get("input_sha") == input_sha and previous.get("GEMINI_USED") is True:
        write_json(out / "plan.json", build_plan([], profiles, input_sha))
        write_json(out / "summary.json", {
            "state": "SKIP_UNCHANGED_GEMINI_EVIDENCE",
            "GEMINI_USED": False,
            "previous_gemini_used": True,
            "input_sha": input_sha,
            "selected_replay_count": 0,
            **SAFETY,
        })
        return 0
    prompt = build_prompt(profiles, sources, policy)
    model, response_text = call_direct_video(key, prompt, sources)
    response = json.loads(response_text)
    reviews, selected = validate_response(response, profiles, catalogs, int(policy["max_selected_replay"]))
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    response_sha = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    run_id = os.environ.get("GITHUB_RUN_ID", "LOCAL")
    plan = build_plan(selected, profiles, input_sha)
    artifact = {
        "schema_version": "3.2",
        "version": VERSION,
        "state": "PASS_GEMINI_V3_2_REVIEW",
        "GEMINI_USED": True,
        "free_only": True,
        "direct_video_used": True,
        "actual_model": model,
        "run_id": run_id,
        "input_sha": input_sha,
        "prompt_sha": prompt_sha,
        "response_sha": response_sha,
        "public_urls": [str(row["url"]) for row in sources],
        "independent_channels": sorted(channels),
        "source_count": len(sources),
        "independent_channel_count": len(channels),
        "reviewed_strategy_count": len(reviews),
        "selected_replay_count": len(selected),
        "selected_rows": selected,
        "alpha_fresh_only": response.get("alpha_fresh_only", {}),
        "response": response,
        "v3_final_sha256": v3_final.get("final_sha256"),
        **SAFETY,
    }
    router_input = {
        "strategy_id": "STRATEGY11_MULTI_STRATEGY_GEMINI_V3_2",
        "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
        "changed_axes": [row["candidate_spec"]["axis"] for row in selected],
        "routing_flags": {
            "external_hypothesis": True,
            "multimodal": True,
            "new_multimodal_evidence": True,
            "new_failure_fingerprint": True,
            "borderline_case": False,
            "major_gate_review": False,
        },
        "hypotheses": selected,
        "lineage": {
            "source_sha": v3_final.get("final_sha256"),
            "data_sha": "985c8561016639b7ab4397bd8064cf3a67d8667db3a21797138aa5326291dbbd",
            "window_sha": "STRATEGY11_V3_12_WINDOW_ARCHIVE",
            "candidate_sha": stable_sha(selected),
        },
        **SAFETY,
    }
    write_json(out / "gemini_artifact.json", artifact)
    write_json(out / "plan.json", plan)
    write_json(out / "router_input.json", router_input)
    write_json(out / "summary.json", {
        "state": artifact["state"],
        "GEMINI_USED": True,
        "actual_model": model,
        "reviewed_strategy_count": len(reviews),
        "selected_replay_count": len(selected),
        "selected_strategy_ids": [row["strategy_id"] for row in selected],
        "alpha_fresh_hypothesis_count": len(artifact.get("alpha_fresh_only", {}).get("hypotheses", [])),
        "input_sha": input_sha,
        "prompt_sha": prompt_sha,
        "response_sha": response_sha,
        **SAFETY,
    })
    print(json.dumps({"state": artifact["state"], "reviewed": len(reviews), "selected": len(selected), "model": model}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
