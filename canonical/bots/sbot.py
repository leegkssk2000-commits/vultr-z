from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .base import Assessment, CanonicalBot
from .contracts import ALLOWED_ACTIONS, BotRequest, BotResponse

CANONICAL_SOURCES = ("cf:", "sheets:")
MIN_DATA = (
    "price", "pos_pct", "lev", "entry_ts", "market_ts",
    "funding_8h_pct", "dd_day_pct", "dd_total_pct", "sl_present",
)
SEVERITY = {"m": 1, "M": 2, "C": 3}
ACTION_PRIORITY = {
    "hold": 0, "reduce25": 1, "partial30": 2, "route_change": 3,
    "rollback": 4, "stop": 5, "block": 6,
}
OPERATORS = {
    "gt": lambda value, limit: value > limit,
    "gte": lambda value, limit: value >= limit,
    "lt": lambda value, limit: value < limit,
    "lte": lambda value, limit: value <= limit,
    "eq": lambda value, limit: value == limit,
    "neq": lambda value, limit: value != limit,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(name: str, value: Any, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}:BOOLEAN")
    result = float(value)
    if not isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name}:INVALID")
    return result


def _time(name: str, value: Any) -> datetime:
    raw = _text(value)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name}:TZ_REQUIRED")
    return parsed


def _source_ok(value: Any) -> bool:
    return _text(value).startswith(CANONICAL_SOURCES)


def _hold(*reasons: str) -> Assessment:
    return Assessment("hold", 0.0, True, False, tuple(dict.fromkeys(reasons)))


