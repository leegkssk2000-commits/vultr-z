from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

EXPECTED_EPOCH = "EXACT25_EDGE_V1"
EXPECTED_NAMESPACE = "EXACT25_EDGE_V1"
EXPECTED_SOURCE = "q4r3_exact25_dedicated_shadow_producer"
EXPECTED_STRATEGY_COUNT = 25


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def parse_time(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def finite_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"FINITE_NUMBER_REQUIRED:{field}") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"FINITE_NUMBER_REQUIRED:{field}")
    return result


def strategy_identity(item: Mapping[str, Any]) -> str:
    for key in ("strategy_id", "id", "name", "strategy"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def owner_sha(item: Mapping[str, Any]) -> str:
    for key in ("owner_sha256", "sha256", "owner_sha", "source_sha256", "sha"):
        value = item.get(key)
        if isinstance(value, str) and len(value.strip()) >= 32:
            return value.strip().lower()
    owner = item.get("owner")
    if isinstance(owner, dict):
        return owner_sha(owner)
    return ""


def manifest_owner_map(manifest: Mapping[str, Any]) -> Dict[str, str]:
    strategies = manifest.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != EXPECTED_STRATEGY_COUNT:
        raise RuntimeError(f"MANIFEST_NOT_EXACT25:{len(strategies) if isinstance(strategies, list) else -1}")
    result: Dict[str, str] = {}
    for raw in strategies:
        if not isinstance(raw, dict):
            raise RuntimeError("MANIFEST_STRATEGY_OBJECT_REQUIRED")
        strategy_id = strategy_identity(raw)
        sha = owner_sha(raw)
        if not strategy_id or not sha:
            raise RuntimeError(f"MANIFEST_OWNER_IDENTITY_MISSING:{strategy_id or 'unknown'}")
        if strategy_id in result:
            raise RuntimeError(f"MANIFEST_DUPLICATE_STRATEGY:{strategy_id}")
        result[strategy_id] = sha
    return result


def rows_from_surface(surface: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows = surface.get("rows")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, dict)]
    if surface.get("event_id"):
        return [dict(surface)]
    return []


def select_event(surface: Mapping[str, Any], expected_event_id: str | None) -> Dict[str, Any]:
    rows = rows_from_surface(surface)
    if not rows:
        raise RuntimeError("CLOSE_SURFACE_EMPTY")
    if expected_event_id:
        matches = [row for row in rows if str(row.get("event_id") or "") == expected_event_id]
        if len(matches) != 1:
            raise RuntimeError(f"EXPECTED_EVENT_MATCH_COUNT:{len(matches)}")
        return matches[0]
    rows.sort(key=lambda row: parse_time(row.get("captured_at") or row.get("exit_ts")) or 0.0)
    return rows[-1]


