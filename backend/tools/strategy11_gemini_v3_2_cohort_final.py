from __future__ import annotations

from collections.abc import Mapping

from backend.tools import strategy11_gemini_v3_2_cohort as cohort

_base_validate_cohort = cohort.validate_cohort


def validate_cohort(response: Mapping, cohort_name, required_family, profiles, catalogs):
    if str(response.get("status") or "").upper() != "PASS":
        raise ValueError(f"COHORT_DECLARED_NONPASS:{cohort_name}:{response.get('status')}")
    return _base_validate_cohort(response, cohort_name, required_family, profiles, catalogs)


cohort.validate_cohort = validate_cohort


if __name__ == "__main__":
    raise SystemExit(cohort.main())
