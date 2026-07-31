from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.tools import strategy11_gemini_v3_2 as gemini

VERSION = "ZEL_MANUAL_MULTIAXIS_GEMINI_V1"
AXES = ("STRATEGY_ENTRY", "BOT_POLICY", "TEAM_POLICY", "SKILL_PROFILE", "ZBOT_PROFILE")
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
CATALOG = {
    "STRATEGY_ENTRY": {
        "minimum_trend_score": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "minimum_confirm_score": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "minimum_volume_z": [-1.0, -0.5, 0.0, 0.5, 1.0],
        "maximum_atr_pct": [1.5, 2.0, 3.0, 4.0, 5.5],
        "long_beam_required": [False, True],
    },
    "BOT_POLICY": {
        "threshold": [0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85],
        "weight": [0.5, 0.6, 0.7, 0.8, 0.9],
        "warning_cap": [0.1, 0.15, 0.25, 0.35, 0.5],
    },
    "TEAM_POLICY": {
        "support_threshold": [0.35, 0.45, 0.55, 0.65, 0.75],
        "watcher_confirmation_threshold": [0.25, 0.35, 0.45, 0.55, 0.65],
        "watcher_veto_threshold": [0.6, 0.7, 0.8, 0.9],
    },
    "SKILL_PROFILE": {
        "skill_id": [
            "SK_ENTRY_LONG_BEAM", "SK_ADD_PYRAMIDING", "SK_ADD_PROFITABLE_SCALE_IN",
            "SK_EXIT_PARTIAL_30", "SK_EXIT_TRAILING_STOP", "SK_EXIT_MFE_RUNNER",
            "SK_EXIT_RUNNER_HOLD", "SK_EXIT_TIME_STOP", "SK_EXIT_BREAK_EVEN_SHIFT",
            "SK_RISK_REDUCE_25",
        ]
    },
    "ZBOT_PROFILE": {"disagreement_threshold": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]},
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def parse_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        raw = "\n".join(lines).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("GEMINI_OBJECT_REQUIRED")
    return value


def sources_view(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_index": index + 1,
            "url": row["url"],
            "title": row.get("title"),
            "channel": row.get("channel"),
            "observed_views": int(row.get("observed_views") or 0),
            "topics": row.get("topics", []),
        }
        for index, row in enumerate(rows)
    ]


def evidence_view(result: Mapping[str, Any]) -> dict[str, Any]:
    modules = result.get("module_results") or {}
    return {
        "strategy_id": result.get("strategy_id"),
        "strategy_variant": result.get("strategy_variant"),
        "state": result.get("state"),
        "trade_count": ((result.get("control") or {}).get("stats") or {}).get("trade_count"),
        "low_sample_hold": (result.get("convergence") or {}).get("low_sample_hold"),
        "control": (result.get("control") or {}).get("stats"),
        "full_stack": (result.get("full_stack") or {}).get("stats", result.get("full_stack")),
        "pipeline_decisions": result.get("pipeline_decisions"),
        "bot_profiles": (modules.get("bots") or {}).get("best_by_role"),
        "team": (modules.get("teams") or {}).get("best"),
        "skill": (modules.get("skills") or {}).get("best"),
        "zbot": ((modules.get("advisors") or {}).get("ZBOT") or {}).get("best"),
    }


def research_prompt(result: Mapping[str, Any], sources: Sequence[Mapping[str, Any]], request: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "reviews": [
            {
                "axis": "one exact axis",
                "verdict": "PROPOSE_HYPOTHESIS|NO_ACTION",
                "hypothesis_id": "unique id or null",
                "target": "strategy|LBot|MBot|OBot|SBot|team|skill|ZBot",
                "parameter": "one exact catalog parameter or null",
                "values": ["one to four exact catalog values"],
                "causal_reason": "single mechanism",
                "video_source_indexes": [1, 2],
                "falsification_test": "deterministic replay test",
                "overfit_risk": "LOW|MEDIUM|HIGH"
            }
        ]
    }
    return (
        "You are a skeptical quantitative trading systems researcher. Directly analyze all attached public YouTube videos. "
        "Popularity is only a discovery weight and is never evidence that a method works. Extract testable mechanisms, reject marketing, repainting, omitted costs, hidden samples, discretionary rules, and look-ahead. "
        "This is a manual same-market-evidence reanalysis: it is not new data and cannot authorize promotion. "
        "Return exactly one review for each axis STRATEGY_ENTRY, BOT_POLICY, TEAM_POLICY, SKILL_PROFILE, ZBOT_PROFILE. "
        "Propose at most one hypothesis per axis. A hypothesis must change exactly one parameter, use one to four values copied exactly from PARAMETER_CATALOG, and cite at least two independent source indexes. "
        "BOT_POLICY target must be one of LBot, MBot, OBot, SBot. TEAM_POLICY target=team. SKILL_PROFILE parameter=skill_id. ZBOT_PROFILE target=ZBot. "
        "When evidence is insufficient use NO_ACTION. Return strict JSON only.\n\n"
        f"REQUEST={canonical(request)}\n"
        f"PUBLIC_VIDEO_SOURCES={canonical(sources_view(sources))}\n"
        f"PARAMETER_CATALOG={canonical(CATALOG)}\n"
        f"PIPELINE_EVIDENCE={canonical(evidence_view(result))}\n"
        f"OUTPUT_SCHEMA={canonical(schema)}"
    )


