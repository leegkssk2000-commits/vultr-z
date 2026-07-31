from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.tools import strategy11_gemini_v3_2 as gemini

VERSION = "ZEL_MANUAL_MULTIAXIS_GEMINI_V2"
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


def preferred_models(key: str) -> list[str]:
    eligible = set(gemini.list_models(key))
    ordered = [model for model in gemini.PREFERRED_MODELS if model in eligible]
    if "models/gemini-flash-latest" in eligible:
        ordered.append("models/gemini-flash-latest")
    return ordered[:5]


def call_generate(
    key: str,
    prompt: str,
    *,
    source: Mapping[str, Any] | None,
    max_output_tokens: int,
) -> tuple[str, str]:
    models = preferred_models(key)
    if not models:
        raise RuntimeError("NO_ELIGIBLE_GEMINI_FLASH_MODEL")
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if source is not None:
        parts.append({"file_data": {"file_uri": str(source["url"])}})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    body = json.dumps(payload).encode()
    errors: list[str] = []
    for model in models:
        for attempt in range(2):
            try:
                request = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                    data=body,
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=900) as response:
                    generated = json.load(response)
                texts: list[str] = []
                for candidate in generated.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        if isinstance(part.get("text"), str):
                            texts.append(part["text"])
                text = "\n".join(texts).strip()
                if not text:
                    raise RuntimeError("EMPTY_GEMINI_RESPONSE")
                return model, text
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")
                errors.append(f"{model}:HTTP_{exc.code}:{detail[:300]}")
                if exc.code == 400:
                    break
                if exc.code == 429 and attempt == 0:
                    time.sleep(12)
                    continue
                break
            except Exception as exc:
                errors.append(f"{model}:{type(exc).__name__}:{str(exc)[:300]}")
                break
        if errors and ":HTTP_400:" in errors[-1]:
            break
    raise RuntimeError("GEMINI_REQUEST_FAILED:" + "|".join(errors))


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


def source_prompt(source_index: int, source: Mapping[str, Any]) -> str:
    schema = {
        "status": "USE|REJECT_SOURCE",
        "methodology_risk": "LOW|MEDIUM|HIGH",
        "mechanisms": [
            {
                "topic": "entry|bot|team|exit_skill|risk|validation",
                "testable_rule": "deterministic rule only",
                "limitations": "omitted costs/sample/discretion/repainting",
                "timestamps_or_sections": ["optional"]
            }
        ],
        "reason": "concise",
    }
    return (
        "Analyze the attached public YouTube video directly as a skeptical quantitative trading researcher. "
        "Extract only deterministic mechanisms that can be replayed. Reject marketing, discretionary chart reading, repainting, omitted fees, hidden samples, and unsupported claims. "
        "Do not recommend live trading. Return strict JSON only.\n"
        f"SOURCE_INDEX={source_index}\n"
        f"SOURCE_META={canonical(dict(source))}\n"
        f"OUTPUT_SCHEMA={canonical(schema)}"
    )


def normalize_source_summary(source_index: int, source: Mapping[str, Any], model: str, text: str) -> dict[str, Any]:
    row = parse_json(text)
    status = str(row.get("status") or "REJECT_SOURCE").upper()
    if status not in {"USE", "REJECT_SOURCE"}:
        status = "REJECT_SOURCE"
    mechanisms = row.get("mechanisms") if isinstance(row.get("mechanisms"), list) else []
    clean = []
    for mechanism in mechanisms[:12]:
        if not isinstance(mechanism, Mapping):
            continue
        rule = str(mechanism.get("testable_rule") or "").strip()
        if not rule:
            continue
        clean.append({
            "topic": str(mechanism.get("topic") or "validation"),
            "testable_rule": rule[:1000],
            "limitations": str(mechanism.get("limitations") or "")[:1000],
            "timestamps_or_sections": list(mechanism.get("timestamps_or_sections") or [])[:10],
        })
    if status == "USE" and not clean:
        status = "REJECT_SOURCE"
    return {
        "source_index": source_index,
        "url": source["url"],
        "title": source.get("title"),
        "channel": source.get("channel"),
        "observed_views": int(source.get("observed_views") or 0),
        "status": status,
        "methodology_risk": str(row.get("methodology_risk") or "HIGH").upper(),
        "mechanisms": clean,
        "reason": str(row.get("reason") or "")[:1000],
        "actual_model": model,
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
    }


