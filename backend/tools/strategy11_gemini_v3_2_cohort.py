from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.tools import strategy11_gemini_v3_2_guard as guard

original = guard.original
VERSION = "STRATEGY11_GEMINI_DIRECT_VIDEO_COHORT_V3_2"
SAFETY = dict(original.SAFETY)

COHORTS = (
    (
        "TREND_FAMILY",
        "trend_following",
        (
            "anchor_vwap_trend",
            "ema_ribbon_scalp",
            "keltner_trend",
            "supertrend_pullback",
            "trend_ma_macd",
            "trend_rider",
        ),
    ),
    (
        "MEAN_REVERSION_FAMILY",
        "mean_reversion",
        (
            "bb_revert",
            "grid_rebalance",
            "mfi_rsi_div",
            "range_fade",
            "rsi_swing_fail",
            "vwap_revert",
        ),
    ),
    (
        "BREAKOUT_SESSION_FAMILY",
        "breakout_momentum",
        (
            "break_and_continue",
            "rbreaker_like",
            "squeeze_break",
            "turtle_trend",
            "session_bias",
            "vol_spike_fade",
        ),
    ),
    (
        "MARKET_STRUCTURE_FAMILY",
        "market_structure",
        (
            "fvg_revert",
            "liquidity_sweep",
            "pivot_reversal",
            "sr_levels",
            "scalp_snap",
            "obv_trend",
        ),
    ),
)


def read_json(path: Path) -> dict[str, Any]:
    return original.read_json(path)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    original.write_json(path, value)


def stable_sha(value: Any) -> str:
    return original.stable_sha(value)


def parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("GEMINI_JSON_OBJECT_REQUIRED")
    return value


def source_view(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_index": index + 1,
            "url": row["url"],
            "title": row["title"],
            "channel": row["channel"],
            "topics": row.get("topics", []),
        }
        for index, row in enumerate(sources)
    ]


