#!/usr/bin/env python3
"""Role-based, fail-closed AI review router for Strategy11 research.

Internal routing and authority fields are never forwarded to external reviewers.
All providers remain advisory-only; deterministic replay/statistics/hard gates
retain sole promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path("backend/research/strategy11_ai_review_router_v1.json")
GROQ_CLIENT = Path("scripts/strategy11_groq_redteam.py")
WORKERS_CLIENT = Path("scripts/strategy11_workers_ai_guard.py")
GITHUB_MODELS_CLIENT = Path("scripts/strategy11_github_models_review.py")

FORBIDDEN_KEY_FRAGMENTS = {
    "api_key", "credential", "exchange_key", "password", "private_key",
    "secret", "token", "wallet", "account_number", "order_id", "position_id",
}

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}

INTERNAL_ONLY_KEYS = {"routing_flags", "stage", *SAFETY.keys()}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_anonymized(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError(f"FORBIDDEN_FIELD:{path}.{raw_key}")
            assert_anonymized(child, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_anonymized(child, f"{path}[{index}]")


def build_external_payload(payload: dict[str, Any], stage: str) -> dict[str, Any]:
    """Create the smallest anonymized evidence envelope sent to AI providers."""
    external = {key: value for key, value in payload.items() if key not in INTERNAL_ONLY_KEYS}
    external["review_stage"] = stage
    external["authority_contract"] = {
        "research_only": True,
        "promotion_authority": False,
        "execution_allowed": False,
    }
    assert_anonymized(external)
    return external


def validate_policy(policy: dict[str, Any]) -> None:
    for key, value in SAFETY.items():
        if policy.get(key) != value:
            raise ValueError(f"POLICY_SAFETY_MISMATCH:{key}")
    if policy.get("final_authority") != "DETERMINISTIC_REPLAY_STATISTICS_HARD_GATES":
        raise ValueError("POLICY_FINAL_AUTHORITY_INVALID")
    providers = policy.get("providers")
    routes = policy.get("stage_routes")
    if not isinstance(providers, dict) or set(providers) != {
        "gemini", "groq", "workers_ai", "github_models"
    }:
        raise ValueError("POLICY_PROVIDER_SET_INVALID")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("POLICY_STAGE_ROUTES_MISSING")


def resolve_directive(provider: str, directive: str, payload: dict[str, Any]) -> tuple[str, bool]:
    flags = payload.get("routing_flags", {})
    if not isinstance(flags, dict):
        raise ValueError("ROUTING_FLAGS_INVALID")
    if directive == "REQUIRED":
        return "RUN", True
    if directive in {"DISABLED", "FORBIDDEN"}:
        return "SKIP", False
    if directive.startswith("DISABLED_UNLESS_NEW_FINGERPRINT_AFTER_RESULT"):
        return ("RUN", True) if flags.get("new_failure_fingerprint") else ("SKIP", False)
    if directive == "CONDITIONAL_NEW_MULTIMODAL_EVIDENCE_ONLY":
        return ("RUN", True) if flags.get("new_multimodal_evidence") else ("SKIP", False)
    if directive == "CONDITIONAL_NEW_FAILURE_FINGERPRINT_ONLY":
        return ("RUN", True) if flags.get("new_failure_fingerprint") else ("SKIP", False)
    if directive == "REQUIRED_WHEN_MULTIMODAL":
        return ("RUN", True) if flags.get("multimodal") else ("SKIP", False)
    if directive == "REQUIRED_FOR_NEW_EXTERNAL_HYPOTHESIS":
        return ("RUN", True) if flags.get("external_hypothesis") else ("SKIP", False)
    if directive == "REQUIRED_FOR_BORDERLINE_CASES":
        return ("RUN", True) if flags.get("borderline_case") else ("SKIP", False)
    if directive == "REQUIRED_FOR_ATTRIBUTION_CONTRADICTIONS":
        return ("RUN", True) if flags.get("attribution_contradiction") else ("SKIP", False)
    if directive == "REQUIRED_FOR_REDUNDANCY_REVIEW":
        return "RUN", True
    if directive == "REQUIRED_FOR_NEW_HYPOTHESES":
        return ("RUN", True) if flags.get("new_external_hypothesis") else ("SKIP", False)
    if directive.startswith("OPTIONAL"):
        enabled = {
            "gemini": flags.get("visual_delta"),
            "groq": flags.get("anomaly_review") or flags.get("new_external_hypothesis")
                    or flags.get("postmortem_review") or flags.get("risk_argument_review"),
            "workers_ai": True,
            "github_models": flags.get("major_gate_review"),
        }.get(provider, False)
        return ("RUN", False) if enabled else ("SKIP", False)
    raise ValueError(f"UNKNOWN_ROUTE_DIRECTIVE:{provider}:{directive}")


def build_plan(policy: dict[str, Any], stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    routes = policy["stage_routes"]
    if stage not in routes:
        raise ValueError(f"UNKNOWN_STAGE:{stage}")
    provider_plan: dict[str, Any] = {}
    for provider in ("gemini", "groq", "workers_ai", "github_models"):
        directive = str(routes[stage].get(provider, "DISABLED"))
        action, required = resolve_directive(provider, directive, payload)
        provider_plan[provider] = {
            "directive": directive,
            "action": action,
            "required": required,
            "role": policy["providers"][provider]["role"],
        }
    return {
        "schema_version": "strategy11.ai_review_plan.v1",
        "stage": stage,
        "provider_plan": provider_plan,
        "final_authority": policy["final_authority"],
        **SAFETY,
    }


def run_client(command: list[str], artifact_path: Path) -> dict[str, Any]:
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    artifact = read_json(artifact_path) if artifact_path.exists() else {}
    return {
        "returncode": process.returncode,
        "stdout_sha": sha256_text(process.stdout),
        "stderr_sha": sha256_text(process.stderr),
        "artifact": artifact,
    }


def validate_provider_safety(provider: str, result: dict[str, Any]) -> None:
    artifact = result.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError(f"{provider.upper()}_ARTIFACT_MISSING")
    for key, value in SAFETY.items():
        if artifact.get(key) != value:
            raise ValueError(f"{provider.upper()}_SAFETY_MISMATCH:{key}")


def verify_gemini_artifact(path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    artifact = read_json(path)
    if artifact.get("GEMINI_USED") is not True:
        raise ValueError("GEMINI_USED_NOT_TRUE")
    urls = artifact.get("public_urls", artifact.get("video_urls", []))
    channels = artifact.get("independent_channels", artifact.get("channel_ids", []))
    limits = policy["providers"]["gemini"]["constraints"]
    if not isinstance(urls, list) or len(set(map(str, urls))) < limits["public_video_min"]:
        raise ValueError("GEMINI_PUBLIC_VIDEO_MIN_FAIL")
    if not isinstance(channels, list) or len(set(map(str, channels))) < limits["independent_channel_min"]:
        raise ValueError("GEMINI_CHANNEL_MIN_FAIL")
    required = {"actual_model", "run_id", "input_sha", "prompt_sha", "response_sha"}
    if not required.issubset(artifact):
        raise ValueError("GEMINI_LINEAGE_MISSING")
    return {
        "status": "PASS_EXISTING_GEMINI_ARTIFACT",
        "actual_model": artifact["actual_model"],
        "run_id": artifact["run_id"],
        "input_sha": artifact["input_sha"],
        "prompt_sha": artifact["prompt_sha"],
        "response_sha": artifact["response_sha"],
        "public_video_count": len(set(map(str, urls))),
        "independent_channel_count": len(set(map(str, channels))),
        **SAFETY,
    }


def execute_plan(
    policy: dict[str, Any], plan: dict[str, Any], payload: dict[str, Any],
    output_dir: Path, gemini_artifact: Path | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    external_payload = build_external_payload(payload, plan["stage"])
    external_path = output_dir / "external_input.json"
    write_json(external_path, external_payload)
    provider_results: dict[str, Any] = {}
    blockers: list[str] = []

    for provider, spec in plan["provider_plan"].items():
        if spec["action"] == "SKIP":
            provider_results[provider] = {"status": "SKIPPED", "required": spec["required"]}
            continue
        try:
            if provider == "gemini":
                if gemini_artifact is None:
                    raise ValueError("HOLD_GEMINI_ARTIFACT_REQUIRED")
                provider_results[provider] = verify_gemini_artifact(gemini_artifact, policy)
                continue

            artifact_path = output_dir / f"{provider}.json"
            if provider == "groq":
                command = [sys.executable, str(GROQ_CLIENT), "--input", str(external_path), "--output", str(artifact_path)]
            elif provider == "workers_ai":
                envelope = {
                    "review_stage": plan["stage"],
                    "lineage_complete": bool(external_payload.get("lineage")),
                    "changed_axes": external_payload.get("changed_axes", []),
                    "payload": external_payload,
                    "prior_provider_status": {
                        name: value.get("status", value.get("artifact", {}).get("status"))
                        for name, value in provider_results.items()
                    },
                    **SAFETY,
                }
                workers_input = output_dir / "workers_input.json"
                write_json(workers_input, envelope)
                command = [sys.executable, str(WORKERS_CLIENT), "--input", str(workers_input), "--output", str(artifact_path)]
            elif provider == "github_models":
                command = [sys.executable, str(GITHUB_MODELS_CLIENT), "--input", str(external_path), "--output", str(artifact_path)]
            else:
                raise ValueError(f"UNKNOWN_PROVIDER:{provider}")

            result = run_client(command, artifact_path)
            validate_provider_safety(provider, result)
            provider_results[provider] = result
            if result["returncode"] != 0:
                raise ValueError(result["artifact"].get("blocker_code", f"HOLD_{provider.upper()}_FAILED"))
        except Exception as exc:
            blocker = str(exc)[:1000]
            provider_results.setdefault(provider, {})["status"] = "HOLD"
            provider_results[provider]["blocker_code"] = blocker
            if spec["required"]:
                blockers.append(f"{provider}:{blocker}")

    return {
        "schema_version": "strategy11.ai_review_execution.v1",
        "status": "HOLD_AI_REVIEW_ROUTER" if blockers else "PASS_AI_REVIEW_ROUTER",
        "stage": plan["stage"],
        "input_sha": sha256_text(canonical_json(payload)),
        "external_input_sha": sha256_text(canonical_json(external_payload)),
        "policy_sha": sha256_text(canonical_json(policy)),
        "plan_sha": sha256_text(canonical_json(plan)),
        "provider_results": provider_results,
        "blocker_codes": blockers,
        "final_decision": "HOLD" if blockers else "ADVISORY_COMPLETE_AWAIT_DETERMINISTIC_GATES",
        "final_authority": policy["final_authority"],
        **SAFETY,
    }


def default_payload(stage: str) -> dict[str, Any]:
    return {
        "strategy_id": "fixture_strategy",
        "stage": stage,
        "changed_axes": ["TREND_REGIME_GATE"],
        "routing_flags": {
            "external_hypothesis": stage == "PRE_W1_INTERNAL_REPLAY",
            "multimodal": False,
            "new_multimodal_evidence": False,
            "new_failure_fingerprint": False,
            "borderline_case": stage == "GLOBAL_CLASSIFICATION",
            "major_gate_review": stage.endswith("GATE"),
        },
        "hypothesis": {
            "axis": "TREND_REGIME_GATE",
            "generation": 1,
            "description": "Single-axis eligibility hypothesis for isolated replay.",
        },
        "control": {"trades": 24, "net_pct": 1.2, "pf": 1.18, "dd_pct": 2.4},
        "candidate": {"trades": 22, "net_pct": 1.4, "pf": 1.22, "dd_pct": 2.3},
        "retention": 0.9167,
        "lineage": {
            "source_sha": "fixture-source-sha",
            "data_sha": "fixture-data-sha",
            "window_sha": "fixture-window-sha",
            "candidate_sha": "fixture-candidate-sha",
        },
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("plan", "execute"), default="plan")
    parser.add_argument("--gemini-artifact", type=Path)
    args = parser.parse_args()
    try:
        policy = read_json(args.policy)
        validate_policy(policy)
        payload = read_json(args.input) if args.input else default_payload(args.stage)
        assert_anonymized(payload)
        plan = build_plan(policy, args.stage, payload)
        if args.mode == "plan":
            result = {
                "status": "PASS_AI_REVIEW_ROUTER_PLAN",
                "policy_sha": sha256_text(canonical_json(policy)),
                "input_sha": sha256_text(canonical_json(payload)),
                "plan": plan,
                **SAFETY,
            }
        else:
            with tempfile.TemporaryDirectory(prefix="strategy11-ai-router-"):
                result = execute_plan(
                    policy=policy,
                    plan=plan,
                    payload=payload,
                    output_dir=args.output.parent / "providers",
                    gemini_artifact=args.gemini_artifact,
                )
        write_json(args.output, result)
        print(f"{result['status']} stage={args.stage} output={args.output}")
        return 0 if result["status"].startswith("PASS_") else 1
    except Exception as exc:
        result = {"status": "HOLD_AI_REVIEW_ROUTER", "blocker_codes": [str(exc)[:1000]], **SAFETY}
        write_json(args.output, result)
        print(f"HOLD_AI_REVIEW_ROUTER blocker={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
