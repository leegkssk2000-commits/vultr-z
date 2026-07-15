from __future__ import annotations

from typing import Any, Mapping

from .base import Assessment, CanonicalBot, advisory_assessment


class OBot(CanonicalBot):
    bot_id = "OBot"
    semantic_role = "observer_breakout_anomaly"
    required_evidence = ("breakout_quality", "anomaly_flags", "mfe_mae_context")

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return advisory_assessment(evidence, default_reason="OBOT_MARKET_STRUCTURE_REVIEWED")
