from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

PREFERRED_MODELS = (
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
)
PIPELINE_VERSION = "R7A4D_STRATEGY11_GEMINI_DIRECT_VIDEO_V2"
PROMPT_VERSION = "S11_GEMINI_DIRECT_VIDEO_CROSS_SOURCE_V2"


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def list_models(key: str) -> list[str]:
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    eligible = [
        str(row["name"])
        for row in payload.get("models", [])
        if row.get("name") and "generateContent" in row.get("supportedGenerationMethods", [])
    ]
    ordered = [model for model in PREFERRED_MODELS if model in eligible]
    ordered.extend(model for model in eligible if model not in ordered and "flash" in model.lower())
    return ordered


def metric_view(variant: Mapping[str, Any]) -> dict[str, Any]:
    comparison = variant.get("comparison_to_incumbent") if isinstance(variant.get("comparison_to_incumbent"), Mapping) else {}
    loss = variant.get("loss_metrics") if isinstance(variant.get("loss_metrics"), Mapping) else {}
    stress = variant.get("stress_2x_p95_plus_one") if isinstance(variant.get("stress_2x_p95_plus_one"), Mapping) else {}
    stress_loss = stress.get("loss_metrics") if isinstance(stress.get("loss_metrics"), Mapping) else {}
    return {
        "variant_id": variant.get("variant_id"),
        "trade_count": variant.get("trade_count"),
        "win_rate_pct": variant.get("win_rate_pct"),
        "net_return_pct_sum": variant.get("net_return_pct_sum"),
        "net_profit_factor": variant.get("net_profit_factor"),
        "payoff_ratio": variant.get("payoff_ratio"),
        "max_drawdown_pct": variant.get("max_drawdown_pct"),
        "positive_windows_pct": variant.get("positive_windows_pct"),
        "avg_win_R": loss.get("avg_win_R"),
        "avg_loss_R": loss.get("avg_loss_R"),
        "worst_net_loss_R": loss.get("worst_net_loss_R"),
        "loss_cap_breach_count": loss.get("loss_cap_breach_count"),
        "stress_worst_net_loss_R": stress_loss.get("worst_net_loss_R"),
        "delta_net_pct_points": comparison.get("delta_net_pct_points"),
        "delta_profit_factor": comparison.get("delta_profit_factor"),
        "delta_payoff_ratio": comparison.get("delta_payoff_ratio"),
        "trade_retention_pct": comparison.get("trade_retention_pct"),
        "pass_to_sealed": comparison.get("pass_to_sealed"),
    }


def profile(summary: Mapping[str, Any], alias: str) -> dict[str, Any]:
    variants = summary.get("variants") if isinstance(summary.get("variants"), list) else []
    return {
        "strategy_alias": alias,
        "current_state": summary.get("state"),
        "current_classification": summary.get("classification"),
        "blockers": summary.get("blockers", []),
        "diagnosis": summary.get("diagnosis"),
        "variants": [metric_view(row) for row in variants if isinstance(row, Mapping)],
    }


