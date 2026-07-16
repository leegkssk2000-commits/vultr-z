from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .base import Assessment, CanonicalBot
from .contracts import BotRequest, BotResponse

CAPABILITY_TAGS = ("breakout", "fakeout", "momentum", "anomaly", "exhaustion", "mfe_mae")
CANONICAL_SOURCES = ("cf:", "sheets:")
OBOT_ALLOWED_ACTIONS = frozenset({"hold", "reduce25", "partial30", "route_change"})
ALLOWED_BREAKOUT_STATES = frozenset({"confirmed", "pending", "failed", "none", "unknown"})
ALLOWED_CATEGORIES = frozenset({"breakout", "fakeout", "momentum", "anomaly", "exhaustion", "mfe_mae"})
CATEGORY_PRIORITY = {"breakout": 1, "momentum": 2, "mfe_mae": 3, "exhaustion": 4, "fakeout": 5, "anomaly": 6}
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
    "breakout_quality_score",
    "fakeout_risk_score",
    "momentum_score",
    "anomaly_score",
    "exhaustion_score",
    "mfe_score",
    "mae_score",
    "volume_confirmation_score",
    "confidence_score",
    "signal_ts",
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


class OBot(CanonicalBot):
    bot_id = "OBot"
    semantic_role = "observer_breakout_anomaly"
    required_evidence = (
        "breakout_state", "fakeout_flags", "anomaly_flags", "exhaustion_flags",
        "integrity", "snapshot", "metric_sources", "rules",
    )

    def evaluate(self, request: BotRequest) -> BotResponse:
        if request.data_state != "FRESH":
            return self._response(request, _hold(f"OBOT_DATA_{request.data_state}"))
        if not request.source_ids or not request.evidence_ids:
            return self._response(request, _hold("OBOT_LINEAGE_SOURCE_MISSING"))
        return self._response(request, self._assess(request.role_evidence))

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return self._assess(evidence)

    def _assess(self, evidence: Mapping[str, Any]) -> Assessment:
        breakout_state = _text(evidence.get("breakout_state")).lower()
        if breakout_state not in ALLOWED_BREAKOUT_STATES:
            return _hold("OBOT_BREAKOUT_STATE_INVALID")

        integrity = evidence.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("ok") is not True:
            return _hold("OBOT_INTEGRITY_UNCONFIRMED")
        failed = tuple(
            key for key in ("missing", "disconnected", "ts_anomaly", "key_mismatch", "stale")
            if bool(integrity.get(key))
        )
        if failed:
            return _hold(*(f"OBOT_INTEGRITY:{key}" for key in failed))

        snapshot = evidence.get("snapshot")
        sources = evidence.get("metric_sources")
        if not isinstance(snapshot, Mapping) or not isinstance(sources, Mapping):
            return _hold("OBOT_SNAPSHOT_OR_SOURCE_MAP_MISSING")
        missing = [key for key in SNAPSHOT_FIELDS if key not in snapshot]
        if missing:
            return _hold(f"OBOT_MIN_DATA_MISSING:{','.join(sorted(missing))}")
        source_gaps = [key for key in SNAPSHOT_FIELDS if not _source_ok(sources.get(key))]
        if source_gaps:
            return _hold(f"OBOT_SOURCE_MISSING:{','.join(sorted(source_gaps))}")

        try:
            previous_posture = _text(snapshot.get("previous_posture"))
            if previous_posture not in OBOT_ALLOWED_ACTIONS:
                raise ValueError("PREVIOUS_POSTURE_INVALID")
            signal_ts = _time("signal_ts", snapshot.get("signal_ts"))
            market_ts = _time("market_ts", snapshot.get("market_ts"))
            if market_ts < signal_ts:
                raise ValueError("TIMESTAMP_ORDER")
            mfe_score = _score("mfe_score", snapshot.get("mfe_score"))
            mae_score = _score("mae_score", snapshot.get("mae_score"))
            metrics = {
                "breakout_quality_score": _score("breakout_quality_score", snapshot.get("breakout_quality_score")),
                "fakeout_risk_score": _score("fakeout_risk_score", snapshot.get("fakeout_risk_score")),
                "momentum_score": _score("momentum_score", snapshot.get("momentum_score")),
                "anomaly_score": _score("anomaly_score", snapshot.get("anomaly_score")),
                "exhaustion_score": _score("exhaustion_score", snapshot.get("exhaustion_score")),
                "mfe_score": mfe_score,
                "mae_score": mae_score,
                "volume_confirmation_score": _score("volume_confirmation_score", snapshot.get("volume_confirmation_score")),
                "confidence_score": _score("confidence_score", snapshot.get("confidence_score")),
                "mfe_mae_spread": mfe_score - mae_score,
                "signal_age_min": (market_ts - signal_ts).total_seconds() / 60.0,
            }
        except (TypeError, ValueError) as exc:
            return _hold(f"OBOT_INPUT_INVALID:{exc}")

        fakeout_flags = tuple(_text(code) for code in evidence.get("fakeout_flags", ()) if _text(code))
        anomaly_flags = tuple(_text(code) for code in evidence.get("anomaly_flags", ()) if _text(code))
        exhaustion_flags = tuple(_text(code) for code in evidence.get("exhaustion_flags", ()) if _text(code))
        rules = evidence.get("rules")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)) or not rules:
            return _hold("OBOT_SSOT_RULES_MISSING")

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
                if action not in OBOT_ALLOWED_ACTIONS or priority < 0 or not unit:
                    raise ValueError(f"RULE_POLICY:{rule_id}")
                if action == "route_change" and category not in {"breakout", "fakeout", "anomaly"}:
                    raise ValueError(f"ROUTE_CHANGE_CATEGORY:{rule_id}")
                if not _source_ok(rule.get("source_id")):
                    raise ValueError(f"RULE_SOURCE:{rule_id}")
                breakout_states = tuple(_text(value).lower() for value in rule.get("breakout_states", ()) if _text(value))
                from_postures = tuple(_text(value) for value in rule.get("from_postures", ()) if _text(value))
                if breakout_states and any(value not in ALLOWED_BREAKOUT_STATES for value in breakout_states):
                    raise ValueError(f"RULE_BREAKOUT_STATE:{rule_id}")
                if from_postures and any(value not in OBOT_ALLOWED_ACTIONS for value in from_postures):
                    raise ValueError(f"RULE_FROM_POSTURE:{rule_id}")
                if breakout_states and breakout_state not in breakout_states:
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
            return _hold(f"OBOT_RULE_INVALID:{exc}")

        matched_categories = {row["category"] for row in matched}
        if breakout_state in {"failed", "unknown"} and "breakout" not in matched_categories:
            return _hold("OBOT_UNRESOLVED_BREAKOUT_STATE", f"OBOT_BREAKOUT_STATE:{breakout_state}")
        if fakeout_flags and "fakeout" not in matched_categories:
            return _hold("OBOT_UNRESOLVED_FAKEOUT_FLAGS", *(f"OBOT_FAKEOUT:{code}" for code in fakeout_flags))
        if anomaly_flags and "anomaly" not in matched_categories:
            return _hold("OBOT_UNRESOLVED_ANOMALY_FLAGS", *(f"OBOT_ANOMALY:{code}" for code in anomaly_flags))
        if exhaustion_flags and "exhaustion" not in matched_categories:
            return _hold("OBOT_UNRESOLVED_EXHAUSTION_FLAGS", *(f"OBOT_EXHAUSTION:{code}" for code in exhaustion_flags))
        if not matched:
            return Assessment("hold", metrics["confidence_score"], False, False, ("OBOT_MARKET_WITHIN_SSOT",))

        selected = max(
            matched,
            key=lambda row: (
                CATEGORY_PRIORITY[row["category"]], row["priority"],
                ACTION_PRIORITY[row["action"]], abs(row["value"] - row["limit"]),
            ),
        )
        reasons = [f"OBOT_BREAKOUT_STATE:{breakout_state}"]
        reasons.extend(f"OBOT_FAKEOUT:{code}" for code in fakeout_flags)
        reasons.extend(f"OBOT_ANOMALY:{code}" for code in anomaly_flags)
        reasons.extend(f"OBOT_EXHAUSTION:{code}" for code in exhaustion_flags)
        reasons.extend(
            f"OBOT_RULE:{row['category']}:{row['rule_id']}:{row['metric']}={row['value']:.6f}{row['unit']}:limit={row['limit']:.6f}{row['unit']}"
            for row in sorted(matched, key=lambda row: (-CATEGORY_PRIORITY[row["category"]], -row["priority"], row["rule_id"]))
        )
        return Assessment(selected["action"], metrics["confidence_score"], False, False, tuple(dict.fromkeys(reasons)))
