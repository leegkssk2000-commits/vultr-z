from __future__ import annotations

import time
from typing import Any, Dict, Iterable


VERSION = "zops.module.contract.v1"
DEFAULT_COMPONENTS = ["ledger", "replay", "promotion", "harness"]


def now_ms() -> int:
    return int(time.time() * 1000)


def base_payload(component: str, kind: str, **extra: Any) -> Dict[str, Any]:
    return {
        "contract_version": VERSION,
        "component": str(component),
        "kind": str(kind),
        "status": "ready_read_only",
        "ts_ms": now_ms(),
        "mutation": "blocked",
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        **extra,
    }


def health_payload(component: str) -> Dict[str, Any]:
    return base_payload(component, "health", ok=True)


def status_payload(component: str) -> Dict[str, Any]:
    return base_payload(component, "status", state="HOLD_READ_ONLY")


def sample_payload(component: str) -> Dict[str, Any]:
    return base_payload(component, "sample", sample={"action": "hold", "source": "fixture_contract"})


def optimization_report_payload() -> Dict[str, Any]:
    return base_payload(
        "optimization",
        "status",
        components=list(DEFAULT_COMPONENTS),
        recommendation="optimize_before_delete",
        automatic_changes=False,
    )