class SBot(CanonicalBot):
    bot_id = "SBot"
    semantic_role = "safety_hard_veto_soft_penalty"
    required_evidence = ("hard_violations", "soft_penalties", "risk_state")

    def evaluate(self, request: BotRequest) -> BotResponse:
        if request.data_state != "FRESH":
            return self._response(request, _hold(f"SBOT_DATA_{request.data_state}"))
        if not request.source_ids or not request.evidence_ids:
            return self._response(request, _hold("SBOT_LINEAGE_SOURCE_MISSING"))
        return self._response(request, self._assess(request.role_evidence, side=request.side))

    def assess(self, evidence: Mapping[str, Any]) -> Assessment:
        return self._assess(evidence, side=_text(evidence.get("side")) or "long")

    def _assess(self, evidence: Mapping[str, Any], *, side: str) -> Assessment:
        hard = tuple(_text(code) for code in evidence.get("hard_violations", ()) if _text(code))
        if hard:
            return Assessment("block", 1.0, False, True, tuple(f"SBOT_HARD:{code}" for code in hard))

        integrity = evidence.get("integrity")
        if not isinstance(integrity, Mapping) or integrity.get("ok") is not True:
            return _hold("SBOT_INTEGRITY_UNCONFIRMED")
        failed = tuple(
            key for key in ("missing", "disconnected", "ts_anomaly", "key_mismatch", "stale")
            if bool(integrity.get(key))
        )
        if failed:
            return _hold(*(f"SBOT_INTEGRITY:{key}" for key in failed))

        snapshot = evidence.get("snapshot")
        sources = evidence.get("metric_sources")
        if not isinstance(snapshot, Mapping) or not isinstance(sources, Mapping):
            return _hold("SBOT_SNAPSHOT_OR_SOURCE_MAP_MISSING")
        missing = [key for key in MIN_DATA if key not in snapshot]
        liquidation_key = "liq_buffer_pct" if snapshot.get("liq_buffer_pct") is not None else "liq_price"
        if liquidation_key not in snapshot:
            missing.append("liq_price|liq_buffer_pct")
        if missing:
            return _hold(f"SBOT_MIN_DATA_MISSING:{','.join(sorted(missing))}")
        source_keys = tuple(MIN_DATA) + (liquidation_key,)
        source_gaps = [key for key in source_keys if not _source_ok(sources.get(key))]
        if source_gaps:
            return _hold(f"SBOT_SOURCE_MISSING:{','.join(sorted(source_gaps))}")

        if snapshot.get("sl_present") is not True:
            return Assessment("block", 1.0, False, True, ("SBOT_HARD:SL_MISSING",))
        if snapshot.get("order_channel_ok") is False:
            return Assessment("block", 1.0, False, True, ("SBOT_HARD:ORDER_CHANNEL_UNAVAILABLE",))

        try:
            price = _number("price", snapshot.get("price"), minimum=0.0)
            pos_pct = _number("pos_pct", snapshot.get("pos_pct"), minimum=0.0)
            lev = _number("lev", snapshot.get("lev"), minimum=0.0)
            entry_ts = _time("entry_ts", snapshot.get("entry_ts"))
            market_ts = _time("market_ts", snapshot.get("market_ts"))
            if market_ts < entry_ts:
                raise ValueError("TIMESTAMP_ORDER")
            if liquidation_key == "liq_buffer_pct":
                liq_buffer = _number("liq_buffer_pct", snapshot.get("liq_buffer_pct"), minimum=0.0)
            else:
                liq_price = _number("liq_price", snapshot.get("liq_price"), minimum=0.0)
                if side.lower() == "long":
                    liq_buffer = (price - liq_price) / price * 100.0
                elif side.lower() == "short":
                    liq_buffer = (liq_price - price) / price * 100.0
                else:
                    raise ValueError("SIDE_INVALID")
                if liq_buffer < 0.0:
                    raise ValueError("LIQ_BUFFER_NEGATIVE")
            metrics = {
                "price": price,
                "pos_pct": pos_pct,
                "lev": lev,
                "exposure_pct_x": lev * pos_pct,
                "funding_8h_pct": _number("funding_8h_pct", snapshot.get("funding_8h_pct")),
                "abs_funding_8h_pct": abs(_number("funding_8h_pct", snapshot.get("funding_8h_pct"))),
                "dd_day_pct": _number("dd_day_pct", snapshot.get("dd_day_pct"), minimum=0.0),
                "dd_total_pct": _number("dd_total_pct", snapshot.get("dd_total_pct"), minimum=0.0),
                "liq_buffer_pct": liq_buffer,
                "time_exposure_min": (market_ts - entry_ts).total_seconds() / 60.0,
            }
        except (TypeError, ValueError) as exc:
            return _hold(f"SBOT_INPUT_INVALID:{exc}")

        rules = evidence.get("rules")
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)) or not rules:
            return _hold("SBOT_SSOT_RULES_MISSING")

        breaches: list[dict[str, Any]] = []
        try:
            for rule in rules:
                if not isinstance(rule, Mapping):
                    raise ValueError("RULE_NOT_OBJECT")
                rule_id = _text(rule.get("rule_id"))
                metric = _text(rule.get("metric"))
                operator = _text(rule.get("operator"))
                severity = _text(rule.get("severity"))
                action = _text(rule.get("action"))
                unit = _text(rule.get("unit"))
                if not rule_id or metric not in metrics or operator not in OPERATORS:
                    raise ValueError(f"RULE_SHAPE:{rule_id}:{metric}:{operator}")
                if severity not in SEVERITY or action not in ALLOWED_ACTIONS or not unit:
                    raise ValueError(f"RULE_POLICY:{rule_id}")
                if not _source_ok(rule.get("source_id")):
                    raise ValueError(f"RULE_SOURCE:{rule_id}")
                limit = _number(f"limit:{rule_id}", rule.get("limit"))
                value = metrics[metric]
                if OPERATORS[operator](value, limit):
                    breaches.append({
                        "rule_id": rule_id, "metric": metric, "value": value,
                        "limit": limit, "unit": unit, "severity": severity, "action": action,
                    })
        except (TypeError, ValueError) as exc:
            return _hold(f"SBOT_RULE_INVALID:{exc}")

        if not breaches:
            soft = tuple(_text(code) for code in evidence.get("soft_penalties", ()) if _text(code))
            reasons = tuple(f"SBOT_SOFT:{code}" for code in soft) or ("SBOT_RISK_WITHIN_SSOT",)
            return Assessment("hold", 0.95, False, False, reasons)

        selected = max(
            breaches,
            key=lambda row: (SEVERITY[row["severity"]], ACTION_PRIORITY[row["action"]], abs(row["value"] - row["limit"])),
        )
        reasons = tuple(
            f"SBOT_BREACH:{row['severity']}:{row['rule_id']}:{row['metric']}={row['value']:.6f}{row['unit']}:limit={row['limit']:.6f}{row['unit']}"
            for row in sorted(breaches, key=lambda row: (-SEVERITY[row["severity"]], row["rule_id"]))
        )
        return Assessment(
            selected["action"],
            min(1.0, 0.75 + 0.05 * len(breaches)),
            False,
            selected["severity"] == "C",
            reasons,
        )
