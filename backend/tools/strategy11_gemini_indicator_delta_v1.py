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
)


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def extract_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, Mapping):
            return dict(value)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    value = json.loads(text[start:index + 1])
                    if isinstance(value, Mapping):
                        return dict(value)
                    break
        start = text.find("{", start + 1)
    raise ValueError("GEMINI_JSON_OBJECT_NOT_FOUND")


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


def call_gemini(key: str, models: list[str], parts: list[dict[str, Any]], *, max_tokens: int = 16384) -> tuple[str, str]:
    body = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "temperature": 0.0,
            "thinkingConfig": {"thinkingLevel": "low"},
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
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}:HTTP_{exc.code}:{detail[:800]}")
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def wait_result(state: str, blocker: str, coverage: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "version": "STRATEGY11_GEMINI_INDICATOR_DELTA_V1",
        "state": state,
        "blockers": [blocker],
        "coverage_policy_sha256": stable_sha(coverage),
        "video_registry_sha256": stable_sha(registry),
        "GEMINI_USED": False,
        "free_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        "next": "WAIT_NEXT_FREE_GEMINI_EPOCH",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    coverage_path = Path(args.coverage)
    registry_path = Path(args.registry)
    coverage = strict_json(coverage_path)
    registry = strict_json(registry_path)
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in sources}
    if len(sources) < 4 or len(channels) < 4:
        raise RuntimeError("INDICATOR_VIDEO_DIVERSITY_LT_4")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    out = Path(args.out)
    if not key:
        atomic_json(out / "plan.json", wait_result("WAIT_GEMINI_SECRET", "GEMINI_API_KEY_MISSING", coverage, registry))
        return 0
    try:
        models = list_models(key)
        if not models:
            atomic_json(out / "plan.json", wait_result("WAIT_GEMINI_MODEL", "NO_FREE_FLASH_MODEL", coverage, registry))
            return 0
        queue = coverage["variant_queue"]
        allowed_ids = {str(row["candidate_id"]) for row in queue}
        source_audit = [
            {"source_index": index + 1, "url": row["url"], "title": row["title"], "channel": row["channel"], "topics": row.get("topics", []), "source_risk": row.get("source_risk")}
            for index, row in enumerate(sources)
        ]
        schema = {
            "status": "PASS|HOLD",
            "source_assessments": [{"source_index": 1, "decision": "USE|REJECT_SOURCE", "reason": "...", "overfit_or_marketing_risk": "LOW|MEDIUM|HIGH"}],
            "ranked_hypotheses": [{
                "candidate_id": "EXACT_ID_FROM_QUEUE",
                "compatible_families": ["trend_following"],
                "supporting_source_indexes": [1, 2],
                "contradicting_source_indexes": [],
                "single_axis_reason": "...",
                "expected_failure_fingerprint": "...",
                "falsification_test": "...",
                "priority": 1,
            }],
        }
        prompt = (
            "You are a skeptical quantitative indicator research planner. Directly inspect all four attached public videos. "
            "The candidate IDs and components are a bounded catalog; do not invent IDs, thresholds, indicators, or multi-axis changes. "
            "Rank at most six genuinely distinct hypotheses for family-compatible isolated replay. A popular golden cross is not evidence. "
            "Reject marketing, low samples, omitted costs, data snooping, market-transfer assumptions, and claims without deterministic rules. "
            "EMA alignment already existed internally, but exact EMA20/50, 50/100, 50/200 and 100/200 crossover-event timing was not exhaustively replayed. "
            "Every selected item remains hypothesis-only and must pass Groq/Workers review, NO_CHANGE parity, immutable F1/F2/F3 or W1, stress, retention and Pareto gates. Return strict JSON only.\n"
            f"COVERAGE_QUEUE={json.dumps(queue, ensure_ascii=False, sort_keys=True)}\n"
            f"PUBLIC_SOURCES={json.dumps(source_audit, ensure_ascii=False, sort_keys=True)}\n"
            f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
        )
        parts = [{"text": prompt}]
        parts.extend({"file_data": {"file_uri": row["url"]}} for row in sources[:4])
        model, text = call_gemini(key, models, parts)
        proposal = extract_object(text)
        proposed = []
        for row in proposal.get("ranked_hypotheses", []):
            if not isinstance(row, Mapping):
                continue
            candidate_id = str(row.get("candidate_id") or "")
            if candidate_id not in allowed_ids:
                continue
            proposed.append(dict(row))
        proposed = proposed[:6]
        red_schema = {
            "status": "PASS|HOLD",
            "approved_candidate_ids": ["EXACT_ID"],
            "rejected": [{"candidate_id": "EXACT_ID", "reason": "duplicate|unsupported|multi_axis|overfit|market_transfer"}],
        }
        red_prompt = (
            "Independently red-team the indicator hypotheses. Approve only catalog IDs with at least two independent supporting sources, a single semantic axis, "
            "family compatibility and a falsifiable deterministic replay. Reject parameter fishing and source popularity. Return strict JSON only.\n"
            f"PROPOSAL={json.dumps(proposed, ensure_ascii=False, sort_keys=True)}\n"
            f"SOURCE_AUDIT={json.dumps(source_audit, ensure_ascii=False, sort_keys=True)}\n"
            f"OUTPUT_SCHEMA={json.dumps(red_schema, ensure_ascii=False, sort_keys=True)}"
        )
        red_model, red_text = call_gemini(key, models, [{"text": red_prompt}], max_tokens=8192)
        red = extract_object(red_text)
        approved_ids = []
        for value in red.get("approved_candidate_ids", []):
            candidate_id = str(value)
            if candidate_id in allowed_ids and candidate_id not in approved_ids:
                approved_ids.append(candidate_id)
        approved_ids = approved_ids[:6]
        lookup = {str(row["candidate_id"]): row for row in queue}
        final_rows = [
            {"candidate_id": candidate_id, "catalog": lookup[candidate_id], "proposal": next((row for row in proposed if str(row.get("candidate_id")) == candidate_id), {})}
            for candidate_id in approved_ids
        ]
        result = {
            "schema_version": "1.0",
            "version": "STRATEGY11_GEMINI_INDICATOR_DELTA_V1",
            "state": "PASS_GEMINI_INDICATOR_DELTA_PLAN" if final_rows else "HOLD_NO_SUPPORTED_INDICATOR_DELTA",
            "blockers": [] if final_rows else ["NO_CROSS_SOURCE_SUPPORTED_CANDIDATE"],
            "coverage_policy_sha256": hashlib.sha256(coverage_path.read_bytes()).hexdigest(),
            "video_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "GEMINI_USED": True,
            "free_only": True,
            "direct_video_used": True,
            "public_urls": [row["url"] for row in sources[:4]],
            "independent_channel_count": len(channels),
            "actual_model": model,
            "red_team_model": red_model,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "red_prompt_sha256": hashlib.sha256(red_prompt.encode()).hexdigest(),
            "red_response_sha256": hashlib.sha256(red_text.encode()).hexdigest(),
            "approved_candidate_count": len(final_rows),
            "rows": final_rows,
            "private_code_sent": False,
            "secret_sent": False,
            "account_order_runtime_data_sent": False,
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
            "next": "GROQ_WORKERS_REVIEW_THEN_ISOLATED_REPLAY" if final_rows else "WAIT_NEW_EVIDENCE",
        }
        atomic_json(out / "proposal.json", proposal)
        atomic_json(out / "red_team.json", red)
        atomic_json(out / "plan.json", result)
        return 0
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        if re.search(r"HTTP_429|RESOURCE_EXHAUSTED|quota", text, re.I):
            result = wait_result("WAIT_GEMINI_QUOTA", "FREE_GEMINI_QUOTA_EXHAUSTED", coverage, registry)
            result["provider_error_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            atomic_json(out / "plan.json", result)
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
