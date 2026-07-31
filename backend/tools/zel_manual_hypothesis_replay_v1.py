from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import zel_component_autonomy_v2 as core

VERSION = "ZEL_MANUAL_HYPOTHESIS_REPLAY_V1"
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
}


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n")


def provider_decisions(review: Mapping[str, Any] | None) -> tuple[str, str, bool]:
    if not review:
        return "MISSING", "MISSING", False
    providers = review.get("provider_results") or {}

    def decision(name: str) -> str:
        return str((((providers.get(name) or {}).get("artifact") or {}).get("review") or {}).get("decision") or "MISSING")

    groq, workers = decision("groq"), decision("workers_ai")
    joint = review.get("status") == "PASS_AI_REVIEW_ROUTER" and groq == "PASS_TO_REPLAY" and workers == "PASS_TO_REPLAY"
    return groq, workers, joint


def strategy_filter(rows: Sequence[Mapping[str, Any]], parameter: str, value: Any) -> list[dict[str, Any]]:
    result = []
    for original in rows:
        row = deepcopy(original)
        keep = {
            "minimum_trend_score": core.number(row["scores"]["trend_score"]) >= core.number(value),
            "minimum_confirm_score": core.number(row["scores"]["confirm_score"]) >= core.number(value),
            "minimum_volume_z": core.number(row.get("volume_z"), -9.0) >= core.number(value),
            "maximum_atr_pct": core.number(row.get("atr_pct")) <= core.number(value),
            "long_beam_required": (not bool(value)) or bool(row.get("beam")),
        }.get(parameter)
        if keep is None:
            raise ValueError(f"STRATEGY_PARAMETER_UNSUPPORTED:{parameter}")
        if keep:
            result.append(row)
    return result