def analyze_sources(key: str, sources: Sequence[Mapping[str, Any]], out: Path) -> list[dict[str, Any]]:
    receipts = []
    for source_index, source in enumerate(sources, start=1):
        try:
            model, text = call_generate(key, source_prompt(source_index, source), source=source, max_output_tokens=4096)
            receipt = normalize_source_summary(source_index, source, model, text)
        except Exception as exc:
            receipt = {
                "source_index": source_index,
                "url": source["url"],
                "title": source.get("title"),
                "channel": source.get("channel"),
                "observed_views": int(source.get("observed_views") or 0),
                "status": "REJECT_SOURCE",
                "methodology_risk": "HIGH",
                "mechanisms": [],
                "reason": f"PROVIDER_SOURCE_FAILURE:{type(exc).__name__}:{str(exc)[:600]}",
                "actual_model": None,
                "response_sha": None,
            }
        write_json(out / "source_receipts" / f"{source_index:02d}.json", receipt)
        receipts.append(receipt)
        time.sleep(2)
    return receipts


def aggregate_prompt(result: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]], request: Mapping[str, Any]) -> str:
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
    usable = [dict(row) for row in receipts if row.get("status") == "USE"]
    return (
        "You are a skeptical quantitative trading systems researcher. Use only the supplied independently generated direct-video receipts. "
        "Popularity is discovery weight, not truth. Return exactly one review for each axis STRATEGY_ENTRY, BOT_POLICY, TEAM_POLICY, SKILL_PROFILE, ZBOT_PROFILE. "
        "Propose at most one hypothesis per axis. Each hypothesis must change exactly one parameter, use one to four exact values from PARAMETER_CATALOG, and cite at least two independent USE source indexes. "
        "BOT_POLICY target must be LBot, MBot, OBot, or SBot. TEAM_POLICY target=team. SKILL_PROFILE parameter=skill_id. ZBOT_PROFILE target=ZBot. "
        "Use NO_ACTION when evidence is weak. This is same-evidence reanalysis and cannot authorize promotion. Return strict JSON only.\n"
        f"REQUEST={canonical(request)}\n"
        f"DIRECT_VIDEO_RECEIPTS={canonical(usable)}\n"
        f"PARAMETER_CATALOG={canonical(CATALOG)}\n"
        f"PIPELINE_EVIDENCE={canonical(evidence_view(result))}\n"
        f"OUTPUT_SCHEMA={canonical(schema)}"
    )


def normalize(response: Mapping[str, Any], source_count: int, usable_indexes: set[int] | None = None) -> list[dict[str, Any]]:
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
            verdict = "NO_ACTION"
        base = {
            "axis": axis,
            "verdict": "NO_ACTION",
            "hypothesis_id": None,
            "target": None,
            "parameter": None,
            "values": [],
            "causal_reason": str(raw.get("causal_reason") or ""),
            "video_source_indexes": [],
            "falsification_test": str(raw.get("falsification_test") or ""),
            "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
        }
        if verdict == "NO_ACTION":
            normalized.append(base)
            continue
        target = str(raw.get("target") or "").strip()
        parameter = str(raw.get("parameter") or "").strip()
        values = raw.get("values")
        indexes = raw.get("video_source_indexes")
        valid = parameter in CATALOG[axis] and isinstance(values, list) and 1 <= len(values) <= 4 and isinstance(indexes, list)
        if axis == "BOT_POLICY":
            valid = valid and target in {"LBot", "MBot", "OBot", "SBot"}
        expected = {"STRATEGY_ENTRY": "strategy", "TEAM_POLICY": "team", "SKILL_PROFILE": "skill", "ZBOT_PROFILE": "ZBot"}.get(axis)
        if expected:
            valid = valid and target == expected
        if valid:
            valid = all(value in CATALOG[axis][parameter] for value in values)
        unique_indexes: list[int] = []
        if valid:
            try:
                unique_indexes = sorted({int(value) for value in indexes})
            except Exception:
                valid = False
        if valid:
            valid = len(unique_indexes) >= 2 and all(1 <= value <= source_count for value in unique_indexes)
        if valid and usable_indexes is not None:
            valid = set(unique_indexes).issubset(usable_indexes)
        if not valid:
            base["causal_reason"] = "INVALID_OR_UNSUPPORTED_HYPOTHESIS_FAIL_CLOSED"
            normalized.append(base)
            continue
        normalized.append({
            **base,
            "verdict": "PROPOSE_HYPOTHESIS",
            "hypothesis_id": str(raw.get("hypothesis_id") or f"MANUAL_{axis}_1"),
            "target": target,
            "parameter": parameter,
            "values": values,
            "video_source_indexes": unique_indexes,
        })
    if seen != set(AXES):
        raise ValueError(f"AXIS_COVERAGE_MISMATCH:{sorted(seen)}")
    return normalized


