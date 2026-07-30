from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def log_shadow_diff(
    *,
    team_name: str,
    legacy_payload: Dict[str, Any],
    new_payload: Dict[str, Any],
    decision_id: str,
    source: str | None = None,
    source_ts: int | None = None,
) -> Dict[str, Any]:
    result = {
        "team_name": str(team_name),
        "decision_id": str(decision_id),
        "source": source,
        "source_ts": source_ts,
        "legacy_sha": _sha(legacy_payload),
        "new_sha": _sha(new_payload),
        "changed": _sha(legacy_payload) != _sha(new_payload),
        "shadow_only": True,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    result["diff_sha"] = _sha(result)
    return result


def write_shadow_diff(
    *,
    team_name: str,
    scope: str,
    bot_name: str,
    legacy_decision: Dict[str, Any],
    new_decision: Dict[str, Any],
) -> Dict[str, Any]:
    result = log_shadow_diff(
        team_name=team_name,
        legacy_payload=legacy_decision,
        new_payload=new_decision,
        decision_id=str(new_decision.get("decision_id") or legacy_decision.get("decision_id") or f"{scope}.{bot_name}"),
        source=str(new_decision.get("source") or legacy_decision.get("source") or ""),
        source_ts=int(new_decision.get("source_ts") or legacy_decision.get("source_ts") or 0),
    )
    result["scope"] = str(scope)
    result["bot_name"] = str(bot_name)
    return result
