"""Frozen causal Router V2 adapter; this module never reads outcomes or refits.

The caller owns the durable event ledger and closed-cohort watermark. Historical
V2 results remain unchanged. Missing lane/data bindings produce HOLD and CASH.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ARTIFACTS = {
    "v1": "causal_strategy_failover_router_v1_results.json",
    "v2": "strategy_specific_failover_router_v2_results.json",
    "features": "strategy_regime_alpha_matrix_v1_results.json",
    "crowding": "economic_core_crowding_allocator_v5_results.json",
}
ACTIVE = frozenset({"KELTNER", "RIDER", "SQUEEZE", "MR"})
HOUR_MS = 3_600_000


def number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("NON_NUMERIC_INPUT")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("NONFINITE_INPUT") from exc
    if not math.isfinite(result):
        raise ValueError("NONFINITE_INPUT")
    return result


def timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("INVALID_TIMESTAMP")
    return value


def digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class FrozenSpec:
    artifacts: dict[str, dict[str, Any]]
    hashes: dict[str, str]
    lane_bindings: dict[str, dict[str, str]]
    data_stale_ms: int | None
    forward_start_ts_ms: int
    rule_hash: str


def load_frozen_spec(
    directory: Path,
    expected_hashes: dict[str, str],
    lane_bindings: dict[str, dict[str, str]],
    data_stale_ms: int | None,
    forward_start_ts_ms: int,
) -> FrozenSpec:
    """Read hash-pinned saved receipts, never regenerate thresholds or state maps."""
    artifacts: dict[str, dict[str, Any]] = {}
    for key, name in ARTIFACTS.items():
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hashes.get(key):
            raise ValueError(f"FROZEN_ARTIFACT_HASH_MISMATCH:{key}")
        artifacts[key] = json.loads(raw)
    if artifacts["v1"]["chosen"] != "STATE_GATE_FAILOVER_1.00":
        raise ValueError("UNSUPPORTED_FROZEN_FAILOVER_RULE")
    if not artifacts["v2"]["train_selected"]:
        raise ValueError("UNSELECTED_ROUTER_V2")
    if artifacts["crowding"]["chosen"] != "CAP_1.0":
        raise ValueError("UNSUPPORTED_CROWDING_RULE")
    cutoffs = {timestamp(a["cutoff_ts"]) for a in artifacts.values()}
    if len(cutoffs) != 1:
        raise ValueError("FROZEN_CUTOFF_MISMATCH")
    for value in artifacts["features"]["regime_thresholds_train_only"].values():
        number(value)
    maps = artifacts["v1"]["state_maps"]
    if set(maps) != ACTIVE:
        raise ValueError("UNSUPPORTED_FROZEN_LANES")
    for item in maps.values():
        for level in item["levels"]:
            for cell in level["states"].values():
                if number(cell["risk"]) not in (0.25, 0.5, 1.0):
                    raise ValueError("UNSUPPORTED_FROZEN_RISK")
    if data_stale_ms is not None:
        timestamp(data_stale_ms)
    timestamp(forward_start_ts_ms)
    bound = {
        "hashes": expected_hashes,
        "lane_bindings": lane_bindings,
        "data_stale_ms": data_stale_ms,
        "forward_start_ts_ms": forward_start_ts_ms,
        "adapter": "economic7_frozen_forward_router_v1",
        "adapter_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cohort_policy": "exact_decision_timestamp_closed_cohort",
    }
    return FrozenSpec(
        artifacts,
        dict(expected_hashes),
        copy.deepcopy(lane_bindings),
        data_stale_ms,
        forward_start_ts_ms,
        digest(bound),
    )


class FrozenForwardRouter:
    """Sequential closed cohorts; callers persist checkpoint with each receipt."""

    def __init__(self, spec: FrozenSpec, checkpoint: dict[str, Any] | None = None):
        self.spec = copy.deepcopy(spec)
        self.last_ts = -1
        self.squeeze_hour = -1
        self.squeeze_count = 0
        self.seen_setup_ids: set[str] = set()
        if checkpoint is not None:
            payload = {k: v for k, v in checkpoint.items() if k != "checkpoint_hash"}
            if checkpoint.get("checkpoint_hash") != digest(payload):
                raise ValueError("CHECKPOINT_CHECKSUM_MISMATCH")
            seen = checkpoint["seen_setup_ids"]
            if not isinstance(seen, list) or any(
                not isinstance(x, str) or not x for x in seen
            ):
                raise ValueError("CHECKPOINT_SETUP_IDS_INVALID")
            self.seen_setup_ids = set(seen)
            if checkpoint["rule_hash"] != spec.rule_hash:
                raise ValueError("CHECKPOINT_RULE_HASH_MISMATCH")
            if (
                checkpoint["last_ts"] == -1
                and checkpoint["squeeze_hour"] == -1
                and checkpoint["squeeze_count"] == 0
            ):
                return
            self.last_ts = timestamp(checkpoint["last_ts"])
            self.squeeze_hour = timestamp(checkpoint["squeeze_hour"])
            self.squeeze_count = timestamp(checkpoint["squeeze_count"])

    def checkpoint(self) -> dict[str, Any]:
        payload = {
            "rule_hash": self.spec.rule_hash,
            "last_ts": self.last_ts,
            "squeeze_hour": self.squeeze_hour,
            "squeeze_count": self.squeeze_count,
            "seen_setup_ids": sorted(self.seen_setup_ids),
        }
        return dict(payload, checkpoint_hash=digest(payload))

    def _row(self, event: dict[str, Any], decision_ts: int) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise ValueError("EVENT_MAPPING_REQUIRED")
        lane = str(event["lane"])
        binding = self.spec.lane_bindings.get(lane)
        if lane not in ACTIVE or not binding:
            raise ValueError(f"LANE_UNBOUND:{lane}")
        for key in ("rule_hash", "code_sha"):
            if not binding.get(key) or event.get(key) != binding[key]:
                raise ValueError(f"LANE_BINDING_MISMATCH:{lane}:{key}")
        side = event["side"]
        if side not in ("long", "short", "market_neutral"):
            raise ValueError("SIDE_UNBOUND")
        if lane != "MR" and side == "market_neutral":
            raise ValueError("SIDE_UNBOUND")
        if lane == "SQUEEZE" and side != "long":
            raise ValueError("SQUEEZE_FROZEN_LONG_ONLY")
        if timestamp(event["decision_ts_ms"]) != decision_ts:
            raise ValueError("MIXED_DECISION_COHORT")
        signal_ts = timestamp(event["signal_ts_ms"])
        available = timestamp(event["available_at_ms"])
        if not self.spec.forward_start_ts_ms <= signal_ts <= available <= decision_ts:
            raise ValueError("SIGNAL_NOT_FRESH_OR_NOT_YET_AVAILABLE")
        feature = event["features"]
        if not isinstance(feature, dict):
            raise ValueError("FEATURE_MAPPING_REQUIRED")
        opened, closed, ready = (
            timestamp(feature[k])
            for k in ("bar_open_ts_ms", "bar_close_ts_ms", "available_at_ms")
        )
        if not opened < closed <= ready <= decision_ts:
            raise ValueError("FEATURE_NOT_YET_CLOSED_OR_AVAILABLE")
        if self.spec.data_stale_ms is None:
            raise ValueError("DATA_STALE_SSOT_UNBOUND")
        if decision_ts - available > self.spec.data_stale_ms:
            raise ValueError("SIGNAL_STALE")
        if decision_ts - closed > self.spec.data_stale_ms:
            raise ValueError("FEATURE_STALE")
        setup = event["setup_evidence"]
        if not isinstance(setup, dict):
            raise ValueError("SETUP_MAPPING_REQUIRED")
        if setup.get("valid") is not True or setup.get("independent") is not True:
            raise ValueError("NO_INDEPENDENT_VALID_SETUP")
        if timestamp(setup["available_at_ms"]) > decision_ts:
            raise ValueError("SETUP_NOT_YET_AVAILABLE")
        if decision_ts - timestamp(setup["available_at_ms"]) > self.spec.data_stale_ms:
            raise ValueError("SETUP_STALE")
        for source in (event, feature, setup):
            if not source.get("source") or not source.get("content_hash"):
                raise ValueError("SOURCE_HASH_UNBOUND")
            canonical = {k: v for k, v in source.items() if k != "content_hash"}
            if source["content_hash"] != digest(canonical):
                raise ValueError("SOURCE_PAYLOAD_HASH_MISMATCH")
        q = self.spec.artifacts["features"]["regime_thresholds_train_only"]
        mean_abs, dispersion, breadth, vol = (
            number(feature[k])
            for k in ("mean_abs24", "dispersion24", "breadth", "vol_ratio")
        )
        if mean_abs < 0 or dispersion < 0 or vol <= 0 or abs(breadth) > 6:
            raise ValueError("FEATURE_OUT_OF_DOMAIN")
        if mean_abs >= q["meanabs_q85"] and dispersion >= q["disp_q67"]:
            regime = "PANIC_DISPERSION"
        elif abs(breadth) >= 4:
            regime = (
                "TREND_DISPERSED" if dispersion >= q["disp_q67"] else "TREND_COHERENT"
            )
        elif vol <= q["vol_q25"]:
            regime = "COMPRESSION"
        elif vol >= q["vol_q67"]:
            regime = "VOL_EXPANSION_MIXED"
        else:
            regime = "RANGE_MIXED"
        if (
            (
                lane == "KELTNER"
                and regime not in ("PANIC_DISPERSION", "TREND_DISPERSED")
            )
            or (lane == "RIDER" and regime != "TREND_COHERENT")
            or (lane == "SQUEEZE" and regime != "PANIC_DISPERSION")
        ):
            raise ValueError("LANE_REGIME_NOT_ELIGIBLE")
        state = {
            "regime": regime,
            "vol_state": (
                "LOW"
                if vol <= q["vol_q25"]
                else "HIGH" if vol >= q["vol_q67"] else "MID"
            ),
            "breadth_state": (
                "B6" if abs(breadth) >= 6 else "B4" if abs(breadth) >= 4 else "MIXED"
            ),
        }
        risk, health = 0.5, "AMBER_INSUFFICIENT_EXACT_STATE"
        for level in self.spec.artifacts["v1"]["state_maps"][lane]["levels"]:
            cell = level["states"].get("|".join(state[k] for k in level["columns"]))
            if cell is not None:
                risk, health = number(cell["risk"]), str(cell["label"])
                break
        base_risk, reason = 1.0, "V1_HIERARCHICAL_STATE"
        if lane == "RIDER":
            crowd = self.spec.artifacts["crowding"]
            load = timestamp(feature["prior_signal_load24"])
            base_risk = number(crowd["base_rider_weight_train_only"])
            base_risk *= (
                0.0
                if vol > crowd["vol_q85_train_only"]
                else 0.25 if vol > q["vol_q67"] else 1.0
            )
            base_risk *= 0.5 if load >= crowd["signal_load24_q85_train_only"] else 1.0
            aligned = number(feature["ema21"]) > number(feature["ema55"])
            if (
                side == "long"
                and risk < 1
                and state["vol_state"] == "MID"
                and state["breadth_state"] == "B4"
                and aligned
            ):
                risk, health, reason = 1.0, "GREEN", "RIDER_TREND_ALIGNMENT_PRESERVE"
        if lane == "SQUEEZE":
            number(feature["market_vol_delta3"])
        if any(
            not isinstance(event.get(key), str) or not event[key]
            for key in ("setup_id", "symbol")
        ):
            raise ValueError("EVENT_IDENTITY_UNBOUND")
        return {
            "setup_id": event["setup_id"],
            "lane": lane,
            "symbol": event["symbol"],
            "side": side,
            "signal_ts_ms": signal_ts,
            "decision_ts_ms": decision_ts,
            "state_snapshot": copy.deepcopy(feature),
            "setup_evidence": copy.deepcopy(setup),
            "state": state,
            "health": health,
            "state_risk": risk,
            "base_risk": base_risk,
            "reason": reason,
            "code_sha": event["code_sha"],
            "lane_rule_hash": event["rule_hash"],
            "event_content_hash": event["content_hash"],
            "event_source": event["source"],
        }

    def decide(
        self,
        events: list[dict[str, Any]],
        decision_ts_ms: int,
        *,
        closed_cohort: bool,
        existing_rider_exposure: dict[str, float],
    ) -> dict[str, Any]:
        before = self.checkpoint()
        try:
            decision_ts = timestamp(decision_ts_ms)
            if closed_cohort is not True or decision_ts <= self.last_ts:
                raise ValueError("COHORT_UNCLOSED_OR_OLD_AMENDMENT")
            if not events:
                raise ValueError("EMPTY_COHORT")
            exposure = {
                side: number(existing_rider_exposure[side])
                for side in ("long", "short")
            }
            if any(value < 0 for value in exposure.values()):
                raise ValueError("NEGATIVE_EXISTING_EXPOSURE")
            rows = [self._row(event, decision_ts) for event in events]
            if len({r["setup_id"] for r in rows}) != len(rows):
                raise ValueError("DUPLICATE_SETUP_IN_COHORT")
            if any(str(row["setup_id"]) in self.seen_setup_ids for row in rows):
                raise ValueError("DUPLICATE_SETUP_PRIOR_COHORT")
            hour = decision_ts // HOUR_MS
            count = self.squeeze_count if self.squeeze_hour == hour else 0
            count += sum(r["lane"] == "SQUEEZE" for r in rows)
            for row in rows:
                if row["lane"] == "SQUEEZE" and count >= 2:
                    f = row["state_snapshot"]
                    if not (
                        row["state"]["vol_state"] == "HIGH"
                        and f["market_vol_delta3"] > 0
                    ):
                        row.update(
                            state_risk=min(row["state_risk"], 0.25),
                            health="RED",
                            reason="SQUEEZE_OBSERVED_MULTI_FIRE_VOL_GUARD",
                        )
                row["squeeze_observed_same_hour_count"] = count
                row["chosen_risk_multiplier"] = row["base_risk"] * row["state_risk"]
            for side in ("long", "short"):
                group = [r for r in rows if r["lane"] == "RIDER" and r["side"] == side]
                total = sum(r["chosen_risk_multiplier"] for r in group)
                scale = (
                    min(1.0, max(0.0, 1.0 - exposure[side]) / total) if total else 1.0
                )
                for row in group:
                    row["chosen_risk_multiplier"] *= scale
                    row["crowding_scale"] = scale
            suppressed = sum(
                max(0.0, r["base_risk"] - r["chosen_risk_multiplier"]) for r in rows
            )
            remaining = suppressed
            receivers = [
                r
                for r in rows
                if r["health"] == "GREEN"
                and r["state_risk"] == 1.0
                and r["chosen_risk_multiplier"] > 0
            ]
            # Only another lane can receive; same-lane released risk is not recycled.
            allocations: list[dict[str, Any]] = []
            for payer in sorted(rows, key=lambda r: str(r["setup_id"])):
                released = max(
                    0.0, payer["base_risk"] - payer["chosen_risk_multiplier"]
                )
                eligible = [r for r in receivers if r["lane"] != payer["lane"]]
                for receiver in sorted(eligible, key=lambda r: str(r["setup_id"])):
                    room = (
                        receiver["base_risk"] * 2.0 - receiver["chosen_risk_multiplier"]
                    )
                    if receiver["lane"] == "RIDER":
                        used = sum(
                            r["chosen_risk_multiplier"]
                            for r in rows
                            if r["lane"] == "RIDER" and r["side"] == receiver["side"]
                        )
                        room = min(
                            room, max(0.0, 1.0 - exposure[receiver["side"]] - used)
                        )
                    extra = min(released, max(0.0, room))
                    if extra > 0:
                        receiver["chosen_risk_multiplier"] += extra
                        allocations.append(
                            {
                                "payer": payer["setup_id"],
                                "receiver": receiver["setup_id"],
                                "risk": extra,
                                "receiver_setup_evidence": copy.deepcopy(
                                    receiver["setup_evidence"]
                                ),
                            }
                        )
                        released -= extra
                        remaining -= extra
            for row in rows:
                row["suppressed_risk"] = max(
                    0.0, row["base_risk"] - row["chosen_risk_multiplier"]
                )
                row["action"] = "hold"
                row["cash_fallback"] = remaining > 1e-12
            assigned = sum(row["chosen_risk_multiplier"] for row in rows)
            budget = sum(row["base_risk"] for row in rows)
            if abs(assigned + remaining - budget) > 1e-9:
                raise ValueError("RISK_CONSERVATION_FAILURE")
            self.seen_setup_ids.update(str(row["setup_id"]) for row in rows)
            self.last_ts, self.squeeze_hour, self.squeeze_count = (
                decision_ts,
                hour,
                count,
            )
            return {
                "state": "FROZEN_SHADOW_ROUTED",
                "rule_hash": self.spec.rule_hash,
                "decision_ts_ms": decision_ts,
                "decisions": rows,
                "failover": allocations,
                "suppressed_risk": suppressed,
                "reallocated_risk": suppressed - remaining,
                "cash_risk": max(0.0, remaining),
                "cash_fallback": remaining > 1e-12,
                "checkpoint": self.checkpoint(),
                "order_authority": "BLOCKED",
                "promotion_authority": False,
            }
        except (ValueError, KeyError, TypeError) as exc:
            return {
                "state": "HOLD",
                "action": "hold",
                "reason": str(exc),
                "rule_hash": self.spec.rule_hash,
                "decisions": [],
                "failover": [],
                "cash_fallback": True,
                "checkpoint": before,
                "order_authority": "BLOCKED",
                "promotion_authority": False,
            }
