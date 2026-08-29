#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_paid_ai_target_gate_v1 as paid_gate
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as factory
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.architecture_factory import a1_terminal_repair_swarm_v5 as v5
from backend.research.architecture_factory import gemini_provider_v1 as gemini
from backend.research.architecture_factory import openai_generator_hardened_v1 as hardened

ROOT = Path(__file__).resolve().parents[3]
V6_CACHE = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v6_latest.json"
SELF = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v6.py"
HARDENED = ROOT / "backend/research/architecture_factory/openai_generator_hardened_v1.py"
TARGET_GATE = ROOT / "backend/research/architecture_factory/a1_paid_ai_target_gate_v1.py"
_ORIGINAL_CACHE_HIT = v5._cache_hit


def _target_identity(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_lane_id": target.get("target_lane_id"),
        "target_stage": target.get("target_stage"),
        "target_gate": target.get("target_gate"),
        "target_strategy_id": target.get("target_strategy_id"),
    }


def _stamp_candidates(value: Any, target: Mapping[str, Any]) -> None:
    if isinstance(value, dict):
        if value.get("candidate_id") and value.get("mode") in {"REPAIR", "NEW_ARCHITECTURE"}:
            value.update(_target_identity(target))
            value["economic_roi_credit_requires_gate_progress"] = True
        for child in value.values():
            _stamp_candidates(child, target)
    elif isinstance(value, list):
        for child in value:
            _stamp_candidates(child, target)


def _target_cache_hit(signature: str) -> dict[str, Any] | None:
    cached = _ORIGINAL_CACHE_HIT(signature)
    if cached is None:
        return None
    target = paid_gate.require_target_binding()
    old = cached.get("paid_ai_target_binding")
    if not isinstance(old, Mapping):
        return None
    if _target_identity(old) != _target_identity(target):
        return None
    return cached


def _call_gemini_bound(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    bound, target = paid_gate.bound_prompt(
        prompt,
        provider="gemini",
        purpose="BOUNDED_G4_OR_G5_CAUSAL_REPAIR",
    )
    model, raw, lineage = gemini.call_gemini_generator(bound)
    raw = paid_gate.filter_generator_payload(raw, target)
    lineage = {
        **lineage,
        "target_lane_id": str(target.get("target_lane_id") or ""),
        "target_stage": str(target.get("target_stage") or ""),
        "target_gate": str(target.get("target_gate") or ""),
        "target_strategy_id": str(target.get("target_strategy_id") or ""),
    }
    return model, raw, lineage


def _install() -> None:
    factory.call_openai_generator = hardened.call_openai_generator
    hashutil.call_gemini_generator = _call_gemini_bound
    v5.CACHE = V6_CACHE
    v5._cache_hit = _target_cache_hit
    paths = list(v5.CODE_PATHS)
    for path in (SELF, HARDENED, TARGET_GATE):
        if path not in paths:
            paths.append(path)
    v5.CODE_PATHS = paths


def run(
    output: Path,
    *,
    target_lane_id: str | None = None,
    target_stage: str | None = None,
    target_gate: str | None = None,
) -> dict[str, Any]:
    paid_gate.configure_target(target_lane_id, target_stage, target_gate)
    target = paid_gate.require_target_binding()
    _install()
    result = v5.run(output)
    _stamp_candidates(result, target)
    result["paid_ai_target_binding"] = _target_identity(target)
    result["openai_output_hardening"] = {
        "state": "ACTIVE_MANUAL_V6",
        "provider": "openai",
        "default_model": hardened.DEFAULT_MODEL,
        "max_output_tokens": hardened.MAX_OUTPUT_TOKENS,
        "max_candidates": hardened.MAX_CANDIDATES,
        "strict_full_json_schema": True,
        "concise_output_contract": True,
        "response_status_checked": True,
        "incomplete_reason_checked": True,
        "request_token_usage_captured_on_success": True,
        "legacy_failure_target": "JSONDecodeError_Unterminated_string_at_approximately_19k_chars",
        "automatic_paid_execution": False,
        "caller_target_gate_required_before_network": True,
    }
    roi = result.setdefault("api_roi", {})
    roi["paid_execution_mode"] = "MANUAL_V6_ONLY"
    roi["automatic_paid_execution"] = False
    roi["provider_output_contract_version"] = "OPENAI_GENERATOR_HARDENED_V1"
    roi["paid_ai_target_binding"] = _target_identity(target)
    roi["detached_generic_candidate_roi_credit"] = False
    roi["roi_credit_requires_measurable_target_gate_progress"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    _install()
    assert v5.CACHE == V6_CACHE
    assert factory.call_openai_generator is hardened.call_openai_generator
    assert hashutil.call_gemini_generator is _call_gemini_bound
    assert v5._cache_hit is _target_cache_hit
    assert SELF in v5.CODE_PATHS and HARDENED in v5.CODE_PATHS and TARGET_GATE in v5.CODE_PATHS
    assert paid_gate.self_test() == 0
    assert hardened.self_test() == 0
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V6_MANUAL_HARDENING_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v6.json"))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--target-lane-id")
    ap.add_argument("--target-stage")
    ap.add_argument("--target-gate")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(
        args.output,
        target_lane_id=args.target_lane_id,
        target_stage=args.target_stage,
        target_gate=args.target_gate,
    )
    roi = result.get("api_roi") or {}
    print(json.dumps({
        "run_mode": result.get("run_mode"),
        "cache_hit": roi.get("cache_hit"),
        "paid_requests": roi.get("paid_request_count"),
        "economic_pass": result.get("development_economic_pass_count"),
        "target": result.get("paid_ai_target_binding"),
        "hardening": result.get("openai_output_hardening"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
