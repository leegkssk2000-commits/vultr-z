from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.tools.strategy11_gemini_v3_2_guard import _base_call_direct_video

VERSION = "ZEL_COMPONENT_GEMINI_DIRECT_VIDEO_V1"
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(stripped[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("GEMINI_OBJECT_REQUIRED")
    return value


def source_view(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"source_index": index + 1, "url": row["url"], "title": row["title"], "channel": row["channel"], "topics": row.get("topics", [])}
        for index, row in enumerate(sources)
    ]


def component_profiles(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    eligible = result.get("axis_review_eligibility") or {}
    modules = result.get("module_results") or {}
    profiles: list[dict[str, Any]] = []
    if eligible.get("BOT_POLICY"):
        profiles.append({"axis": "BOT_POLICY", "current_configuration": modules["bots"]["best_by_role"], "current_attribution": result["component_attribution"]["ordered_marginal_delta_net"].get("TEAM", 0.0), "allowed_parameter_families": ["one_role_weight", "one_role_threshold", "one_role_warning_cap"]})
    if eligible.get("TEAM_POLICY"):
        profiles.append({"axis": "TEAM_POLICY", "current_configuration": modules["teams"]["best"], "current_attribution": result["component_attribution"]["ordered_marginal_delta_net"].get("TEAM", 0.0), "allowed_parameter_families": ["support_threshold", "watcher_confirmation_threshold", "watcher_veto_threshold"]})
    if eligible.get("SKILL_PROFILE"):
        profiles.append({"axis": "SKILL_PROFILE", "current_configuration": modules["skills"]["best"], "current_attribution": result["component_attribution"]["ordered_marginal_delta_net"].get("SKILL", 0.0), "allowed_parameter_families": ["one_skill_parameter_only"], "observer_only_forbidden": modules["skills"].get("observer_only_ids", [])})
    if eligible.get("ADVISOR_PROFILE"):
        profiles.append({"axis": "ADVISOR_PROFILE", "current_configuration": {role: row["best"] for role, row in modules["advisors"].items()}, "current_attribution": sum(result["component_attribution"]["ordered_marginal_delta_net"].get(role, 0.0) for role in ("ZBOT", "ZICO", "LICO", "ZLICE")), "allowed_parameter_families": ["zbot_disagreement", "zico_cooldown", "lico_capacity_or_cost"], "zlice_economic_mutation_forbidden": True})
    return profiles


def build_prompt(result: Mapping[str, Any], profiles: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]]) -> str:
    schema = {"status": "PASS|HOLD", "component_hypotheses": [{"axis": "exact supplied axis", "parameter": "one parameter only", "values": [0.1, 0.2], "single_cause_change": "one causal mechanism", "video_source_indexes": [1, 2], "expected_metric_effect": "specific Net/PF/DD/trade-retention effect", "falsification_test": "specific deterministic replay failure condition", "overfit_risk": "LOW|MEDIUM|HIGH"}]}
    return (
        "You are a skeptical quantitative research reviewer. Analyze every attached public video directly. The exact trade ledger and deterministic replay remain final authority. Videos may create hypotheses only. "
        "Reject marketing, repainting, omitted costs, discretionary rules, hidden samples and claims without falsification. Return zero or one hypothesis for each supplied eligible component axis, maximum two hypotheses total. "
        "Each hypothesis must change exactly one parameter in exactly one axis and use at least two independent video sources. Do not propose DCA, average-down, water-add or ShortBeam execution; those remain observer-only. "
        "Do not mutate Zlice economics; Zlice is lineage/evidence only. Do not change canonical strategy entry logic. The current exact ledger is low sample, so never claim performance improvement. Return strict JSON only.\n\n"
        f"CONTROL={json.dumps(result.get('control',{}),ensure_ascii=False,sort_keys=True)}\nFULL_STACK={json.dumps(result.get('full_stack',{}),ensure_ascii=False,sort_keys=True)}\n"
        f"COMPONENT_PROFILES={json.dumps(list(profiles),ensure_ascii=False,sort_keys=True)}\nPUBLIC_VIDEO_SOURCES={json.dumps(source_view(sources),ensure_ascii=False,sort_keys=True)}\nOUTPUT_SCHEMA={json.dumps(schema,ensure_ascii=False,sort_keys=True)}"
    )