def validate_event(
    row: Mapping[str, Any],
    owners: Mapping[str, str],
    *,
    min_event_epoch: float | None,
) -> Dict[str, Any]:
    required_text = (
        "event_id", "position_id", "strategy_id", "owner_sha256", "symbol", "side",
        "entry_ts", "exit_ts", "source", "epoch_id", "measurement_namespace",
    )
    for key in required_text:
        if not isinstance(row.get(key), str) or not str(row.get(key)).strip():
            raise RuntimeError(f"REQUIRED_TEXT_MISSING:{key}")

    if row.get("epoch_id") != EXPECTED_EPOCH:
        raise RuntimeError(f"EPOCH_MISMATCH:{row.get('epoch_id')}")
    if row.get("measurement_namespace") != EXPECTED_NAMESPACE:
        raise RuntimeError(f"NAMESPACE_MISMATCH:{row.get('measurement_namespace')}")
    if row.get("source") != EXPECTED_SOURCE:
        raise RuntimeError(f"SOURCE_MISMATCH:{row.get('source')}")
    if str(row.get("mode") or "").lower() != "shadow" or row.get("shadow") is not True:
        raise RuntimeError("SHADOW_MODE_REQUIRED")
    for key in ("paper_enabled", "live_enabled", "order_enabled"):
        if row.get(key) is not False:
            raise RuntimeError(f"UNSAFE_EVENT_FLAG:{key}:{row.get(key)}")
    if str(row.get("status") or "").upper() != "CLOSED" or row.get("closed") is not True:
        raise RuntimeError("CLOSED_EVENT_REQUIRED")

    strategy_id = str(row["strategy_id"])
    expected_owner = owners.get(strategy_id)
    actual_owner = str(row["owner_sha256"]).lower()
    if not expected_owner:
        raise RuntimeError(f"STRATEGY_NOT_IN_MANIFEST:{strategy_id}")
    if expected_owner != actual_owner:
        raise RuntimeError(f"OWNER_SHA_MISMATCH:{strategy_id}")

    initial_risk = finite_number(row.get("initial_risk_usdt"), "initial_risk_usdt")
    realized_pnl = finite_number(row.get("realized_pnl_usdt"), "realized_pnl_usdt")
    realized_r = finite_number(row.get("realized_R"), "realized_R")
    if initial_risk <= 0:
        raise RuntimeError("INITIAL_RISK_NOT_POSITIVE")
    expected_r = realized_pnl / initial_risk
    tolerance = max(1e-10, abs(expected_r) * 1e-9)
    if abs(realized_r - expected_r) > tolerance:
        raise RuntimeError(f"REALIZED_R_FORMULA_MISMATCH:{realized_r}:{expected_r}")

    event_epoch = parse_time(row.get("captured_at") or row.get("exit_ts"))
    if event_epoch is None:
        raise RuntimeError("EVENT_TIMESTAMP_INVALID")
    if min_event_epoch is not None and event_epoch < min_event_epoch:
        raise RuntimeError(f"EVENT_PREDATES_CANARY:{event_epoch}:{min_event_epoch}")

    normalized = dict(row)
    normalized.update({
        "schema": "q4r3_exact25_forward_measurement_row_v1",
        "measurement_epoch": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "measurement_source": "q4r3_exact25_single_event_measurement_adapter",
        "measurement_written_at": now_iso(),
        "initial_risk_usdt": initial_risk,
        "realized_pnl_usdt": realized_pnl,
        "realized_R": realized_r,
        "formula_verified": True,
        "owner_lineage_verified": True,
        "shadow_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill": False,
    })
    return normalized


def existing_event_ids(handle: Any) -> set[str]:
    handle.seek(0)
    result: set[str] = set()
    for line in handle:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("event_id"):
            result.add(str(row["event_id"]))
    return result


def append_exactly_once(ledger: Path, row: Mapping[str, Any]) -> bool:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        event_id = str(row["event_id"])
        if event_id in existing_event_ids(handle):
            return False
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return True


def count_valid_rows(ledger: Path) -> int:
    if not ledger.exists():
        return 0
    count = 0
    for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            count += 1
    return count


def event_hash(event_id: str) -> str:
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()


def run(args: argparse.Namespace) -> int:
    surface = load_json(args.close_surface.resolve())
    manifest = load_json(args.manifest.resolve())
    owners = manifest_owner_map(manifest)
    selected = select_event(surface, args.expected_event_id)
    normalized = validate_event(selected, owners, min_event_epoch=args.min_event_epoch)

    before_count = count_valid_rows(args.ledger)
    accepted = append_exactly_once(args.ledger, normalized)
    after_count = count_valid_rows(args.ledger)
    delta = after_count - before_count
    if accepted and delta != 1:
        raise RuntimeError(f"ACCEPTED_ROW_DELTA_NOT_ONE:{delta}")
    if not accepted and delta != 0:
        raise RuntimeError(f"DUPLICATE_ROW_DELTA_NOT_ZERO:{delta}")

    receipt = {
        "schema": "q4r3_exact25_single_event_measurement_receipt_v1",
        "state": "ACCEPTED" if accepted else "DUPLICATE_REJECTED",
        "updated_at": now_iso(),
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "event_hash": event_hash(str(normalized["event_id"])),
        "strategy_id": normalized["strategy_id"],
        "symbol": normalized["symbol"],
        "accepted_count": 1 if accepted else 0,
        "duplicate_rejected_count": 0 if accepted else 1,
        "row_count_before": before_count,
        "row_count_after": after_count,
        "row_delta": delta,
        "formula_verified": True,
        "owner_lineage_verified": True,
        "shadow_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill": False,
        "ledger_path": str(args.ledger.resolve()),
    }
    atomic_json(args.receipt.resolve(), receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--close-surface", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-event-id")
    parser.add_argument("--min-event-epoch", type=float)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
