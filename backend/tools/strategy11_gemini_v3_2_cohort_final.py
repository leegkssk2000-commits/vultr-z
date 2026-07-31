from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.tools import strategy11_gemini_v3_2_cohort as cohort

_base_validate_cohort = cohort.validate_cohort


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


cohort.validate_cohort = validate_cohort


if __name__ == "__main__":
    raise SystemExit(cohort.main())
