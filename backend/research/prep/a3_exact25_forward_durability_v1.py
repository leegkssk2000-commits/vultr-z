from __future__ import annotations

import sys

from backend.research.prep import a3_exact25_forward_durability_v3 as v3
from backend.research.prep.a3_exact25_forward_durability_v3 import *  # noqa: F401,F403


def main() -> int:
    if "--self-test" in sys.argv:
        contract = v3.read(v3.CONTRACT)
        hardening = v3.read(v3.HARDENING)
        v3.validate_contract(contract, hardening)
        assert contract["activation_boundary_utc"] == "2026-08-21T18:00:00Z"
        assert contract["prospective_cohort"]["minimum_causally_matched_trades"] == 25
        print("PASS_A3_EXACT25_FORWARD_DURABILITY_COMPAT_SELF_TEST")
        return 0
    return v3.main()


if __name__ == "__main__":
    raise SystemExit(main())
