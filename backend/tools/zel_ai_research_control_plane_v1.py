from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION = "ZEL_AI_RESEARCH_CONTROL_PLANE_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return data


def validate_policy(policy: Mapping[str, Any], adversarial: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    layers = policy.get("layers", {})
    safety = policy.get("safety", {})
    if policy.get("schema_version") != "zel.ai.research_control_plane.v1":
        errors.append("POLICY_SCHEMA")
    vault = layers.get("blind_holdout_vault", {})
    if vault.get("proposer_access") != ["RESEARCH"]:
        errors.append("PROPOSER_HOLDOUT_ACCESS")
    if vault.get("final_holdout_one_shot") is not True:
        errors.append("FINAL_HOLDOUT_NOT_ONE_SHOT")
    roles = layers.get("role_separation", {})
    for key in ("proposer_must_differ_from_evaluator", "evaluator_must_differ_from_judge", "single_ai_self_approval_forbidden"):
        if roles.get(key) is not True:
            errors.append(f"ROLE_{key.upper()}")
    budget = layers.get("proposal_budget_and_multiple_testing", {})
    if int(budget.get("max_changed_axes_per_proposal", 0)) != 1:
        errors.append("MULTI_AXIS_PROPOSAL_ALLOWED")
    if int(budget.get("minimum_closed_sample", 0)) < 30:
        errors.append("MIN_SAMPLE_TOO_LOW")
    scenarios = adversarial.get("scenarios", [])
    if len(scenarios) < 15:
        errors.append("ADVERSARIAL_COVERAGE_LOW")
    expected_safety = {
        "canonical_strategy_mutation": False,
        "formal_ledger_mutation": False,
        "runtime_registry_write": False,
        "shadow_start_allowed": False,
        "paper_start_allowed": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    for key, expected in expected_safety.items():
        if safety.get(key) != expected:
            errors.append(f"UNSAFE_{key.upper()}")
    return errors


def validate_proposal(row: Mapping[str, Any], required: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for field in required:
        if row.get(field) in (None, ""):
            errors.append(f"MISSING_{field.upper()}")
    for field in ("prompt_sha256", "context_sha256", "source_data_sha256", "parent_variant_sha256", "candidate_sha256"):
        if row.get(field) and not SHA_RE.fullmatch(str(row[field])):
            errors.append(f"INVALID_{field.upper()}")
    changed_axis = row.get("changed_axis")
    if isinstance(changed_axis, list) and len(changed_axis) != 1:
        errors.append("CHANGED_AXIS_COUNT")
    elif not isinstance(changed_axis, (str, list)):
        errors.append("CHANGED_AXIS_TYPE")
    if row.get("role") in ("EVALUATOR", "JUDGE"):
        errors.append("NON_PROPOSER_ROLE_REGISTERED")
    if not row.get("duplicate_group_id"):
        errors.append("DUPLICATE_GROUP_ID_MISSING")
    return errors


def adjusted_score(raw_score: float, trial_count: int, sample_count: int) -> float:
    penalty = 0.25 * math.sqrt(math.log1p(max(trial_count, 0)) / max(sample_count, 1))
    return raw_score - penalty


def ai_value_score(row: Mapping[str, Any]) -> float:
    return (
        2.0 * float(row.get("w3_pass", 0))
        + float(row.get("w2_pass", 0))
        + max(float(row.get("net_r_delta", 0)), 0.0)
        + max(float(row.get("dd_improvement_r", 0)), 0.0)
        - float(row.get("duplicate_rate", 0))
        - 2.0 * float(row.get("rollback_rate", 0))
        - min(float(row.get("cost_usd", 0)) / 100.0, 1.0)
    )


def evaluate(policy: Mapping[str, Any], adversarial: Mapping[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    policy_errors = validate_policy(policy, adversarial)
    required = policy["layers"]["model_prompt_lineage"]["required_fields"]
    budget = policy["layers"]["proposal_budget_and_multiple_testing"]
    row_results: list[dict[str, Any]] = []
    epoch_counts = Counter(str(p.get("epoch_id")) for p in proposals)
    parent_counts = Counter((str(p.get("epoch_id")), str(p.get("parent_variant_sha256"))) for p in proposals)
    model_counts = Counter((str(p.get("epoch_id")), str(p.get("provider")), str(p.get("model"))) for p in proposals)
    duplicate_counts = Counter((str(p.get("epoch_id")), str(p.get("duplicate_group_id"))) for p in proposals)

    for p in proposals:
        errors = validate_proposal(p, required)
        epoch = str(p.get("epoch_id"))
        parent = str(p.get("parent_variant_sha256"))
        model_key = (epoch, str(p.get("provider")), str(p.get("model")))
        if epoch_counts[epoch] > int(budget["max_proposals_per_epoch"]):
            errors.append("EPOCH_BUDGET_EXCEEDED")
        if parent_counts[(epoch, parent)] > int(budget["max_proposals_per_parent"]):
            errors.append("PARENT_BUDGET_EXCEEDED")
        if model_counts[model_key] > int(budget["max_proposals_per_model_per_epoch"]):
            errors.append("MODEL_BUDGET_EXCEEDED")
        if duplicate_counts[(epoch, str(p.get("duplicate_group_id")))] > 1:
            errors.append("DUPLICATE_CANDIDATE")
        raw = float(p.get("raw_score", 0.0))
        trials = int(p.get("trial_count", epoch_counts[epoch]))
        sample = int(p.get("sample_count", 0))
        if sample < int(budget["minimum_closed_sample"]):
            errors.append("LOW_SAMPLE")
        row_results.append({
            "proposal_id": p.get("proposal_id"),
            "pass": not errors,
            "errors": sorted(set(errors)),
            "raw_score": raw,
            "adjusted_score": adjusted_score(raw, trials, sample),
            "candidate_sha256": p.get("candidate_sha256"),
        })

    scoreboard_rows: list[dict[str, Any]] = []
    by_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in proposals:
        by_model[(str(p.get("provider")), str(p.get("model")))].append(p)
    for (provider, model), rows in sorted(by_model.items()):
        count = len(rows)
        scoreboard_rows.append({
            "provider": provider,
            "model": model,
            "proposal_count": count,
            "compile_pass_rate": sum(float(r.get("compile_pass", 0)) for r in rows) / max(count, 1),
            "material_signal_repair_rate": sum(float(r.get("material_signal_repair", 0)) for r in rows) / max(count, 1),
            "w2_pass_rate": sum(float(r.get("w2_pass", 0)) for r in rows) / max(count, 1),
            "w3_pass_rate": sum(float(r.get("w3_pass", 0)) for r in rows) / max(count, 1),
            "value_score": sum(ai_value_score(r) for r in rows) / max(count, 1),
            "automatic_weight_change_allowed": False,
        })

    passed = not policy_errors and all(row["pass"] for row in row_results)
    return {
        "schema_version": "zel.ai.research_control_plane.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_AI_RESEARCH_CONTROL_PLANE" if passed else "HOLD_AI_RESEARCH_CONTROL_PLANE",
        "policy_sha256": canonical_sha(policy),
        "adversarial_manifest_sha256": canonical_sha(adversarial),
        "policy_errors": policy_errors,
        "proposal_count": len(proposals),
        "proposal_results": row_results,
        "ai_scoreboard": scoreboard_rows,
        "blind_holdout_access_granted": False,
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold"
    }


def self_test() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = load_json(root / "research/zel_ai_research_control_plane_v1.json")
    adversarial = load_json(root / "research/zel_adversarial_market_lab_v1.json")
    sha = "a" * 64
    proposal = {
        "proposal_id": "p1", "epoch_id": "e1", "role": "EXPLORER", "actor_id": "ai-a",
        "provider": "test", "model": "m1", "prompt_sha256": sha, "context_sha256": sha,
        "source_data_sha256": sha, "parent_variant_sha256": sha, "candidate_sha256": "b" * 64,
        "changed_axis": "entry_filter", "hypothesis": "reduce false positives",
        "expected_failure_mode": "lower sample", "created_at": now_iso(), "duplicate_group_id": "g1",
        "raw_score": 1.0, "trial_count": 1, "sample_count": 50, "compile_pass": 1,
        "material_signal_repair": 1, "w2_pass": 0, "w3_pass": 0, "net_r_delta": 0.2,
        "dd_improvement_r": 0.1, "duplicate_rate": 0, "rollback_rate": 0, "cost_usd": 0.1
    }
    result = evaluate(policy, adversarial, [proposal])
    assert result["state"] == "PASS_AI_RESEARCH_CONTROL_PLANE", result
    bad = dict(proposal)
    bad["proposal_id"] = "p2"
    bad["candidate_sha256"] = "not-sha"
    bad["duplicate_group_id"] = "g1"
    hold = evaluate(policy, adversarial, [proposal, bad])
    assert hold["state"] == "HOLD_AI_RESEARCH_CONTROL_PLANE", hold
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "receipt.json"
        path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        assert json.loads(path.read_text())["runtime_mutated"] is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--adversarial", type=Path)
    parser.add_argument("--proposals", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.policy, args.adversarial, args.proposals, args.out)):
        parser.error("policy, adversarial, proposals and out are required")
    policy = load_json(args.policy)
    adversarial = load_json(args.adversarial)
    raw = json.loads(args.proposals.read_text(encoding="utf-8"))
    proposals = raw if isinstance(raw, list) else raw.get("proposals", [])
    result = evaluate(policy, adversarial, proposals)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "proposal_count": len(proposals)}, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
