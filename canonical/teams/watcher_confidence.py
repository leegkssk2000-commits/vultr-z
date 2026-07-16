from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

from .policy_contracts import CANONICAL_SOURCES, TEAM_POLICY_REGISTRY

BotName = Literal["LBot", "MBot", "OBot", "SBot"]
TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]
Severity = Literal["none", "m", "M", "C"]

WATCHER_CONFIDENCE_VERSION = "team-watcher-confidence/1.0.0"
SEVERITY_ORDER: Mapping[Severity, int] = MappingProxyType({"none": 0, "m": 1, "M": 2, "C": 3})
REMAINING_SHARED_GAPS = (
    "counterfactual_team_selection",
    "regime_eligibility_engine",
    "team_router_ranking",
)


def _source_reasons(source_ids: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if not source_ids:
        return (f"{prefix}_SOURCE_IDS_MISSING",)
    invalid = tuple(source for source in source_ids if not source.startswith(CANONICAL_SOURCES))
    if invalid:
        reasons.append(f"{prefix}_SOURCE_PREFIX_INVALID")
    if not any(source.startswith("cf:") for source in source_ids):
        reasons.append(f"{prefix}_CF_SOURCE_MISSING")
    if not any(source.startswith("sheets:") for source in source_ids):
        reasons.append(f"{prefix}_SHEETS_SOURCE_MISSING")
    return tuple(reasons)


def _confidence_valid(value: float) -> bool:
    return 0.0 <= value <= 1.0


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    policy_id: str
    source_ids: tuple[str, ...]
    role_weights: Mapping[str, float]
    watcher_penalties: Mapping[Severity, float]
    minimum_ready_confidence: float
    critical_requires_hold: bool = True
    contract_version: str = WATCHER_CONFIDENCE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_weights", MappingProxyType(dict(self.role_weights)))
        object.__setattr__(self, "watcher_penalties", MappingProxyType(dict(self.watcher_penalties)))
        errors = self.validate()
        if errors:
            raise ValueError("CALIBRATION_POLICY_INVALID:" + ",".join(errors))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = list(_source_reasons(self.source_ids, "POLICY"))
        if not self.policy_id:
            errors.append("POLICY_ID_MISSING")
        if set(self.role_weights) != {"main", "support", "helper"}:
            errors.append("ROLE_WEIGHT_KEYS_INVALID")
        elif any(value < 0.0 for value in self.role_weights.values()):
            errors.append("ROLE_WEIGHT_NEGATIVE")
        elif self.role_weights["main"] + self.role_weights["support"] <= 0.0:
            errors.append("CORE_ROLE_WEIGHT_ZERO")
        if set(self.watcher_penalties) != set(SEVERITY_ORDER):
            errors.append("WATCHER_PENALTY_KEYS_INVALID")
        elif any(not _confidence_valid(value) for value in self.watcher_penalties.values()):
            errors.append("WATCHER_PENALTY_RANGE_INVALID")
        if not _confidence_valid(self.minimum_ready_confidence):
            errors.append("MINIMUM_CONFIDENCE_RANGE_INVALID")
        if self.contract_version != WATCHER_CONFIDENCE_VERSION:
            errors.append("CONTRACT_VERSION_INVALID")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class WatcherSignal:
    watcher: BotName
    severity: Severity
    confidence: float
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    data_state: str = "FRESH"
    abstain: bool = False
    hard_veto: bool = False
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.watcher not in {"LBot", "MBot", "OBot", "SBot"}:
            raise ValueError("WATCHER_INVALID")
        if self.severity not in SEVERITY_ORDER:
            raise ValueError("WATCHER_SEVERITY_INVALID")
        if not _confidence_valid(self.confidence):
            raise ValueError("WATCHER_CONFIDENCE_RANGE_INVALID")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("WATCHER_SOURCE_DUPLICATE")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("WATCHER_EVIDENCE_DUPLICATE")
        if self.hard_veto and self.watcher != "SBot":
            raise ValueError("HARD_VETO_OWNER_INVALID")


@dataclass(frozen=True, slots=True)
class TeamConfidenceRequest:
    team_id: TeamName
    role_assignment_id: str
    main_confidence: float
    support_confidence: float
    helper_active: bool
    helper_confidence: float | None
    watcher_signals: tuple[WatcherSignal, ...]
    policy: CalibrationPolicy
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    data_state: str = "FRESH"
    role_ready: bool = True

    def __post_init__(self) -> None:
        if self.team_id not in TEAM_POLICY_REGISTRY:
            raise ValueError("TEAM_ID_INVALID")
        if not self.role_assignment_id:
            raise ValueError("ROLE_ASSIGNMENT_ID_MISSING")
        if not _confidence_valid(self.main_confidence):
            raise ValueError("MAIN_CONFIDENCE_RANGE_INVALID")
        if not _confidence_valid(self.support_confidence):
            raise ValueError("SUPPORT_CONFIDENCE_RANGE_INVALID")
        if self.helper_active:
            if self.helper_confidence is None or not _confidence_valid(self.helper_confidence):
                raise ValueError("HELPER_CONFIDENCE_REQUIRED")
        elif self.helper_confidence is not None and not _confidence_valid(self.helper_confidence):
            raise ValueError("HELPER_CONFIDENCE_RANGE_INVALID")
        watchers = tuple(signal.watcher for signal in self.watcher_signals)
        if len(set(watchers)) != len(watchers):
            raise ValueError("WATCHER_SIGNAL_DUPLICATE")


@dataclass(frozen=True, slots=True)
class TeamConfidenceEnvelope:
    calibration_id: str
    team_id: TeamName
    severity: Severity
    dominant_watcher: BotName | None
    role_confidence: float
    watcher_penalty: float
    calibrated_confidence: float
    decision_ready: bool
    fail_closed: bool
    abstain: bool
    hard_veto: bool
    action: str
    reason_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    policy_id: str
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = WATCHER_CONFIDENCE_VERSION

    def binding_confidence(self) -> float | None:
        return self.calibrated_confidence if self.decision_ready else None


def _calibration_id(request: TeamConfidenceRequest) -> str:
    raw = "|".join(
        (
            request.team_id,
            request.role_assignment_id,
            request.policy.policy_id,
            str(request.main_confidence),
            str(request.support_confidence),
            str(request.helper_confidence),
            ",".join(
                f"{signal.watcher}:{signal.severity}:{signal.confidence}:{signal.hard_veto}"
                for signal in sorted(request.watcher_signals, key=lambda item: item.watcher)
            ),
            ",".join(request.source_ids),
            ",".join(request.evidence_ids),
        )
    ).encode("utf-8")
    return f"confidence.{hashlib.sha256(raw).hexdigest()[:24]}"


def calibrate_team_confidence(request: TeamConfidenceRequest) -> TeamConfidenceEnvelope:
    team_policy = TEAM_POLICY_REGISTRY[request.team_id]
    reasons: list[str] = []
    reasons.extend(_source_reasons(request.source_ids, "REQUEST"))
    reasons.extend(_source_reasons(request.policy.source_ids, "POLICY"))
    if request.data_state != "FRESH":
        reasons.append("CONFIDENCE_DATA_NOT_FRESH")
    if not request.evidence_ids:
        reasons.append("CONFIDENCE_EVIDENCE_IDS_MISSING")
    if not request.role_ready:
        reasons.append("CONFIDENCE_ROLE_ASSIGNMENT_NOT_READY")

    expected_watchers = tuple(team_policy.watcher_priorities)
    actual_watchers = tuple(signal.watcher for signal in request.watcher_signals)
    if set(actual_watchers) != set(expected_watchers) or len(actual_watchers) != len(expected_watchers):
        reasons.append("CONFIDENCE_WATCHER_SET_MISMATCH")

    for signal in request.watcher_signals:
        reasons.extend(_source_reasons(signal.source_ids, f"WATCHER_{signal.watcher}"))
        if signal.data_state != "FRESH":
            reasons.append(f"WATCHER_{signal.watcher}_DATA_NOT_FRESH")
        if not signal.evidence_ids:
            reasons.append(f"WATCHER_{signal.watcher}_EVIDENCE_MISSING")
        if signal.abstain:
            reasons.append(f"WATCHER_{signal.watcher}_ABSTAIN")

    active_roles: list[tuple[float, float]] = [
        (request.main_confidence, request.policy.role_weights["main"]),
        (request.support_confidence, request.policy.role_weights["support"]),
    ]
    if request.helper_active and request.helper_confidence is not None:
        active_roles.append((request.helper_confidence, request.policy.role_weights["helper"]))
    total_weight = sum(weight for _, weight in active_roles)
    if total_weight <= 0.0:
        reasons.append("CONFIDENCE_ACTIVE_ROLE_WEIGHT_ZERO")
        role_confidence = 0.0
    else:
        role_confidence = sum(value * weight for value, weight in active_roles) / total_weight

    severity: Severity = "none"
    dominant_watcher: BotName | None = None
    if request.watcher_signals:
        dominant = max(
            request.watcher_signals,
            key=lambda signal: (SEVERITY_ORDER[signal.severity], signal.confidence, signal.watcher),
        )
        severity = dominant.severity
        dominant_watcher = dominant.watcher

    remaining_confidence = 1.0
    for signal in request.watcher_signals:
        penalty = request.policy.watcher_penalties[signal.severity] * signal.confidence
        penalty = min(max(penalty, 0.0), 1.0)
        remaining_confidence *= 1.0 - penalty
    watcher_penalty = 1.0 - remaining_confidence
    calibrated_confidence = min(max(role_confidence * remaining_confidence, 0.0), 1.0)

    hard_veto = any(signal.hard_veto for signal in request.watcher_signals)
    if hard_veto:
        reasons.append("CONFIDENCE_SBOT_HARD_VETO")
    if severity == "C" and request.policy.critical_requires_hold:
        reasons.append("CONFIDENCE_CRITICAL_WATCHER_HOLD")
    if calibrated_confidence < request.policy.minimum_ready_confidence:
        reasons.append("CONFIDENCE_BELOW_SSOT_MINIMUM")

    hard_prefixes = (
        "REQUEST_",
        "POLICY_",
        "WATCHER_",
        "CONFIDENCE_DATA_",
        "CONFIDENCE_EVIDENCE_",
        "CONFIDENCE_ROLE_",
        "CONFIDENCE_WATCHER_",
        "CONFIDENCE_ACTIVE_",
        "CONFIDENCE_SBOT_",
        "CONFIDENCE_CRITICAL_",
        "CONFIDENCE_BELOW_",
    )
    fail_closed = any(reason.startswith(hard_prefixes) for reason in reasons)
    decision_ready = not fail_closed

    return TeamConfidenceEnvelope(
        calibration_id=_calibration_id(request),
        team_id=request.team_id,
        severity=severity,
        dominant_watcher=dominant_watcher,
        role_confidence=role_confidence,
        watcher_penalty=watcher_penalty,
        calibrated_confidence=calibrated_confidence,
        decision_ready=decision_ready,
        fail_closed=fail_closed,
        abstain=fail_closed,
        hard_veto=hard_veto,
        action="block" if hard_veto else "hold",
        reason_codes=tuple(dict.fromkeys(reasons)),
        source_ids=request.source_ids,
        evidence_ids=request.evidence_ids,
        policy_id=request.policy.policy_id,
    )


def validate_watcher_confidence_contract() -> tuple[str, ...]:
    errors: list[str] = []
    if set(TEAM_POLICY_REGISTRY) != {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}:
        errors.append("WATCHER_CONFIDENCE_TEAM_SET_INVALID")
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        if len(policy.watcher_priorities) != 2:
            errors.append(f"{team_id}:WATCHER_COUNT_INVALID")
        if policy.authority != "advisory_only" or policy.runtime_enabled or policy.execution_authority != "none":
            errors.append(f"{team_id}:WATCHER_CONFIDENCE_AUTHORITY_INVALID")
    if tuple(SEVERITY_ORDER) != ("none", "m", "M", "C"):
        errors.append("SEVERITY_ORDER_INVALID")
    return tuple(errors)