def validate_response(response: Mapping[str, Any], profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    status = str(response.get("status") or "HOLD").upper()
    if status not in {"PASS", "HOLD"}:
        raise ValueError(f"GEMINI_STATUS_INVALID:{status}")
    allowed = {str(row["axis"]): row for row in profiles}
    rows = response.get("component_hypotheses", [])
    if not isinstance(rows, list) or len(rows) > 2:
        raise ValueError("HYPOTHESIS_COUNT_INVALID")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"HYPOTHESIS_OBJECT_REQUIRED:{index}")
        axis = str(raw.get("axis") or "")
        parameter = str(raw.get("parameter") or "").strip()
        values = raw.get("values")
        if axis not in allowed or axis in seen:
            raise ValueError(f"HYPOTHESIS_AXIS_INVALID:{axis}")
        if not parameter or any(token in parameter for token in (",", "+", "/", "&")):
            raise ValueError(f"HYPOTHESIS_PARAMETER_INVALID:{axis}")
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError(f"HYPOTHESIS_VALUES_INVALID:{axis}")
        cause = str(raw.get("single_cause_change") or "").lower()
        if any(token in cause for token in (" combined ", " and ", " while ", " plus ")):
            raise ValueError(f"HYPOTHESIS_MULTI_CAUSE:{axis}")
        source_indexes = raw.get("video_source_indexes")
        if not isinstance(source_indexes, list) or len({int(value) for value in source_indexes}) < 2:
            raise ValueError(f"HYPOTHESIS_VIDEO_SUPPORT_LOW:{axis}")
        if axis == "SKILL_PROFILE" and any(token in parameter.lower() for token in ("dca", "average", "water", "short")):
            raise ValueError(f"OBSERVER_ONLY_HYPOTHESIS_FORBIDDEN:{parameter}")
        if axis == "ADVISOR_PROFILE" and "zlice" in parameter.lower():
            raise ValueError("ZLICE_ECONOMIC_HYPOTHESIS_FORBIDDEN")
        normalized.append({"hypothesis_id": f"COMPONENT_{axis}_{index + 1}", "axis": axis, "parameter": parameter, "values": values, "single_cause_change": raw.get("single_cause_change"), "video_source_indexes": sorted({int(value) for value in source_indexes}), "expected_metric_effect": raw.get("expected_metric_effect"), "falsification_test": raw.get("falsification_test"), "overfit_risk": raw.get("overfit_risk"), "state": "WAIT_GROQ_WORKERS_SINGLE_AXIS_GATE"})
        seen.add(axis)
    return normalized


