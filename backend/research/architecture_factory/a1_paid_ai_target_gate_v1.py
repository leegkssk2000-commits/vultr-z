#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/contracts/a1_paid_ai_routing_policy_v1.json"
BRIDGE = ROOT / "backend/research/contracts/a1_ai_g4_g5_economic_bridge_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"

ENV_LANE = "A1_PAID_AI_TARGET_LANE_ID"
ENV_STAGE = "A1_PAID_AI_TARGET_STAGE"
ENV_GATE = "A1_PAID_AI_TARGET_GATE"
PAID_PROVIDERS = {"openai", "gemini"}
FORBIDDEN_GATE_TOKENS = {"GENERIC", "UNBOUND", "DETACHED", "NEW_CANDIDATE_SWEEP", "BROAD_SWEEP"}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def configure_target(lane_id: str | None, stage: str | None, gate: str | None) -> None:
    values = ((ENV_LANE, lane_id), (ENV_STAGE, stage), (ENV_GATE, gate))
    for key, value in values:
        if value is not None:
            os.environ[key] = str(value).strip()


def _top5_by_lane(top5: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in top5.get("top5") or []:
        if isinstance(row, Mapping) and str(row.get("lane_id") or ""):
            out[str(row["lane_id"])] = row
    return out


def validate_target_binding(
    lane_id: str,
    stage: str,
    gate: str,
    *,
    provider: str | None = None,
    policy: Mapping[str, Any] | None = None,
    bridge: Mapping[str, Any] | None = None,
    top5: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    p = dict(policy) if isinstance(policy, Mapping) else _read(POLICY)
    b = dict(bridge) if isinstance(bridge, Mapping) else _read(BRIDGE)
    s = dict(top5) if isinstance(top5, Mapping) else _read(TOP5)
    controls = p.get("mandatory_controls") or {}
    if p.get("schema_version") != "zel.a1.paid_ai_routing_policy.v1" or p.get("state") != "PAID_AI_ROI_GATED_ROUTING_FROZEN":
        raise RuntimeError("PAID_AI_POLICY_AUTHORITY_DRIFT")
    if b.get("schema_version") != "zel.a1.ai_g4_g5_economic_bridge.v1" or b.get("state") != "G4_G5_ONLY_AI_ECONOMIC_ATTRIBUTION_FROZEN":
        raise RuntimeError("PAID_AI_BRIDGE_AUTHORITY_DRIFT")
    for key in (
        "target_lane_id_required_before_provider_call",
        "target_stage_required_before_provider_call",
        "target_gate_required_before_provider_call",
        "generic_unbound_NEW_candidate_success_forbidden",
        "paid_ai_credit_requires_g4_or_g5_gate_progress",
    ):
        if controls.get(key) is not True:
            raise RuntimeError(f"PAID_AI_CONTROL_DRIFT:{key}")
    if controls.get("fresh_sample_wait_triggers_paid_ai") is not False:
        raise RuntimeError("PAID_AI_FRESH_WAIT_POLICY_DRIFT")

    lane = str(lane_id or "").strip()
    target_stage = str(stage or "").strip().upper()
    target_gate = str(gate or "").strip()
    if not lane:
        raise RuntimeError("PAID_AI_TARGET_LANE_ID_REQUIRED_BEFORE_PROVIDER_CALL")
    if not target_stage:
        raise RuntimeError("PAID_AI_TARGET_STAGE_REQUIRED_BEFORE_PROVIDER_CALL")
    if not target_gate:
        raise RuntimeError("PAID_AI_TARGET_GATE_REQUIRED_BEFORE_PROVIDER_CALL")
    allowed_stages = {str(x) for x in controls.get("allowed_target_stages") or []}
    if target_stage not in allowed_stages:
        raise RuntimeError(f"PAID_AI_TARGET_STAGE_FORBIDDEN:{target_stage}")
    gate_upper = target_gate.upper()
    if any(token in gate_upper for token in FORBIDDEN_GATE_TOKENS):
        raise RuntimeError(f"PAID_AI_TARGET_GATE_DETACHED_OR_GENERIC:{target_gate}")
    if provider is not None and str(provider).lower() not in PAID_PROVIDERS:
        raise RuntimeError(f"PAID_AI_PROVIDER_NOT_GATED_CLASS:{provider}")

    rules = p.get("active_stage_rules") or {}
    rule = rules.get(lane)
    if not isinstance(rule, Mapping):
        raise RuntimeError(f"PAID_AI_TARGET_LANE_NOT_CURRENT_TOP5:{lane}")
    rows = _top5_by_lane(s)
    top5_row = rows.get(lane)
    if not isinstance(top5_row, Mapping):
        raise RuntimeError(f"PAID_AI_TARGET_LANE_MISSING_FROM_TOP5_SSOT:{lane}")
    current_stage = str(rule.get("stage") or "")
    if target_stage in {"G4", "G5"} and current_stage != target_stage:
        raise RuntimeError(f"PAID_AI_TARGET_STAGE_LANE_MISMATCH:{lane}:{target_stage}:{current_stage}")
    if target_stage == "G4_CAUSAL_BACKPORT_FROM_G5" and current_stage != "G5":
        raise RuntimeError(f"PAID_AI_BACKPORT_REQUIRES_G5_SOURCE_LANE:{lane}")

    current_state = str(rule.get("state") or "")
    ai_allowed_now = str(rule.get("ai_allowed_now") or "")
    if target_stage == "G4":
        if ai_allowed_now.startswith("NO_") or "NO_MUTATION_WHILE" in ai_allowed_now:
            raise RuntimeError(f"PAID_AI_G4_FRESH_SAMPLE_WAIT_BLOCKED:{lane}:{current_state}")
    elif target_stage == "G5":
        if ai_allowed_now.startswith("NO_"):
            raise RuntimeError(f"PAID_AI_G5_CURRENT_STAGE_BLOCKED:{lane}:{current_state}")
        if "FORENSIC_CAUSAL_ANALYSIS_ONLY" in ai_allowed_now and not ({"FORENSIC", "CAUSAL"} & set(gate_upper.replace("-", "_").split("_"))):
            raise RuntimeError(f"PAID_AI_G5_GATE_MUST_BE_CAUSAL_OR_FORENSIC:{target_gate}")
    else:
        terminal_markers = ("FAIL", "FALSIFIED", "TERMINAL")
        if not any(marker in current_state.upper() for marker in terminal_markers):
            raise RuntimeError(f"PAID_AI_G4_BACKPORT_BLOCKED_UNTIL_G5_TERMINAL_FAIL:{lane}:{current_state}")

    strategy_id = str(top5_row.get("strategy_id") or "").strip()
    if not strategy_id:
        raise RuntimeError(f"PAID_AI_TARGET_STRATEGY_ID_MISSING:{lane}")
    return {
        "target_lane_id": lane,
        "target_stage": target_stage,
        "target_gate": target_gate,
        "target_strategy_id": strategy_id,
        "current_stage": current_stage,
        "current_state": current_state,
        "ai_allowed_now": ai_allowed_now,
        "selected_causal_axis": rule.get("selected_causal_axis"),
        "policy_state": p.get("state"),
        "bridge_state": b.get("state"),
    }


def require_target_binding(*, provider: str | None = None) -> dict[str, Any]:
    return validate_target_binding(
        os.environ.get(ENV_LANE, ""),
        os.environ.get(ENV_STAGE, ""),
        os.environ.get(ENV_GATE, ""),
        provider=provider,
    )


def bound_prompt(prompt: str, *, provider: str, purpose: str) -> tuple[str, dict[str, Any]]:
    target = require_target_binding(provider=provider)
    contract = {
        "target_lane_id": target["target_lane_id"],
        "target_stage": target["target_stage"],
        "target_gate": target["target_gate"],
        "target_strategy_id": target["target_strategy_id"],
        "current_state": target["current_state"],
        "selected_causal_axis": target.get("selected_causal_axis"),
        "purpose": str(purpose),
    }
    prefix = (
        "PAID_AI_G4_G5_TARGET_BINDING=" + json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        "HARD RULE: Work ONLY on the named current Top5 lane, stage, and economic gate. "
        "Do not create detached generic research, broad sweeps, or unrelated NEW candidates. "
        "Any NEW_ARCHITECTURE output is permitted only as a replacement/backport architecture for this named lane. "
        "Fresh-sample waiting cannot be solved by AI and must never be represented as stage progress.\n"
    )
    return prefix + str(prompt), target


def filter_generator_payload(payload: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise RuntimeError("PAID_AI_GENERATOR_CANDIDATES_REQUIRED")
    strategy_id = str(target.get("target_strategy_id") or "")
    stage = str(target.get("target_stage") or "")
    kept: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        mode = str(raw.get("mode") or "")
        candidate_strategy = str(raw.get("strategy_id") or "")
        if mode == "REPAIR" and candidate_strategy != strategy_id:
            continue
        if mode == "NEW_ARCHITECTURE" and stage == "G5":
            continue
        if mode not in {"REPAIR", "NEW_ARCHITECTURE"}:
            continue
        kept.append(dict(raw))
    if not kept:
        raise RuntimeError("PAID_AI_NO_TARGET_BOUND_GENERATOR_CANDIDATES")
    return {"candidates": kept}


def stamp_rows(rows: list[dict[str, Any]], target: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["target_lane_id"] = target.get("target_lane_id")
        item["target_stage"] = target.get("target_stage")
        item["target_gate"] = target.get("target_gate")
        item["target_strategy_id"] = target.get("target_strategy_id")
        item["economic_roi_credit_requires_gate_progress"] = True
        out.append(item)
    return out


def self_test() -> int:
    policy = _read(POLICY)
    bridge = _read(BRIDGE)
    top5 = _read(TOP5)
    failures = 0
    for lane, stage, gate in (
        ("", "G5", "W2_FORENSIC_CAUSAL"),
        ("trend_rider_broad_wr7000", "BAD", "W2_FORENSIC_CAUSAL"),
        ("trend_rider_primary_wr8125", "G4", "G4_CAUSAL_REPAIR"),
        ("break_and_continue_main", "G4", "G4_CAUSAL_REPAIR"),
        ("trend_rider_broad_wr7000", "G4_CAUSAL_BACKPORT_FROM_G5", "G4_CAUSAL_BACKPORT"),
    ):
        try:
            validate_target_binding(lane, stage, gate, policy=policy, bridge=bridge, top5=top5)
        except RuntimeError:
            failures += 1
    assert failures == 5
    ok = validate_target_binding(
        "trend_rider_broad_wr7000", "G5", "W2_FORENSIC_CAUSAL_ANALYSIS",
        policy=policy, bridge=bridge, top5=top5,
    )
    assert ok["target_strategy_id"] == "trend_rider"
    assert ok["current_state"] == "WAIT_G5_W2_12"
    filtered = filter_generator_payload({"candidates": [
        {"mode": "REPAIR", "strategy_id": "trend_rider", "candidate_id": "keep"},
        {"mode": "REPAIR", "strategy_id": "other", "candidate_id": "drop"},
        {"mode": "NEW_ARCHITECTURE", "strategy_id": "NEW", "candidate_id": "drop_new_in_g5"},
    ]}, ok)
    assert [x["candidate_id"] for x in filtered["candidates"]] == ["keep"]
    print("PASS_A1_PAID_AI_TARGET_GATE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--target-lane-id")
    ap.add_argument("--target-stage")
    ap.add_argument("--target-gate")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    configure_target(args.target_lane_id, args.target_stage, args.target_gate)
    print(json.dumps(require_target_binding(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
