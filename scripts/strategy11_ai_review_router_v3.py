#!/usr/bin/env python3
"""Quota-aware resumable Strategy11 pre-replay AI decision gate.

Valid provider reviews are reused only when the outer router result is bound to
exactly the same external input, policy and route plan. Groq is evaluated first.
A semantic Groq rejection terminates review safely without consuming Workers AI.
Workers AI is required only for a Groq PASS_TO_REPLAY candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from scripts import strategy11_ai_review_router as v1

PRE_REPLAY_STAGES = {"PRE_W1_INTERNAL_REPLAY", "PRE_REPLAY_EXTERNAL_HYPOTHESIS"}
SAFETY = dict(v1.SAFETY)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def provider_review(row: dict[str, Any], provider: str) -> dict[str, Any]:
    artifact = row.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError(f"{provider.upper()}_ARTIFACT_MISSING")
    review = artifact.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"{provider.upper()}_REVIEW_MISSING")
    return review


def valid_provider_row(row: Any, provider: str) -> dict[str, Any] | None:
    if not isinstance(row, dict) or row.get("returncode") != 0:
        return None
    try:
        v1.validate_provider_safety(provider, row)
        provider_review(row, provider)
    except Exception:
        return None
    return row


def iter_prior_results(roots: Iterable[Path], file_name: str) -> Iterable[dict[str, Any]]:
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob(file_name)):
            try:
                yield read_json(path)
            except Exception:
                continue


def matching_prior_results(
    roots: Iterable[Path],
    file_name: str,
    external_input_sha: str,
    policy_sha: str,
    plan_sha: str,
) -> list[dict[str, Any]]:
    rows = []
    for result in iter_prior_results(roots, file_name):
        if result.get("external_input_sha") != external_input_sha:
            continue
        if result.get("policy_sha") != policy_sha:
            continue
        if result.get("plan_sha") != plan_sha:
            continue
        rows.append(result)
    return rows


def cached_provider(prior: list[dict[str, Any]], provider: str) -> dict[str, Any] | None:
    for result in reversed(prior):
        row = (result.get("provider_results") or {}).get(provider)
        valid = valid_provider_row(row, provider)
        if valid is not None:
            reused = dict(valid)
            reused["reused"] = True
            reused["reused_from_run_id"] = (valid.get("artifact") or {}).get("run_id")
            reused["reused_from_run_attempt"] = (valid.get("artifact") or {}).get("run_attempt")
            return reused
    return None


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
        command = [sys.executable, str(v1.GROQ_CLIENT.resolve()), "--input", str(external_path), "--output", str(artifact_path)]
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
            **SAFETY,
        }
        workers_input = output_dir / "workers_input.json"
        write_json(workers_input, envelope)
        command = [sys.executable, str(v1.WORKERS_CLIENT.resolve()), "--input", str(workers_input), "--output", str(artifact_path)]
    else:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{provider}")
    row = v1.run_client(command, artifact_path)
    v1.validate_provider_safety(provider, row)
    return row


def semantic_blocker(provider: str, review: dict[str, Any]) -> str | None:
    decision = review.get("decision")
    if decision == "PASS_TO_REPLAY":
        if review.get("single_axis") is not True:
            return f"{provider}:SINGLE_AXIS_FALSE"
        if provider == "workers_ai" and review.get("lineage_complete") is not True:
            return "workers_ai:LINEAGE_INCOMPLETE"
        return None
    codes = ",".join(map(str, review.get("blocker_codes") or []))
    return f"{provider}:DECISION_{decision}:{codes}"


def build_result(
    *,
    payload: dict[str, Any],
    policy: dict[str, Any],
    plan: dict[str, Any],
    external_payload: dict[str, Any],
    provider_results: dict[str, Any],
    blockers: list[str],
    wait_codes: list[str],
    new_provider_calls: int,
) -> dict[str, Any]:
    if wait_codes:
        status = "WAIT_AI_QUOTA_REVIEW"
        final_decision = "WAIT_QUOTA"
    elif blockers:
        status = "HOLD_AI_REVIEW_DECISION_GATE"
        final_decision = "HOLD"
    else:
        status = "PASS_AI_REVIEW_DECISION_GATE"
        final_decision = "ADVISORY_COMPLETE_AWAIT_DETERMINISTIC_GATES"
    return {
        "schema_version": "strategy11.ai_review_decision_gate.v3",
        "status": status,
        "stage": plan["stage"],
        "input_sha": v1.sha256_text(v1.canonical_json(payload)),
        "external_input_sha": v1.sha256_text(v1.canonical_json(external_payload)),
        "policy_sha": v1.sha256_text(v1.canonical_json(policy)),
        "plan_sha": v1.sha256_text(v1.canonical_json(plan)),
        "provider_results": provider_results,
        "blocker_codes": sorted(set(map(str, blockers))),
        "wait_codes": sorted(set(map(str, wait_codes))),
        "new_provider_calls": new_provider_calls,
        "final_decision": final_decision,
        "final_authority": policy["final_authority"],
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=v1.DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, action="append", default=[])
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()

    try:
        policy = read_json(args.policy)
        v1.validate_policy(policy)
        payload = read_json(args.input)
        v1.assert_anonymized(payload)
        plan = v1.build_plan(policy, args.stage, payload)
        if args.stage not in PRE_REPLAY_STAGES:
            raise ValueError("V3_PRE_REPLAY_ONLY")

        output_dir = args.output.parent / f"{args.output.stem}-providers"
        output_dir.mkdir(parents=True, exist_ok=True)
        external_payload = v1.build_external_payload(payload, args.stage)
        external_path = output_dir / "external_input.json"
        write_json(external_path, external_payload)
        external_sha = v1.sha256_text(v1.canonical_json(external_payload))
        policy_sha = v1.sha256_text(v1.canonical_json(policy))
        plan_sha = v1.sha256_text(v1.canonical_json(plan))
        prior = matching_prior_results(args.prior_root, args.output.name, external_sha, policy_sha, plan_sha)

        provider_results: dict[str, Any] = {
            "gemini": {"status": "SKIPPED", "required": False},
            "github_models": {"status": "SKIPPED", "required": False},
        }
        blockers: list[str] = []
        wait_codes: list[str] = []
        new_calls = 0

        groq = cached_provider(prior, "groq")
        if groq is None and not args.cache_only:
            try:
                groq = run_provider("groq", external_payload, external_path, output_dir, provider_results, args.stage)
                new_calls += 1
            except Exception as exc:
                wait_codes.append(f"groq:{str(exc)[:700]}")
        if groq is None:
            provider_results["groq"] = {"status": "WAIT_QUOTA", "required": True}
            if not wait_codes:
                wait_codes.append("groq:WAIT_NEXT_QUOTA_BATCH")
        else:
            provider_results["groq"] = groq
            groq_review = provider_review(groq, "groq")
            groq_blocker = semantic_blocker("groq", groq_review)
            if groq_blocker:
                blockers.append(groq_blocker)
                provider_results["workers_ai"] = {
                    "status": "SKIPPED_UPSTREAM_GROQ_REJECT",
                    "required": False,
                    "quota_preserved": True,
                }
            else:
                workers = cached_provider(prior, "workers_ai")
                if workers is None and not args.cache_only:
                    try:
                        workers = run_provider("workers_ai", external_payload, external_path, output_dir, provider_results, args.stage)
                        new_calls += 1
                    except Exception as exc:
                        wait_codes.append(f"workers_ai:{str(exc)[:700]}")
                if workers is None:
                    provider_results["workers_ai"] = {"status": "WAIT_QUOTA", "required": True}
                    if not wait_codes:
                        wait_codes.append("workers_ai:WAIT_NEXT_QUOTA_BATCH")
                else:
                    provider_results["workers_ai"] = workers
                    workers_blocker = semantic_blocker("workers_ai", provider_review(workers, "workers_ai"))
                    if workers_blocker:
                        blockers.append(workers_blocker)

        result = build_result(
            payload=payload,
            policy=policy,
            plan=plan,
            external_payload=external_payload,
            provider_results=provider_results,
            blockers=blockers,
            wait_codes=wait_codes,
            new_provider_calls=new_calls,
        )
        write_json(args.output, result)
        print(f"{result['status']} stage={args.stage} new_calls={new_calls} output={args.output}")
        return 0
    except Exception as exc:
        result = {
            "schema_version": "strategy11.ai_review_decision_gate.v3",
            "status": "HOLD_AI_REVIEW_DECISION_GATE",
            "blocker_codes": [str(exc)[:1000]],
            "wait_codes": [],
            "new_provider_calls": 0,
            "final_decision": "HOLD",
            **SAFETY,
        }
        write_json(args.output, result)
        print(f"HOLD_AI_REVIEW_DECISION_GATE blocker={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
