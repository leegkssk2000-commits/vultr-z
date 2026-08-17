from __future__ import annotations

import time

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

v1.policy_functions = policy_functions

_base_request_json = v1.request_json


def request_json_with_transient_retry(url: str, params: dict[str, object]):
    """Retry only BingX's explicit transient 100410 response; all other defects fail closed."""
    for attempt in range(3):
        try:
            return _base_request_json(url, params)
        except RuntimeError as exc:
            if "BINGX_API_ERROR:100410:" not in str(exc) or attempt >= 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("UNREACHABLE_TRANSIENT_RETRY")


v1.request_json = request_json_with_transient_retry


if __name__ == "__main__":
    v1.main()
