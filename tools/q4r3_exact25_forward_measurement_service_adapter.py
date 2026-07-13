from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

EXPECTED_EPOCH = "EXACT25_EDGE_V1"
EXPECTED_NAMESPACE = "EXACT25_EDGE_V1"
EXPECTED_WRITER_SHA256 = "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50"

_STOP = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def env_bool(name: str, expected: str) -> None:
    actual = os.environ.get(name)
    if actual != expected:
        raise RuntimeError(f"ENVIRONMENT_GATE_MISMATCH:{name}:expected={expected}:actual={actual}")


def validate_environment() -> None:
    expected = {
        "Q4R3_EPOCH_ID": EXPECTED_EPOCH,
        "Q4R3_MEASUREMENT_NAMESPACE": EXPECTED_NAMESPACE,
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_SERVICE_STAGE": "DRYRUN_ONLY",
    }
    for key, value in expected.items():
        env_bool(key, value)


def validate_gate(gate: Mapping[str, Any]) -> None:
    required = {
        "schema": "q4r3_exact25_forward_measurement_writer_gate_v1",
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "shadow_only": True,
        "write_enabled": False,
        "canary_enabled": False,
        "activation_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
    }
    for key, expected in required.items():
        actual = gate.get(key)
        if actual != expected:
            raise RuntimeError(f"GATE_MISMATCH:{key}:expected={expected!r}:actual={actual!r}")


def validate_writer(path: Path, expected_sha256: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"WRITER_NOT_FOUND:{path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise RuntimeError(f"WRITER_SHA_MISMATCH:expected={expected_sha256}:actual={actual}")
    return actual


def status_payload(
    *,
    state: str,
    gate_path: Path,
    writer_path: Path,
    writer_sha256: str,
    heartbeat_count: int,
    started_at: str,
    error: str | None = None,
) -> Dict[str, Any]:
    return {
        "schema": "q4r3_exact25_forward_measurement_service_adapter_status_v1",
        "state": state,
        "updated_at": now_iso(),
        "started_at": started_at,
        "pid": os.getpid(),
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "gate_path": str(gate_path),
        "writer_path": str(writer_path),
        "writer_sha256": writer_sha256,
        "heartbeat_count": heartbeat_count,
        "shadow_only": True,
        "write_enabled": False,
        "canary_enabled": False,
        "activation_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
        "writer_invocation_count": 0,
        "error": error,
    }


def request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def run(args: argparse.Namespace) -> int:
    gate_path = args.gate.resolve()
    writer_path = args.writer.resolve()
    status_path = args.status.resolve()
    started_at = now_iso()
    heartbeat_count = 0
    writer_sha = ""

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        validate_environment()
        gate = load_json(gate_path)
        validate_gate(gate)
        writer_sha = validate_writer(writer_path, args.writer_sha256)
    except Exception as exc:
        atomic_json(
            status_path,
            status_payload(
                state="BLOCKED",
                gate_path=gate_path,
                writer_path=writer_path,
                writer_sha256=writer_sha,
                heartbeat_count=heartbeat_count,
                started_at=started_at,
                error=f"{type(exc).__name__}:{exc}",
            ),
        )
        print(f"Q4R3_EXACT25_ADAPTER_BLOCKED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 78

    while not _STOP:
        try:
            validate_environment()
            gate = load_json(gate_path)
            validate_gate(gate)
            writer_sha = validate_writer(writer_path, args.writer_sha256)
            heartbeat_count += 1
            atomic_json(
                status_path,
                status_payload(
                    state="RUNNING_DRYRUN",
                    gate_path=gate_path,
                    writer_path=writer_path,
                    writer_sha256=writer_sha,
                    heartbeat_count=heartbeat_count,
                    started_at=started_at,
                ),
            )
        except Exception as exc:
            atomic_json(
                status_path,
                status_payload(
                    state="BLOCKED",
                    gate_path=gate_path,
                    writer_path=writer_path,
                    writer_sha256=writer_sha,
                    heartbeat_count=heartbeat_count,
                    started_at=started_at,
                    error=f"{type(exc).__name__}:{exc}",
                ),
            )
            print(f"Q4R3_EXACT25_ADAPTER_RUNTIME_BLOCKED:{type(exc).__name__}:{exc}", file=sys.stderr)
            return 78
        time.sleep(max(1.0, args.interval_sec))

    atomic_json(
        status_path,
        status_payload(
            state="STOPPED",
            gate_path=gate_path,
            writer_path=writer_path,
            writer_sha256=writer_sha,
            heartbeat_count=heartbeat_count,
            started_at=started_at,
        ),
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--writer", type=Path, required=True)
    parser.add_argument("--writer-sha256", default=EXPECTED_WRITER_SHA256)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
