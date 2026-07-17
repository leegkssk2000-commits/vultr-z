from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _id(prefix: str, *parts: object) -> str:
    raw = "|".join(map(str, parts)).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()


def build_lane_events(source: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    required = (
        "source_event_id", "source_position_id", "source_sequence", "strategy_id",
        "strategy_source_sha256", "method_id", "symbol", "side", "entry_ts_ms",
        "observed_at_ms", "entry_price", "market_path_id", "cost_model_ref", "source_ref",
    )
    for key in required:
        if source.get(key) in (None, ""):
            reasons.append("SOURCE_FIELD_MISSING:" + key)
    if source.get("side") not in {"long", "short"}:
        reasons.append("SOURCE_SIDE_INVALID")
    if float(source.get("entry_price", 0) or 0) <= 0:
        reasons.append("ENTRY_PRICE_INVALID")
    if int(source.get("source_sequence", -1)) < 0:
        reasons.append("SOURCE_SEQUENCE_INVALID")
    source_digest = str(source.get("strategy_source_sha256", ""))
    if not source_digest.startswith("sha256:") or len(source_digest) != 71:
        reasons.append("STRATEGY_DIGEST_INVALID")
    entry_ts = int(source.get("entry_ts_ms", 0) or 0)
    observed_ts = int(source.get("observed_at_ms", 0) or 0)
    if entry_ts <= 0 or observed_ts <= 0 or entry_ts > observed_ts:
        reasons.append("SOURCE_TIMESTAMP_INVALID")
    elif observed_ts - entry_ts > 300000:
        reasons.append("SOURCE_ENTRY_STALE")
    if not str(source.get("source_ref", "")).startswith(("cf:", "sheets:", "runtime:")):
        reasons.append("SOURCE_REF_INVALID")
    templates = [row for row in projection.get("templates", []) if row.get("strategy_id") == source.get("strategy_id")]
    if len(templates) != 4:
        reasons.append("FOUR_EXIT_TEMPLATES_NOT_FOUND")
    if any(row.get("skill_set") != [] for row in templates):
        reasons.append("RAW_SKILL_CONTAMINATION")
    if any(row.get("cost_model_ref") != source.get("cost_model_ref") for row in templates):
        reasons.append("COST_MODEL_MISMATCH")
    events: list[dict[str, Any]] = []
    if not reasons:
        for row in sorted(templates, key=lambda item: str(item["exit_policy_id"])):
            template = str(row["lane_template_id"])
            events.append({
                "source_event_id": source["source_event_id"],
                "source_position_id": source["source_position_id"],
                "source_sequence": source["source_sequence"],
                "lane_event_id": _id("r73a.event.", source["source_event_id"], source["source_sequence"], template),
                "lane_position_id": _id("r73a.position.", source["source_position_id"], template),
                "lane_template_id": template,
                "strategy_id": source["strategy_id"],
                "method_id": source["method_id"],
                "exit_policy_id": row["exit_policy_id"],
                "symbol": source["symbol"],
                "side": source["side"],
                "entry_ts_ms": source["entry_ts_ms"],
                "entry_price": source["entry_price"],
                "market_path_id": source["market_path_id"],
                "cost_model_ref": source["cost_model_ref"],
                "skill_set": [],
                "state_namespace": row["state_namespace"],
                "cooldown_namespace": row["cooldown_namespace"],
                "observer_only": True,
                "execution_authority": "none",
                "order_authority": "blocked",
            })
    packed = json.dumps(events, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "state": "BRIDGE_READY" if not reasons else "HOLD",
        "reason_codes": ["SOURCE_ENTRY_FOUR_LANE_BRIDGE_READY"] if not reasons else sorted(set(reasons)),
        "lane_event_count": len(events),
        "bridge_sha256": "sha256:" + hashlib.sha256(packed).hexdigest() if events else "",
        "lane_events": events,
        "runtime_binding_allowed": False,
        "source_event_subscription_allowed": False,
        "formal_ledger_write_allowed": False,
    }
