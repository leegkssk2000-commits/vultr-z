from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

_STOP = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def require_environment() -> None:
    expected = {
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_MEASUREMENT_WRITE_ENABLED": "1",
        "Q4R3_EPOCH_ID": "EXACT25_EDGE_V1",
        "Q4R3_SYMBOL_UNIVERSE": "EXACT5",
    }
    for key, expected_value in expected.items():
        actual = os.environ.get(key)
        if actual != expected_value:
            raise RuntimeError(f"ENVIRONMENT_GATE_MISMATCH:{key}:expected={expected_value}:actual={actual}")


def load_adapter(root: Path) -> Any:
    tools = root / "tools"
    sys.path.insert(0, str(tools))
    try:
        import q4r3_exact25_single_event_measurement_adapter as adapter  # type: ignore
    finally:
        if sys.path and sys.path[0] == str(tools):
            sys.path.pop(0)
    return adapter


def gate_payload(path: Path) -> Dict[str, Any]:
    payload = load_json(path)
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 5:
        raise RuntimeError("EXACT5_GATE_SYMBOL_COUNT_NOT_5")
    normalized = [str(symbol).upper() for symbol in symbols]
    if len(set(normalized)) != 5:
        raise RuntimeError("EXACT5_GATE_SYMBOL_DUPLICATE")
    for required in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"):
        if required not in normalized:
            raise RuntimeError(f"EXACT5_GATE_CORE4_MISSING:{required}")
    start_epoch = payload.get("start_epoch")
    try:
        start_epoch_value = float(start_epoch)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("MEASUREMENT_START_EPOCH_INVALID") from exc
    if start_epoch_value <= 0:
        raise RuntimeError("MEASUREMENT_START_EPOCH_INVALID")
    return {**payload, "symbols": normalized, "start_epoch": start_epoch_value}


def event_epoch(adapter: Any, row: Mapping[str, Any]) -> float | None:
    return adapter.parse_time(row.get("captured_at") or row.get("exit_ts"))


def entry_epoch(adapter: Any, row: Mapping[str, Any]) -> float | None:
    return adapter.parse_time(row.get("entry_ts"))


def ledger_ids(adapter: Any, ledger: Path) -> set[str]:
    if not ledger.exists():
        return set()
    with ledger.open("r", encoding="utf-8", errors="ignore") as handle:
        return adapter.existing_event_ids(handle)


def process_once(
    *,
    adapter: Any,
    close_surface: Path,
    owners: Mapping[str, str],
    ledger: Path,
    allowed_symbols: Sequence[str],
    start_epoch: float,
    observed_ids: set[str],
) -> Dict[str, Any]:
    surface = load_json(close_surface)
    rows = adapter.rows_from_surface(surface)
    rows.sort(key=lambda row: event_epoch(adapter, row) or 0.0)
    accepted = 0
    duplicates = 0
    skipped_prestart = 0
    skipped_symbol = 0
    newly_observed = 0
    last_event_id: str | None = None

    for row in rows:
        event_id = str(row.get("event_id") or "")
        if not event_id or event_id in observed_ids:
            continue
        captured_epoch = event_epoch(adapter, row)
        opened_epoch = entry_epoch(adapter, row)
        symbol = str(row.get("symbol") or "").upper()
        if captured_epoch is None or opened_epoch is None:
            raise RuntimeError(f"EVENT_TIME_CONTRACT_INVALID:{event_id or 'missing'}")
        if captured_epoch < start_epoch or opened_epoch < start_epoch:
            observed_ids.add(event_id)
            skipped_prestart += 1
            newly_observed += 1
            continue
        if symbol not in set(allowed_symbols):
            observed_ids.add(event_id)
            skipped_symbol += 1
            newly_observed += 1
            continue
        normalized = adapter.validate_event(row, owners, min_event_epoch=start_epoch)
        if entry_epoch(adapter, normalized) is None or float(entry_epoch(adapter, normalized)) < start_epoch:
            raise RuntimeError(f"ENTRY_PREDATES_MEASUREMENT_GATE:{event_id}")
        was_accepted = adapter.append_exactly_once(ledger, normalized)
        observed_ids.add(event_id)
        newly_observed += 1
        last_event_id = event_id
        if was_accepted:
            accepted += 1
        else:
            duplicates += 1

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "skipped_prestart": skipped_prestart,
        "skipped_symbol": skipped_symbol,
        "newly_observed": newly_observed,
        "last_event_id": last_event_id,
        "surface_row_count": len(rows),
    }


