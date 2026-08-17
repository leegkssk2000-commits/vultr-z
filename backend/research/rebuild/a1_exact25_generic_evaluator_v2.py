from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import attach_survivor_gate, load_external_hardening_evidence

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


def _output_path(argv: list[str]) -> Path:
    for i, arg in enumerate(argv):
        if arg == "--out" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--out="):
            return Path(arg.split("=", 1)[1])
    return Path("a1_exact25_receipt.json")


def main() -> None:
    # Preserve the v1 prospective evaluator exactly, then add only a fail-closed
    # hardening adapter. Missing existing H4/OOS/retention evidence can never be
    # synthesized into PASS.
    v1.main()
    out_path = _output_path(sys.argv[1:])
    receipt = json.loads(out_path.read_text(encoding="utf-8"))
    receipt = attach_survivor_gate(receipt, hardening_evidence=load_external_hardening_evidence())
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({
        "state": receipt.get("state"),
        "strategy_id": receipt.get("strategy_id"),
        "completed_trades": receipt.get("completed_trades"),
        "survivor_gate_state": (receipt.get("survivor_gate") or {}).get("state"),
        "survivor_gate_passed": (receipt.get("survivor_gate") or {}).get("passed"),
        "receipt_sha256": receipt.get("receipt_sha256"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
