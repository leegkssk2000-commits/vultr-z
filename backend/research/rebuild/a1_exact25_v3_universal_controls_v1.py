from __future__ import annotations

# Compatibility entrypoint retained for existing workflows. The authoritative
# evaluator is V2, which freezes the first 25 trades and control randomization
# for each policy/config/boundary identity to prevent repeated-seed p-hacking.
from backend.research.rebuild.a1_exact25_v3_universal_controls_v2 import *  # noqa: F401,F403
from backend.research.rebuild.a1_exact25_v3_universal_controls_v2 import main


if __name__ == "__main__":
    raise SystemExit(main())
