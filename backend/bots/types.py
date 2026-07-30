from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TeamSnapshot(BaseModel):
    name: str
    selected: bool = False
    score: float = 0.0
    health: str = "unknown"
    mode: str = "paper"
    lead: str = ""
    support: str = ""
    conditional_helper: Optional[str] = None
    watchers: List[str] = Field(default_factory=list)
    why: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    next_candidate: Optional[str] = None
    watcher_consensus: str = "unknown"
    helper_trigger: bool = False
    decision_id: str = ""
    stale_ms: int = 0
    source_ts: int = 0
    reconcile_status: str = "ok"
    source: str = ""


class TeamDetail(BaseModel):
    team: TeamSnapshot
    lead_decision: Dict[str, Any] = Field(default_factory=dict)
    support_decision: Dict[str, Any] = Field(default_factory=dict)
    helper_decision: Optional[Dict[str, Any]] = None
    runtime_policy: Dict[str, Any] = Field(default_factory=dict)
