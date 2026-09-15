"""Durable Micro15m observation producer; source read-only, no trade fills/orders."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Sequence

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import digest
from backend.research.rebuild.economic7_canonical_history_v1 import (
    atomic_json,
    immutable_bytes,
    json_bytes,
)
from backend.research.rebuild.scalp7_micro_decision_v2 import (
    IDENTITY,
    MicroDecision,
    MicroSourceError,
)
from backend.research.rebuild.scalp7_source_data_v2 import sha_file


def row_at_offset(path: Path, offset: int) -> dict[str, Any]:
    if offset <= 0 or offset > path.stat().st_size:
        raise MicroSourceError("RAW_CURSOR_OUTSIDE_FILE")
    size = min(offset, 65_536)
    with path.open("rb") as handle:
        while True:
            handle.seek(offset - size)
            raw = handle.read(size)
            if not raw.endswith(b"\n"):
                raise MicroSourceError("RAW_CURSOR_NOT_COMPLETE_LINE")
            lines = raw[:-1].rsplit(b"\n", 1)
            if len(lines) == 2 or size == offset:
                row = json.loads(lines[-1])
                if digest(
                    {k: v for k, v in row.items() if k != "record_sha256"}
                ) != row.get("record_sha256"):
                    raise MicroSourceError("RAW_CURSOR_HASH")
                return row
            if size >= 32 * 1024 * 1024:
                raise MicroSourceError("RAW_CURSOR_RECORD_OVERSIZE")
            size = min(offset, size * 2)


def _code_hashes() -> dict[str, str]:
    here = Path(__file__).parent
    return {
        name: sha_file(here / name)
        for name in (
            "scalp7_micro_decision_v2.py",
            "scalp7_micro_producer_v2.py",
            "economic7_bingx_raw_capture_v1.py",
        )
    }


def initialize(out: Path, source: Path) -> dict[str, Any]:
    freeze_path = out / "FREEZE.json"
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_bytes())
        if freeze["code_sha256"] != _code_hashes() or freeze["source"] != str(
            source.resolve()
        ):
            raise MicroSourceError("FROZEN_PRODUCER_IDENTITY_CHANGED")
        return freeze
    checkpoint = json.loads((source / "checkpoint.json").read_bytes())
    source_identity = json.loads((source / "identity.json").read_bytes())
    if digest(source_identity) != checkpoint["identity_sha256"]:
        raise MicroSourceError("SOURCE_IDENTITY_CHECKPOINT_MISMATCH")
    anchor = row_at_offset(source / "raw.jsonl", checkpoint["ledger_bytes"])
    if (
        anchor["local_seq"] != checkpoint["local_seq"]
        or anchor["record_sha256"] != checkpoint["tail_sha256"]
    ):
        raise MicroSourceError("SOURCE_CHECKPOINT_PREFIX_MISMATCH")
    freeze = {
        "schema": "scalp7.micro.fresh_producer.v2",
        "identity": IDENTITY,
        "frozen_at_ms": int(time.time() * 1000),
        "source": str(source.resolve()),
        "source_identity_sha256": checkpoint["identity_sha256"],
        "initial_offset": checkpoint["ledger_bytes"],
        "initial_seq": checkpoint["local_seq"],
        "initial_hash": checkpoint["tail_sha256"],
        "code_sha256": _code_hashes(),
        "decision_tf_min": 15,
        "sides": [-1, 1],
        "max_hold_bars": 4,
        "mechanism": "observed previous15m extreme break -> retest -> reclaim in next15m; opposite extreme invalidates",
        "stop_rule": "observed retest extreme",
        "exit_rule": "stop or four15mbar maximum",
        "entry_rule": "observed executable quote strictly after decision availability",
        "context_rule": "at least one complete15m bucket after freeze and after each connection reset",
        "l2_state": "UNUSED_SCHEMA_UNBOUND",
        "quantity_or_maker_direction_used": False,
        "synthetic_l2": False,
        "historical_replay": False,
        "economic_execution_owner": "root",
        "producer_role": "SIGNALS_ONLY",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    immutable_bytes(freeze_path, json_bytes(freeze))
    return freeze


def signal_ids(out: Path) -> set[str]:
    ids: set[str] = set()
    previous = "0" * 64
    path = out / "signals.jsonl"
    if not path.exists():
        return ids
    with path.open("rb") as handle:
        for line in handle:
            if not line.endswith(b"\n"):
                raise MicroSourceError("TORN_SIGNAL_LEDGER")
            row = json.loads(line)
            saved = row.pop("record_sha256")
            if row["previous_sha256"] != previous or digest(row) != saved:
                raise MicroSourceError("SIGNAL_LEDGER_HASH")
            if row["signal"]["setup_id"] in ids:
                raise MicroSourceError("SIGNAL_LEDGER_DUPLICATE")
            ids.add(row["signal"]["setup_id"])
            previous = saved
    return ids


def append_signal(out: Path, signal: dict[str, Any]) -> None:
    path = out / "signals.jsonl"
    previous = "0" * 64
    if path.exists() and path.stat().st_size:
        previous = row_at_offset(path, path.stat().st_size)["record_sha256"]
    emitted_at = int(time.time() * 1000)
    actual_available = max(signal["available_ts_ms"], emitted_at)
    signal = {
        **signal,
        "strategy_observed_at_ms": emitted_at,
        "signal_ts_ms": actual_available,
        "available_ts_ms": actual_available,
        "earliest_entry_ts_ms": actual_available + 1,
    }
    row = {"previous_sha256": previous, "recorded_at_ms": emitted_at, "signal": signal}
    row["record_sha256"] = digest(row)
    with path.open("ab", buffering=0) as handle:
        handle.write(json_bytes(row))
        os.fsync(handle.fileno())


def poll(out: Path, source: Path, *, max_records: int = 5000) -> dict[str, Any]:
    """The caller owns the writer lock for the full producer lifetime."""
    freeze = initialize(out, source)
    checkpoint_path = out / "CHECKPOINT.json"
    engine = MicroDecision(
        frozen_at_ms=freeze["frozen_at_ms"],
        initial_seq=freeze["initial_seq"],
        initial_hash=freeze["initial_hash"],
        identity_sha256=freeze["source_identity_sha256"],
    )
    offset = freeze["initial_offset"]
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_bytes())
        saved = checkpoint.pop("checkpoint_sha256")
        if digest(checkpoint) != saved or checkpoint["freeze_sha256"] != sha_file(
            out / "FREEZE.json"
        ):
            raise MicroSourceError("PRODUCER_CHECKPOINT_HASH")
        engine.__dict__.update(checkpoint["engine"])
        engine.emitted = set(engine.emitted)
        offset = checkpoint["offset"]
    anchor = row_at_offset(source / "raw.jsonl", offset)
    if (
        anchor["local_seq"] != engine.local_seq
        or anchor["record_sha256"] != engine.tail_hash
    ):
        raise MicroSourceError("PRODUCER_CURSOR_SOURCE_MISMATCH")
    engine.emitted.update(signal_ids(out))
    processed = 0
    emitted = 0
    with (source / "raw.jsonl").open("rb") as handle:
        handle.seek(offset)
        for _ in range(max_records):
            line = handle.readline()
            if not line or not line.endswith(b"\n"):
                break
            record = json.loads(line)
            for signal in engine.update(record):
                append_signal(out, signal)
                emitted += 1
            offset = handle.tell()
            processed += 1
    state = {**engine.__dict__, "emitted": sorted(engine.emitted)}
    checkpoint = {
        "schema": "scalp7.micro.producer.checkpoint.v2",
        "freeze_sha256": sha_file(out / "FREEZE.json"),
        "offset": offset,
        "engine": state,
        "saved_at_ms": int(time.time() * 1000),
    }
    checkpoint["checkpoint_sha256"] = digest(checkpoint)
    atomic_json(checkpoint_path, checkpoint)
    result = {
        "status": engine.status,
        "processed_records": processed,
        "new_signals": emitted,
        "total_signals": len(engine.emitted),
        "source_local_seq": engine.local_seq,
        "source_offset": offset,
        "last_received_ms": engine.last_received_ms,
        "observed_at_ms": int(time.time() * 1000),
        "fresh_closed_trades": 0,
        "economic_execution": False,
        "order_authority": "BLOCKED",
    }
    atomic_json(out / "STATUS.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=0)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (args.out / "producer.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                result = poll(args.out, args.source)
            except (MicroSourceError, ValueError, KeyError, OSError) as exc:
                atomic_json(
                    args.out / "STATUS.json",
                    {
                        "state": "HOLD_SOURCE_INTEGRITY",
                        "reason": str(exc),
                        "observed_at_ms": int(time.time() * 1000),
                        "order_authority": "BLOCKED",
                    },
                )
                return 2
            print(json.dumps(result), flush=True)
            if args.max_seconds and time.monotonic() - started >= args.max_seconds:
                return 0
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
