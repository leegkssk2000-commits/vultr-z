from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .base import Assessment, CanonicalBot
from .contracts import BotRequest, BotResponse

CAPABILITY_TAGS = ("trend", "strength", "continuation", "invalidation", "hysteresis", "conflict")
CANONICAL_SOURCES = ("cf:", "sheets:")
LBOT_ALLOWED_ACTIONS = frozenset({"hold", "reduce25", "partial30", "route_change"})
ALLOWED_DIRECTIONS = frozenset({"long", "short", "neutral"})
ALLOWED_CATEGORIES = frozenset({"invalidation", "conflict", "hysteresis", "continuation", "strength"})
CATEGORY_PRIORITY = {"strength": 1, "continuation": 2, "hysteresis": 3, "conflict": 4, "invalidation": 5}
ACTION_PRIORITY = {"hold": 0, "reduce25": 1, "partial30": 2, "route_change": 3}
OPERATORS = {
    "gt": lambda value, limit: value > limit,
    "gte": lambda value, limit: value >= limit,
    "lt": lambda value, limit: value < limit,
    "lte": lambda value, limit: value <= limit,
    "eq": lambda value, limit: value == limit,
    "neq": lambda value, limit: value != limit,
}
SNAPSHOT_FIELDS = (
    "trend_direction",
    "trend_strength_score",
    "continuation_score",
    "structure_score",
    "momentum_score",
    "invalidation_score",
    "conflict_score",
    "regime_stability_score",
    "confidence_score",
    "trend_ts",
    "market_ts",
    "previous_posture",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}:BOOLEAN")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name}:INVALID")
    return result


def _score(name: str, value: Any) -> float:
    result = _number(name, value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name}:OUT_OF_RANGE")
    return result


def _time(name: str, value: Any) -> datetime:
    parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name}:TZ_REQUIRED")
    return parsed


def _source_ok(value: Any) -> bool:
    return _text(value).startswith(CANONICAL_SOURCES)


def _hold(*reasons: str) -> Assessment:
    return Assessment("hold", 0.0, True, False, tuple(dict.fromkeys(reasons)))


