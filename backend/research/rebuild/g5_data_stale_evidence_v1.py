#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/g5_clean_runner_contract_v1.json"
DEFAULT_STATE_LOG = ROOT / "backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl"
DEFAULT_SHADOW = ROOT / "backend/research/rebuild/g5_clean_runner_shadow_v1.json"
DEFAULT_OUTPUT = ROOT / "backend/research/rebuild/g5_data_stale_evidence_v1.json"
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
DISTRIBUTION_FIELDS = (
    "evaluation_age_ms",
    "source_lag_ms",
    "scheduler_lag_ms",
    "evaluation_duration_ms",
)


class EvidenceError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceError(f"OBJECT_REQUIRED:{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            if not raw.endswith("\n"):
                raise EvidenceError(f"PARTIAL_JSONL_RECORD:{number}")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise EvidenceError(f"JSONL_OBJECT_REQUIRED:{number}")
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


def quantile_nearest(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(int(x) for x in values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def distribution(values: Sequence[int]) -> dict[str, int | None]:
    if not values:
        return {"min": None, "p50": None, "p90": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(int(x) for x in values)
    return {
        "min": ordered[0],
        "p50": quantile_nearest(ordered, 0.50),
        "p90": quantile_nearest(ordered, 0.90),
        "p95": quantile_nearest(ordered, 0.95),
        "p99": quantile_nearest(ordered, 0.99),
        "max": ordered[-1],
    }


def _assert_integrity(shadow: Mapping[str, Any], contract: Mapping[str, Any]) -> list[int]:
    if shadow.get("state") != "CLEAN_RUNNER_SHADOW_PASS" or shadow.get("shadow_3bar_pass") is not True:
        raise EvidenceError("SHADOW_3BAR_PASS_REQUIRED")
    if int(shadow.get("complete_bar_count") or 0) < 3 or int(shadow.get("consecutive_complete_bar_count") or 0) < 3:
        raise EvidenceError("THREE_CONSECUTIVE_BARS_REQUIRED")
    if shadow.get("source_parity") is not True or shadow.get("child_parity") is not True:
        raise EvidenceError("PARITY_REQUIRED")
    if int(shadow.get("duplicate") or 0) != 0 or int(shadow.get("lookahead") or 0) != 0:
        raise EvidenceError("DUPLICATE_OR_LOOKAHEAD_NONZERO")
    if int(shadow.get("formal_credit") or 0) != 0:
        raise EvidenceError("FORMAL_CREDIT_MUST_REMAIN_ZERO")
    bars = [shadow.get("bar1"), shadow.get("bar2"), shadow.get("bar3")]
    if any(not value for value in bars):
        raise EvidenceError("SHADOW_BAR_TIMESTAMP_MISSING")
    interval_ms = int(contract["source"]["interval_ms"])
    from datetime import datetime, timezone
    parsed = [int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000) for value in bars]
    if any(right - left != interval_ms for left, right in zip(parsed, parsed[1:])):
        raise EvidenceError("SHADOW_BAR_INTERVAL_DRIFT")
    return parsed


def build_evidence(contract: Mapping[str, Any], shadow: Mapping[str, Any], state_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bar_ts = _assert_integrity(shadow, contract)
    bar_set = set(bar_ts)
    strategies = {str(row["strategy_id"]): str(row["child_id"]) for row in contract["active_strategies"]}
    symbols = set(map(str, contract["source"]["symbols"]))
    expected_per_bar = len(strategies) * len(symbols)

    evaluated: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in state_rows:
        if row.get("status") != "EVALUATED":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        close_ts = int(payload.get("signal_bar_close_ts") or 0)
        if close_ts not in bar_set:
            continue
        strategy_id = str(payload.get("strategy_id") or "")
        child_id = str(payload.get("child_id") or "")
        symbol = str(payload.get("symbol") or "")
        if strategies.get(strategy_id) != child_id:
            raise EvidenceError(f"CHILD_IDENTITY_DRIFT:{strategy_id}:{child_id}")
        if symbol not in symbols:
            raise EvidenceError(f"UNEXPECTED_SYMBOL:{symbol}")
        if payload.get("closed_bar") is not True or payload.get("evaluated") is not True or payload.get("source_seen") is not True or payload.get("correct_child") is not True:
            raise EvidenceError("INCOMPLETE_EVALUATED_PAYLOAD")
        if int(payload.get("duplicate") or 0) != 0 or int(payload.get("lookahead") or 0) != 0:
            raise EvidenceError("EVALUATION_INTEGRITY_FAIL")
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, Mapping):
            raise EvidenceError("TELEMETRY_MISSING")
        missing = [name for name in REQUIRED_TELEMETRY if telemetry.get(name) is None]
        if missing:
            raise EvidenceError("TELEMETRY_FIELDS_MISSING:" + ",".join(missing))
        evaluation_key = str(payload.get("evaluation_key") or "")
        if not evaluation_key or evaluation_key in seen_keys:
            raise EvidenceError("DUPLICATE_EVALUATION_KEY")
        seen_keys.add(evaluation_key)
        evaluated.append(dict(payload))

    by_bar = Counter(int(row["signal_bar_close_ts"]) for row in evaluated)
    if len(evaluated) != expected_per_bar * 3:
        raise EvidenceError(f"EVALUATION_COUNT_MISMATCH:{len(evaluated)}!={expected_per_bar * 3}")
    for ts in bar_ts:
        if by_bar[ts] != expected_per_bar:
            raise EvidenceError(f"BAR_COVERAGE_MISMATCH:{ts}:{by_bar[ts]}!={expected_per_bar}")

    observed_strategies = {str(row["strategy_id"]) for row in evaluated}
    observed_symbols = {str(row["symbol"]) for row in evaluated}
    if observed_strategies != set(strategies) or observed_symbols != symbols:
        raise EvidenceError("STRATEGY_OR_SYMBOL_COVERAGE_MISMATCH")

    normal_values: dict[str, list[int]] = {name: [] for name in DISTRIBUTION_FIELDS}
    timestamp_inversion = 0
    clock_mismatch = 0
    for row in evaluated:
        t = row["telemetry"]
        for name in DISTRIBUTION_FIELDS:
            value = int(t[name])
            if value < 0:
                timestamp_inversion += 1
            normal_values[name].append(value)
        ordered = [int(t[name]) for name in ("source_event_ts", "bar_close_ts", "source_received_ts", "scheduler_fire_ts", "evaluation_start_ts", "evaluation_end_ts", "writer_ts")]
        if int(t["source_event_ts"]) != int(t["bar_close_ts"]):
            clock_mismatch += 1
        if int(t["evaluation_end_ts"]) < int(t["evaluation_start_ts"]) or int(t["writer_ts"]) < int(t["evaluation_end_ts"]):
            timestamp_inversion += 1
    if timestamp_inversion or clock_mismatch:
        raise EvidenceError(f"TIMESTAMP_INTEGRITY_FAIL:{timestamp_inversion}:{clock_mismatch}")

    interval_ms = int(contract["source"]["interval_ms"])
    synthetic_failure = {
        "label": "ONE_MISSED_GENUINE_4H_CADENCE",
        "provenance": "contract.source.interval_ms",
        "interval_ms": interval_ms,
        "authoritative": False,
        "N": len(evaluated),
        "evaluation_age_ms": distribution([value + interval_ms for value in normal_values["evaluation_age_ms"]]),
        "source_lag_ms": distribution([value + interval_ms for value in normal_values["source_lag_ms"]]),
        "scheduler_lag_ms": distribution([value + interval_ms for value in normal_values["scheduler_lag_ms"]]),
    }

    core = {
        "schema_version": "zel.g5.data_stale.evidence.v1",
        "state": "AUTHORITY_EVIDENCE_PARTIAL_SYNTHETIC_ONLY",
        "first_blocker": "REAL_LABELED_FAILURE_MISSING",
        "canonical_semantic": "EVALUATION_TIME_MINUS_NORMALIZED_SOURCE_EVENT_TIME",
        "authority_value": None,
        "authority_unit": "ms",
        "authority_created": False,
        "ssot_mutated": False,
        "fresh_credit": 0,
        "strategy_mutation": False,
        "economic_mutation": False,
        "contract_mutation": False,
        "normal_N": len(evaluated),
        "real_failure_N": 0,
        "synthetic_failure_N": len(evaluated),
        "bars": list(shadow.get(name) for name in ("bar1", "bar2", "bar3")),
        "bars_N": 3,
        "expected_evaluations_per_bar": expected_per_bar,
        "strategies": sorted(observed_strategies),
        "symbols": sorted(observed_symbols),
        "timestamp_integrity": "PASS",
        "timestamp_inversion": 0,
        "clock_mismatch": 0,
        "normal_distributions_ms": {name: distribution(values) for name, values in normal_values.items()},
        "synthetic_failure_diagnostic": synthetic_failure,
        "false_stale_false_fresh_tradeoff_computable": False,
        "robust_plateau": None,
        "threshold_surface_allowed": False,
        "data_stale_authority_allowed": False,
        "next": "COLLECT_OR_LABEL_REAL_FAILURE_EVIDENCE_BEFORE_THRESHOLD_SURFACE",
    }
    return receipt(core)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--shadow", type=Path, default=DEFAULT_SHADOW)
    parser.add_argument("--state-log", type=Path, default=DEFAULT_STATE_LOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evidence = build_evidence(read_json(args.contract), read_json(args.shadow), read_jsonl(args.state_log))
    write_json(args.output, evidence)
    print(json.dumps({
        "state": evidence["state"],
        "normal_N": evidence["normal_N"],
        "real_failure_N": evidence["real_failure_N"],
        "synthetic_failure_N": evidence["synthetic_failure_N"],
        "authority_value": evidence["authority_value"],
        "fresh_credit": evidence["fresh_credit"],
        "first_blocker": evidence["first_blocker"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
