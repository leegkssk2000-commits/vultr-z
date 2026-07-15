from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ALLOWED_ACTIONS, BotRequest, BotResponse


@dataclass(frozen=True, slots=True)
class Assessment:
    action: str
    confidence: float
    abstain: bool
    veto: bool
    reason_codes: tuple[str, ...]


class CanonicalBot(ABC):
    bot_id: str
    semantic_role: str
    required_evidence: tuple[str, ...]

    def evaluate(self, request: BotRequest) -> BotResponse:
        if request.data_state != "FRESH":
            return self._response(
                request,
                Assessment("hold", 0.0, True, False, (f"DATA_{request.data_state}",)),
            )
        missing = tuple(key for key in self.required_evidence if key not in request.role_evidence)
        if missing:
            return self._response(
                request,
                Assessment("hold", 0.0, True, False, tuple(f"EVIDENCE_MISSING:{key}" for key in missing)),
            )
        assessment = self.assess(request.role_evidence)
        if assessment.action not in ALLOWED_ACTIONS:
            assessment = Assessment("hold", 0.0, True, False, ("UNSUPPORTED_ACTION",))
        return self._response(request, assessment)

    @abstractmethod
    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        raise NotImplementedError

    def _response(self, request: BotRequest, assessment: Assessment) -> BotResponse:
        return BotResponse(
            bot_id=self.bot_id,
            semantic_role=self.semantic_role,
            decision_id=request.decision_id,
            position_id=request.position_id,
            event_id=request.event_id,
            parent_event_id=request.parent_event_id,
            event_ts=request.event_ts,
            symbol=request.symbol,
            side=request.side,
            strategy_id=request.strategy_id,
            method_id=request.method_id,
            skill_id=request.skill_id,
            team_id=request.team_id,
            team_role=request.team_role,
            data_state=request.data_state,
            action=assessment.action,
            confidence=max(0.0, min(1.0, float(assessment.confidence))),
            abstain=bool(assessment.abstain),
            veto=bool(assessment.veto),
            reason_codes=assessment.reason_codes,
            source_ids=request.source_ids,
            evidence_ids=request.evidence_ids,
            freshness_ms=request.freshness_ms,
            latency_ms=request.latency_ms,
        )


def advisory_assessment(evidence: Mapping[str, Any], *, default_reason: str) -> Assessment:
    action = str(evidence.get("suggested_action") or "hold")
    confidence = float(evidence.get("confidence") or 0.0)
    abstain = bool(evidence.get("abstain", False))
    reasons = tuple(str(code) for code in evidence.get("reason_codes", ()) if str(code))
    if not reasons:
        reasons = (default_reason,)
    return Assessment(action, confidence, abstain, False, reasons)