def build_prompt(profiles: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    source_audit = [
        {
            "source_index": index + 1,
            "url": row["url"],
            "title": row["title"],
            "channel": row["channel"],
            "view_count_observed": row["view_count_observed"],
            "topics": row.get("topics", []),
        }
        for index, row in enumerate(sources)
    ]
    schema = {
        "status": "PASS|HOLD",
        "source_assessments": [{
            "source_index": 1,
            "decision": "USE|REJECT_SOURCE",
            "relevance": 0,
            "evidence_quality": 0,
            "methodology_transparency": 0,
            "marketing_or_overfit_risk": "LOW|MEDIUM|HIGH",
            "reason": "..."
        }],
        "cross_source_matrix": [{
            "claim": "...",
            "supporting_source_indexes": [1, 2],
            "contradicting_source_indexes": [],
            "evidence_strength": "LOW|MEDIUM|HIGH",
            "internal_falsification_test": "..."
        }],
        "strategy_reviews": [{
            "strategy_alias": "A",
            "verdict": "KEEP_CONTROL|RESEARCH_MORE|NO_EDGE_CONFIRMED",
            "why_prior_repairs_failed": ["..."],
            "hypotheses": [{
                "label": "HYPOTHESIS_EXTERNAL",
                "change_type": "stop|target|BE|partial|trailing|time_stop|feature_gate|regime_whitelist|exit_selector|NO_CHANGE",
                "single_cause_change": "...",
                "parameter_search_space": "bounded values only",
                "expected_metric_effect": "...",
                "winner_contamination_risk": "...",
                "overfit_risk": "...",
                "falsification_test": "..."
            }]
        }],
        "recommended_test_order": ["A:NO_CHANGE", "A:hypothesis_1"]
    }
    return (
        "You are a skeptical quantitative trading research reviewer. Analyze all attached public YouTube videos directly and compare them against each other. "
        "Popularity is only a source-priority signal, never proof. Reject marketing, hidden samples, lookahead, repainting, omitted fees, and claims without reproducible rules. "
        "The internal strategies are anonymized summaries; no private code, account, exchange key, user data, or order path is provided. "
        "Three failed internal iterations mean only INTERNAL_REPAIR_BUDGET_EXHAUSTED_FOR_TESTED_HYPOTHESES, not global strategy impossibility. "
        "For each strategy, identify whether a genuinely different single-cause hypothesis remains. Produce at most two new hypotheses per strategy and always include NO_CHANGE as control. "
        "Do not recommend multi-axis changes. Every idea remains HYPOTHESIS_EXTERNAL until full replay on selection, validation, holdout, fresh non-overlap, cost stress, and sealed one-shot. "
        "Return strict JSON only matching the schema.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"ANONYMIZED_INTERNAL_PROFILES={json.dumps(profiles, ensure_ascii=False, sort_keys=True)}\n"
        f"PUBLIC_SOURCE_AUDIT={json.dumps(source_audit, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def call_direct_video(key: str, models: list[str], prompt: str, sources: list[dict[str, Any]]) -> tuple[str, str]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend({"file_data": {"file_uri": row["url"]}} for row in sources)
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "thinkingConfig": {"thinkingLevel": "low"}
        }
    }
    body = json.dumps(payload).encode("utf-8")
    errors: list[str] = []
    for model in models:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as response:
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
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}:HTTP_{exc.code}:{detail[:1000]}")
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--alpha", required=True)
    parser.add_argument("--turtle", required=True)
    parser.add_argument("--ema1", required=True)
    parser.add_argument("--ema2", required=True)
    parser.add_argument("--ema3", required=True)
    parser.add_argument("--previous-gemini", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    registry = strict_json(Path(args.registry))
    alpha = strict_json(Path(args.alpha))
    turtle = strict_json(Path(args.turtle))
    ema1 = strict_json(Path(args.ema1))
    ema2 = strict_json(Path(args.ema2))
    ema3 = strict_json(Path(args.ema3))
    prior = strict_json(Path(args.previous_gemini))
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    blockers: list[str] = []
    if not key:
        blockers.append("GEMINI_API_KEY_MISSING")
    sources = [row for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in sources}
    if len(sources) < 3:
        blockers.append("PUBLIC_VIDEO_SOURCES_LT_3")
    if len(channels) < 2:
        blockers.append("INDEPENDENT_CHANNELS_LT_2")
    if prior.get("GEMINI_USED") is not False:
        blockers.append("PRIOR_GEMINI_NOT_CONFIRMED_UNUSED")
    if alpha.get("strategy_id") != "alpha_combo" or turtle.get("strategy_id") != "turtle_trend" or ema3.get("strategy_id") != "ema_ribbon_scalp":
        blockers.append("STRATEGY_AUTHORITY_MISMATCH")
    if blockers:
        atomic_json(out / "summary.json", {
            "schema_version": "2.0", "pipeline_version": PIPELINE_VERSION,
            "state": "HOLD", "GEMINI_USED": False, "free_only": True,
            "blockers": blockers, "execution_allowed": False
        })
        return 0

    ema_combined = dict(ema3)
    ema_combined["variants"] = [
        *[row for row in ema1.get("variants", []) if isinstance(row, Mapping)],
        *[row for row in ema2.get("variants", []) if isinstance(row, Mapping) and row.get("variant_id") != "INCUMBENT_CONTROL"],
        *[row for row in ema3.get("variants", []) if isinstance(row, Mapping) and row.get("variant_id") != "INCUMBENT_CONTROL"],
    ]
    profiles = [profile(alpha, "A"), profile(turtle, "B"), profile(ema_combined, "C")]
    models = list_models(key)
    if not models:
        raise RuntimeError("NO_FREE_FLASH_MODEL")
    prompt = build_prompt(profiles, sources)
    model, response_text = call_direct_video(key, models, prompt, sources)
    try:
        response = json.loads(response_text)
    except json.JSONDecodeError:
        response = {"status": "HOLD", "blockers": ["GEMINI_NON_JSON"], "raw_response": response_text[:30000]}
    state = "PASS" if response.get("status") == "PASS" else "HOLD"
    alias_map = {"A": "alpha_combo", "B": "turtle_trend", "C": "ema_ribbon_scalp"}
    hypotheses: list[dict[str, Any]] = []
    for review in response.get("strategy_reviews", []):
        if not isinstance(review, Mapping):
            continue
        alias = str(review.get("strategy_alias") or "")
        for row in review.get("hypotheses", []):
            if isinstance(row, Mapping):
                hypotheses.append({"strategy_id": alias_map.get(alias, alias), **dict(row)})
    audit = {
        "schema_version": "2.0",
        "pipeline_version": PIPELINE_VERSION,
        "state": state,
        "GEMINI_USED": True,
        "free_only": True,
        "actual_model": model,
        "public_urls": [row["url"] for row in sources],
        "source_count": len(sources),
        "independent_channel_count": len(channels),
        "prompt_version": PROMPT_VERSION,
        "input_artifact_sha256": stable_sha({"profiles": profiles, "sources": sources}),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        "response": response,
        "hypothesis_count": len(hypotheses),
        "classification_correction": {
            "ema_ribbon_scalp_previous": "STRUCTURAL_REJECT",
            "ema_ribbon_scalp_corrected": "INTERNAL_REPAIR_BUDGET_EXHAUSTED_RESEARCH_REVIEWED"
        },
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "CREATE_RESEARCH_DERIVED_SINGLE_CAUSE_CHILD" if state == "PASS" and hypotheses else "RETAIN_CONTROL_OR_WAIT_FRESH_DATA"
    }
    atomic_json(out / "analysis.json", audit)
    atomic_json(out / "repair_queue.json", {
        "schema_version": "2.0", "state": state,
        "authority": "GEMINI_HYPOTHESES_ONLY_NO_STRATEGY_MUTATION",
        "rows": hypotheses, "execution_allowed": False
    })
    atomic_json(out / "summary.json", {key: value for key, value in audit.items() if key != "response"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
