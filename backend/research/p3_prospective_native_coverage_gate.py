#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.p3.prospective_native_coverage.v1"
EXPECTED_FEATURES = ("premium_index", "open_interest")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _int(value: Any, label: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"COVERAGE_INTEGER_INVALID:{label}") from exc
    if out <= 0:
        raise RuntimeError(f"COVERAGE_INTEGER_NONPOSITIVE:{label}")
    return out


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"COVERAGE_HISTORY_MISSING:{path.name}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise RuntimeError(f"COVERAGE_HISTORY_JSON_INVALID:{path.name}:{line_no}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"COVERAGE_HISTORY_ROW_NOT_OBJECT:{path.name}:{line_no}")
        rows.append(row)
    if not rows:
        raise RuntimeError(f"COVERAGE_HISTORY_EMPTY:{path.name}")
    return rows


def _validate_record(row: Mapping[str, Any], *, feature: str, symbol: str) -> tuple[int, int, str]:
    if row.get("schema_version") != "zel.p3.prospective_native_feature_record.v1":
        raise RuntimeError(f"COVERAGE_RECORD_SCHEMA_INVALID:{feature}:{symbol}")
    if row.get("feature") != feature or row.get("symbol") != symbol:
        raise RuntimeError(f"COVERAGE_RECORD_IDENTITY_MISMATCH:{feature}:{symbol}")
    if row.get("prospective_only") is not True or row.get("historical_coverage_claim") is not False:
        raise RuntimeError(f"COVERAGE_RECORD_PROSPECTIVE_CONTRACT_INVALID:{feature}:{symbol}")
    if row.get("signal_generation_enabled") is not False:
        raise RuntimeError(f"COVERAGE_RECORD_SIGNAL_AUTHORITY_INVALID:{feature}:{symbol}")
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"COVERAGE_RECORD_SELECTION_AUTHORITY_INVALID:{feature}:{symbol}")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"COVERAGE_RECORD_EXECUTION_AUTHORITY_INVALID:{feature}:{symbol}")
    source_ts = _int(row.get("source_timestamp_ms"), f"{feature}.{symbol}.source_timestamp_ms")
    collected_ts = _int(row.get("collected_at_ms"), f"{feature}.{symbol}.collected_at_ms")
    payload_sha = str(row.get("source_payload_sha256") or "")
    if len(payload_sha) != 64 or any(ch not in "0123456789abcdef" for ch in payload_sha.lower()):
        raise RuntimeError(f"COVERAGE_RECORD_SHA_INVALID:{feature}:{symbol}")
    return source_ts, collected_ts, payload_sha


