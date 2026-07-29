from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import read_json, stable_sha, write_json
from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1_1 import strict_classify

VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_STATE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

EXECUTABLE_CATALOG: dict[str, dict[str, Any]] = {
    "PATH_TRAIL_R075_ATR075": {"kind": "EXIT", "changes": {"trail_activate_r": 0.75, "trail_atr_mult": 0.75}},
    "PATH_PARTIAL30_R100": {"kind": "EXIT", "changes": {"partial_r": 1.0, "partial_fraction": 0.30}},
    "PATH_BE075": {"kind": "EXIT", "changes": {"breakeven_r": 0.75}},
    "PATH_BE100": {"kind": "EXIT", "changes": {"breakeven_r": 1.0}},
    "PATH_STOP_STRUCTURE_BUFFER_1": {"kind": "EXIT", "changes": {"stop_mult": 1.15}},
    "PATH_STOP_ATR_FLOOR_1": {"kind": "EXIT", "changes": {"stop_mult": 1.25}},
    "PATH_STOP_ATR_CAP_1": {"kind": "EXIT", "changes": {"stop_mult": 0.85}},
    "PATH_STOP_STRUCTURE_CAP_1": {"kind": "EXIT", "changes": {"stop_mult": 0.75}},
    "PATH_TARGET_RUNNER_SPLIT_1": {"kind": "EXIT", "changes": {"runner_target_r": 3.0}},
    "PATH_TARGET_EXTENSION_1": {"kind": "EXIT", "changes": {"target_mult": 1.25}},
    "PATH_TIME_STOP_20": {"kind": "EXIT", "changes": {"time_stop_bars": 20}},
    "PATH_TIME_STOP_16": {"kind": "EXIT", "changes": {"time_stop_bars": 16}},
}


def assert_safety(value: Mapping[str, Any], name: str) -> None:
    for key, expected in SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"SAFETY_MISMATCH:{name}:{key}")


def prepare(path_plan: Mapping[str, Any], out_root: Path) -> dict[str, Any]:
    assert_safety(path_plan, "path_plan")
    if path_plan.get("state") not in {"PASS_PRE_SHADOW_PATH_OPTIMIZE_BATCH_PLAN", "WAIT_NEW_PATH_EVIDENCE"}:
        raise ValueError(f"PATH_PLAN_STATE_INVALID:{path_plan.get('state')}")
    payload_root = out_root / "payloads"
    payload_root.mkdir(parents=True, exist_ok=True)
    executable = []
    unsupported = []
    seen: set[tuple[str, str]] = set()
    for strategy_row in path_plan.get("rows") or []:
        if not isinstance(strategy_row, Mapping):
            raise ValueError("PATH_PLAN_ROW_OBJECT_REQUIRED")
        proposal = strategy_row.get("next_candidate_proposal")
        if not isinstance(proposal, Mapping):
            continue
        strategy_id = str(proposal.get("strategy_id") or "")
        candidate_id = str(proposal.get("candidate_id") or "")
        axis = str(proposal.get("axis") or "")
        basis_variant_id = str(proposal.get("basis_variant_id") or "")
        key = (strategy_id, candidate_id)
        if not all(key) or not axis or not basis_variant_id:
            raise ValueError(f"PATH_PROPOSAL_IDENTITY_MISSING:{strategy_id}:{candidate_id}")
        if key in seen:
            raise ValueError(f"PATH_PROPOSAL_DUPLICATE:{strategy_id}:{candidate_id}")
        seen.add(key)
        catalog = EXECUTABLE_CATALOG.get(candidate_id)
        common = {
            "strategy_id": strategy_id,
            "basis_variant_id": basis_variant_id,
            "basis_bundle_sha": proposal.get("basis_bundle_sha"),
            "basis_source_sha": proposal.get("basis_source_sha"),
            "candidate_id": candidate_id,
            "candidate_sha": proposal.get("candidate_sha"),
            "axis": axis,
            "generation": proposal.get("generation"),
            "failure_fingerprint": proposal.get("failure_fingerprint"),
            "failure_support_sha": proposal.get("failure_support_sha"),
            "source_proposal": copy.deepcopy(dict(proposal)),
        }
        if catalog is None:
            unsupported.append({
                **common,
                "state": "WAIT_FAMILY_BINDING",
                "reason": "ENTRY_OR_CONTEXT_AXIS_REQUIRES_STRATEGY_FAMILY_SEMANTIC_BINDING",
            })
            continue
        executable_spec = {
            **common,
            "kind": catalog["kind"],
            "changes": copy.deepcopy(catalog["changes"]),
            "single_axis": True,
            "replay_required": True,
            **SAFETY,
        }
        executable_spec["executable_spec_sha"] = stable_sha(executable_spec)
        executable.append(executable_spec)
        payload = {
            "strategy_id": strategy_id,
            "changed_axes": [axis],
            "routing_flags": {
                "external_hypothesis": True,
                "multimodal": False,
                "new_multimodal_evidence": False,
                "new_failure_fingerprint": True,
                "borderline_case": True,
                "major_gate_review": False,
            },
            "hypothesis": {
                "source": "SOURCE_BOUND_TRADE_PATH_CAUSAL_LOOP",
                "axis": axis,
                "candidate_id": candidate_id,
                "description": str(proposal.get("why") or "path-derived single-axis candidate"),
            },
            "evidence": {
                "basis_variant_id": basis_variant_id,
                "basis_bundle_sha": proposal.get("basis_bundle_sha"),
                "failure_fingerprint": proposal.get("failure_fingerprint"),
                "failure_support_sha": proposal.get("failure_support_sha"),
                "generation": proposal.get("generation"),
                "executable_changes": catalog["changes"],
                "single_axis": True,
                "bounded_catalog": True,
            },
            "lineage": {
                "source_sha": proposal.get("basis_source_sha"),
                "data_sha": path_plan.get("path_index_sha"),
                "window_sha": path_plan.get("triage_sha"),
                "candidate_sha": proposal.get("candidate_sha"),
            },
            **SAFETY,
        }
        write_json(payload_root / f"{strategy_id}__{candidate_id}.json", payload)
    prepared = {
        "schema_version": "strategy11.path_candidate_prepared.v1",
        "version": VERSION,
        "state": "PASS_PATH_CANDIDATES_PREPARED" if executable else "WAIT_PATH_FAMILY_BINDING_OR_NEW_EVIDENCE",
        "source_path_plan_sha": path_plan.get("plan_sha"),
        "executable_count": len(executable),
        "unsupported_count": len(unsupported),
        "executable": executable,
        "unsupported": unsupported,
        **SAFETY,
    }
    prepared["prepared_sha"] = stable_sha(prepared)
    write_json(out_root / "prepared.json", prepared)
    return prepared


