from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_STATE_MACHINE_V1"


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def build_payloads(plan_root: Path, payload_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = read_json(plan_root / "plan.json")
    causes = read_json(plan_root / "cause_analysis.json")
    ledger = read_json(plan_root / "search_ledger.json")
    crows = {row["strategy_id"]: row for row in causes["rows"]}
    data_sha = hashlib.sha256(b"SOURCE_RUN_30252022416").hexdigest()
    manifest = []
    payload_root.mkdir(parents=True, exist_ok=True)
    for row in plan["rows"]:
        cause = crows[row["strategy_id"]]
        for candidate_id in row["candidate_ids"]:
            spec = row["candidate_specs"][candidate_id]
            axis = spec["axis"]
            evidence = {
                "generation": 7,
                "failure_fingerprint": row["failure_fingerprint"],
                "control_metrics": cause["control"],
                "prior_candidate_metrics": cause["candidates"],
                "zero_trade_candidate_count": cause["zero_trade_candidate_count"],
                "nonzero_candidate_count": cause["nonzero_candidate_count"],
                "selection_rationale": row["selection_rationale"],
                "candidate_spec": spec,
                "immutable_windows": ["F1", "F2", "F3"],
                "bounded_epoch": True,
                "same_axis_retest": False,
            }
            candidate_sha = stable_sha({
                "strategy_id": row["strategy_id"],
                "candidate_id": candidate_id,
                "spec": spec,
                "evidence": evidence,
                "source_plan_sha": plan["prior_final_sha256"],
            })
            payload = {
                "strategy_id": row["strategy_id"],
                "changed_axes": [axis],
                "routing_flags": {
                    "external_hypothesis": True,
                    "multimodal": False,
                    "new_multimodal_evidence": False,
                    "new_failure_fingerprint": True,
                    "borderline_case": row["failure_fingerprint"] in {"NEAR_PASS_LOSS_SHAPE", "NEAR_BREAKEVEN_ECONOMICS"},
                    "major_gate_review": False,
                },
                "hypothesis": {
                    "source": "DETERMINISTIC_GENERATION6_FAILURE_ANALYSIS",
                    "axis": axis,
                    "candidate_id": candidate_id,
                    "description": row["selection_rationale"]["why"],
                },
                "evidence": evidence,
                "lineage": {
                    "source_sha": "64e27d16d7f28b9fae59cf2a875d195f4bca22a1",
                    "data_sha": data_sha,
                    "window_sha": plan["prior_final_sha256"],
                    "candidate_sha": candidate_sha,
                },
                **SAFETY,
            }
            file_name = f"{row['strategy_id']}__{candidate_id}.json"
            write_json(payload_root / file_name, payload)
            manifest.append({
                "strategy_id": row["strategy_id"],
                "candidate_id": candidate_id,
                "axis": axis,
                "file": file_name,
                "candidate_sha": candidate_sha,
            })
    if len(manifest) != plan["candidate_count"]:
        raise ValueError(f"PAYLOAD_COUNT_MISMATCH:{len(manifest)}:{plan['candidate_count']}")
    write_json(payload_root.parent / "payload_manifest.json", {
        "state": "PASS_GENERATION7_QUOTA_PAYLOADS",
        "source_plan_sha": plan["prior_final_sha256"],
        "rows": manifest,
        **SAFETY,
    })
    return plan, causes, ledger


def run_router(
    router: Path,
    policy: Path,
    payload: Path,
    output: Path,
    prior_roots: list[Path],
    cache_only: bool,
) -> None:
    command = [
        sys.executable,
        str(router.resolve()),
        "--stage", "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
        "--input", str(payload.resolve()),
        "--policy", str(policy.resolve()),
        "--output", str(output.resolve()),
    ]
    for root in prior_roots:
        command.extend(["--prior-root", str(root.resolve())])
    if cache_only:
        command.append("--cache-only")
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode not in (0, 1):
        raise RuntimeError(f"ROUTER_PROCESS_ERROR:{payload.name}:{process.returncode}:{process.stderr[:500]}")
    if not output.exists():
        raise RuntimeError(f"ROUTER_OUTPUT_MISSING:{payload.name}")


def classify(path: Path) -> str:
    result = read_json(path)
    status = str(result.get("status") or "")
    if status == "PASS_AI_REVIEW_DECISION_GATE":
        return "ACCEPTED"
    if status == "WAIT_AI_QUOTA_REVIEW":
        return "WAIT_QUOTA"
    if status == "HOLD_AI_REVIEW_DECISION_GATE":
        blockers = [str(value) for value in result.get("blocker_codes") or []]
        if blockers and all("DECISION_" in blocker or "SINGLE_AXIS_FALSE" in blocker or "LINEAGE_INCOMPLETE" in blocker for blocker in blockers):
            return "SEMANTIC_REJECT"
        return "BLOCKER"
    return "BLOCKER"


def finalize(
    plan: dict[str, Any],
    causes: dict[str, Any],
    ledger: dict[str, Any],
    ai_root: Path,
    output_root: Path,
    max_new_candidates: int,
) -> dict[str, Any]:
    states: dict[tuple[str, str], dict[str, Any]] = {}
    accepted = []
    rejected = []
    waiting = []
    blockers = []
    new_provider_calls = 0
    for path in sorted(ai_root.glob("*.json")):
        strategy_id, candidate_id = path.stem.split("__", 1)
        result = read_json(path)
        state = classify(path)
        row = {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "state": state,
            "status": result.get("status"),
            "blocker_codes": result.get("blocker_codes") or [],
            "wait_codes": result.get("wait_codes") or [],
            "input_sha": result.get("input_sha"),
            "external_input_sha": result.get("external_input_sha"),
            "policy_sha": result.get("policy_sha"),
            "plan_sha": result.get("plan_sha"),
            "new_provider_calls": int(result.get("new_provider_calls") or 0),
            "review_sha": stable_sha(result),
            "file": path.name,
        }
        new_provider_calls += row["new_provider_calls"]
        states[(strategy_id, candidate_id)] = row
        if state == "ACCEPTED":
            accepted.append(row)
        elif state == "SEMANTIC_REJECT":
            rejected.append(row)
        elif state == "WAIT_QUOTA":
            waiting.append(row)
        else:
            blockers.append(row)

    if blockers:
        write_json(output_root / "blockers.json", blockers)
        raise RuntimeError(f"UNRECOVERABLE_AI_REVIEW_BLOCKERS:{len(blockers)}")
    if new_provider_calls > max_new_candidates * 2:
        raise RuntimeError(f"PROVIDER_CALL_BUDGET_BREACH:{new_provider_calls}:{max_new_candidates * 2}")

    accepted_set = {(row["strategy_id"], row["candidate_id"]) for row in accepted}
    rejected_set = {(row["strategy_id"], row["candidate_id"]) for row in rejected}
    waiting_set = {(row["strategy_id"], row["candidate_id"]) for row in waiting}
    ledger_rows = {row["strategy_id"]: row for row in ledger["rows"]}
    replay_rows = []
    strategy_states = []
    for source_row in plan["rows"]:
        row = json.loads(json.dumps(source_row))
        strategy_id = row["strategy_id"]
        original = list(row["candidate_ids"])
        unresolved = [candidate_id for candidate_id in original if (strategy_id, candidate_id) in waiting_set]
        kept = [candidate_id for candidate_id in original if (strategy_id, candidate_id) in accepted_set]
        dropped = [candidate_id for candidate_id in original if (strategy_id, candidate_id) in rejected_set]
        if len(unresolved) + len(kept) + len(dropped) != len(original):
            raise RuntimeError(f"CANDIDATE_STATE_ACCOUNTING_MISMATCH:{strategy_id}")
        ledger_row = ledger_rows[strategy_id]
        if unresolved:
            state = "WAIT_QUOTA"
            ledger_row["rejection_reason"] = ";".join(f"{candidate_id}:WAIT_AI_QUOTA" for candidate_id in unresolved)
            ledger_row["next_axis"] = "WAIT_AI_QUOTA"
        elif kept:
            state = "READY_TO_REPLAY"
            row["candidate_ids"] = kept
            row["candidate_specs"] = {candidate_id: row["candidate_specs"][candidate_id] for candidate_id in kept}
            row["ai_review_state"] = "PASS_TO_REPLAY_FILTERED"
            row["ai_rejected_candidates"] = dropped
            replay_rows.append(row)
            ledger_row["selected_candidate_ids"] = kept
            ledger_row["selected_axes"] = [row["candidate_specs"][candidate_id]["axis"] for candidate_id in kept]
            ledger_row["rejection_reason"] = ";".join(f"{candidate_id}:AI_SEMANTIC_REJECT" for candidate_id in dropped)
        else:
            state = "WAIT_NEW_EVIDENCE"
            ledger_row["selected_candidate_ids"] = []
            ledger_row["selected_axes"] = []
            ledger_row["rejection_reason"] = "ALL_GENERATION7_AXES_AI_SEMANTIC_REJECT"
            ledger_row["next_axis"] = "WAIT_NEW_EVIDENCE"
        strategy_states.append({
            "strategy_id": strategy_id,
            "state": state,
            "accepted_candidate_ids": kept,
            "semantic_rejected_candidate_ids": dropped,
            "wait_quota_candidate_ids": unresolved,
        })

    ready = not waiting
    accepted_plan = json.loads(json.dumps(plan))
    accepted_plan["rows"] = replay_rows if ready else []
    accepted_plan["state"] = "PASS_GENERATION7_QUOTA_REVIEW_COMPLETE" if ready else "WAIT_GENERATION7_AI_QUOTA"
    accepted_plan["original_strategy_count"] = len(plan["rows"])
    accepted_plan["strategy_count"] = len(replay_rows) if ready else 0
    accepted_plan["candidate_count"] = sum(len(row["candidate_ids"]) for row in replay_rows) if ready else 0
    accepted_plan["ai_pass_count"] = len(accepted)
    accepted_plan["ai_semantic_reject_count"] = len(rejected)
    accepted_plan["ai_wait_quota_count"] = len(waiting)
    accepted_plan["ready_to_replay"] = ready and bool(replay_rows)
    accepted_plan["all_candidates_final"] = ready
    accepted_plan.update(SAFETY)

    ledger["ai_pass_count"] = len(accepted)
    ledger["ai_semantic_reject_count"] = len(rejected)
    ledger["ai_wait_quota_count"] = len(waiting)
    ledger["strategy_states"] = strategy_states
    ledger["quota_epoch_complete"] = ready
    ledger["state_machine_version"] = VERSION
    ledger.update(SAFETY)

    manifest = {
        "schema_version": "strategy11.generation7.quota_state_machine.v1",
        "version": VERSION,
        "state": "PASS_GENERATION7_AI_REVIEW_COMPLETE" if ready else "WAIT_GENERATION7_AI_QUOTA",
        "review_count": len(states),
        "pass_count": len(accepted),
        "semantic_reject_count": len(rejected),
        "wait_quota_count": len(waiting),
        "new_provider_calls": new_provider_calls,
        "max_new_candidates": max_new_candidates,
        "replay_strategy_count": len(replay_rows) if ready else 0,
        "ready_to_replay": ready and bool(replay_rows),
        "all_candidates_final": ready,
        "accepted": accepted,
        "semantic_rejected": rejected,
        "wait_quota": waiting,
        "strategy_states": strategy_states,
        "next": "REPLAY_ACCEPTED_CANDIDATES" if ready and replay_rows else "WAIT_NEXT_DAILY_QUOTA_EPOCH" if waiting else "WAIT_NEW_EVIDENCE",
        **SAFETY,
    }
    manifest["state_sha"] = stable_sha(manifest)
    write_json(output_root / "accepted_plan.json", accepted_plan)
    write_json(output_root / "search_ledger.json", ledger)
    write_json(output_root / "cause_analysis.json", causes)
    write_json(output_root / "ai_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--ai-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, action="append", default=[])
    parser.add_argument("--max-new-candidates", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.max_new_candidates <= 10:
        raise SystemExit("MAX_NEW_CANDIDATES_MUST_BE_1_TO_10")

    plan, causes, ledger = build_payloads(args.plan_root, args.payload_root)
    args.ai_root.mkdir(parents=True, exist_ok=True)
    prior_roots = list(args.prior_root)

    for payload in sorted(args.payload_root.glob("*.json")):
        run_router(args.router, args.policy, payload, args.ai_root / payload.name, prior_roots, cache_only=True)

    unresolved = [path for path in sorted(args.ai_root.glob("*.json")) if classify(path) == "WAIT_QUOTA"]
    selected = unresolved[: args.max_new_candidates]
    live_prior = [*prior_roots, args.ai_root]
    for result_path in selected:
        payload = args.payload_root / result_path.name
        run_router(args.router, args.policy, payload, result_path, live_prior, cache_only=False)

    manifest = finalize(plan, causes, ledger, args.ai_root, args.output_root, args.max_new_candidates)
    print(manifest["state"], "pass=", manifest["pass_count"], "reject=", manifest["semantic_reject_count"], "wait=", manifest["wait_quota_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
