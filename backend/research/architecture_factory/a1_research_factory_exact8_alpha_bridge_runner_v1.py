from __future__ import annotations

# Importing the established Exact8 runner installs the frozen parent-policy
# dispatch shim used by the production through-A3 path. This changes no
# strategy thresholds or economics; it only resolves batch parent APIs.
from backend.research.architecture_factory import a1_external_research_exact8_through_a3_runner_v1 as exact8_runner
from backend.research.architecture_factory import a1_research_factory_exact8_alpha_bridge_v1 as bridge


def main() -> int:
    exact8_runner.validate_parent_dispatch()
    return bridge.main()


if __name__ == "__main__":
    raise SystemExit(main())
