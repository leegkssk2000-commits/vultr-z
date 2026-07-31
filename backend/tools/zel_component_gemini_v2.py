from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import strategy11_gemini_v3_2 as gemini

VERSION = "ZEL_COMPONENT_GEMINI_DIRECT_VIDEO_V2"
AXES = {"BOT_POLICY", "TEAM_POLICY", "SKILL_PROFILE", "ADVISOR_PROFILE"}
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
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
        raise ValueError("GEMINI_JSON_OBJECT_REQUIRED")
    return value


def source_view(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_index": index + 1,
            "url": row["url"],
            "title": row.get("title"),
            "channel": row.get("channel"),
            "topics": row.get("topics", []),
        }
        for index, row in enumerate(sources)
    ]


def component_view(result: Mapping[str, Any]) -> dict[str, Any]:
    modules = result.get("module_results") or {}
    return {
        "strategy_id": result.get("strategy_id"),
        "state": result.get("state"),
        "low_sample_hold": (result.get("convergence") or {}).get("low_sample_hold"),
        "control": (result.get("control") or {}).get("stats"),
        "full_stack": result.get("full_stack"),
        "pipeline_decisions": result.get("pipeline_decisions"),
        "attribution": result.get("component_attribution"),
        "axis_review_eligibility": result.get("axis_review_eligibility"),
        "bot_profiles": (modules.get("bots") or {}).get("best_by_role"),
        "team": (modules.get("teams") or {}).get("best"),
        "skill": (modules.get("skills") or {}).get("best"),
        "advisors": {
            role: ((modules.get("advisors") or {}).get(role) or {}).get("best")
            for role in ("ZBOT", "ZICO", "LICO", "ZLICE")
        },
    }


def prompt(result: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "component_reviews": [
            {
                "axis": "BOT_POLICY|TEAM_POLICY|SKILL_PROFILE|ADVISOR_PROFILE",
                "verdict": "PROPOSE_HYPOTHESIS|NO_ACTION",
                "hypothesis_id": "unique id or null",
                "parameter": "one exact parameter or null",
                "values": [1, 2],
                "causal_reason": "one mechanism",
                "video_source_indexes": [1, 2],
                "falsification_test": "specific deterministic replay test",
                "overfit_risk": "LOW|MEDIUM|HIGH",
            }
        ],
    }
    return (
        "You are a skeptical quantitative trading systems reviewer. Analyze every attached public YouTube video directly and compare it with the anonymized component-pipeline evidence. "
        "The pipeline is research-only and has no order authority. Videos create hypotheses only. Reject repainting, omitted fees, hidden samples, discretionary rules, unverifiable claims, and parameter combinations. "
        "Review BOT_POLICY, TEAM_POLICY, SKILL_PROFILE, and ADVISOR_PROFILE exactly once each. Return one row per axis. "
        "For each axis, propose at most two hypotheses. Every proposed hypothesis must change exactly one parameter with one bounded list of one to four values. "
        "Do not combine bot and team changes, entry and exit changes, partial and trailing, cost and latency, or any two mechanisms. "
        "Use at least two independent video source indexes for each proposed hypothesis. Low-sample evidence may generate a hypothesis but can never authorize replay promotion or a performance claim. "
        "Return strict JSON only.\n\n"
        f"PUBLIC_VIDEO_SOURCES={json.dumps(source_view(sources), ensure_ascii=False, sort_keys=True)}\n"
        f"COMPONENT_PIPELINE_EVIDENCE={json.dumps(component_view(result), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def normalize_response(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = response.get("component_reviews")
    if not isinstance(rows, list):
        raise ValueError("COMPONENT_REVIEWS_REQUIRED")
    grouped: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"COMPONENT_REVIEW_OBJECT_REQUIRED:{index}")
        axis = str(raw.get("axis") or "").strip().upper()
        if axis not in AXES:
            raise ValueError(f"COMPONENT_AXIS_INVALID:{axis}")
        verdict = str(raw.get("verdict") or "NO_ACTION").strip().upper()
        if verdict not in {"PROPOSE_HYPOTHESIS", "NO_ACTION"}:
            raise ValueError(f"COMPONENT_VERDICT_INVALID:{axis}:{verdict}")
        grouped[axis] += 1
        if grouped[axis] > 2:
            raise ValueError(f"COMPONENT_HYPOTHESIS_LIMIT:{axis}:{grouped[axis]}")
        if verdict == "NO_ACTION":
            normalized.append({
                "axis": axis,
                "verdict": verdict,
                "hypothesis_id": None,
                "parameter": None,
                "values": [],
                "causal_reason": raw.get("causal_reason"),
                "video_source_indexes": [],
                "falsification_test": raw.get("falsification_test"),
                "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
            })
            continue
        hypothesis_id = str(raw.get("hypothesis_id") or f"GEMINI_{axis}_{grouped[axis]}").strip()
        parameter = str(raw.get("parameter") or "").strip()
        values = raw.get("values")
        cause = str(raw.get("causal_reason") or "").strip()
        video_indexes = raw.get("video_source_indexes")
        if not parameter or any(token in parameter for token in (",", "+", "/", "&")):
            raise ValueError(f"COMPONENT_PARAMETER_NOT_SINGLE:{axis}:{parameter}")
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError(f"COMPONENT_VALUES_INVALID:{axis}")
        if any(token in cause.lower() for token in (" combined ", " and ", " plus ", " while ")):
            raise ValueError(f"COMPONENT_CAUSE_NOT_SINGLE:{axis}")
        if not isinstance(video_indexes, list) or len({int(value) for value in video_indexes}) < 2:
            raise ValueError(f"COMPONENT_VIDEO_SUPPORT_LOW:{axis}")
        normalized.append({
            "axis": axis,
            "verdict": verdict,
            "hypothesis_id": hypothesis_id,
            "parameter": parameter,
            "values": values,
            "causal_reason": cause,
            "video_source_indexes": sorted({int(value) for value in video_indexes}),
            "falsification_test": str(raw.get("falsification_test") or "").strip(),
            "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
        })
    if set(grouped) != AXES:
        raise ValueError(f"COMPONENT_AXIS_COVERAGE_MISMATCH:{sorted(grouped)}")
    proposed = [row for row in normalized if row["verdict"] == "PROPOSE_HYPOTHESIS"]
    if len(proposed) > 8:
        raise ValueError(f"COMPONENT_TOTAL_HYPOTHESIS_LIMIT:{len(proposed)}")
    return normalized