def run(args: argparse.Namespace) -> int:
    require_environment()
    root = args.root.resolve()
    adapter = load_adapter(root)
    manifest = load_json(args.manifest.resolve())
    owners = adapter.manifest_owner_map(manifest)
    gate = gate_payload(args.gate.resolve())
    allowed_symbols = tuple(gate["symbols"])
    start_epoch = float(gate["start_epoch"])
    observed_ids = ledger_ids(adapter, args.ledger.resolve())

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    counters = {
        "heartbeat_count": 0,
        "accepted_count": 0,
        "duplicate_rejected_count": 0,
        "skipped_prestart_count": 0,
        "skipped_symbol_count": 0,
        "cycle_error_count": 0,
    }
    state = "RUNNING"
    last_error: str | None = None
    last_event_id: str | None = None
    started_at = now_iso()

    while not _STOP:
        try:
            result = process_once(
                adapter=adapter,
                close_surface=args.close_surface.resolve(),
                owners=owners,
                ledger=args.ledger.resolve(),
                allowed_symbols=allowed_symbols,
                start_epoch=start_epoch,
                observed_ids=observed_ids,
            )
            counters["accepted_count"] += int(result["accepted"])
            counters["duplicate_rejected_count"] += int(result["duplicates"])
            counters["skipped_prestart_count"] += int(result["skipped_prestart"])
            counters["skipped_symbol_count"] += int(result["skipped_symbol"])
            if result.get("last_event_id"):
                last_event_id = str(result["last_event_id"])
            last_error = None
        except Exception as exc:
            counters["cycle_error_count"] += 1
            last_error = f"{type(exc).__name__}:{exc}"
            state = "BLOCKED"
            atomic_json(args.status.resolve(), {
                "schema": "q4r3_exact25_persistent_single_event_writer_status_v1",
                "state": state,
                "started_at": started_at,
                "updated_at": now_iso(),
                "epoch_id": "EXACT25_EDGE_V1",
                "measurement_namespace": "EXACT25_EDGE_V1",
                "symbol_universe": "EXACT5",
                "symbols": list(allowed_symbols),
                "start_epoch": start_epoch,
                "production_measurement_write_enabled": True,
                "shadow_only": True,
                "paper_enabled": False,
                "live_enabled": False,
                "order_enabled": False,
                "historical_backfill_allowed": False,
                "ledger_path": str(args.ledger.resolve()),
                "ledger_row_count": adapter.count_valid_rows(args.ledger.resolve()),
                "last_event_id": last_event_id,
                "last_error": last_error,
                **counters,
            })
            raise

        counters["heartbeat_count"] += 1
        atomic_json(args.status.resolve(), {
            "schema": "q4r3_exact25_persistent_single_event_writer_status_v1",
            "state": state,
            "started_at": started_at,
            "updated_at": now_iso(),
            "epoch_id": "EXACT25_EDGE_V1",
            "measurement_namespace": "EXACT25_EDGE_V1",
            "symbol_universe": "EXACT5",
            "symbols": list(allowed_symbols),
            "start_epoch": start_epoch,
            "production_measurement_write_enabled": True,
            "shadow_only": True,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "historical_backfill_allowed": False,
            "ledger_path": str(args.ledger.resolve()),
            "ledger_row_count": adapter.count_valid_rows(args.ledger.resolve()),
            "last_event_id": last_event_id,
            "last_error": last_error,
            **counters,
        })
        time.sleep(max(float(args.poll_sec), 1.0))

    state = "STOPPED"
    atomic_json(args.status.resolve(), {
        "schema": "q4r3_exact25_persistent_single_event_writer_status_v1",
        "state": state,
        "started_at": started_at,
        "updated_at": now_iso(),
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "symbol_universe": "EXACT5",
        "symbols": list(allowed_symbols),
        "start_epoch": start_epoch,
        "production_measurement_write_enabled": True,
        "shadow_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
        "ledger_path": str(args.ledger.resolve()),
        "ledger_row_count": adapter.count_valid_rows(args.ledger.resolve()),
        "last_event_id": last_event_id,
        "last_error": last_error,
        **counters,
    })
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--close-surface", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
