#!/usr/bin/env python3
"""Direct Gemini multimodal evidence gate for session-event research.

The tool may produce one pre-replay hypothesis only. It cannot promote a
strategy, mutate runtime state or inspect sealed holdouts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

PREFERRED_MODELS = (
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
    "models/gemini-2.5-flash",
)
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def extract_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("GEMINI_JSON_OBJECT_NOT_FOUND")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("GEMINI_JSON_NOT_OBJECT")
    return value


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


def call_gemini(key: str, models: list[str], parts: list[dict[str, Any]], max_tokens: int = 12000) -> tuple[str, str]:
    body = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "temperature": 0.0,
        },
    }).encode("utf-8")
    errors: list[str] = []
    for model in models:
        try:
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = json.load(response)
            texts = [
                part["text"]
                for candidate in payload.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", [])
                if isinstance(part.get("text"), str)
            ]
            text = "\n".join(texts).strip()
            if not text:
                raise RuntimeError("EMPTY_GEMINI_RESPONSE")
            return model, text
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            errors.append(f"{model}:HTTP_{exc.code}:{detail}")
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def validate_sources(registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    papers = [dict(row) for row in registry.get("primary_sources", []) if isinstance(row, dict)]
    videos = [dict(row) for row in registry.get("video_sources", []) if isinstance(row, dict)]
    channels = {str(row.get("channel", "")).strip() for row in videos if str(row.get("channel", "")).strip()}
    urls = {str(row.get("url", "")).strip() for row in videos if str(row.get("url", "")).strip()}
    if len(videos) < int(registry.get("required_video_count", 4)):
        raise ValueError("VIDEO_SOURCE_COUNT_LT_REQUIRED")
    if len(channels) < int(registry.get("required_independent_channel_count", 4)):
        raise ValueError("VIDEO_CHANNEL_DIVERSITY_LT_REQUIRED")
    if len(papers) < 3:
        raise ValueError("PRIMARY_SOURCE_COUNT_LT_3")
    return papers, videos, channels, urls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = args.output_dir / "gemini_artifact.json"
    router_input_path = args.output_dir / "router_input.json"

    try:
        plan = read_object(args.plan)
        registry = read_object(args.registry)
        if plan.get("state") != "PASS_SESSION_EVENT_CONTINUATION_PLAN_SEALED_RESEARCH_ONLY":
            raise ValueError("SESSION_EVENT_PLAN_NOT_SEALED")
        if registry.get("state") != "PASS_EXTERNAL_EVIDENCE_REGISTRY_SEALED_RESEARCH_ONLY":
            raise ValueError("EXTERNAL_EVIDENCE_REGISTRY_NOT_SEALED")
        papers, videos, channels, urls = validate_sources(registry)
        allowed_axes = {str(value) for value in registry.get("allowed_axes", [])}
        plan_axes = {str(row.get("axis")) for row in plan.get("pre_registered_axes", []) if isinstance(row, dict)}
        if not allowed_axes or allowed_axes != plan_axes:
            raise ValueError("EVIDENCE_PLAN_AXIS_MISMATCH")

        key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_V3_2_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("HOLD_GEMINI_API_KEY_MISSING")
        models = list_models(key)
        if not models:
            raise RuntimeError("HOLD_NO_GEMINI_GENERATE_CONTENT_MODEL")

        source_digest = {
            "papers": [{
                "evidence_id": row["evidence_id"],
                "title": row["title"],
                "claim": row["claim"],
                "limitations": row["limitations"],
                "applicable_axes": row["applicable_axes"],
            } for row in papers],
            "videos": [{
                "evidence_id": row["evidence_id"],
                "channel": row["channel"],
                "title": row["title"],
                "claim_to_test": row["claim_to_test"],
                "limitations": row["limitations"],
            } for row in videos],
        }
        schema = {
            "status": "PASS|HOLD",
            "source_assessments": [{
                "evidence_id": "EXACT_ID",
                "decision": "USE|REJECT_SOURCE",
                "reason": "string",
                "reproducibility_risk": "LOW|MEDIUM|HIGH"
            }],
            "ranked_hypotheses": [{
                "axis": "EXACT_ALLOWED_AXIS",
                "supporting_evidence_ids": ["EXACT_ID"],
                "contradicting_evidence_ids": ["EXACT_ID"],
                "mechanism": "string",
                "closed_bar_definition": "string",
                "entry_time_observable": True,
                "expected_metric_movement": "string",
                "falsification_control": "EXACT_CONTROL_FROM_PLAN",
                "data_requirement": "string",
                "priority": 1
            }]
        }
        prompt = (
            "You are a skeptical quantitative crypto researcher. Directly inspect all four attached public videos and compare them with the supplied academic-source summaries. "
            "Popularity, claimed win rate and visual chart examples are not evidence. Do not invent indicators, thresholds, sessions, axes or data. "
            "Return at most two hypotheses and only from the exact pre-registered axes. Each hypothesis must be one causal axis, closed-bar observable, compatible with next-15m-open execution, and falsifiable by one exact existing control. "
            "Use contradictory sources actively. Reject generic indicator stacking, hidden multi-axis changes, holdout tuning and discretionary rules. "
            "No source or AI output can promote a strategy; deterministic W1/W2/W3 and cost/stress replay remain final authority. Return strict JSON only.\n"
            f"SEALED_PLAN={canonical(plan)}\n"
            f"SOURCE_DIGEST={canonical(source_digest)}\n"
            f"OUTPUT_SCHEMA={canonical(schema)}"
        )
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend({"file_data": {"file_uri": row["url"]}} for row in videos[:4])
        model, response_text = call_gemini(key, models, parts)
        proposal = extract_object(response_text)

        valid: list[dict[str, Any]] = []
        controls = {str(value) for value in plan.get("controls", [])}
        evidence_ids = {str(row["evidence_id"]) for row in papers + videos}
        for raw in proposal.get("ranked_hypotheses", []):
            if not isinstance(raw, dict):
                continue
            axis = str(raw.get("axis", ""))
            if axis not in allowed_axes or raw.get("entry_time_observable") is not True:
                continue
            if str(raw.get("falsification_control", "")) not in controls:
                continue
            support = [str(value) for value in raw.get("supporting_evidence_ids", []) if str(value) in evidence_ids]
            if len(set(support)) < 2:
                continue
            row = dict(raw)
            row["supporting_evidence_ids"] = sorted(set(support))
            valid.append(row)
        valid = sorted(valid, key=lambda row: int(row.get("priority", 999)))[:2]
        if not valid:
            raise RuntimeError("HOLD_GEMINI_NO_SUPPORTED_SINGLE_AXIS_HYPOTHESIS")

        red_schema = {
            "status": "PASS|HOLD",
            "approved_axis": "ONE_EXACT_AXIS_OR_EMPTY",
            "reason": "string",
            "blocker_codes": ["string"]
        }
        red_prompt = (
            "Independently red-team the proposed hypotheses. Approve exactly one axis only when it is single-axis, entry-time observable, supported by at least two independent evidence IDs, contradicted evidence is acknowledged, and the existing control can falsify it. "
            "Reject popularity, strategy marketing, parameter fishing, hidden trade deletion and data unavailable at signal time. Return strict JSON only.\n"
            f"PROPOSALS={canonical(valid)}\n"
            f"SOURCE_DIGEST={canonical(source_digest)}\n"
            f"OUTPUT_SCHEMA={canonical(red_schema)}"
        )
        red_model, red_text = call_gemini(key, models, [{"text": red_prompt}], max_tokens=5000)
        red = extract_object(red_text)
        approved_axis = str(red.get("approved_axis", ""))
        selected = next((row for row in valid if row["axis"] == approved_axis), None)
        if red.get("status") != "PASS" or selected is None:
            raise RuntimeError("HOLD_GEMINI_RED_TEAM_NO_APPROVED_AXIS")

        input_sha = sha_text(canonical({"plan": plan, "registry": registry}))
        prompt_sha = sha_text(prompt)
        response_sha = sha_text(response_text)
        run_id = os.environ.get("GITHUB_RUN_ID", "local")
        artifact = {
            "schema_version": "zel.session_event.gemini_research_gate.v1",
            "status": "PASS_GEMINI_SESSION_EVENT_HYPOTHESIS",
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "provider": "gemini",
            "role": "MULTIMODAL_HYPOTHESIS_GENERATOR",
            "required": True,
            "used": True,
            "GEMINI_USED": True,
            "actual_model": model,
            "red_team_model": red_model,
            "run_id": run_id,
            "input_sha": input_sha,
            "prompt_sha": prompt_sha,
            "response_sha": response_sha,
            "red_prompt_sha": sha_text(red_prompt),
            "red_response_sha": sha_text(red_text),
            "decision": "PASS_TO_ROUTER",
            "blocker_codes": [],
            "public_urls": sorted(urls),
            "independent_channels": sorted(channels),
            "selected_hypothesis": selected,
            "proposal_sha": sha_text(canonical(proposal)),
            "red_team_sha": sha_text(canonical(red)),
            "plan_sha": sha_file(args.plan),
            "registry_sha": sha_file(args.registry),
            "sealed_holdout_visible_to_ai": False,
            "private_runtime_data_sent": False,
            **SAFETY,
        }
        router_input = {
            "strategy_id": "session_event_continuation_v1",
            "changed_axes": [selected["axis"]],
            "routing_flags": {
                "external_hypothesis": True,
                "multimodal": True,
                "new_multimodal_evidence": True,
                "new_failure_fingerprint": True,
                "major_gate_review": False
            },
            "hypothesis": {
                "axis": selected["axis"],
                "generation": 1,
                "description": selected["mechanism"],
                "closed_bar_definition": selected["closed_bar_definition"],
                "expected_metric_movement": selected["expected_metric_movement"],
                "falsification_control": selected["falsification_control"],
                "supporting_evidence_ids": selected["supporting_evidence_ids"]
            },
            "control": {"state": "PRE_REPLAY_FROZEN_PLAN", "plan_sha": sha_file(args.plan)},
            "candidate": {"state": "PRE_REPLAY_UNMEASURED", "axis": selected["axis"]},
            "retention": 1.0,
            "lineage": {
                "source_sha": sha_file(args.plan),
                "data_sha": "SEALED_CORPUS_BOUND_AT_REPLAY",
                "window_sha": "W1_SELECTION_W2_W3_FROZEN_CONTRACT",
                "candidate_sha": sha_text(canonical(selected)),
                "registry_sha": sha_file(args.registry),
                "gemini_input_sha": input_sha,
                "gemini_response_sha": response_sha
            },
            "evidence": source_digest,
            "execution_authority": "NONE",
            "runtime_bound": False,
            **SAFETY,
        }
        write_object(args.output_dir / "proposal.json", proposal)
        write_object(args.output_dir / "gemini_red_team.json", red)
        write_object(artifact_path, artifact)
        write_object(router_input_path, router_input)
        print(f"PASS_GEMINI_SESSION_EVENT_HYPOTHESIS axis={selected['axis']} model={model}")
        return 0
    except Exception as exc:
        hold = {
            "schema_version": "zel.session_event.gemini_research_gate.v1",
            "status": "HOLD_GEMINI_SESSION_EVENT_GATE",
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "provider": "gemini",
            "role": "MULTIMODAL_HYPOTHESIS_GENERATOR",
            "required": True,
            "used": False,
            "GEMINI_USED": False,
            "actual_model": None,
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "input_sha": None,
            "prompt_sha": None,
            "response_sha": None,
            "decision": "HOLD",
            "blocker_codes": [str(exc)[:1200]],
            **SAFETY,
        }
        write_object(artifact_path, hold)
        print(str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
