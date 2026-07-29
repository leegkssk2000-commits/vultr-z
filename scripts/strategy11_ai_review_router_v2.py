#!/usr/bin/env python3
"""Fail-closed decision gate over Strategy11 AI review router v1.

V1 owns provider routing and lineage. V2 additionally enforces that required
pre-replay semantic reviewers explicitly return PASS_TO_REPLAY for a single
causal axis with complete lineage. Major-gate model opinions remain advisory;
deterministic replay/statistics/hard gates retain promotion authority.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

V1 = Path(__file__).resolve().with_name("strategy11_ai_review_router.py")
ROUTER_ROOT = V1.parent.parent
PRE_REPLAY_STAGES = {"PRE_W1_INTERNAL_REPLAY", "PRE_REPLAY_EXTERNAL_HYPOTHESIS"}
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def provider_review(result: dict[str, Any], provider: str) -> dict[str, Any]:
    row = result.get("provider_results", {}).get(provider)
    if not isinstance(row, dict):
        raise ValueError(f"{provider.upper()}_RESULT_MISSING")
    artifact = row.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError(f"{provider.upper()}_ARTIFACT_MISSING")
    review = artifact.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"{provider.upper()}_REVIEW_MISSING")
    return review


def enforce_pre_replay(result: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for provider in ("groq", "workers_ai"):
        try:
            review = provider_review(result, provider)
            decision = review.get("decision")
            if decision != "PASS_TO_REPLAY":
                codes = review.get("blocker_codes") or []
                blockers.append(f"{provider}:DECISION_{decision}:{','.join(map(str, codes))}")
            if review.get("single_axis") is not True:
                blockers.append(f"{provider}:SINGLE_AXIS_FALSE")
            if provider == "workers_ai" and review.get("lineage_complete") is not True:
                blockers.append("workers_ai:LINEAGE_INCOMPLETE")
        except Exception as exc:
            blockers.append(f"{provider}:{str(exc)[:500]}")
    return blockers


def run_v1(args: argparse.Namespace, raw_output: Path) -> int:
    command = [
        sys.executable, str(V1),
        "--stage", args.stage,
        "--mode", args.mode,
        "--policy", str(args.policy.resolve()),
        "--output", str(raw_output.resolve()),
    ]
    if args.input:
        command.extend(["--input", str(args.input.resolve())])
    if args.gemini_artifact:
        command.extend(["--gemini-artifact", str(args.gemini_artifact.resolve())])
    process = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        cwd=ROUTER_ROOT,
    )
    return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--policy", type=Path, default=Path("backend/research/strategy11_ai_review_router_v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("plan", "execute"), default="plan")
    parser.add_argument("--gemini-artifact", type=Path)
    parser.add_argument("--router-result", type=Path, help="Validate an existing v1 result without external calls")
    args = parser.parse_args()

    try:
        if args.router_result:
            result = read_json(args.router_result)
            v1_returncode = 0 if result.get("status", "").startswith("PASS_") else 1
        else:
            with tempfile.TemporaryDirectory(prefix="strategy11-ai-router-v2-") as tmp:
                raw_output = Path(tmp) / "router_v1.json"
                v1_returncode = run_v1(args, raw_output)
                result = read_json(raw_output)

        blockers = list(result.get("blocker_codes") or [])
        if v1_returncode != 0 or not str(result.get("status", "")).startswith("PASS_"):
            blockers.append("ROUTER_V1_NOT_PASS")

        if args.mode == "execute" and args.stage in PRE_REPLAY_STAGES and not blockers:
            blockers.extend(enforce_pre_replay(result))

        gated = {
            **result,
            "schema_version": "strategy11.ai_review_decision_gate.v2",
            "upstream_status": result.get("status"),
            "status": "HOLD_AI_REVIEW_DECISION_GATE" if blockers else "PASS_AI_REVIEW_DECISION_GATE",
            "blocker_codes": sorted(set(map(str, blockers))),
            "final_decision": "HOLD" if blockers else result.get("final_decision", "ADVISORY_COMPLETE_AWAIT_DETERMINISTIC_GATES"),
            **SAFETY,
        }
        write_json(args.output, gated)
        print(f"{gated['status']} stage={args.stage} output={args.output}")
        return 1 if blockers else 0
    except Exception as exc:
        gated = {
            "schema_version": "strategy11.ai_review_decision_gate.v2",
            "status": "HOLD_AI_REVIEW_DECISION_GATE",
            "blocker_codes": [str(exc)[:1000]],
            "final_decision": "HOLD",
            **SAFETY,
        }
        write_json(args.output, gated)
        print(f"HOLD_AI_REVIEW_DECISION_GATE blocker={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