def run(result: Mapping[str, Any], registry: Mapping[str, Any], out: Path) -> int:
    ai = result.get("ai_usage") or {}
    if ai.get("gemini_required_this_epoch") is not True:
        receipt = {"state": "SKIP_GEMINI_NOT_REQUIRED", "GEMINI_USED": False, "hypotheses": [], **SAFE}
        receipt["receipt_sha256"] = stable_sha(receipt)
        write_json(out / "gemini_artifact.json", receipt)
        print(receipt["state"], receipt["receipt_sha256"])
        return 0
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    if len(sources) < 4 or len({str(row.get("channel") or "") for row in sources}) < 4:
        raise RuntimeError("GEMINI_SOURCE_DIVERSITY_LOW")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    research_prompt = prompt(result, sources)
    model, text = gemini.call_direct_video(key, research_prompt, sources)
    parsed = parse_json_text(text)
    reviews = normalize_response(parsed)
    hypotheses = [row for row in reviews if row["verdict"] == "PROPOSE_HYPOTHESIS"]
    input_payload = {
        "result_sha256": result.get("result_sha256"),
        "data_fingerprint": result.get("data_fingerprint"),
        "sources": source_view(sources),
        "component_evidence": component_view(result),
    }
    artifact = {
        "schema_version": "2.0",
        "version": VERSION,
        "state": "PASS_COMPONENT_GEMINI_DIRECT_VIDEO",
        "GEMINI_USED": True,
        "actual_model": model,
        "free_only": True,
        "trigger_reason": ai.get("gemini_trigger_reason"),
        "hypothesis_only_low_sample": bool(ai.get("gemini_hypothesis_only_when_low_sample")),
        "public_video_count": len(sources),
        "independent_channel_count": len({str(row.get("channel") or "") for row in sources}),
        "sources": source_view(sources),
        "reviews": reviews,
        "hypotheses": hypotheses,
        "input_sha256": stable_sha(input_payload),
        "prompt_sha256": hashlib.sha256(research_prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "replay_allowed": False,
        "next": "GROQ_WORKERS_SINGLE_AXIS_GATE_THEN_WAIT_NEW_EXACT_LEDGER",
        **SAFE,
    }
    artifact["receipt_sha256"] = stable_sha(artifact)
    write_json(out / "gemini_artifact.json", artifact)
    for index, hypothesis in enumerate(hypotheses, start=1):
        payload = {
            "strategy_id": result.get("strategy_id"),
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "changed_axes": [hypothesis["axis"]],
            "routing_flags": {
                "external_hypothesis": True,
                "multimodal": True,
                "new_multimodal_evidence": True,
                "new_failure_fingerprint": ai.get("gemini_trigger_reason") in {"NEW_EXACT_FINGERPRINT", "CONVERGENCE"},
                "borderline_case": False,
                "major_gate_review": False,
            },
            "hypothesis": hypothesis,
            "lineage_complete": True,
            "lineage": {
                "ledger_sha": (result.get("source_authority") or {}).get("ledger_sha256"),
                "summary_sha": (result.get("source_authority") or {}).get("summary_sha256"),
                "fingerprint": result.get("data_fingerprint"),
                "candidate_result_sha": result.get("result_sha256"),
                "gemini_receipt_sha": artifact["receipt_sha256"],
            },
            "control": (result.get("control") or {}).get("stats"),
            "candidate": {},
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        }
        write_json(out / "hypotheses" / f"{index:02d}-{hypothesis['axis']}-{hypothesis['hypothesis_id']}.json", payload)
    print(artifact["state"], len(hypotheses), artifact["receipt_sha256"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--video-registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    return run(read_json(args.result), read_json(args.video_registry), Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