def evaluate(history_dir: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != "zel.p3.carry_flow.prospective_native.v1":
        raise RuntimeError("COVERAGE_CONTRACT_SCHEMA_INVALID")
    if contract.get("state") != "FROZEN_PROSPECTIVE_SOURCE_ACQUISITION":
        raise RuntimeError("COVERAGE_CONTRACT_STATE_INVALID")
    if contract.get("family") != "carry_flow" or contract.get("research_only") is not True:
        raise RuntimeError("COVERAGE_CONTRACT_FAMILY_INVALID")

    frozen = contract.get("frozen_window_contract")
    if not isinstance(frozen, Mapping):
        raise RuntimeError("COVERAGE_FROZEN_WINDOW_MISSING")
    w1_start = _int(frozen.get("w1_start_ms"), "w1_start_ms")
    w2_end = _int(frozen.get("w2_end_ms"), "w2_end_ms")
    pre_roll = _int(frozen.get("history_pre_roll_ms"), "history_pre_roll_ms")
    target_start = w1_start - pre_roll
    required_span_ms = w2_end - target_start
    if required_span_ms <= 0:
        raise RuntimeError("COVERAGE_FROZEN_WINDOW_INVALID")
    declared_span = _int(frozen.get("required_capture_span_ms"), "required_capture_span_ms")
    if declared_span != required_span_ms:
        raise RuntimeError("COVERAGE_FROZEN_WINDOW_SPAN_MISMATCH")

    symbols = contract.get("symbols")
    if not isinstance(symbols, list) or sorted(symbols) != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("COVERAGE_SYMBOL_CONTRACT_INVALID")

    results: list[dict[str, Any]] = []
    all_duration_ready = True
    min_progress = 1.0
    for feature in EXPECTED_FEATURES:
        for symbol in symbols:
            file_name = f"{feature}__{str(symbol).replace('-', '')}.ndjson"
            path = history_dir / file_name
            rows = _read_ndjson(path)
            identities: set[tuple[int, str]] = set()
            collected: list[int] = []
            source_times: list[int] = []
            for row in rows:
                source_ts, collected_ts, payload_sha = _validate_record(row, feature=feature, symbol=str(symbol))
                identity = (source_ts, payload_sha)
                if identity in identities:
                    raise RuntimeError(f"COVERAGE_DUPLICATE_IDENTITY:{file_name}")
                identities.add(identity)
                collected.append(collected_ts)
                source_times.append(source_ts)
            if collected != sorted(collected):
                raise RuntimeError(f"COVERAGE_COLLECTED_TS_NONMONOTONIC:{file_name}")
            capture_span_ms = max(collected) - min(collected)
            duration_ready = capture_span_ms >= required_span_ms
            all_duration_ready = all_duration_ready and duration_ready
            progress = min(capture_span_ms / required_span_ms, 1.0)
            min_progress = min(min_progress, progress)
            gaps = [b - a for a, b in zip(collected, collected[1:])]
            results.append(
                {
                    "feature": feature,
                    "symbol": symbol,
                    "history_file": str(path),
                    "record_count": len(rows),
                    "first_collected_at_ms": min(collected),
                    "latest_collected_at_ms": max(collected),
                    "capture_span_ms": capture_span_ms,
                    "required_capture_span_ms": required_span_ms,
                    "coverage_progress_ratio": progress,
                    "duration_gate_pass": duration_ready,
                    "source_timestamp_span_ms": max(source_times) - min(source_times),
                    "max_observed_collection_gap_ms": max(gaps) if gaps else None,
                }
            )

    native_sources = contract.get("native_sources")
    flow = native_sources.get("flow") if isinstance(native_sources, Mapping) else None
    flow_bound = isinstance(flow, Mapping) and flow.get("status") != "SOURCE_NOT_BOUND"

    if not all_duration_ready:
        state = "HOLD_P3_PROSPECTIVE_HISTORY_ACCUMULATING"
        blocker = "BASIS_OI_CAPTURE_SPAN_BELOW_FROZEN_WINDOW"
    elif not flow_bound:
        state = "PASS_P3_BASIS_OI_COVERAGE_READY_FLOW_BLOCKED"
        blocker = "FLOW_NATIVE_SOURCE_NOT_BOUND"
    else:
        state = "HOLD_P3_FLOW_ALIGNMENT_GATE_NOT_IMPLEMENTED"
        blocker = "FLOW_HISTORY_ALIGNMENT_REQUIRES_SEPARATE_GATE"

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": state,
        "family": "carry_flow",
        "frozen_window_source_pull_request": frozen.get("source_pull_request"),
        "target_start_ms": target_start,
        "target_end_ms": w2_end,
        "required_capture_span_ms": required_span_ms,
        "minimum_coverage_progress_ratio": min_progress,
        "basis_oi_duration_gate_pass": all_duration_ready,
        "flow_source_bound": flow_bound,
        "blocker": blocker,
        "results": results,
        "historical_coverage_claim": False,
        "replay_allowed": False,
        "signal_generation_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="P3 prospective native basis/OI frozen-window coverage gate")
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = evaluate(args.history_dir, contract)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "basis_oi_duration_gate_pass": result["basis_oi_duration_gate_pass"],
        "minimum_coverage_progress_ratio": result["minimum_coverage_progress_ratio"],
        "flow_source_bound": result["flow_source_bound"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
