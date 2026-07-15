from __future__ import annotations

from typing import Any, Mapping

from .base import Assessment, CanonicalBot, advisory_assessment


class MBot(CanonicalBot):
    bot_id = "MBot"
    semantic_role = "method_range_confirmation"
    required_evidence = ("method_fit", "range_state", "timing_quality", "conflict_flags")

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return advisory_assessment(evidence, default_reason="MBOT_METHOD_FIT_REVIEWED")
