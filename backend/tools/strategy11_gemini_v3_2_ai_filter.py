from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "runtime_bound": False,
    "order_authority": "BLOCKED",
}
PASS_DECISION = "PASS_TO_REPLAY"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def find_results(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("**/result.json")):
        try:
            value = read_json(path)
        except Exception:
            continue
        strategy_id = str(value.get("strategy_id") or "")
        if strategy_id:
            rows[strategy_id] = value
    return rows


def metric_view(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_count": row.get("trade_count"),
        "win_rate_pct": row.get("win_rate_pct"),
        "net_return_pct_sum": row.get("net_return_pct_sum"),
        "net_profit_factor": row.get("net_profit_factor"),
        "payoff_ratio": row.get("payoff_ratio"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "positive_window_count": row.get("positive_window_count"),
        "research_state": row.get("research_state"),
    }


def prepare(plan: Mapping[str, Any], artifact: Mapping[str, Any], results: Mapping[str, Mapping[str, Any]], out: Path) -> dict[str, Any]:
    selections = {
        str(row["strategy_id"]): dict(row)
        for row in artifact.get("selected_rows", [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    rows: list[dict[str, Any]] = []
    for plan_row in plan.get("rows", []):
        if not isinstance(plan_row, Mapping):
            continue
        strategy_id = str(plan_row["strategy_id"])
        candidate_ids = [str(value) for value in plan_row.get("candidate_ids", [])]
        if len(candidate_ids) != 1:
            raise ValueError(f"ONE_CANDIDATE_REQUIRED:{strategy_id}")
        candidate_id = candidate_ids[0]
        selection = selections.get(strategy_id)
        if not selection or selection.get("candidate_id") != candidate_id:
            raise ValueError(f"SELECTION_LINEAGE_MISMATCH:{strategy_id}:{candidate_id}")
        candidate_spec = dict(selection.get("candidate_spec") or {})
        axis = str(candidate_spec.get("axis") or "")
        if not axis:
            raise ValueError(f"CANDIDATE_AXIS_MISSING:{strategy_id}")
        result = results.get(strategy_id)
        if not result:
            raise ValueError(f"RESULT_MISSING:{strategy_id}")
        control = result.get("control") if isinstance(result.get("control"), Mapping) else {}
        payload = {
            "strategy_id": strategy_id,
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "changed_axes": [axis],
            "routing_flags": {
                "external_hypothesis": True,
                "multimodal": True,
                "new_multimodal_evidence": True,
                "new_failure_fingerprint": True,
                "borderline_case": False,
                "major_gate_review": False,
            },
            "hypothesis": {
                "candidate_id": candidate_id,
                "axis": axis,
                "candidate_spec": candidate_spec,
                "causal_reason": selection.get("causal_reason"),
                "internal_evidence_refs": selection.get("internal_evidence_refs", []),
                "video_source_indexes": selection.get("video_source_indexes", []),
                "expected_metric_effect": selection.get("expected_metric_effect"),
                "falsification_test": selection.get("falsification_test"),
                "overfit_risk": selection.get("overfit_risk"),
            },
            "control_evidence": metric_view(control),
            "tested_variant_evidence": [
                metric_view(row)
                for row in result.get("variants", [])
                if isinstance(row, Mapping)
            ],
            "candidate_generation": {
                "one_axis_only": candidate_spec.get("one_axis_only"),
                "same_axis_generation_limit": candidate_spec.get("same_axis_generation_limit"),
                "canonical_mutated": candidate_spec.get("canonical_mutated"),
                "selected_by": "GEMINI_DIRECT_VIDEO_V3_2_COHORT",
                "deterministic_replay_pending": True,
            },
            "lineage": {
                "source_sha": artifact.get("v3_final_sha256"),
                "data_sha": "985c8561016639b7ab4397bd8064cf3a67d8667db3a21797138aa5326291dbbd",
                "window_sha": "STRATEGY11_V3_12_WINDOW_ARCHIVE",
                "candidate_sha": candidate_spec.get("candidate_spec_sha256"),
                "gemini_input_sha": artifact.get("input_sha"),
                "gemini_response_sha": artifact.get("response_sha"),
            },
            **SAFETY,
        }
        path = out / f"{strategy_id}.json"
        write_json(path, payload)
        rows.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "axis": axis, "input_file": path.name})
    index = {
        "schema_version": "3.2",
        "state": "PASS_CANDIDATE_AI_INPUTS_PREPARED",
        "candidate_count": len(rows),
        "rows": rows,
        **SAFETY,
    }
    write_json(out / "index.json", index)
    return index


def provider_decision(router: Mapping[str, Any], provider: str) -> tuple[str, list[str], str]:
    result = router.get("provider_results", {}).get(provider, {})
    artifact = result.get("artifact") if isinstance(result, Mapping) else {}
    review = artifact.get("review") if isinstance(artifact, Mapping) else {}
    decision = str(review.get("decision") or "MISSING") if isinstance(review, Mapping) else "MISSING"
    blockers = review.get("blocker_codes", []) if isinstance(review, Mapping) else []
    reason = str(review.get("reason") or "") if isinstance(review, Mapping) else ""
    return decision, [str(value) for value in blockers] if isinstance(blockers, list) else [], reason


def filter_plan(plan: Mapping[str, Any], router_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in plan.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        strategy_id = str(row["strategy_id"])
        router = read_json(router_root / f"{strategy_id}.json")
        groq_decision, groq_blockers, groq_reason = provider_decision(router, "groq")
        workers_decision, workers_blockers, workers_reason = provider_decision(router, "workers_ai")
        passed = (
            router.get("status") == "PASS_AI_REVIEW_ROUTER"
            and groq_decision == PASS_DECISION
            and workers_decision == PASS_DECISION
        )
        audit = {
            "strategy_id": strategy_id,
            "candidate_ids": list(row.get("candidate_ids", [])),
            "router_status": router.get("status"),
            "groq_decision": groq_decision,
            "groq_blockers": groq_blockers,
            "groq_reason": groq_reason,
            "workers_ai_decision": workers_decision,
            "workers_ai_blockers": workers_blockers,
            "workers_ai_reason": workers_reason,
            "accepted_for_deterministic_replay": passed,
        }
        if passed:
            accepted.append(dict(row))
        else:
            rejected.append(audit)
    output = dict(plan)
    output["rows"] = accepted
    output["active_strategy_ids"] = [str(row["strategy_id"]) for row in accepted]
    output["active_strategy_count"] = len(accepted)
    output["candidate_count"] = len(accepted)
    output["state"] = "PASS_AI_FILTERED_GEMINI_V3_2_PLAN" if accepted else "COMPLETE_NO_AI_APPROVED_REPLAY_AXIS"
    output["ai_rejected_count"] = len(rejected)
    output["ai_filter_required"] = True
    report = {
        "schema_version": "3.2",
        "state": "PASS_CANDIDATE_AI_FILTER",
        "input_candidate_count": len(accepted) + len(rejected),
        "accepted_candidate_count": len(accepted),
        "rejected_candidate_count": len(rejected),
        "accepted_strategy_ids": [str(row["strategy_id"]) for row in accepted],
        "rejected_rows": rejected,
        **SAFETY,
    }
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--plan", required=True)
    prepare_parser.add_argument("--gemini-artifact", required=True)
    prepare_parser.add_argument("--results-root", required=True)
    prepare_parser.add_argument("--out", required=True)
    filter_parser = sub.add_parser("filter")
    filter_parser.add_argument("--plan", required=True)
    filter_parser.add_argument("--router-root", required=True)
    filter_parser.add_argument("--out-plan", required=True)
    filter_parser.add_argument("--out-report", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        index = prepare(
            read_json(Path(args.plan)),
            read_json(Path(args.gemini_artifact)),
            find_results(Path(args.results_root)),
            Path(args.out),
        )
        print(json.dumps(index, sort_keys=True))
    else:
        plan, report = filter_plan(read_json(Path(args.plan)), Path(args.router_root))
        write_json(Path(args.out_plan), plan)
        write_json(Path(args.out_report), report)
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
