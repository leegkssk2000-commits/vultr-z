from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ContractBase(BaseModel):
    model_config = ConfigDict(extra='allow')


class FreshnessContract(ContractBase):
    source_ts: Optional[int] = None
    stale: Optional[bool] = None
    stale_ms: Optional[int] = None
    verification_status: Optional[str] = None


class AckContract(ContractBase):
    scope: Optional[str] = None
    ttl_s: Optional[int] = None
    key: Optional[str] = None
    status: Optional[str] = None


class ChangeDigestContract(ContractBase):
    sha256: Optional[str] = None
    source: Optional[str] = None


class RailStatusResponse(ContractBase):
    ok: bool = True
    backend_ver: str
    decision_id: str
    freshness: FreshnessContract
    change_digest: Dict[str, Any] = Field(default_factory=dict)
    ack: Dict[str, Any] = Field(default_factory=dict)
    contracts: Dict[str, Any] = Field(default_factory=dict)
    verification_status: Optional[str] = None


class StateSummaryResponse(ContractBase):
    contract_version: Optional[str] = 'state.summary.v1'
    backend_ver: Optional[str] = None
    decision_id: Optional[str] = None
    freshness: Dict[str, Any] = Field(default_factory=dict)
    change_digest: Dict[str, Any] = Field(default_factory=dict)
    ack: Dict[str, Any] = Field(default_factory=dict)
    contracts: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    source_ts: Optional[int] = None
    stale: Optional[bool] = None
    stale_ms: Optional[int] = None
    verification_status: Optional[str] = None


class TradeContextResponse(ContractBase):
    contract_version: Optional[str] = 'trade.context.v2'
    backend_ver: Optional[str] = None
    decision_id: Optional[str] = None
    freshness: Dict[str, Any] = Field(default_factory=dict)
    change_digest: Dict[str, Any] = Field(default_factory=dict)
    ack: Dict[str, Any] = Field(default_factory=dict)
    contracts: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    source_ts: Optional[int] = None
    stale: Optional[bool] = None
    stale_ms: Optional[int] = None
    reconcile_status: Optional[str] = None
    strategy_registry: Dict[str, Any] = Field(default_factory=dict)
    execution_chain: Dict[str, Any] = Field(default_factory=dict)
    recovery_path: Dict[str, Any] = Field(default_factory=dict)
    counterfactual: Dict[str, Any] = Field(default_factory=dict)
    alert_ladder: Dict[str, Any] = Field(default_factory=dict)


class LogReplayResponse(ContractBase):
    contract_version: Optional[str] = 'log.replay.v4'
    backend_ver: Optional[str] = None
    decision_id: str
    freshness: Dict[str, Any] = Field(default_factory=dict)
    change_digest: Dict[str, Any] = Field(default_factory=dict)
    ack: Dict[str, Any] = Field(default_factory=dict)
    contracts: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    source_ts: Optional[int] = None
    replay_anchor: Optional[str] = None
    count: int = 0
    items: List[Dict[str, Any]] = Field(default_factory=list)
    snapshot_ref: Optional[str] = None


RAIL_STATUS_EXAMPLE = {
    'ok': True,
    'backend_ver': '14.5.7b.v1',
    'decision_id': 'settings:route:0',
    'freshness': {'source_ts': 0, 'stale': False, 'stale_ms': 0, 'verification_status': 'ready'},
    'change_digest': {'ack': None, 'hold': None, 'validator': None},
    'ack': {'scope': 'decision_id', 'ttl_s': 600, 'key': 'settings:route:0', 'status': 'ready'},
    'contracts': {'ingestion_converged_ver': '15B.1'},
    'verification_status': 'ready',
}

STATE_SUMMARY_EXAMPLE = {
    'contract_version': 'state.summary.v1',
    'backend_ver': '14.5.7b.v1',
    'decision_id': 'settings:route:0',
    'freshness': {'source_ts': 0, 'stale': False, 'stale_ms': 0, 'verification_status': 'ready'},
    'change_digest': {'source': 'journal_summary'},
    'ack': {'scope': 'decision_id', 'ttl_s': 600, 'key': 'settings:route:0', 'status': 'ready'},
    'contracts': {'ingestion_converged_ver': '15B.1', 'schema': '15A.5'},
    'source': 'journal_summary',
    'source_ts': 0,
    'stale': False,
    'stale_ms': 0,
    'verification_status': 'ready',
}

TRADE_CONTEXT_EXAMPLE = {
    'contract_version': 'trade.context.v2',
    'backend_ver': '14.5.7b.v1',
    'decision_id': 'settings:route:0',
    'freshness': {'source_ts': 0, 'stale': False, 'stale_ms': 0, 'verification_status': 'ready'},
    'change_digest': {'source': 'trade_context'},
    'ack': {'scope': 'decision_id', 'ttl_s': 600, 'key': 'settings:route:0', 'status': 'ready'},
    'contracts': {'schema': '15C.1', 'ingestion_converged_ver': '15B.1'},
    'source': 'trade_state',
    'source_ts': 0,
    'stale': False,
    'stale_ms': 0,
    'reconcile_status': 'ok',
    'strategy_registry': {'lookup_status': 'runtime_only', 'strategy_key': None},
    'execution_chain': {'mode': 'paper', 'authority': 'shadow', 'live_execution_enabled': False},
    'recovery_path': {'status': 'ready', 'blockers': [], 'next_steps': ['state ready; keep envelope stable']},
    'counterfactual': {'actual_action': 'hold', 'actual_risk_action': 'hold', 'alt_action_if_live_ready': 'hold', 'alt_reason': 'default', 'strategy': None, 'profile': 'paper'},
    'alert_ladder': {'severity': 'info', 'reason_code': 'OK', 'decision_action': 'hold', 'risk_action': 'hold'},
}

LOG_REPLAY_EXAMPLE = {
    'contract_version': 'log.replay.v4',
    'backend_ver': '14.5.7b.v1',
    'decision_id': 'settings:route:0',
    'freshness': {'source_ts': 0, 'stale': False, 'stale_ms': 0, 'verification_status': 'ready'},
    'change_digest': {'source': 'log_replay'},
    'ack': {'scope': 'decision_id', 'ttl_s': 600, 'key': 'settings:route:0', 'status': 'ready'},
    'contracts': {'schema': '15A.5'},
    'source': 'json:/home/z/z/backend/trade_state.json',
    'source_ts': 0,
    'replay_anchor': None,
    'count': 0,
    'items': [],
    'snapshot_ref': 'json:/home/z/z/backend/trade_state.json',
}