def normalize(response: Mapping[str, Any], source_count: int) -> list[dict[str, Any]]:
    if str(response.get("status") or "PASS").upper() not in {"PASS", "HOLD"}:
        raise ValueError("STATUS_INVALID")
    rows = response.get("reviews")
    if not isinstance(rows, list):
        raise ValueError("REVIEWS_REQUIRED")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("REVIEW_OBJECT_REQUIRED")
        axis = str(raw.get("axis") or "").upper()
        if axis not in AXES or axis in seen:
            raise ValueError(f"AXIS_INVALID_OR_DUPLICATE:{axis}")
        seen.add(axis)
        verdict = str(raw.get("verdict") or "NO_ACTION").upper()
        if verdict not in {"PROPOSE_HYPOTHESIS", "NO_ACTION"}:
            raise ValueError(f"VERDICT_INVALID:{axis}")
        if verdict == "NO_ACTION":
            normalized.append({"axis": axis, "verdict": verdict, "hypothesis_id": None, "target": None, "parameter": None, "values": [], "causal_reason": str(raw.get("causal_reason") or ""), "video_source_indexes": [], "falsification_test": str(raw.get("falsification_test") or ""), "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper()})
            continue
        target = str(raw.get("target") or "").strip()
        parameter = str(raw.get("parameter") or "").strip()
        values = raw.get("values")
        indexes = raw.get("video_source_indexes")
        if parameter not in CATALOG[axis]:
            raise ValueError(f"PARAMETER_NOT_ALLOWED:{axis}:{parameter}")
        if axis == "BOT_POLICY" and target not in {"LBot", "MBot", "OBot", "SBot"}:
            raise ValueError("BOT_TARGET_INVALID")
        expected_target = {"STRATEGY_ENTRY": "strategy", "TEAM_POLICY": "team", "SKILL_PROFILE": "skill", "ZBOT_PROFILE": "ZBot"}.get(axis)
        if expected_target and target != expected_target:
            raise ValueError(f"TARGET_INVALID:{axis}:{target}")
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError(f"VALUES_INVALID:{axis}")
        allowed = CATALOG[axis][parameter]
        if any(value not in allowed for value in values):
            raise ValueError(f"VALUE_NOT_ALLOWED:{axis}:{parameter}:{values}")
        if not isinstance(indexes, list):
            raise ValueError(f"VIDEO_INDEXES_REQUIRED:{axis}")
        unique_indexes = sorted({int(value) for value in indexes})
        if len(unique_indexes) < 2 or any(value < 1 or value > source_count for value in unique_indexes):
            raise ValueError(f"VIDEO_SUPPORT_INVALID:{axis}")
        normalized.append({
            "axis": axis,
            "verdict": verdict,
            "hypothesis_id": str(raw.get("hypothesis_id") or f"MANUAL_{axis}_1"),
            "target": target,
            "parameter": parameter,
            "values": values,
            "causal_reason": str(raw.get("causal_reason") or "").strip(),
            "video_source_indexes": unique_indexes,
            "falsification_test": str(raw.get("falsification_test") or "").strip(),
            "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
        })
    if seen != set(AXES):
        raise ValueError(f"AXIS_COVERAGE_MISMATCH:{sorted(seen)}")
    return normalized


def run(result: Mapping[str, Any], registry: Mapping[str, Any], request: Mapping[str, Any], out: Path) -> dict[str, Any]:
    if request.get("same_evidence_reanalysis") is not True or request.get("new_market_data_claim") is not False:
        raise RuntimeError("MANUAL_REANALYSIS_CONTRACT_INVALID")
    for key, value in SAFE.items():
        if request.get(key) != value:
            raise RuntimeError(f"REQUEST_SAFETY_MISMATCH:{key}")
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    policy = registry.get("selection_policy") or {}
    if len(sources) < int(policy.get("minimum_sources", 6)):
        raise RuntimeError("SOURCE_COUNT_LOW")
    if len({str(row.get("channel")) for row in sources}) < int(policy.get("minimum_independent_channels", 5)):
        raise RuntimeError("CHANNEL_DIVERSITY_LOW")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    prompt = research_prompt(result, sources, request)
    model, text = gemini.call_direct_video(key, prompt, sources)
    try:
        reviews = normalize(parse_json(text), len(sources))
    except Exception:
        model, text = gemini.call_direct_video(key, prompt + "\nYour previous answer violated the schema. Return one strict JSON object with exactly five reviews.", sources)
        reviews = normalize(parse_json(text), len(sources))
    hypotheses = [row for row in reviews if row["verdict"] == "PROPOSE_HYPOTHESIS"]
    registry_sha = stable_sha(registry)
    underlying = str(result.get("data_fingerprint") or "")
    research_fingerprint = stable_sha({"underlying": underlying, "registry": registry_sha, "request_id": request["request_id"], "version": VERSION})
    artifact = {
        "schema_version": "zel.manual_multiaxis_gemini.v1",
        "version": VERSION,
        "state": "PASS_MANUAL_MULTIAXIS_GEMINI_VIDEO",
        "GEMINI_USED": True,
        "actual_model": model,
        "run_id": str(os.environ.get("GITHUB_RUN_ID") or "LOCAL_MANUAL_RESEARCH"),
        "request_id": request["request_id"],
        "same_evidence_reanalysis": True,
        "new_market_data_claim": False,
        "underlying_data_fingerprint": underlying,
        "research_fingerprint": research_fingerprint,
        "video_registry_sha256": registry_sha,
        "public_urls": [str(row["url"]) for row in sources],
        "independent_channels": sorted({str(row.get("channel")) for row in sources}),
        "source_count": len(sources),
        "observed_view_sum": sum(int(row.get("observed_views") or 0) for row in sources),
        "reviews": reviews,
        "hypotheses": hypotheses,
        "input_sha": stable_sha({"result": result.get("result_sha256"), "request": request, "registry": registry}),
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
        "replay_allowed": False,
        **SAFE,
    }
    artifact["receipt_sha256"] = stable_sha(artifact)
    write_json(out / "gemini_artifact.json", artifact)
    for index, hypothesis in enumerate(hypotheses, start=1):
        route_axis = "ADVISOR_PROFILE" if hypothesis["axis"] == "ZBOT_PROFILE" else hypothesis["axis"]
        payload = {
            "strategy_id": result.get("strategy_id"),
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "changed_axes": [route_axis],
            "routing_flags": {"external_hypothesis": True, "multimodal": True, "new_multimodal_evidence": True, "new_failure_fingerprint": False, "borderline_case": False, "major_gate_review": False},
            "hypothesis": hypothesis,
            "lineage_complete": True,
            "lineage": {
                "ledger_sha": (result.get("source_authority") or {}).get("ledger_sha256"),
                "summary_sha": (result.get("source_authority") or {}).get("summary_sha256"),
                "underlying_fingerprint": underlying,
                "research_fingerprint": research_fingerprint,
                "candidate_result_sha": result.get("result_sha256"),
                "gemini_receipt_sha": artifact["receipt_sha256"],
            },
            "control": ((result.get("control") or {}).get("stats") or {}),
            "candidate": {},
            **SAFE,
        }
        write_json(out / "hypotheses" / f"{index:02d}-{hypothesis['axis']}-{hypothesis['hypothesis_id']}.json", payload)
    return artifact


def fixture(out: Path) -> None:
    response = {"status": "PASS", "reviews": []}
    for axis in AXES:
        response["reviews"].append({"axis": axis, "verdict": "NO_ACTION"})
    rows = normalize(response, 6)
    write_json(out / "fixture.json", {"reviews": rows, **SAFE})


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fx = sub.add_parser("fixture")
    fx.add_argument("--out", type=Path, required=True)
    runp = sub.add_parser("run")
    runp.add_argument("--result", type=Path, required=True)
    runp.add_argument("--registry", type=Path, required=True)
    runp.add_argument("--request", type=Path, required=True)
    runp.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "fixture":
        fixture(args.out)
        print("PASS_MANUAL_MULTIAXIS_GEMINI_FIXTURE")
        return 0
    artifact = run(read_json(args.result), read_json(args.registry), read_json(args.request), args.out)
    print(artifact["state"], len(artifact["hypotheses"]), artifact["receipt_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