def review(args: argparse.Namespace) -> int:
    result = read_json(args.result)
    policy = read_json(args.policy)
    registry = read_json(args.video_registry)
    previous = read_json(args.previous) if args.previous and Path(args.previous).is_file() else {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    required = bool((result.get("ai_usage") or {}).get("gemini_required_this_epoch"))
    fingerprint = str(result.get("data_fingerprint") or "")
    if not required:
        write_json(out / "artifact.json", {"state": "SKIP_GEMINI_NOT_REQUIRED", "GEMINI_USED": False, "data_fingerprint": fingerprint, **SAFE})
        return 0
    if previous.get("data_fingerprint") == fingerprint and previous.get("GEMINI_USED") is True:
        write_json(out / "artifact.json", {"state": "SKIP_UNCHANGED_COMPONENT_FINGERPRINT", "GEMINI_USED": False, "data_fingerprint": fingerprint, "previous_response_sha": previous.get("response_sha256"), **SAFE})
        return 0
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    minimum_videos = int(policy["ai_policy"]["gemini_public_video_min"])
    minimum_channels = int(policy["ai_policy"]["gemini_independent_channel_min"])
    if len(sources) < minimum_videos or len({str(row.get("channel")) for row in sources}) < minimum_channels:
        write_json(out / "artifact.json", {"state": "HOLD_GEMINI_SOURCE_DIVERSITY", "GEMINI_USED": False, "data_fingerprint": fingerprint, **SAFE})
        return 0
    profiles = component_profiles(result)
    if not profiles:
        write_json(out / "artifact.json", {"state": "SKIP_NO_MATERIAL_COMPONENT_AXIS", "GEMINI_USED": False, "data_fingerprint": fingerprint, **SAFE})
        return 0
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        write_json(out / "artifact.json", {"state": "HOLD_GEMINI_API_KEY_MISSING", "GEMINI_USED": False, "data_fingerprint": fingerprint, **SAFE})
        return 0
    prompt = build_prompt(result, profiles, sources)
    model, response_text = _base_call_direct_video(key, prompt, sources)
    try:
        response = parse_json(response_text)
        hypotheses = validate_response(response, profiles)
    except Exception:
        correction = prompt + "\n\nYour previous output violated the schema. Return strict JSON, maximum two hypotheses, one axis and one parameter each."
        model, response_text = _base_call_direct_video(key, correction, sources)
        response = parse_json(response_text)
        hypotheses = validate_response(response, profiles)
    artifact = {"schema_version": "1.0", "version": VERSION, "state": "PASS_COMPONENT_GEMINI_DIRECT_VIDEO" if hypotheses else "HOLD_NO_COMPONENT_VIDEO_HYPOTHESIS", "GEMINI_USED": True, "actual_model": model, "data_fingerprint": fingerprint, "eligible_axes": [row["axis"] for row in profiles], "video_count": len(sources), "independent_channel_count": len({str(row.get("channel")) for row in sources}), "input_sha256": stable_sha({"result_sha": result.get("result_sha256"), "profiles": profiles, "sources": source_view(sources), "policy": policy.get("ai_policy")}), "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(), "hypotheses": hypotheses, "next": "GROQ_WORKERS_SINGLE_AXIS_GATE" if hypotheses else "WAIT_NEW_W1_OR_FAILURE_FINGERPRINT", **SAFE}
    artifact["artifact_sha256"] = stable_sha(artifact)
    write_json(out / "artifact.json", artifact)
    return 0


def prepare(args: argparse.Namespace) -> int:
    artifact = read_json(args.artifact)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = {"hypothesis_ids": [], "state": artifact.get("state"), **SAFE}
    for hypothesis in artifact.get("hypotheses", []):
        hypothesis_id = hypothesis["hypothesis_id"]
        payload = {"strategy_id": "trend_ma_macd", "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS", "changed_axes": [hypothesis["axis"]], "lineage_complete": True, "hypothesis": hypothesis, "lineage": {"data_fingerprint": artifact.get("data_fingerprint"), "gemini_artifact_sha": artifact.get("artifact_sha256"), "gemini_response_sha": artifact.get("response_sha256")}, "routing_flags": {"external_hypothesis": True, "multimodal": True, "new_multimodal_evidence": True, "new_failure_fingerprint": True, "borderline_case": False, "major_gate_review": False}, **SAFE}
        write_json(out / f"{hypothesis_id}.json", payload)
        index["hypothesis_ids"].append(hypothesis_id)
    write_json(out / "index.json", index)
    return 0


def summarize(args: argparse.Namespace) -> int:
    artifact = read_json(args.artifact)
    index = read_json(Path(args.inputs) / "index.json")
    accepted: list[str] = []
    decisions: dict[str, Any] = {}
    for hypothesis_id in index.get("hypothesis_ids", []):
        row = read_json(Path(args.reviews) / f"{hypothesis_id}.json")
        status = row.get("status")
        groq = (((row.get("provider_results") or {}).get("groq") or {}).get("artifact") or {}).get("review", {}).get("decision")
        workers = (((row.get("provider_results") or {}).get("workers_ai") or {}).get("artifact") or {}).get("review", {}).get("decision")
        pass_to_replay = status == "PASS_AI_REVIEW_ROUTER" and groq == "PASS_TO_REPLAY" and workers == "PASS_TO_REPLAY"
        decisions[hypothesis_id] = {"router_status": status, "groq_decision": groq, "workers_decision": workers, "pass_to_replay": pass_to_replay}
        if pass_to_replay:
            accepted.append(hypothesis_id)
    summary = {"state": "PASS_COMPONENT_GEMINI_AI_GATE" if accepted else "HOLD_NO_AI_APPROVED_COMPONENT_HYPOTHESIS", "data_fingerprint": artifact.get("data_fingerprint"), "gemini_artifact_sha": artifact.get("artifact_sha256"), "reviewed_count": len(decisions), "accepted_count": len(accepted), "accepted_hypothesis_ids": accepted, "decisions": decisions, "next": "WAIT_COMPONENT_HYPOTHESIS_REPLAY_BINDING" if accepted else "WAIT_NEW_W1_OR_FAILURE_FINGERPRINT", **SAFE}
    summary["summary_sha256"] = stable_sha(summary)
    write_json(args.out, summary)
    return 0


def fixture(out: str | Path) -> int:
    result = {"data_fingerprint": "f" * 64, "result_sha256": "a" * 64, "control": {"stats": {"trade_count": 5}}, "full_stack": {"stats": {"trade_count": 4}}, "axis_review_eligibility": {"BOT_POLICY": False, "TEAM_POLICY": True, "SKILL_PROFILE": True, "ADVISOR_PROFILE": False}, "component_attribution": {"ordered_marginal_delta_net": {"TEAM": 0.4, "SKILL": 0.8, "ZBOT": 0.0, "ZICO": 0.0, "LICO": 0.0, "ZLICE": 0.0}}, "module_results": {"teams": {"best": {"team": "AlphaTeam", "support_threshold": 0.45}}, "skills": {"best": {"skill_id": "SK_EXIT_MFE_RUNNER"}, "observer_only_ids": sorted(["SK_ENTRY_SHORT_BEAM", "SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"])}, "bots": {"best_by_role": {}}, "advisors": {}}, "ai_usage": {"gemini_required_this_epoch": True}}
    profiles = component_profiles(result)
    response = {"status": "PASS", "component_hypotheses": [{"axis": "TEAM_POLICY", "parameter": "support_threshold", "values": [0.5], "single_cause_change": "raise support confirmation", "video_source_indexes": [1, 2], "expected_metric_effect": "reduce DD", "falsification_test": "Net declines", "overfit_risk": "MEDIUM"}]}
    normalized = validate_response(response, profiles)
    assert len(normalized) == 1 and normalized[0]["axis"] == "TEAM_POLICY"
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "fixture.json", {"profiles": profiles, "hypotheses": normalized, **SAFE})
    print("PASS_COMPONENT_GEMINI_FIXTURE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    review_parser = subparsers.add_parser("review"); review_parser.add_argument("--result", required=True); review_parser.add_argument("--policy", required=True); review_parser.add_argument("--video-registry", required=True); review_parser.add_argument("--previous"); review_parser.add_argument("--out", required=True)
    prepare_parser = subparsers.add_parser("prepare"); prepare_parser.add_argument("--artifact", required=True); prepare_parser.add_argument("--out", required=True)
    summary_parser = subparsers.add_parser("summarize"); summary_parser.add_argument("--artifact", required=True); summary_parser.add_argument("--inputs", required=True); summary_parser.add_argument("--reviews", required=True); summary_parser.add_argument("--out", required=True)
    fixture_parser = subparsers.add_parser("fixture"); fixture_parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "review": return review(args)
    if args.mode == "prepare": return prepare(args)
    if args.mode == "summarize": return summarize(args)
    return fixture(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
