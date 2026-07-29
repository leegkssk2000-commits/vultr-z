from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .diff_logger import log_shadow_diff
from .legacy_adapter import adapt_team_overview, adapt_team_payload


def _safe_source(raw: Dict[str, Any], legacy_payload: Dict[str, Any], shadow_payload: Dict[str, Any] | None = None) -> Optional[str]:
    for obj in (raw, shadow_payload or {}, legacy_payload):
        source = obj.get("source")
        if source:
            return str(source)
        source = obj.get("_source")
        if source:
            return str(source)
    return None


def _safe_source_ts(raw: Dict[str, Any], legacy_payload: Dict[str, Any], shadow_payload: Dict[str, Any] | None = None) -> int | None:
    for obj in (raw, shadow_payload or {}, legacy_payload):
        for key in ("source_ts", "_source_ts", "ts", "timestamp", "updated_at"):
            value = obj.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                return int(float(value))
            except Exception:
                continue
    return None


def _default_decision_id(team_name: str) -> str:
    return f"shadow.{team_name}.{int(time.time() * 1000)}"


def emit_team_detail_shadow(
    team_name: str,
    team_cfg: Dict[str, Any],
    raw: Dict[str, Any],
    legacy_payload: Dict[str, Any],
    decision_id: str | None = None,
) -> Dict[str, Any]:
    shadow_payload = adapt_team_payload(team_name, team_cfg, raw)
    return log_shadow_diff(
        team_name=team_name,
        legacy_payload=legacy_payload,
        new_payload=shadow_payload,
        decision_id=decision_id or _default_decision_id(team_name),
        source=_safe_source(raw, legacy_payload, shadow_payload),
        source_ts=_safe_source_ts(raw, legacy_payload, shadow_payload),
    )


def build_team_overview_shadow(
    team_name: str,
    team_cfg: Dict[str, Any],
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    return adapt_team_overview(team_name, team_cfg, raw)
