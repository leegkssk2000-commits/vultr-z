from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.production.zel_production_auto_cycle_supervisor_v1 import (
    ProductionAutoCycleSupervisor,
    cycle_key_for,
)
from backend.production.zel_production_owner_binding_v1 import (
    ProductionEventLedger,
    stable_sha,
)

SCHEMA = "zel.production_paper_loop.v1"
DEFAULT_LEDGER = "/home/zel/apps/zel/ledger/production_events_v1.sqlite"
DEFAULT_SNAPSHOT = "/home/zel/apps/zel/ledger/production_snapshot_v1.json"
DEFAULT_SUPERVISOR_STATE = "/home/zel/apps/zel/ledger/production_auto_cycle_supervisor_v1.sqlite"
DEFAULT_INPUT = "/home/zel/apps/zel/ledger/production_paper_input_v1.json"
DEFAULT_LOOP_STATE = "/home/zel/apps/zel/ledger/production_paper_loop_state_v1.json"


@dataclass(frozen=True)
class PaperLoopPolicy:
    interval_s: float = 5.0
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        if self.interval_s < 0:
            raise ValueError("interval_s must be >= 0")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class JsonFilePayloadProvider:
    """Read one canonical PAPER payload from a producer-owned JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __call__(self) -> Mapping[str, Any] | None:
        if not self.path.exists():
            return None
        row = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            raise ValueError("PAPER_INPUT_MUST_BE_JSON_OBJECT")
        return row


class PaperLoopStateStore:
    def __init__(self, path: str | Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.initial()
        try:
            row = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"PAPER_LOOP_STATE_INVALID:{type(exc).__name__}") from exc
        if not isinstance(row, dict) or row.get("schema_version") != SCHEMA:
            raise RuntimeError("PAPER_LOOP_STATE_CONTRACT_INVALID")
        return row

    def initial(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "state": "INIT",
            "action": "hold",
            "reason": "NOT_STARTED",
            "iterations": 0,
            "cycles_executed": 0,
            "idle_count": 0,
            "consecutive_failures": 0,
            "circuit_open": False,
            "last_input_sha256": None,
            "last_cycle_key": None,
            "last_receipt_sha256": None,
            "last_snapshot_sha256": None,
            "updated_at": self.clock(),
            "exchange_order_submitted": False,
            "strategy_mutation_applied": False,
            "self_modification_applied": False,
            "live_execution": "BLOCKED",
        }

    def write(self, state: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(state)
        row["schema_version"] = SCHEMA
        row["updated_at"] = self.clock()
        row["exchange_order_submitted"] = False
        row["strategy_mutation_applied"] = False
        row["self_modification_applied"] = False
        row["live_execution"] = "BLOCKED"
        _atomic_json_write(self.path, row)
        return row


class ProductionPaperLoop:
    """PAPER-only process loop around the durable production supervisor.

    This layer performs process orchestration only. It never upgrades mode,
    submits exchange orders, mutates strategy configuration, or modifies code.
    """

    def __init__(
        self,
        *,
        payload_provider: Callable[[], Mapping[str, Any] | None],
        ledger: ProductionEventLedger,
        supervisor: ProductionAutoCycleSupervisor,
        snapshot_path: str | Path,
        state_path: str | Path,
        policy: PaperLoopPolicy | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.payload_provider = payload_provider
        self.ledger = ledger
        self.supervisor = supervisor
        self.snapshot_path = Path(snapshot_path)
        self.policy = policy or PaperLoopPolicy()
        self.clock = clock
        self.sleeper = sleeper
        self.state_store = PaperLoopStateStore(state_path, clock=clock)

    def _safe_state(self) -> dict[str, Any]:
        return self.state_store.load()

    def reset_circuit(self) -> dict[str, Any]:
        state = self._safe_state()
        state.update(
            {
                "state": "RESET",
                "action": "hold",
                "reason": "CIRCUIT_RESET_EXPLICIT",
                "consecutive_failures": 0,
                "circuit_open": False,
            }
        )
        return self.state_store.write(state)

    def _failure(self, state: dict[str, Any], reason: str, *, input_sha: str | None = None) -> dict[str, Any]:
        failures = int(state.get("consecutive_failures", 0)) + 1
        circuit_open = failures >= self.policy.max_consecutive_failures
        state.update(
            {
                "state": "CIRCUIT_OPEN" if circuit_open else "FAILED",
                "action": "hold",
                "reason": reason,
                "consecutive_failures": failures,
                "circuit_open": circuit_open,
            }
        )
        if input_sha is not None:
            state["last_failed_input_sha256"] = input_sha
        return self.state_store.write(state)

    def _blocked_non_paper(self, state: dict[str, Any], mode: str, input_sha: str) -> dict[str, Any]:
        state.update(
            {
                "state": "CIRCUIT_OPEN",
                "action": "hold",
                "reason": f"PAPER_LOOP_REJECT_NON_PAPER_MODE:{mode or 'MISSING'}",
                "consecutive_failures": self.policy.max_consecutive_failures,
                "circuit_open": True,
                "last_failed_input_sha256": input_sha,
            }
        )
        return self.state_store.write(state)

    def run_once(self) -> dict[str, Any]:
        state = self._safe_state()
        state["iterations"] = int(state.get("iterations", 0)) + 1

        if bool(state.get("circuit_open", False)):
            state.update(
                {
                    "state": "CIRCUIT_OPEN",
                    "action": "hold",
                    "reason": "PAPER_LOOP_CIRCUIT_OPEN",
                }
            )
            return self.state_store.write(state)

        try:
            payload = self.payload_provider()
        except Exception as exc:
            return self._failure(state, f"PAPER_INPUT_READ_FAILED:{type(exc).__name__}:{exc}")

        if payload is None:
            state.update(
                {
                    "state": "IDLE",
                    "action": "hold",
                    "reason": "PAPER_INPUT_MISSING",
                    "idle_count": int(state.get("idle_count", 0)) + 1,
                    "consecutive_failures": 0,
                }
            )
            return self.state_store.write(state)

        if not isinstance(payload, Mapping):
            return self._failure(state, "PAPER_INPUT_NOT_MAPPING")

        row = dict(payload)
        input_sha = stable_sha(row)
        mode = str(row.get("mode") or "").upper()
        if mode != "PAPER":
            return self._blocked_non_paper(state, mode, input_sha)

        if state.get("last_input_sha256") == input_sha:
            state.update(
                {
                    "state": "IDLE",
                    "action": "hold",
                    "reason": "PAPER_INPUT_UNCHANGED",
                    "idle_count": int(state.get("idle_count", 0)) + 1,
                    "consecutive_failures": 0,
                }
            )
            return self.state_store.write(state)

        cycle_key = cycle_key_for(row)
        try:
            receipt = self.supervisor.supervise(row, self.ledger)
        except Exception as exc:
            return self._failure(
                state,
                f"PAPER_SUPERVISOR_FAILED:{type(exc).__name__}:{exc}",
                input_sha=input_sha,
            )

        receipt_state = str(receipt.get("state") or "UNKNOWN")
        if receipt_state == "FAILED":
            return self._failure(
                state,
                f"PAPER_CYCLE_FAILED:{receipt.get('reason') or 'UNKNOWN'}",
                input_sha=input_sha,
            )

        result = receipt.get("result")
        canonical: Mapping[str, Any] | None = None
        if isinstance(result, Mapping):
            snapshot = result.get("snapshot")
            if isinstance(snapshot, Mapping):
                maybe_canonical = snapshot.get("canonical")
                if isinstance(maybe_canonical, Mapping):
                    canonical = maybe_canonical

        if canonical is not None:
            try:
                _atomic_json_write(self.snapshot_path, canonical)
            except Exception as exc:
                # Do not mark the input consumed. A subsequent iteration can replay
                # the supervisor receipt and repair snapshot persistence safely.
                return self._failure(
                    state,
                    f"PAPER_SNAPSHOT_WRITE_FAILED:{type(exc).__name__}:{exc}",
                    input_sha=input_sha,
                )

        state.update(
            {
                "state": receipt_state if receipt_state in {"COMPLETED", "HOLD"} else "HOLD",
                "action": str(receipt.get("action") or "hold"),
                "reason": str(receipt.get("reason") or "PAPER_CYCLE_COMPLETE"),
                "cycles_executed": int(state.get("cycles_executed", 0)) + 1,
                "consecutive_failures": 0,
                "last_input_sha256": input_sha,
                "last_cycle_key": cycle_key,
                "last_receipt_sha256": receipt.get("receipt_sha256"),
                "last_snapshot_sha256": None if canonical is None else canonical.get("snapshot_sha256"),
                "last_receipt_state": receipt_state,
                "circuit_open": False,
            }
        )
        return self.state_store.write(state)

    def run_forever(self, *, max_iterations: int | None = None) -> dict[str, Any]:
        if max_iterations is not None and max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        last: dict[str, Any] = self._safe_state()
        iterations = 0
        while True:
            last = self.run_once()
            iterations += 1
            if bool(last.get("circuit_open", False)):
                return last
            if max_iterations is not None and iterations >= max_iterations:
                return last
            if self.policy.interval_s:
                self.sleeper(self.policy.interval_s)


def build_default_loop(*, interval_s: float = 5.0, max_consecutive_failures: int = 3) -> ProductionPaperLoop:
    ledger_path = Path(os.environ.get("ZEL_PRODUCTION_LEDGER_PATH", DEFAULT_LEDGER))
    snapshot_path = Path(os.environ.get("ZEL_PRODUCTION_SNAPSHOT_PATH", DEFAULT_SNAPSHOT))
    supervisor_path = Path(os.environ.get("ZEL_PRODUCTION_SUPERVISOR_PATH", DEFAULT_SUPERVISOR_STATE))
    input_path = Path(os.environ.get("ZEL_PRODUCTION_PAPER_INPUT_PATH", DEFAULT_INPUT))
    loop_state_path = Path(os.environ.get("ZEL_PRODUCTION_PAPER_LOOP_STATE_PATH", DEFAULT_LOOP_STATE))
    return ProductionPaperLoop(
        payload_provider=JsonFilePayloadProvider(input_path),
        ledger=ProductionEventLedger(ledger_path),
        supervisor=ProductionAutoCycleSupervisor(supervisor_path),
        snapshot_path=snapshot_path,
        state_path=loop_state_path,
        policy=PaperLoopPolicy(
            interval_s=interval_s,
            max_consecutive_failures=max_consecutive_failures,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL production PAPER-only autonomous loop")
    parser.add_argument("--once", action="store_true", help="run one iteration and exit")
    parser.add_argument("--interval-s", type=float, default=5.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--reset-circuit", action="store_true")
    args = parser.parse_args(argv)

    loop = build_default_loop(
        interval_s=args.interval_s,
        max_consecutive_failures=args.max_consecutive_failures,
    )
    if args.reset_circuit:
        row = loop.reset_circuit()
        print(json.dumps(row, sort_keys=True))
        return 0

    try:
        row = loop.run_once() if args.once else loop.run_forever(max_iterations=args.max_iterations)
    except KeyboardInterrupt:
        return 130
    print(json.dumps(row, sort_keys=True))
    return 2 if row.get("circuit_open") else 0


if __name__ == "__main__":
    raise SystemExit(main())
