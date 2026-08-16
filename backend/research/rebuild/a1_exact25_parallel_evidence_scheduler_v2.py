from __future__ import annotations

from backend.research.rebuild import a1_exact25_parallel_evidence_scheduler_v1 as v1
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

v1.ge.policy_functions = policy_functions


if __name__ == "__main__":
    v1.main()
