from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.tools import strategy11_gemini_v3_2_cohort as cohort

_base_validate_cohort = cohort.validate_cohort
_base_validate_merged = cohort.guard.validate_response
_POLICY_HOLD_PREFIXES = (
    "INSUFFICIENT_BOUNDED_REPLAY_SELECTION:",
    "INSUFFICIENT_FAILED_RESCUE_SELECTION:",
    "FAILED_RESCUE_FAMILY_DIVERSITY_LOW:",
)


def _hold_rows(profiles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": str(profile["strategy_id"]),
            "verdict": "NO_ACTION",
            "selected_candidate_id": None,
            "causal_reason": "GEMINI_COHORT_DECLARED_HOLD",
            "internal_evidence_refs": [],
            "video_source_indexes": [],
            "expected_metric_effect": None,
            "falsification_test": None,
            "overfit_risk": "HIGH",
        }
        for profile in profiles
    ]


def validate_cohort(response: Mapping[str, Any], cohort_name, required_family, profiles, catalogs):
    status = str(response.get("status") or "").upper()
    if status == "PASS":
        return _base_validate_cohort(response, cohort_name, required_family, profiles, catalogs)
    if status == "HOLD":
        return _hold_rows(profiles), []
    raise ValueError(f"COHORT_DECLARED_INVALID_STATUS:{cohort_name}:{response.get('status')}")


def validate_merged_response(response: Mapping[str, Any], profiles, catalogs, max_selected):
    try:
        return _base_validate_merged(response, profiles, catalogs, max_selected)
    except ValueError as exc:
        reason = str(exc)
        if not reason.startswith(_POLICY_HOLD_PREFIXES):
            raise
        normalized, _selected = cohort.guard._base_validate_response(response, profiles, catalogs, max_selected)
        cohort.guard.validate_alpha(response)
        if isinstance(response, dict):
            response["terminal_hold_reason"] = reason
            response["terminal_hold_scope"] = "GEMINI_SELECTION_POLICY"
        return normalized, []


cohort.validate_cohort = validate_cohort
cohort.guard.validate_response = validate_merged_response


if __name__ == "__main__":
    raise SystemExit(cohort.main())