def cohort_prompt(
    cohort_name: str,
    required_family: str,
    profiles: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> str:
    exact_ids = [str(row["strategy_id"]) for row in profiles]
    schema = {
        "status": "PASS|HOLD",
        "cohort": cohort_name,
        "strategy_reviews": [
            {
                "strategy_id": "exact supplied strategy_id",
                "verdict": "SELECT_REPLAY|NO_ACTION|NEW_CHILD_REQUIRED",
                "selected_candidate_id": "exact available candidate id or null",
                "causal_reason": "one cause",
                "internal_evidence_refs": ["exact metric or hold reason"],
                "video_source_indexes": [1, 2],
                "expected_metric_effect": "specific",
                "falsification_test": "specific",
                "overfit_risk": "LOW|MEDIUM|HIGH",
            }
        ],
    }
    return (
        "You are a skeptical quantitative trading research reviewer. Analyze every attached public YouTube video directly and compare it with the supplied anonymized V3 evidence. "
        "Videos create hypotheses only; reject marketing, repainting, omitted fees, hidden samples, discretionary rules, and non-reproducible claims. "
        f"Review exactly these six strategies once each and no others: {exact_ids}. "
        "Return all six rows even when the verdict is NO_ACTION. "
        "Select at most three replay candidates. Each selected candidate ID must be copied exactly from that strategy's available_candidate_ids and must represent one causal axis. "
        f"If any strategy in family {required_family} has a nonempty candidate catalog, select at least one falsifiable candidate from that family. "
        "Selection is not endorsement: deterministic replay should reject weak ideas. Use at least two independent video source indexes for every selected replay. "
        "For supertrend_pullback and trend_rider, the official Supertrend basis already produced negative economics; use NEW_CHILD_REQUIRED or NO_ACTION only. "
        "Do not invent candidate IDs or parameter values. Return strict JSON only.\n\n"
        f"COHORT={cohort_name}\n"
        f"REQUIRED_SELECTION_FAMILY={required_family}\n"
        f"PUBLIC_VIDEO_SOURCES={json.dumps(source_view(sources), ensure_ascii=False, sort_keys=True)}\n"
        f"STRATEGY_PROFILES={json.dumps(list(profiles), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def validate_cohort(
    response: Mapping[str, Any],
    cohort_name: str,
    required_family: str,
    profiles: Sequence[Mapping[str, Any]],
    catalogs: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected = {str(row["strategy_id"]) for row in profiles}
    profile_map = {str(row["strategy_id"]): row for row in profiles}
    reviews = [dict(row) for row in response.get("strategy_reviews", []) if isinstance(row, Mapping)]
    seen = [str(row.get("strategy_id") or "") for row in reviews]
    if len(seen) != len(expected) or set(seen) != expected:
        raise ValueError(f"COHORT_COVERAGE_MISMATCH:{cohort_name}:{len(seen)}:{len(expected)}")
    selected: list[dict[str, Any]] = []
    for row in reviews:
        strategy_id = str(row["strategy_id"])
        verdict = str(row.get("verdict") or "NO_ACTION")
        candidate_id = row.get("selected_candidate_id")
        if strategy_id in original.REVIEW_ONLY and verdict == "SELECT_REPLAY":
            raise ValueError(f"COHORT_REVIEW_ONLY_REPLAY_FORBIDDEN:{strategy_id}")
        if verdict == "SELECT_REPLAY":
            if not isinstance(candidate_id, str) or candidate_id not in catalogs.get(strategy_id, {}):
                raise ValueError(f"COHORT_INVALID_CANDIDATE:{strategy_id}:{candidate_id}")
            video_indexes = row.get("video_source_indexes", [])
            if not isinstance(video_indexes, list) or len({int(value) for value in video_indexes}) < 2:
                raise ValueError(f"COHORT_VIDEO_SUPPORT_LOW:{strategy_id}")
            selected.append(
                {
                    "strategy_id": strategy_id,
                    "candidate_id": candidate_id,
                    "candidate_spec": dict(catalogs[strategy_id][candidate_id]),
                    "causal_reason": row.get("causal_reason"),
                    "internal_evidence_refs": row.get("internal_evidence_refs", []),
                    "video_source_indexes": video_indexes,
                    "expected_metric_effect": row.get("expected_metric_effect"),
                    "falsification_test": row.get("falsification_test"),
                    "overfit_risk": row.get("overfit_risk"),
                    "cohort": cohort_name,
                }
            )
        elif candidate_id not in (None, "", "NO_ACTION"):
            raise ValueError(f"COHORT_CANDIDATE_WITHOUT_SELECT:{strategy_id}")
    if len(selected) > 3:
        raise ValueError(f"COHORT_SELECTION_LIMIT:{cohort_name}:{len(selected)}")
    required_available = any(
        str(profile.get("family")) == required_family and bool(catalogs.get(str(profile["strategy_id"])))
        for profile in profiles
    )
    if required_available and not any(
        str(profile_map[row["strategy_id"]].get("family")) == required_family for row in selected
    ):
        raise ValueError(f"COHORT_REQUIRED_FAMILY_NOT_SELECTED:{cohort_name}:{required_family}")
    return reviews, selected


def alpha_prompt(sources: Sequence[Mapping[str, Any]]) -> str:
    authority = {
        "TIME54": {"trades": 40, "net_pct": 21.0965579, "pf": 4.4221376, "payoff": 3.2685365, "dd_pct": 1.5011034},
        "TIME60": {"trades": 40, "net_pct": 20.6681, "pf": 4.3526, "payoff": 3.2172, "dd_pct": 1.2549},
        "same_archive_generation_budget_exhausted": True,
        "next_authority": "W1_FRESH_NON_OVERLAP_ONLY",
    }
    schema = {
        "strategy_id": "alpha_combo",
        "authority": "TIME54_TIME60_W1_FRESH_ONLY",
        "hypotheses": [
            {
                "label": "HYPOTHESIS_EXTERNAL_FRESH_ONLY",
                "axis": "one axis",
                "parameter": "one parameter",
                "values": [1, 2],
                "single_cause_change": "one mechanism only",
                "why_distinct_from_TIME54_TIME60": "specific",
                "falsification_test": "specific",
            }
        ],
    }
    return (
        "Analyze all attached public videos directly as skeptical quantitative research evidence. Alpha Combo has already exhausted same-archive tuning and TIME54/TIME60 are fixed controls. "
        "Return zero, one, or two hypotheses for fresh W1 data only. Each hypothesis must have exactly one axis, one parameter, and one bounded values list of one to four values. "
        "Never combine entry gate with exit, partial with trailing, ATR with VWAP, or any two mechanisms. Do not replay on the old archive. Reject weak video claims. Return strict JSON only.\n\n"
        f"PUBLIC_VIDEO_SOURCES={json.dumps(source_view(sources), ensure_ascii=False, sort_keys=True)}\n"
        f"ALPHA_AUTHORITY={json.dumps(authority, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def call_json(key: str, prompt: str, sources: Sequence[Mapping[str, Any]], correction: str) -> tuple[str, str, dict[str, Any]]:
    model, text = guard._base_call_direct_video(key, prompt, sources)
    try:
        return model, text, parse_json_text(text)
    except Exception:
        model, text = guard._base_call_direct_video(key, prompt + "\n\n" + correction, sources)
        return model, text, parse_json_text(text)


def validate_alpha(alpha: Mapping[str, Any]) -> None:
    guard.validate_alpha({"alpha_fresh_only": dict(alpha)})


def build_router_input(selected: Sequence[Mapping[str, Any]], v3_final: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": "STRATEGY11_MULTI_STRATEGY_GEMINI_V3_2_COHORT",
        "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
        "changed_axes": [row["candidate_spec"]["axis"] for row in selected],
        "routing_flags": {
            "external_hypothesis": True,
            "multimodal": True,
            "new_multimodal_evidence": True,
            "new_failure_fingerprint": True,
            "borderline_case": False,
            "major_gate_review": False,
        },
        "hypotheses": list(selected),
        "lineage": {
            "source_sha": v3_final.get("final_sha256"),
            "data_sha": "985c8561016639b7ab4397bd8064cf3a67d8667db3a21797138aa5326291dbbd",
            "window_sha": "STRATEGY11_V3_12_WINDOW_ARCHIVE",
            "candidate_sha": stable_sha(list(selected)),
        },
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--video-registry", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--v3-final", required=True)
    parser.add_argument("--previous-summary")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        registry = read_json(Path(args.registry).resolve())
        ledger = read_json(Path(args.ledger).resolve())
        v3_final = read_json(Path(args.v3_final).resolve())
        video_registry = read_json(Path(args.video_registry).resolve())
        policy = read_json(Path(args.policy).resolve())
        results = original.find_results(Path(args.results_root).resolve())
        sources = [dict(row) for row in video_registry.get("sources", []) if isinstance(row, Mapping)]
        channels = {str(row.get("channel") or "") for row in sources}
        blockers: list[str] = []
        if v3_final.get("state") != "PASS_V3_ORGANIC_AUDIT":
            blockers.append("V3_FINAL_AUTHORITY_INVALID")
        if registry.get("strategy_count") != 25:
            blockers.append("REGISTRY_STRATEGY_COUNT_INVALID")
        if len(results) != 24:
            blockers.append(f"RESULT_COUNT_INVALID:{len(results)}")
        if len(sources) < int(policy["minimum_public_videos"]):
            blockers.append("PUBLIC_VIDEO_COUNT_LOW")
        if len(channels) < int(policy["minimum_independent_channels"]):
            blockers.append("INDEPENDENT_CHANNEL_COUNT_LOW")
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            blockers.append("GEMINI_API_KEY_MISSING")
        if blockers:
            write_json(out / "summary.json", {"state": "HOLD", "blockers": blockers, "GEMINI_USED": False, **SAFETY})
            return 0

        profiles, catalogs = guard.build_profiles(registry, ledger, results, int(policy["max_catalog_per_strategy"]))
        profile_map = {str(row["strategy_id"]): row for row in profiles}
        if set(profile_map) != {strategy_id for _, _, ids in COHORTS for strategy_id in ids}:
            raise ValueError("COHORT_PROFILE_SET_MISMATCH")
        input_payload = {
            "v3_final_sha256": v3_final.get("final_sha256"),
            "registry_sha256": registry.get("registry_sha256"),
            "ledger_sha256": stable_sha(ledger),
            "video_registry_sha256": stable_sha(video_registry),
            "policy_sha256": stable_sha(policy),
            "tool_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cohorts": COHORTS,
            "profiles": profiles,
        }
        input_sha = stable_sha(input_payload)
        previous = read_json(Path(args.previous_summary).resolve()) if args.previous_summary and Path(args.previous_summary).exists() else {}
        if previous.get("input_sha") == input_sha and previous.get("GEMINI_USED") is True:
            write_json(out / "plan.json", original.build_plan([], profiles, input_sha))
            write_json(out / "summary.json", {
                "state": "SKIP_UNCHANGED_GEMINI_EVIDENCE",
                "GEMINI_USED": False,
                "previous_gemini_used": True,
                "input_sha": input_sha,
                "selected_replay_count": 0,
                **SAFETY,
            })
            return 0

        all_reviews: list[dict[str, Any]] = []
        all_selected: list[dict[str, Any]] = []
        prompts: list[str] = []
        responses: list[str] = []
        models: list[str] = []
        cohort_artifacts: list[dict[str, Any]] = []
        for cohort_name, required_family, ids in COHORTS:
            cohort_profiles = [profile_map[strategy_id] for strategy_id in ids]
            prompt = cohort_prompt(cohort_name, required_family, cohort_profiles, sources)
            correction = (
                f"Regenerate complete strict JSON for all six exact strategies in cohort {cohort_name}. "
                f"Select at least one valid candidate from required family {required_family} when available, copy IDs exactly, and include all six review rows."
            )
            model, text, response = call_json(key, prompt, sources, correction)
            try:
                reviews, selected = validate_cohort(response, cohort_name, required_family, cohort_profiles, catalogs)
            except Exception:
                model, text, response = call_json(key, prompt + "\n\n" + correction, sources, correction)
                reviews, selected = validate_cohort(response, cohort_name, required_family, cohort_profiles, catalogs)
            models.append(model)
            prompts.append(prompt)
            responses.append(text)
            all_reviews.extend(reviews)
            all_selected.extend(selected)
            cohort_artifacts.append({
                "cohort": cohort_name,
                "required_family": required_family,
                "model": model,
                "review_count": len(reviews),
                "selected_count": len(selected),
                "selected_strategy_ids": [row["strategy_id"] for row in selected],
                "response": response,
            })

        alpha_review_prompt = alpha_prompt(sources)
        alpha_model, alpha_text, alpha = call_json(
            key,
            alpha_review_prompt,
            sources,
            "Return the complete Alpha object only. Every hypothesis must contain exactly one axis, one parameter, and one values list; remove compound mechanisms.",
        )
        try:
            validate_alpha(alpha)
        except Exception:
            alpha_model, alpha_text, alpha = call_json(
                key,
                alpha_review_prompt + "\n\nPrevious Alpha output was invalid. Remove every compound mechanism and return one parameter per hypothesis.",
                sources,
                "Strict single-axis Alpha JSON only.",
            )
            validate_alpha(alpha)
        models.append(alpha_model)
        prompts.append(alpha_review_prompt)
        responses.append(alpha_text)

        merged_response = {
            "status": "PASS",
            "strategy_reviews": all_reviews,
            "alpha_fresh_only": alpha,
            "selected_replay_order": [f"{row['strategy_id']}:{row['candidate_id']}" for row in all_selected],
            "cohort_count": len(COHORTS),
        }
        _, selected = guard.validate_response(merged_response, profiles, catalogs, int(policy["max_selected_replay"]))
        plan = original.build_plan(selected, profiles, input_sha)
        prompt_sha = hashlib.sha256("\n---\n".join(prompts).encode()).hexdigest()
        response_sha = hashlib.sha256("\n---\n".join(responses).encode()).hexdigest()
        actual_models = sorted(set(models))
        artifact = {
            "schema_version": "3.2",
            "version": VERSION,
            "state": "PASS_GEMINI_V3_2_COHORT_REVIEW",
            "GEMINI_USED": True,
            "free_only": True,
            "direct_video_used": True,
            "actual_model": actual_models[0] if len(actual_models) == 1 else ",".join(actual_models),
            "run_id": os.environ.get("GITHUB_RUN_ID", "LOCAL"),
            "input_sha": input_sha,
            "prompt_sha": prompt_sha,
            "response_sha": response_sha,
            "public_urls": [str(row["url"]) for row in sources],
            "independent_channels": sorted(channels),
            "source_count": len(sources),
            "independent_channel_count": len(channels),
            "reviewed_strategy_count": len(all_reviews),
            "selected_replay_count": len(selected),
            "selected_rows": selected,
            "alpha_fresh_only": alpha,
            "cohort_artifacts": cohort_artifacts,
            "response": merged_response,
            "v3_final_sha256": v3_final.get("final_sha256"),
            **SAFETY,
        }
        write_json(out / "gemini_artifact.json", artifact)
        write_json(out / "plan.json", plan)
        write_json(out / "router_input.json", build_router_input(selected, v3_final))
        write_json(out / "summary.json", {
            "state": artifact["state"],
            "GEMINI_USED": True,
            "actual_model": artifact["actual_model"],
            "reviewed_strategy_count": len(all_reviews),
            "selected_replay_count": len(selected),
            "selected_strategy_ids": [row["strategy_id"] for row in selected],
            "alpha_fresh_hypothesis_count": len(alpha.get("hypotheses", [])),
            "input_sha": input_sha,
            "prompt_sha": prompt_sha,
            "response_sha": response_sha,
            **SAFETY,
        })
        print(json.dumps({"state": artifact["state"], "reviewed": len(all_reviews), "selected": len(selected)}, sort_keys=True))
        return 0
    except Exception as exc:
        write_json(out / "failure.json", {
            "state": "FAIL_GEMINI_V3_2_COHORT",
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            **SAFETY,
        })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
