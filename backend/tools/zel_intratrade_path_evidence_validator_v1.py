from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_INTRATRADE_PATH_EVIDENCE_VALIDATOR_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def rows_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return [row for row in value["rows"] if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def bundle_match(row: Mapping[str, Any], bundle: Mapping[str, Any]) -> bool:
    required = bundle.get("required_fields") if isinstance(bundle.get("required_fields"), list) else []
    return all(field in row and row.get(field) not in (None, "") for field in required)


def sequence(row: Mapping[str, Any], key: str) -> list[Any]:
    value = row.get(key)
    return list(value) if isinstance(value, list) else []


def validate_lineage(row: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    lineage = contract.get("lineage") if isinstance(contract.get("lineage"), dict) else {}
    required = lineage.get("required_fields") if isinstance(lineage.get("required_fields"), list) else []
    for field in required:
        if row.get(field) in (None, ""):
            errors.append(f"LINEAGE_MISSING:{field}")
    source = str(row.get("path_source") or "")
    prefixes = lineage.get("accepted_path_source_prefixes") if isinstance(lineage.get("accepted_path_source_prefixes"), list) else []
    if source and not any(source.startswith(str(prefix)) for prefix in prefixes):
        errors.append("PATH_SOURCE_PREFIX_INVALID")
    for field in ("path_source_sha256", "strategy_config_sha256", "signal_source_sha256"):
        value = str(row.get(field) or "")
        if value and (len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value)):
            errors.append(f"SHA256_INVALID:{field}")
    return errors


def validate_common(row: Mapping[str, Any], timestamps: Sequence[Any], prices: Sequence[Any], sizes: Sequence[Any]) -> list[str]:
    errors: list[str] = []
    if len(timestamps) < 2:
        errors.append("PATH_LENGTH_LT_2")
    if not (len(timestamps) == len(prices) == len(sizes)):
        errors.append("PATH_ARRAY_LENGTH_MISMATCH")
    parsed = [parse_ts(value) for value in timestamps]
    if any(value is None for value in parsed):
        errors.append("PATH_TIMESTAMP_INVALID")
    else:
        assert all(value is not None for value in parsed)
        if any(right <= left for left, right in zip(parsed, parsed[1:])):
            errors.append("PATH_TIMESTAMPS_NOT_STRICTLY_INCREASING")
        entry = parse_ts(row.get("entry_ts"))
        exit_ts = parse_ts(row.get("exit_ts"))
        if entry is None or exit_ts is None:
            errors.append("ENTRY_OR_EXIT_TIMESTAMP_INVALID")
        else:
            if parsed and parsed[0] > entry:
                errors.append("PATH_START_AFTER_ENTRY")
            if parsed and parsed[-1] < exit_ts:
                errors.append("PATH_END_BEFORE_EXIT")
    if any(not finite(value) or float(value) <= 0 for value in prices):
        errors.append("PATH_PRICE_INVALID")
    if any(not finite(value) or float(value) < 0 for value in sizes):
        errors.append("POSITION_SIZE_PATH_INVALID")
    return errors


def validate_tick(row: Mapping[str, Any]) -> list[str]:
    return validate_common(
        row,
        sequence(row, "timestamp_path"),
        sequence(row, "intratrade_price_path"),
        sequence(row, "position_size_path"),
    )


def validate_bar(row: Mapping[str, Any]) -> list[str]:
    timestamps = sequence(row, "bar_timestamp_path")
    opens = sequence(row, "bar_open_path")
    highs = sequence(row, "bar_high_path")
    lows = sequence(row, "bar_low_path")
    closes = sequence(row, "bar_close_path")
    sizes = sequence(row, "position_size_path")
    errors = validate_common(row, timestamps, closes, sizes)
    lengths = {len(timestamps), len(opens), len(highs), len(lows), len(closes), len(sizes)}
    if len(lengths) != 1:
        errors.append("BAR_ARRAY_LENGTH_MISMATCH")
    for index, values in enumerate(zip(opens, highs, lows, closes)):
        open_, high, low, close = values
        if not all(finite(value) for value in values):
            errors.append(f"BAR_NONFINITE:{index}")
            continue
        if min(float(open_), float(close_), float(high), float(low)) <= 0:
            errors.append(f"BAR_NONPOSITIVE:{index}")
        if float(high) < max(float(open_), float(close_), float(low)):
            errors.append(f"BAR_HIGH_INVALID:{index}")
        if float(low) > min(float(open_), float(close_), float(high)):
            errors.append(f"BAR_LOW_INVALID:{index}")
    return errors


def validate_row(row: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    bundles = contract.get("bundles") if isinstance(contract.get("bundles"), list) else []
    matches = [bundle for bundle in bundles if isinstance(bundle, dict) and bundle_match(row, bundle)]
    errors = validate_lineage(row, contract)
    bundle_id = None
    supports: list[str] = []
    if not matches:
        errors.append("NO_COMPLETE_PATH_BUNDLE")
    else:
        bundle = matches[0]
        bundle_id = str(bundle.get("bundle_id") or "")
        supports = [str(value) for value in bundle.get("supports", [])]
        if bundle_id == "TICK_PATH_BUNDLE":
            errors.extend(validate_tick(row))
        elif bundle_id == "BAR_PATH_BUNDLE":
            errors.extend(validate_bar(row))
        else:
            errors.append("UNKNOWN_BUNDLE_ID")
    errors = sorted(set(errors))
    return {
        "event_id": row.get("event_id"),
        "strategy_id": row.get("strategy_id") or row.get("strategy"),
        "window_id": row.get("window_id"),
        "state": "PASS_INTRATRADE_PATH_EVIDENCE" if not errors else "HOLD_INTRATRADE_PATH_EVIDENCE",
        "bundle_id": bundle_id,
        "supports": supports,
        "errors": errors,
        "exact_replay_allowed": not errors,
        "economic_claim_allowed": False,
        "action": "hold",
    }


def build(contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    receipts = [validate_row(row, contract) for row in rows]
    passed = [row for row in receipts if row["state"].startswith("PASS_")]
    state = "PASS_INTRATRADE_PATH_DATASET" if receipts and len(passed) == len(receipts) else "HOLD_INTRATRADE_PATH_DATASET"
    result: dict[str, Any] = {
        "schema_version": "zel.intratrade_path_evidence.validation.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "row_count": len(receipts),
        "pass_count": len(passed),
        "blocked_count": len(receipts) - len(passed),
        "rows": receipts,
        "economic_superiority_claim_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha({key: value for key, value in result.items() if key != "receipt_sha256"})
    return result


def self_test() -> None:
    contract = load_json(Path(__file__).resolve().parents[1] / "research/zel_intratrade_path_evidence_contract_v1.json")
    sha = "a" * 64
    base = {
        "event_id": "e1", "strategy_id": "s1", "symbol": "BTCUSDT", "side": "long",
        "entry_ts": "2026-01-01T00:00:00Z", "exit_ts": "2026-01-01T00:02:00Z",
        "path_source": "sealed_dataset:/fixture", "path_source_sha256": sha,
        "strategy_config_sha256": sha, "signal_source_sha256": sha,
        "interval": "1m", "timezone": "UTC",
    }
    tick = {
        **base,
        "timestamp_path": ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"],
        "intratrade_price_path": [100, 101, 102],
        "position_size_path": [1, 1, 0],
    }
    passed = build(contract, [tick])
    assert passed["state"] == "PASS_INTRATRADE_PATH_DATASET", passed
    broken = dict(tick, timestamp_path=list(reversed(tick["timestamp_path"])))
    held = build(contract, [broken])
    assert held["state"] == "HOLD_INTRATRADE_PATH_DATASET", held
    assert "PATH_TIMESTAMPS_NOT_STRICTLY_INCREASING" in held["rows"][0]["errors"], held
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.input:
        parser.error("contract and input are required")
    result = build(load_json(args.contract), rows_from_value(load_json(args.input)))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