class LBot(CanonicalBot):
    bot_id = "LBot"
    semantic_role = "lead_trend_primary_decision_bridge"
    required_evidence = (
        "trend_thesis", "invalidation_flags", "conflict_flags",
        "integrity", "snapshot", "metric_sources", "rules",
    )

    def evaluate(self, request: BotRequest) -> BotResponse:
        if request.data_state != "FRESH":
            return self._response(request, _hold(f"LBOT_DATA_{request.data_state}"))
        if not request.source_ids or not request.evidence_ids:
            return self._response(request, _hold("LBOT_LINEAGE_SOURCE_MISSING"))
        return self._response(request, self._assess(request.role_evidence, side=request.side))

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return self._assess(evidence, side=_text(evidence.get("side")) or "long")

    def _assess(self, evidence: Mapping[str, Any], *, side: str) -> Assessment:
        thesis = _text(evidence.get("trend_thesis"))
        if not thesis:
            return _hold("LBOT_TREND_THESIS_MISSING")

        integrity = evidence.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("ok") is not True:
            return _hold("LBOT_INTEGRITY_UNCONFIRMED")
        failed = tuple(
            key for key in ("missing", "disconnected", "ts_anomaly", "key_mismatch", "stale")
            if bool(integrity.get(key))
        )
        if failed:
            return _hold(*(f"LBOT_INTEGRITY:{key}" for key in failed))

        snapshot = evidence.get("snapshot")
        sources = evidence.get("metric_sources")
        if not isinstance(snapshot, Mapping) or not isinstance(sources, Mapping):
            return _hold("LBOT_SNAPSHOT_OR_SOURCE_MAP_MISSING")
        missing = [key for key in SNAPSHOT_FIELDS if key not in snapshot]
        if missing:
            return _hold(f"LBOT_MIN_DATA_MISSING:{','.join(sorted(missing))}")
        source_gaps = [key for key in SNAPSHOT_FIELDS if not _source_ok(sources.get(key))]
        if source_gaps:
            return _hold(f"LBOT_SOURCE_MISSING:{','.join(sorted(source_gaps))}")

        try:
            direction = _text(snapshot.get("trend_direction")).lower()
            request_side = side.lower()
            if direction not in ALLOWED_DIRECTIONS or request_side not in {"long", "short"}:
                raise ValueError("DIRECTION_OR_SIDE_INVALID")
            previous_posture = _text(snapshot.get("previous_posture"))
            if previous_posture not in LBOT_ALLOWED_ACTIONS:
                raise ValueError("PREVIOUS_POSTURE_INVALID")
            trend_ts = _time("trend_ts", snapshot.get("trend_ts"))
            market_ts = _time("market_ts", snapshot.get("market_ts"))
            if market_ts < trend_ts:
                raise ValueError("TIMESTAMP_ORDER")
            direction_alignment = 1.0 if direction == request_side else (0.0 if direction == "neutral" else -1.0)
            metrics = {
                "direction_alignment": direction_alignment,
                "trend_strength_score": _score("trend_strength_score", snapshot.get("trend_strength_score")),
                "continuation_score": _score("continuation_score", snapshot.get("continuation_score")),
                "structure_score": _score("structure_score", snapshot.get("structure_score")),
                "momentum_score": _score("momentum_score", snapshot.get("momentum_score")),
                "invalidation_score": _score("invalidation_score", snapshot.get("invalidation_score")),
                "conflict_score": _score("conflict_score", snapshot.get("conflict_score")),
                "regime_stability_score": _score("regime_stability_score", snapshot.get("regime_stability_score")),
                "confidence_score": _score("confidence_score", snapshot.get("confidence_score")),
                "trend_age_min": (market_ts - trend_ts).total_seconds() / 60.0,
            }
        except (TypeError, ValueError) as exc:
            return _hold(f"LBOT_INPUT_INVALID:{exc}")

        invalidation_flags = tuple(_text(code) for code in evidence.get("invalidation_flags", ()) if _text(code))
        conflict_flags = tuple(_text(code) for code in evidence.get("conflict_flags", ()) if _text(code))
        rules = evidence.get("rules")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)) or not rules:
            return _hold("LBOT_SSOT_RULES_MISSING")

        matched: list[dict[str, Any]] = []
        try:
            for rule in rules:
                if not isinstance(rule, Mapping):
                    raise ValueError("RULE_NOT_OBJECT")
                rule_id = _text(rule.get("rule_id"))
                category = _text(rule.get("category"))
                metric = _text(rule.get("metric"))
                operator = _text(rule.get("operator"))
                action = _text(rule.get("action"))
                unit = _text(rule.get("unit"))
                priority = int(rule.get("priority", 0))
                if not rule_id or category not in ALLOWED_CATEGORIES or metric not in metrics or operator not in OPERATORS:
                    raise ValueError(f"RULE_SHAPE:{rule_id}:{category}:{metric}:{operator}")
                if action not in LBOT_ALLOWED_ACTIONS or priority < 0 or not unit:
                    raise ValueError(f"RULE_POLICY:{rule_id}")
                if not _source_ok(rule.get("source_id")):
                    raise ValueError(f"RULE_SOURCE:{rule_id}")
                from_postures = tuple(_text(value) for value in rule.get("from_postures", ()) if _text(value))
                if from_postures and any(value not in LBOT_ALLOWED_ACTIONS for value in from_postures):
                    raise ValueError(f"RULE_FROM_POSTURE:{rule_id}")
                if category == "hysteresis" and not from_postures:
                    raise ValueError(f"HYSTERESIS_FROM_POSTURE_REQUIRED:{rule_id}")
                if from_postures and previous_posture not in from_postures:
                    continue
                limit = _number(f"limit:{rule_id}", rule.get("limit"))
                value = metrics[metric]
                if OPERATORS[operator](value, limit):
                    matched.append({
                        "rule_id": rule_id, "category": category, "metric": metric,
                        "value": value, "limit": limit, "unit": unit,
                        "priority": priority, "action": action,
                    })
        except (TypeError, ValueError) as exc:
            return _hold(f"LBOT_RULE_INVALID:{exc}")

        matched_categories = {row["category"] for row in matched}
        if invalidation_flags and "invalidation" not in matched_categories:
            return _hold("LBOT_UNRESOLVED_INVALIDATION_FLAGS", *(f"LBOT_INVALIDATION:{code}" for code in invalidation_flags))
        if conflict_flags and "conflict" not in matched_categories:
            return _hold("LBOT_UNRESOLVED_CONFLICT_FLAGS", *(f"LBOT_CONFLICT:{code}" for code in conflict_flags))
        if not matched:
            return Assessment("hold", metrics["confidence_score"], False, False, ("LBOT_TREND_WITHIN_SSOT",))

        selected = max(
            matched,
            key=lambda row: (
                CATEGORY_PRIORITY[row["category"]], row["priority"],
                ACTION_PRIORITY[row["action"]], abs(row["value"] - row["limit"]),
            ),
        )
        if selected["category"] in {"strength", "continuation"} and selected["action"] != previous_posture:
            transition_allowed = any(
                row["category"] == "hysteresis" and row["action"] == selected["action"]
                for row in matched
            )
            if not transition_allowed:
                return _hold(
                    "LBOT_HYSTERESIS_TRANSITION_UNAUTHORIZED",
                    f"LBOT_FROM:{previous_posture}", f"LBOT_TO:{selected['action']}",
                )

        reasons = [f"LBOT_THESIS:{thesis}"]
        reasons.extend(f"LBOT_INVALIDATION:{code}" for code in invalidation_flags)
        reasons.extend(f"LBOT_CONFLICT:{code}" for code in conflict_flags)
        reasons.extend(
            f"LBOT_RULE:{row['category']}:{row['rule_id']}:{row['metric']}={row['value']:.6f}{row['unit']}:limit={row['limit']:.6f}{row['unit']}"
            for row in sorted(matched, key=lambda row: (-CATEGORY_PRIORITY[row["category"]], -row["priority"], row["rule_id"]))
        )
        return Assessment(selected["action"], metrics["confidence_score"], False, False, tuple(dict.fromkeys(reasons)))