def filter_reviews(prepared: Mapping[str, Any], ai_root: Path, out_root: Path) -> dict[str, Any]:
    assert_safety(prepared, "prepared")
    accepted = []
    semantic_rejected = []
    advisory_held = []
    waiting = []
    blockers = []
    specs = {(row["strategy_id"], row["candidate_id"]): row for row in prepared.get("executable") or []}
    for key, spec in sorted(specs.items()):
        path = ai_root / f"{key[0]}__{key[1]}.json"
        if not path.exists():
            waiting.append({**spec, "review_state": "WAIT_QUOTA", "reason": "AI_REVIEW_OUTPUT_MISSING"})
            continue
        result = read_json(path)
        state = strict_classify(path)
        row = {
            **spec,
            "review_state": state,
            "review_status": result.get("status"),
            "review_sha": stable_sha(result),
            "blocker_codes": result.get("blocker_codes") or [],
            "wait_codes": result.get("wait_codes") or [],
        }
        if state == "ACCEPTED":
            accepted.append(row)
        elif state == "SEMANTIC_REJECT":
            semantic_rejected.append(row)
        elif state == "ADVISORY_HOLD":
            advisory_held.append(row)
        elif state == "WAIT_QUOTA":
            waiting.append(row)
        else:
            blockers.append(row)
    if blockers:
        state = "HOLD_PATH_AI_REVIEW_BLOCKER"
    elif waiting:
        state = "WAIT_PATH_AI_QUOTA"
    elif accepted:
        state = "PASS_PATH_AI_REVIEW_READY_TO_REPLAY"
    else:
        state = "WAIT_PATH_ALL_SEMANTIC_REJECT_OR_FAMILY_BINDING"
    replay_plan = {
        "schema_version": "strategy11.path_candidate_replay_plan.v1",
        "version": VERSION,
        "state": state,
        "rows": [
            {
                "strategy_id": row["strategy_id"],
                "basis_variant_id": row["basis_variant_id"],
                "candidate_ids": [row["candidate_id"]],
                "candidate_specs": {
                    row["candidate_id"]: {
                        "kind": row["kind"],
                        "axis": row["axis"],
                        "changes": row["changes"],
                        "basis_variant_id": row["basis_variant_id"],
                        "source_proposal_sha": row["candidate_sha"],
                    }
                },
            }
            for row in accepted
        ],
        "accepted_count": len(accepted),
        "semantic_reject_count": len(semantic_rejected),
        "advisory_hold_count": len(advisory_held),
        "wait_quota_count": len(waiting),
        "blocker_count": len(blockers),
        "unsupported_count": int(prepared.get("unsupported_count") or 0),
        "accepted": accepted,
        "semantic_rejected": semantic_rejected,
        "advisory_held": advisory_held,
        "waiting": waiting,
        "blockers": blockers,
        "unsupported": copy.deepcopy(prepared.get("unsupported") or []),
        **SAFETY,
    }
    replay_plan["replay_plan_sha"] = stable_sha(replay_plan)
    write_json(out_root / "replay_plan.json", replay_plan)
    return replay_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "filter"), required=True)
    parser.add_argument("--path-plan", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--ai-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        if args.path_plan is None:
            raise SystemExit("PATH_PLAN_REQUIRED")
        result = prepare(read_json(args.path_plan), args.out)
    else:
        if args.prepared is None or args.ai_root is None:
            raise SystemExit("PREPARED_AND_AI_ROOT_REQUIRED")
        result = filter_reviews(read_json(args.prepared), args.ai_root, args.out)
    print(result["state"])
    return 1 if str(result["state"]).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
