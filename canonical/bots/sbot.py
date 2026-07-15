from __future__ import annotations

from typing import Any, Mapping

from .base import Assessment, CanonicalBot


class SBot(CanonicalBot):
    bot_id = "SBot"
    semantic_role = "safety_hard_veto_soft_penalty"
    required_evidence = ("hard_violations", "soft_penalties", "risk_state")

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        hard = tuple(str(code) for code in evidence.get("hard_violations", ()) if str(code))
        if hard:
            return Assessment("block", 1.0, False, True, tuple(f"SBOT_HARD:{code}" for code in hard))
        action = str(evidence.get("suggested_action") or "hold")
        confidence = float(evidence.get("confidence") or 0.0)
        abstain = bool(evidence.get("abstain", False))
        reasons = tuple(str(code) for code in evidence.get("reason_codes", ()) if str(code))
        if not reasons:
            soft = tuple(str(code) for code in evidence.get("soft_penalties", ()) if str(code))
            reasons = tuple(f"SBOT_SOFT:{code}" for code in soft) or ("SBOT_RISK_REVIEWED",)
        return Assessment(action, confidence, abstain, False, reasons)