def current_team_rows(rows: Sequence[Mapping[str, Any]], result: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    modules = result["module_results"]
    return core.apply_team(rows, modules["teams"]["best"], policy, modules["bots"]["best_by_role"])


def current_team_skill_rows(rows: Sequence[Mapping[str, Any]], result: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (result.get("pipeline_decisions") or {}).get("TEAM", {}).get("applied"):
        team_rows = current_team_rows(rows, result, policy)
    else:
        team_rows = [deepcopy(row) for row in rows]
    skill = result["module_results"]["skills"]["best"]["skill_id"]
    if (result.get("pipeline_decisions") or {}).get("SKILL", {}).get("applied"):
        transformed, _ = core.transform_skill(team_rows, skill)
        return transformed
    return team_rows


def replay_value(axis: str, target: str, parameter: str, value: Any, rows: Sequence[Mapping[str, Any]], result: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    modules = result["module_results"]
    if axis == "STRATEGY_ENTRY":
        return [deepcopy(row) for row in rows], strategy_filter(rows, parameter, value), {"fidelity": "EXACT_LEDGER_SUBSET_OVERLAY_NO_SOURCE_MUTATION"}
    if axis == "BOT_POLICY":
        profiles = deepcopy(modules["bots"]["best_by_role"])
        if target not in profiles or parameter not in {"threshold", "weight", "warning_cap"}:
            raise ValueError("BOT_HYPOTHESIS_INVALID")
        baseline = current_team_rows(rows, result, policy)
        profiles[target][parameter] = value
        candidate = core.apply_team(rows, modules["teams"]["best"], policy, profiles)
        return baseline, candidate, {"fidelity": "EXACT_LEDGER_TEAM_REPLAY_WITH_SINGLE_BOT_OVERRIDE", "target_role": target}
    if axis == "TEAM_POLICY":
        if parameter not in {"support_threshold", "watcher_confirmation_threshold", "watcher_veto_threshold"}:
            raise ValueError("TEAM_HYPOTHESIS_INVALID")
        profiles = modules["bots"]["best_by_role"]
        best = deepcopy(modules["teams"]["best"])
        baseline = core.apply_team(rows, best, policy, profiles)
        best[parameter] = value
        candidate = core.apply_team(rows, best, policy, profiles)
        return baseline, candidate, {"fidelity": "EXACT_LEDGER_TEAM_THRESHOLD_REPLAY"}
    if axis == "SKILL_PROFILE":
        if parameter != "skill_id":
            raise ValueError("SKILL_PARAMETER_MUST_BE_SKILL_ID")
        base_rows = current_team_rows(rows, result, policy) if (result.get("pipeline_decisions") or {}).get("TEAM", {}).get("applied") else [deepcopy(row) for row in rows]
        current_skill = modules["skills"]["best"]["skill_id"]
        baseline, current_meta = core.transform_skill(base_rows, current_skill)
        candidate, meta = core.transform_skill(base_rows, str(value))
        return baseline, candidate, {"fidelity": meta["fidelity"], "selection_eligible": meta["selection_eligible"], "current_fidelity": current_meta["fidelity"]}
    if axis == "ZBOT_PROFILE":
        if target != "ZBot" or parameter != "disagreement_threshold":
            raise ValueError("ZBOT_HYPOTHESIS_INVALID")
        base_rows = current_team_skill_rows(rows, result, policy)
        current = core.number(modules["advisors"]["ZBOT"]["best"]["profile"]["disagreement_threshold"])

        def apply(threshold: float) -> list[dict[str, Any]]:
            return [deepcopy(row) for row in base_rows if abs(core.number(row["scores"]["trend_score"]) - core.number(row["scores"]["confirm_score"])) <= threshold]

        return apply(current), apply(core.number(value)), {"fidelity": "EXACT_LEDGER_ZBOT_DISAGREEMENT_FILTER"}
    raise ValueError(f"AXIS_UNSUPPORTED:{axis}")


def evaluate(hypothesis: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], result: Mapping[str, Any], policy: Mapping[str, Any], review: Mapping[str, Any] | None) -> dict[str, Any]:
    groq, workers, joint = provider_decisions(review)
    axis = str(hypothesis["axis"])
    target = str(hypothesis["target"])
    parameter = str(hypothesis["parameter"])
    candidates = []
    for value in hypothesis["values"]:
        before_rows, after_rows, meta = replay_value(axis, target, parameter, value, rows, result, policy)
        before, after = core.stats(before_rows), core.stats(after_rows)
        ev = core.evidence(after, before, policy)
        candidates.append({
            "value": value,
            "before": before,
            "after": after,
            "evidence": ev,
            "delta_net_pct_points": core.number(after["net_return_pct_sum"]) - core.number(before["net_return_pct_sum"]),
            "fidelity": meta,
        })
    best = max(candidates, key=lambda row: (1 if row["evidence"]["material"] else 0, row["delta_net_pct_points"], row["after"]["profit_factor"], -row["after"]["max_drawdown_pct"], row["after"]["trade_count"]))
    control_count = int(((result.get("control") or {}).get("stats") or {}).get("trade_count") or 0)
    synthetic = str((best.get("fidelity") or {}).get("fidelity")) in {"EVENT_LEVEL_COUNTERFACTUAL", "OBSERVER_ONLY_LOSS_DIRECTION_ADD"}
    return {
        "hypothesis_id": hypothesis["hypothesis_id"],
        "axis": axis,
        "target": target,
        "parameter": parameter,
        "video_source_indexes": hypothesis.get("video_source_indexes", []),
        "groq_decision": groq,
        "workers_decision": workers,
        "joint_ai_approval": joint,
        "exploratory_replay_completed": True,
        "accepted_replay": bool(joint),
        "candidates": candidates,
        "best": best,
        "improvement_observed": bool(best["evidence"]["material"]),
        "performance_claim_allowed": control_count >= int((policy.get("claim_policy") or {}).get("hypothesis_review_min_trades", 20)) and not synthetic,
        "exact_skill_replay_required": axis == "SKILL_PROFILE" and synthetic,
        "source_file_mutated": False,
        "promotion_allowed": False,
    }


def run(policy: Mapping[str, Any], ledger: Mapping[str, Any], summary: Mapping[str, Any], result: Mapping[str, Any], gemini_artifact: Mapping[str, Any], reviews_dir: Path, out: Path) -> dict[str, Any]:
    rows = core.load_events(ledger, summary)
    review_index = {path.stem: read_json(path) for path in reviews_dir.glob("*.json")}
    evaluations = []
    for path in sorted((reviews_dir.parent / "hypotheses").glob("*.json")):
        hypothesis = read_json(path)["hypothesis"]
        matching = next((row for key, row in review_index.items() if hypothesis["hypothesis_id"] in key), None)
        evaluations.append(evaluate(hypothesis, rows, result, policy, matching))
    observed = [row for row in evaluations if row["improvement_observed"]]
    accepted = [row for row in observed if row["joint_ai_approval"]]
    state = "HOLD_LOW_SAMPLE_MANUAL_IMPROVEMENTS_OBSERVED" if observed else "HOLD_NO_MANUAL_IMPROVEMENT"
    if accepted:
        state = "HOLD_AI_APPROVED_REPLAY_CANDIDATE_LOW_SAMPLE"
    report = {
        "schema_version": "zel.manual_hypothesis_replay.v1",
        "version": VERSION,
        "state": state,
        "strategy_id": result.get("strategy_id"),
        "underlying_data_fingerprint": result.get("data_fingerprint"),
        "research_fingerprint": gemini_artifact.get("research_fingerprint"),
        "same_evidence_reanalysis": True,
        "trade_count": len(rows),
        "hypothesis_count": len(evaluations),
        "improvement_observed_count": len(observed),
        "joint_ai_approved_improvement_count": len(accepted),
        "evaluations": evaluations,
        "strategy_file_mechanism_tested": any(row["axis"] == "STRATEGY_ENTRY" for row in evaluations),
        "team_bot_mechanism_tested": any(row["axis"] in {"BOT_POLICY", "TEAM_POLICY"} for row in evaluations),
        "skill_mechanism_tested": any(row["axis"] == "SKILL_PROFILE" for row in evaluations),
        "zbot_mechanism_tested": any(row["axis"] == "ZBOT_PROFILE" for row in evaluations),
        "source_file_mutated": False,
        "new_market_data_claim": False,
        "performance_claim_allowed": False,
        "next": "WAIT_NEW_EXACT_LEDGER_MIN_20_AND_EXACT_SKILL_REPLAY",
        **SAFE,
    }
    write_json(out / "report.json", report)
    return report


def fixture(out: Path) -> None:
    write_json(out / "fixture.json", {"state": "PASS_MANUAL_HYPOTHESIS_REPLAY_FIXTURE", **SAFE})


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fx = sub.add_parser("fixture")
    fx.add_argument("--out", type=Path, required=True)
    rp = sub.add_parser("run")
    for name in ("policy", "ledger", "summary", "result", "gemini_artifact"):
        rp.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)
    rp.add_argument("--reviews-dir", type=Path, required=True)
    rp.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "fixture":
        fixture(args.out)
        print("PASS_MANUAL_HYPOTHESIS_REPLAY_FIXTURE")
        return 0
    report = run(read_json(args.policy), read_json(args.ledger), read_json(args.summary), read_json(args.result), read_json(args.gemini_artifact), args.reviews_dir, args.out)
    print(report["state"], report["hypothesis_count"], report["improvement_observed_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
