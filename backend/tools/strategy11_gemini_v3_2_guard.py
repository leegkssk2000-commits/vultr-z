from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from backend.tools import strategy11_gemini_v3_2 as original

MIN_SELECTED = 4
MIN_FAILED_RESCUE = 3
BASIS_REJECTS = {
    "supertrend_pullback": {
        "trade_count": 203,
        "win_rate_pct": 30.0493,
        "net_return_pct_sum": -3.1185,
        "net_profit_factor": 0.9472,
        "payoff_ratio": 2.2049,
        "max_drawdown_pct": 8.8382,
        "positive_window_count": 5,
        "research_state": "REJECT_BASIS_ECONOMICS",
        "authority_run_id": 30602112063,
    },
    "trend_rider": {
        "trade_count": 180,
        "win_rate_pct": 28.3333,
        "net_return_pct_sum": -26.3187,
        "net_profit_factor": 0.7463,
        "payoff_ratio": 1.8876,
        "max_drawdown_pct": 42.1254,
        "positive_window_count": 3,
        "research_state": "REJECT_BASIS_ECONOMICS",
        "authority_run_id": 30602112063,
    },
}

_base_build_profiles = original.build_profiles
_base_build_prompt = original.build_prompt
_base_validate_response = original.validate_response
_base_call_direct_video = original.call_direct_video


def build_profiles(*args: Any, **kwargs: Any):
    profiles, catalogs = _base_build_profiles(*args, **kwargs)
    for profile in profiles:
        sid = str(profile.get("strategy_id") or "")
        if sid in BASIS_REJECTS:
            profile["control"] = dict(BASIS_REJECTS[sid])
            profile["tested_variants"] = []
            profile["top_hold_reasons"] = [{"reason": "official_basis_economics_rejected", "count": 1}]
            profile["review_mode"] = "NEW_CHILD_ONLY"
            profile["candidate_catalog"] = []
            profile["available_candidate_ids"] = []
            catalogs[sid] = {}
    return profiles, catalogs


def build_prompt(profiles: Sequence[Mapping[str, Any]], sources: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> str:
    base = _base_build_prompt(profiles, sources, policy)
    return base + (
        "\n\nV3_2_CORRECTION_CONTRACT="
        "Select at least four replay candidates when at least four nonempty catalogs exist, including at least three FAILED_OR_HOLD_RESCUE strategies from distinct strategy families. "
        "This is bounded discovery, not promotion; deterministic replay must reject weak ideas. "
        "For Alpha, every hypothesis must contain exactly one axis, exactly one parameter, and one bounded values list. "
        "Do not combine a gate with an exit, partial with trailing, ATR with VWAP, or any two mechanisms in one Alpha hypothesis. "
        "Alpha hypothesis exact keys: label, axis, parameter, values, single_cause_change, why_distinct_from_TIME54_TIME60, falsification_test."
    )


def validate_alpha(response: Mapping[str, Any]) -> None:
    alpha = response.get("alpha_fresh_only")
    if not isinstance(alpha, Mapping):
        raise ValueError("ALPHA_FRESH_ONLY_MISSING")
    if alpha.get("strategy_id") != "alpha_combo" or alpha.get("authority") != "TIME54_TIME60_W1_FRESH_ONLY":
        raise ValueError("ALPHA_AUTHORITY_INVALID")
    hypotheses = alpha.get("hypotheses")
    if not isinstance(hypotheses, list) or len(hypotheses) > 2:
        raise ValueError("ALPHA_HYPOTHESIS_COUNT_INVALID")
    for index, row in enumerate(hypotheses):
        if not isinstance(row, Mapping):
            raise ValueError(f"ALPHA_HYPOTHESIS_INVALID:{index}")
        axis = str(row.get("axis") or "").strip()
        parameter = str(row.get("parameter") or "").strip()
        values = row.get("values")
        if not axis or not parameter or not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError(f"ALPHA_SINGLE_AXIS_SCHEMA_INVALID:{index}")
        if any(token in parameter for token in (",", "+", "/", "&")):
            raise ValueError(f"ALPHA_PARAMETER_COMPOSITE:{index}")
        change = str(row.get("single_cause_change") or "").lower()
        if any(token in change for token in (" combined ", " and ", " while ", " plus ")):
            raise ValueError(f"ALPHA_MULTI_CAUSE_TEXT:{index}")


def validate_response(response: Mapping[str, Any], profiles, catalogs, max_selected):
    normalized, selected = _base_validate_response(response, profiles, catalogs, max_selected)
    validate_alpha(response)
    available = sum(bool(catalogs.get(str(profile["strategy_id"]))) for profile in profiles)
    failed = [row for row in selected if str(row["strategy_id"]) not in original.STRONG]
    families = {
        str(next(profile for profile in profiles if profile["strategy_id"] == row["strategy_id"]).get("family"))
        for row in failed
    }
    if available >= MIN_SELECTED and len(selected) < MIN_SELECTED:
        raise ValueError(f"INSUFFICIENT_BOUNDED_REPLAY_SELECTION:{len(selected)}")
    if available >= MIN_FAILED_RESCUE and len(failed) < MIN_FAILED_RESCUE:
        raise ValueError(f"INSUFFICIENT_FAILED_RESCUE_SELECTION:{len(failed)}")
    if len(families) < min(MIN_FAILED_RESCUE, len(failed)):
        raise ValueError(f"FAILED_RESCUE_FAMILY_DIVERSITY_LOW:{len(families)}")
    return normalized, selected


def coarse_response_valid(text: str) -> bool:
    try:
        payload = json.loads(text)
        reviews = [row for row in payload.get("strategy_reviews", []) if isinstance(row, Mapping)]
        selected = [row for row in reviews if row.get("verdict") == "SELECT_REPLAY"]
        alpha = payload.get("alpha_fresh_only")
        if len(reviews) != 24 or len(selected) < MIN_SELECTED or not isinstance(alpha, Mapping):
            return False
        hypotheses = alpha.get("hypotheses")
        if not isinstance(hypotheses, list) or len(hypotheses) > 2:
            return False
        for row in hypotheses:
            if not isinstance(row, Mapping) or not row.get("axis") or not row.get("parameter") or not isinstance(row.get("values"), list):
                return False
        return True
    except Exception:
        return False


def call_direct_video(key: str, prompt: str, sources):
    model, text = _base_call_direct_video(key, prompt, sources)
    if coarse_response_valid(text):
        return model, text
    correction = prompt + (
        "\n\nYOUR_PREVIOUS_OUTPUT_VIOLATED_THE_CONTRACT. Regenerate the entire JSON. "
        "Review all 24 strategies, select at least four bounded replay candidates including at least three failed/HOLD strategies from distinct families, "
        "and express each Alpha fresh-only hypothesis as exactly one axis plus exactly one parameter and one values list. "
        "Do not combine mechanisms. Return complete strict JSON only."
    )
    return _base_call_direct_video(key, correction, sources)


original.build_profiles = build_profiles
original.build_prompt = build_prompt
original.validate_response = validate_response
original.call_direct_video = call_direct_video


if __name__ == "__main__":
    raise SystemExit(original.main())
