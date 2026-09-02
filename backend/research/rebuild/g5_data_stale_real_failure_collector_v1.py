#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/g5_clean_runner_contract_v1.json"
DEFAULT_STATE_LOG = ROOT / "backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl"
DEFAULT_OUTPUT = ROOT / "backend/research/rebuild/g5_data_stale_real_failure_evidence_v1.json"
REQUIRED_TELEMETRY = (
    "source_event_ts",
    "source_received_ts",
    "bar_close_ts",
    "scheduler_fire_ts",
    "evaluation_start_ts",
    "evaluation_end_ts",
    "writer_ts",
    "evaluation_age_ms",
    "source_lag_ms",
    "scheduler_lag_ms",
    "evaluation_duration_ms",
)


class FailureEvidenceError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FailureEvidenceError(f"OBJECT_REQUIRED:{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            if not raw.endswith("\n"):
                raise FailureEvidenceError(f"PARTIAL_JSONL_RECORD:{number}")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise FailureEvidenceError(f"JSONL_OBJECT_REQUIRED:{number}")
            rows.append(value)
    return rows


def sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["receipt_sha256"] = sha_json(result)
    return result


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _telemetry(payload: Mapping[str, Any]) -> dict[str, int]:
    telemetry = payload.get("telemetry")
    if not isinstance(telemetry, Mapping):
        raise FailureEvidenceError("TELEMETRY_MISSING")
    missing = [name for name in REQUIRED_TELEMETRY if telemetry.get(name) is None]
    if missing:
        raise FailureEvidenceError("TELEMETRY_FIELDS_MISSING:" + ",".join(missing))
    result = {name: int(telemetry[name]) for name in REQUIRED_TELEMETRY}
    if result["source_event_ts"] != result["bar_close_ts"]:
        raise FailureEvidenceError("SOURCE_EVENT_BAR_CLOSE_MISMATCH")
    if result["source_received_ts"] < result["source_event_ts"]:
        raise FailureEvidenceError("SOURCE_TIMESTAMP_INVERSION")
    if result["evaluation_start_ts"] < result["scheduler_fire_ts"]:
        raise FailureEvidenceError("SCHEDULER_TIMESTAMP_INVERSION")
    if result["evaluation_end_ts"] < result["evaluation_start_ts"]:
        raise FailureEvidenceError("EVALUATION_TIMESTAMP_INVERSION")
    if result["writer_ts"] < result["evaluation_end_ts"]:
        raise FailureEvidenceError("WRITER_TIMESTAMP_INVERSION")
    for name in ("evaluation_age_ms", "source_lag_ms", "scheduler_lag_ms", "evaluation_duration_ms"):
        if result[name] < 0:
            raise FailureEvidenceError("NEGATIVE_DERIVED_TIME:" + name)
    return result


def collect_real_failures(contract: Mapping[str, Any], state_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    interval_ms = int(contract["source"]["interval_ms"])
    source_id = str(contract["source"]["source_id"])
    strategies = {str(row["strategy_id"]): str(row["child_id"]) for row in contract["active_strategies"]}
    symbols = set(map(str, contract["source"]["symbols"]))

    observed: dict[str, dict[str, Any]] = {}
    by_lane: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    late_events: list[dict[str, Any]] = []

    for row in state_rows:
        if row.get("status") != "EVALUATED":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        strategy_id = str(payload.get("strategy_id") or "")
        child_id = str(payload.get("child_id") or "")
        symbol = str(payload.get("symbol") or "")
        if strategies.get(strategy_id) != child_id or symbol not in symbols:
            continue
        if str(payload.get("source_id") or "") != source_id:
            continue
        if payload.get("closed_bar") is not True or payload.get("evaluated") is not True or payload.get("source_seen") is not True or payload.get("correct_child") is not True:
            raise FailureEvidenceError("INCOMPLETE_EVALUATED_PAYLOAD")
        if int(payload.get("duplicate") or 0) != 0 or int(payload.get("lookahead") or 0) != 0:
            raise FailureEvidenceError("EVALUATION_INTEGRITY_FAIL")
        if int(payload.get("formal_credit") or 0) != 0:
            raise FailureEvidenceError("FORMAL_CREDIT_MUST_REMAIN_ZERO")
        telemetry = _telemetry(payload)
        close_ts = int(payload.get("signal_bar_close_ts") or 0)
        if close_ts <= 0 or close_ts != telemetry["bar_close_ts"]:
            raise FailureEvidenceError("SIGNAL_BAR_CLOSE_MISMATCH")
        evaluation_key = str(payload.get("evaluation_key") or "")
        if not evaluation_key:
            raise FailureEvidenceError("EVALUATION_KEY_MISSING")
        fingerprint = sha_json({"evaluation_key": evaluation_key, "telemetry": telemetry})
        previous = observed.get(evaluation_key)
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise FailureEvidenceError("CONFLICTING_EVALUATION_KEY:" + evaluation_key)
            continue
        observed[evaluation_key] = {"fingerprint": fingerprint}
        by_lane[(strategy_id, child_id, symbol)].append(close_ts)

        if telemetry["evaluation_age_ms"] >= interval_ms:
            late_events.append({
                "event_type": "LATE_EVALUATION",
                "label": "MISSED_GENUINE_4H_CADENCE",
                "label_rule": "evaluation_age_ms>=contract.source.interval_ms",
                "observed_not_synthetic": True,
                "threshold_eligible": True,
                "evaluation_key": evaluation_key,
                "strategy_id": strategy_id,
                "child_id": child_id,
                "symbol": symbol,
                "bar_close_ts": close_ts,
                "interval_ms": interval_ms,
                "evaluation_age_ms": telemetry["evaluation_age_ms"],
                "source_lag_ms": telemetry["source_lag_ms"],
                "scheduler_lag_ms": telemetry["scheduler_lag_ms"],
                "evaluation_duration_ms": telemetry["evaluation_duration_ms"],
                "telemetry_sha256": sha_json(telemetry),
            })

    gap_events: list[dict[str, Any]] = []
    for (strategy_id, child_id, symbol), closes in sorted(by_lane.items()):
        ordered = sorted(set(closes))
        for left, right in zip(ordered, ordered[1:]):
            delta = right - left
            if delta <= interval_ms:
                continue
            if delta % interval_ms != 0:
                raise FailureEvidenceError(f"BAR_INTERVAL_DRIFT:{strategy_id}:{symbol}:{left}:{right}")
            missed = delta // interval_ms - 1
            for offset in range(1, missed + 1):
                missing_close_ts = left + offset * interval_ms
                gap_events.append({
                    "event_type": "MISSING_EVALUATION_GAP",
                    "label": "MISSED_GENUINE_4H_CADENCE",
                    "label_rule": "adjacent_evaluated_bar_gap>contract.source.interval_ms",
                    "observed_not_synthetic": True,
                    "threshold_eligible": False,
                    "strategy_id": strategy_id,
                    "child_id": child_id,
                    "symbol": symbol,
                    "missing_bar_close_ts": missing_close_ts,
                    "previous_evaluated_bar_close_ts": left,
                    "next_evaluated_bar_close_ts": right,
                    "interval_ms": interval_ms,
                })

    events = sorted(
        late_events + gap_events,
        key=lambda row: (
            int(row.get("bar_close_ts") or row.get("missing_bar_close_ts") or 0),
            str(row.get("strategy_id") or ""),
            str(row.get("symbol") or ""),
            str(row.get("event_type") or ""),
        ),
    )
    for event in events:
        event["event_sha256"] = sha_json(event)

    threshold_eligible = [row for row in events if row["threshold_eligible"] is True]
    if threshold_eligible:
        state = "REAL_FAILURE_EVIDENCE_AVAILABLE"
        next_step = "COMPUTE_THRESHOLD_SURFACE_FROM_OBSERVED_CLASSES"
    elif events:
        state = "REAL_FAILURE_INCIDENT_OBSERVED_NO_THRESHOLD_TELEMETRY"
        next_step = "WAIT_FOR_LATE_EVALUATION_WITH_COMPLETE_TELEMETRY"
    else:
        state = "REAL_FAILURE_COLLECTION_ACTIVE_NO_EVENTS"
        next_step = "WAIT_FOR_OBSERVED_REAL_FAILURE_OR_STALL"

    core = {
        "schema_version": "zel.g5.data_stale.real_failure_evidence.v1",
        "state": state,
        "scope": "FULL_CLEAN_RUNNER_APPEND_ONLY_STATE_LOG",
        "canonical_semantic": "EVALUATION_TIME_MINUS_NORMALIZED_SOURCE_EVENT_TIME",
        "failure_label": "MISSED_GENUINE_4H_CADENCE",
        "interval_ms": interval_ms,
        "evaluated_N": len(observed),
        "real_failure_N": len(events),
        "threshold_eligible_failure_N": len(threshold_eligible),
        "late_evaluation_N": len(late_events),
        "missing_evaluation_gap_N": len(gap_events),
        "timestamp_integrity": "PASS",
        "events": events,
        "authority_value": None,
        "authority_created": False,
        "ssot_mutated": False,
        "contract_mutation": False,
        "strategy_mutation": False,
        "economic_mutation": False,
        "fresh_credit": 0,
        "next": next_step,
    }
    return receipt(core)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--state-log", type=Path, default=DEFAULT_STATE_LOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = collect_real_failures(read_json(args.contract), read_jsonl(args.state_log))
    write_json(args.output, result)
    print(json.dumps({
        "state": result["state"],
        "evaluated_N": result["evaluated_N"],
        "real_failure_N": result["real_failure_N"],
        "threshold_eligible_failure_N": result["threshold_eligible_failure_N"],
        "authority_value": result["authority_value"],
        "fresh_credit": result["fresh_credit"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