def run(result: Mapping[str, Any], registry: Mapping[str, Any], request: Mapping[str, Any], out: Path) -> dict[str, Any]:
    if request.get("same_evidence_reanalysis") is not True or request.get("new_market_data_claim") is not False:
        raise RuntimeError("MANUAL_REANALYSIS_CONTRACT_INVALID")
    for key_name, value in SAFE.items():
        if request.get(key_name) != value:
            raise RuntimeError(f"REQUEST_SAFETY_MISMATCH:{key_name}")
    sources = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    policy = registry.get("selection_policy") or {}
    if len(sources) < int(policy.get("minimum_sources", 6)):
        raise RuntimeError("SOURCE_COUNT_LOW")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    receipts = analyze_sources(key, sources, out)
    usable = [row for row in receipts if row["status"] == "USE"]
    usable_channels = {str(row.get("channel")) for row in usable}
    minimum_usable = max(4, int(policy.get("minimum_independent_channels", 5)) - 1)
    if len(usable) < minimum_usable or len(usable_channels) < minimum_usable:
        raise RuntimeError(f"GEMINI_USABLE_VIDEO_COVERAGE_LOW:{len(usable)}:{len(usable_channels)}")
    prompt = aggregate_prompt(result, receipts, request)
    model, text = call_generate(key, prompt, source=None, max_output_tokens=16384)
    reviews = normalize(parse_json(text), len(sources), {int(row["source_index"]) for row in usable})
    hypotheses = [row for row in reviews if row["verdict"] == "PROPOSE_HYPOTHESIS"]
    registry_sha = stable_sha(registry)
    underlying = str(result.get("data_fingerprint") or "")
    research_fingerprint = stable_sha({"underlying": underlying, "registry": registry_sha, "request_id": request["request_id"], "version": VERSION})
    artifact = {
        "schema_version": "zel.manual_multiaxis_gemini.v2",
        "version": VERSION,
        "state": "PASS_MANUAL_MULTIAXIS_GEMINI_PER_VIDEO",
        "GEMINI_USED": True,
        "actual_model": model,
        "run_id": str(os.environ.get("GITHUB_RUN_ID") or "LOCAL_MANUAL_RESEARCH"),
        "request_id": request["request_id"],
        "same_evidence_reanalysis": True,
        "new_market_data_claim": False,
        "underlying_data_fingerprint": underlying,
        "research_fingerprint": research_fingerprint,
        "video_registry_sha256": registry_sha,
        "requested_source_count": len(sources),
        "usable_source_count": len(usable),
        "rejected_source_count": len(receipts) - len(usable),
        "usable_independent_channels": len(usable_channels),
        "public_urls": [str(row["url"]) for row in usable],
        "independent_channels": sorted(usable_channels),
        "source_count": len(usable),
        "observed_view_sum": sum(int(row.get("observed_views") or 0) for row in usable),
        "source_receipts": receipts,
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
    response = {"status": "PASS", "reviews": [{"axis": axis, "verdict": "NO_ACTION"} for axis in AXES]}
    rows = normalize(response, 6, {1, 2, 3, 4, 5, 6})
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
        print("PASS_MANUAL_MULTIAXIS_GEMINI_V2_FIXTURE")
        return 0
    artifact = run(read_json(args.result), read_json(args.registry), read_json(args.request), args.out)
    print(artifact["state"], len(artifact["hypotheses"]), artifact["usable_source_count"], artifact["receipt_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
