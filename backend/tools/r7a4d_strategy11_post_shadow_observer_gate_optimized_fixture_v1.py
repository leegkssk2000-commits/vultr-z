from __future__ import annotations

from backend.research.strategy11_ml_light_observer_optimized_v1 import observe as observe_ml_optimized
from backend.tools import r7a4d_strategy11_post_shadow_observer_gate_fixture_v1 as fixture


# The merged optimized observer supersedes the uncalibrated core observer for
# PASS/HOLD evidence. Reuse the complete gate fixture while replacing only the
# observer callable; all inputs, negative cases and authority assertions remain
# unchanged.
fixture.observe_ml = observe_ml_optimized


if __name__ == "__main__":
    raise SystemExit(fixture.main())
