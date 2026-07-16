from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .base import Assessment, CanonicalBot
from .contracts import BotRequest, BotResponse

CAPABILITY_TAGS = ("method", "range", "timing", "retest", "conflict", "helper")
CANONICAL_SOURCES = ("cf:", "sheets:")
MBOT_ALLOWED_ACTIONS = frozenset({"hold", "reduce25", "partial30", "route_change"})
ALLOWED_METHOD_STATES = frozenset({"fit", "partial", "mismatch", "unknown"})
ALLOWED_RANGE_STATES = frozenset({"trend", "range", "breakout", "transition", "unknown"})
ALLOWED_CATEGORIES = frozenset({"method", "range", "timing", "retest", "helper", "conflict"})
CATEGORY_PRIORITY = {"method": 1, "range": 2, "timing": 3, "retest": 4, "helper": 5, "conflict": 6}
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
    "method_fit_score",
    "range_quality_score",
    "timing_quality_score",
    "retest_quality_score",
    "entry_quality_score",
    "volatility_fit_score",
    "conflict_score",
    "helper_need_score",
    "confidence_score",
    "method_ts",
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


class MBot(CanonicalBot):
    bot_id = "MBot"
    semantic_role = "method_range_confirmation"
    required_evidence = (
        "method_fit", "range_state", "conflict_flags", "helper_flags",
        "integrity", "snapshot", "metric_sources", "rules",
    )

    def evaluate(self, request: BotRequest) -> BotResponse:
        if request.data_state != "FRESH":
            return self._response(request, _hold(f"MBOT_DATA_{request.data_state}"))
        if not request.source_ids or not request.evidence_ids:
            return self._response(request, _hold("MBOT_LINEAGE_SOURCE_MISSING"))
        return self._response(request, self._assess(request.role_evidence))

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return self._assess(evidence)

    def _assess(self, evidence: Mapping[str, Any]) -> Assessment:
        method_fit = _text(evidence.get("method_fit")).lower()
        range_state = _text(evidence.get("range_state")).lower()
        if method_fit not in ALLOWED_METHOD_STATES:
            return _hold("MBOT_METHOD_STATE_INVALID")
        if range_state not in ALLOWED_RANGE_STATES:
            return _hold("MBOT_RANGE_STATE_INVALID")

        integrity = evidence.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("ok") is not True:
            return _hold("MBOT_INTEGRITY_UNCONFIRMED")
        failed = tuple(
            key for key in ("missing", "disconnected", "ts_anomaly", "key_mismatch", "stale")
            if bool(integrity.get(key))
        )
        if failed:
            return _hold(*(f"MBOT_INTEGRITY:{key}" for key in failed))

        snapshot = evidence.get("snapshot")
        sources = evidence.get("metric_sources")
        if not isinstance(snapshot, Mapping) or not isinstance(sources, Mapping):
            return _hold("MBOT_SNAPSHOT_OR_SOURCE_MAP_MISSING")
        missing = [key for key in SNAPSHOT_FIELDS if key not in snapshot]
        if missing:
            return _hold(f"MBOT_MIN_DATA_MISSING:{','.join(sorted(missing))}")
        source_gaps = [key for key in SNAPSHOT_FIELDS if not _source_ok(sources.get(key))]
        if source_gaps:
            return _hold(f"MBOT_SOURCE_MISSING:{','.join(sorted(source_gaps))}")

        try:
            previous_posture = _text(snapshot.get("previous_posture"))
            if previous_posture not in MBOT_ALLOWED_ACTIONS:
                raise ValueError("PREVIOUS_POSTURE_INVALID")
            method_ts = _time("method_ts", snapshot.get("method_ts"))
            market_ts = _time("market_ts", snapshot.get("market_ts"))
            if market_ts < method_ts:
                raise ValueError("TIMESTAMP_ORDER")
            metrics = {
                "method_fit_score": _score("method_fit_score", snapshot.get("method_fit_score")),
                "range_quality_score": _score("range_quality_score", snapshot.get("range_quality_score")),
                "timing_quality_score": _score("timing_quality_score", snapshot.get("timing_quality_score")),
                "retest_quality_score": _score("retest_quality_score", snapshot.get("retest_quality_score")),
                "entry_quality_score": _score("entry_quality_score", snapshot.get("entry_quality_score")),
                "volatility_fit_score": _score("volatility_fit_score", snapshot.get("volatility_fit_score")),
                "conflict_score": _score("conflict_score", snapshot.get("conflict_score")),
                "helper_need_score": _score("helper_need_score", snapshot.get("helper_need_score")),
                "confidence_score": _score("confidence_score", snapshot.get("confidence_score")),
                "method_age_min": (market_ts - method_ts).total_seconds() / 60.0,
            }
        except (TypeError, ValueError) as exc:
            return _hold(f"MBOT_INPUT_INVALID:{exc}")

        conflict_flags = tuple(_text(code) for code in evidence.get("conflict_flags", ()) if _text(code))
        helper_flags = tuple(_text(code) for code in evidence.get("helper_flags", ()) if _text(code))
        rules = evidence.get("rules")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)) or not rules:
            return _hold("MBOT_SSOT_RULES_MISSING")

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
                if action not in MBOT_ALLOWED_ACTIONS or priority < 0 or not unit:
                    raise ValueError(f"RULE_POLICY:{rule_id}")
                if action == "route_change" and category not in {"method", "helper", "conflict"}:
                    raise ValueError(f"ROUTE_CHANGE_CATEGORY:{rule_id}")
                if not _source_ok(rule.get("source_id")):
                    raise ValueError(f"RULE_SOURCE:{rule_id}")
                method_states = tuple(_text(value).lower() for value in rule.get("method_states", ()) if _text(value))
                range_states = tuple(_text(value).lower() for value in rule.get("range_states", ()) if _text(value))
                from_postures = tuple(_text(value) for value in rule.get("from_postures", ()) if _text(value))
                if method_states and any(value not in ALLOWED_METHOD_STATES for value in method_states):
                    raise ValueError(f"RULE_METHOD_STATE:{rule_id}")
                if range_states and any(value not in ALLOWED_RANGE_STATES for value in range_states):
                    raise ValueError(f"RULE_RANGE_STATE:{rule_id}")
                if from_postures and any(value not in MBOT_ALLOWED_ACTIONS for value in from_postures):
                    raise ValueError(f"RULE_FROM_POSTURE:{rule_id}")
                if method_states and method_fit not in method_states:
                    continue
                if range_states and range_state not in range_states:
                    continue
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
            return _hold(f"MBOT_RULE_INVALID:{exc}")

        matched_categories = {row["category"] for row in matched}
        if method_fit in {"mismatch", "unknown"} and "method" not in matched_categories:
            return _hold("MBOT_UNRESOLVED_METHOD_FIT", f"MBOT_METHOD_STATE:{method_fit}")
        if range_state == "unknown" and "range" not in matched_categories:
            return _hold("MBOT_UNRESOLVED_RANGE_STATE")
        if conflict_flags and "conflict" not in matched_categories:
            return _hold("MBOT_UNRESOLVED_CONFLICT_FLAGS", *(f"MBOT_CONFLICT:{code}" for code in conflict_flags))
        if helper_flags and "helper" not in matched_categories:
            return _hold("MBOT_UNRESOLVED_HELPER_FLAGS", *(f"MBOT_HELPER:{code}" for code in helper_flags))
        if not matched:
            return Assessment("hold", metrics["confidence_score"], False, False, ("MBOT_METHOD_WITHIN_SSOT",))

        selected = max(
            matched,
            key=lambda row: (
                CATEGORY_PRIORITY[row["category"]], row["priority"],
                ACTION_PRIORITY[row["action"]], abs(row["value"] - row["limit"]),
            ),
        )
        reasons = [f"MBOT_METHOD_STATE:{method_fit}", f"MBOT_RANGE_STATE:{range_state}"]
        reasons.extend(f"MBOT_CONFLICT:{code}" for code in conflict_flags)
        reasons.extend(f"MBOT_HELPER:{code}" for code in helper_flags)
        reasons.extend(
            f"MBOT_RULE:{row['category']}:{row['rule_id']}:{row['metric']}={row['value']:.6f}{row['unit']}:limit={row['limit']:.6f}{row['unit']}"
            for row in sorted(matched, key=lambda row: (-CATEGORY_PRIORITY[row["category"]], -row["priority"], row["rule_id"]))
        )
        return Assessment(selected["action"], metrics["confidence_score"], False, False, tuple(dict.fromkeys(reasons)))
