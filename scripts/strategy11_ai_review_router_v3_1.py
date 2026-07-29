#!/usr/bin/env python3
"""Strict fault adapter for the resumable Strategy11 AI router v3.

Verified quota faults remain WAIT_QUOTA. Explicit semantic rejection and valid
advisory HOLD are distinct terminal candidate drops. Malformed output and the
bounded Groq JSON-mode BadRequest fallback are provider retries. Configuration,
authentication and other failures remain blockers. No paid fallback is allowed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scripts import strategy11_ai_review_router_v3 as core

GROQ_JSON_CLIENT = Path("scripts/strategy11_groq_redteam_v1_2.py")
QUOTA_MARKERS = (
    "rate limit", "ratelimit", "rate_limit", "http 429", "http_429",
    "status 429", "daily free allocation", "used up your daily free allocation",
    "quota exceeded", "quota_exceeded", "resource_exhausted", "too many requests",
)
RETRYABLE_OUTPUT_MARKERS = (
    "response_json_recovery_exhausted", "response_json_decode_failed",
    "response_json_shape_mismatch", "badrequesterror",
)


def is_verified_quota_failure(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in QUOTA_MARKERS)


def is_retryable_provider_output(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in RETRYABLE_OUTPUT_MARKERS)


def semantic_blocker(provider: str, review: dict[str, Any]) -> str | None:
    decision = str(review.get("decision") or "HOLD").upper()
    codes = ",".join(map(str, review.get("blocker_codes") or []))
    if decision == "PASS_TO_REPLAY":
        if review.get("single_axis") is not True:
            return f"{provider}:SINGLE_AXIS_FALSE"
        if provider == "workers_ai" and review.get("lineage_complete") is not True:
            return "workers_ai:LINEAGE_INCOMPLETE"
        return None
    if decision == "REJECT":
        return f"{provider}:SEMANTIC_REJECT:{codes}"
    if decision == "HOLD":
        return f"{provider}:ADVISORY_HOLD:{codes}"
    return f"{provider}:INCONCLUSIVE_{decision}:{codes}"


def run_provider(
    provider: str,
    external_payload: dict[str, Any],
    external_path: Path,
    output_dir: Path,
    prior_provider_results: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    artifact_path = output_dir / f"{provider}.json"
    if provider == "groq":
        command = [sys.executable, str(GROQ_JSON_CLIENT.resolve()), "--input", str(external_path), "--output", str(artifact_path)]
    elif provider == "workers_ai":
        envelope = {
            "review_stage": stage,
            "lineage_complete": bool(external_payload.get("lineage")),
            "changed_axes": external_payload.get("changed_axes", []),
            "payload": external_payload,
            "prior_provider_status": {
                name: value.get("status", value.get("artifact", {}).get("status"))
                for name, value in prior_provider_results.items()
            },
            **core.SAFETY,
        }
        workers_input = output_dir / "workers_input.json"
        core.write_json(workers_input, envelope)
        command = [sys.executable, str(core.v1.WORKERS_CLIENT.resolve()), "--input", str(workers_input), "--output", str(artifact_path)]
    else:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{provider}")

    row = core.v1.run_client(command, artifact_path)
    core.v1.validate_provider_safety(provider, row)
    if row.get("returncode") != 0:
        artifact = row.get("artifact") or {}
        blocker = artifact.get("blocker_code") or artifact.get("status") or f"HOLD_{provider.upper()}_FAILED"
        if is_verified_quota_failure(blocker):
            raise ValueError(f"VERIFIED_QUOTA:{str(blocker)[:850]}")
        if is_retryable_provider_output(blocker):
            raise ValueError(f"RETRYABLE_PROVIDER_OUTPUT:{str(blocker)[:850]}")
        raise RuntimeError(f"PROVIDER_BLOCKER:{str(blocker)[:850]}")
    return row


core.run_provider = run_provider
core.semantic_blocker = semantic_blocker

if __name__ == "__main__":
    raise SystemExit(core.main())
