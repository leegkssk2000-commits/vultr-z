from __future__ import annotations

from typing import Any, Mapping

from .base import Assessment, CanonicalBot, advisory_assessment


class LBot(CanonicalBot):
    bot_id = "LBot"
    semantic_role = "lead_trend_primary_decision_bridge"
    required_evidence = ("trend_thesis", "hold_reduce_posture", "invalidation_flags")

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return advisory_assessment(evidence, default_reason="LBOT_TREND_THESIS_REVIEWED")
