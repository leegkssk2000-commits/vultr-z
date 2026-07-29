from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_LOG_PATH = Path("/home/z/z/backend/data/logs/core_contract_violations.jsonl")


def log_violation(
    *,
    decision_id: str,
    backend_ver: str,
    rule_id: str,
    severity: str,
    reason: str,
    details: Optional[Dict[str, Any]] = None,
    ts: Optional[float] = None,
    path: str = "",
) -> Dict[str, Any]:
    payload = {
        "decision_id": decision_id or "missing",
        "backend_ver": backend_ver or "unknown",
        "rule_id": rule_id,
        "severity": severity,
        "reason": reason,
        "details": details or {},
        "ts": ts if ts is not None else time.time(),
        "path": path,
    }
    DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_LOG_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload
