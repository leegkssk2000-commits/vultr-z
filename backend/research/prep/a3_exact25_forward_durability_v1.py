from __future__ import annotations

# Compatibility entrypoint retained for the existing hourly fanout workflow.
# The authoritative A3 evaluator is V3, which enforces the pre-sealed
# prospective durability contract and excludes all pre-activation outcomes.
from backend.research.prep.a3_exact25_forward_durability_v3 import *  # noqa: F401,F403
from backend.research.prep.a3_exact25_forward_durability_v3 import main


if __name__ == "__main__":
    raise SystemExit(main())
