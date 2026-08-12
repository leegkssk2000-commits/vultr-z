from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_trend_momentum_v1 import generate_live_signal, load_config
from backend.production.zel_production_v2_family_signal_v1 import SUPPORTED_STRATEGIES as V2_FAMILY_STRATEGIES, generate_runtime_signal

SCHEMA = "zel.production_alpha_signal_runner.v1"
DEFAULT_FACTORY = Path("config/zel_production_alpha_factory_v1.json")
DEFAULT_RECEIPT = Path("/home/z/z/ledger/production_alpha_signal_runner_v1.json")


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
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


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label}_MISSING:{path}") from exc
    except Exception as exc:
        raise RuntimeError(f"{label}_INVALID_JSON:{type(exc).__name__}") from exc
    if not isinstance(row, dict):
        raise RuntimeError(f"{label}_NOT_OBJECT")
    return row


def resolve_paths(factory: Mapping[str, Any]) -> tuple[Path, Path]:
    authority_raw = os.environ.get("ZEL_PRODUCTION_ALPHA_AUTHORITY_PATH") or factory.get("active_authority_path")
    signal_raw = os.environ.get("ZEL_PRODUCTION_ACTIVE_ALPHA_SIGNAL_PATH") or factory.get("active_signal_path")
    if not authority_raw:
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_AUTHORITY_PATH_UNBOUND")
    if not signal_raw:
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_PATH_UNBOUND")
    return Path(str(authority_raw)), Path(str(signal_raw))


def hold_receipt(reason: str, *, authority_path: Path, signal_path: Path, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": "HOLD_NO_EXECUTABLE_ALPHA",
        "action": "hold",
        "reason": reason,
        "observed_at_ms": now_ms,
        "authority_path": str(authority_path),
        "signal_path": str(signal_path),
        "network_called": False,
        "signal_written": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }


def run_once(
    *,
    factory: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
    signal_generator=None,
) -> dict[str, Any]:
    cfg = dict(factory) if factory is not None else load_config(DEFAULT_FACTORY)
    if cfg.get("schema_version") != "zel.production_alpha_factory.v1":
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_FACTORY_SCHEMA_INVALID")
    if str(cfg.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_NON_PAPER_FORBIDDEN")
    if cfg.get("order_authority") != "BLOCKED" or cfg.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_LIVE_AUTHORITY_FORBIDDEN")

    authority_path, signal_path = resolve_paths(cfg)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)

    # Critical SAFE-IDLE fast path: missing authority must not touch BingX and
    # must not create, truncate, or overwrite the active signal file.
    if not authority_path.exists():
        return hold_receipt(
            "ALPHA_AUTHORITY_MISSING",
            authority_path=authority_path,
            signal_path=signal_path,
            now_ms=now,
        )

    authority = read_json(authority_path, "ALPHA_SIGNAL_RUNNER_AUTHORITY")
    if not authority_is_executable(authority):
        return hold_receipt(
            "ALPHA_AUTHORITY_NON_EXECUTABLE",
            authority_path=authority_path,
            signal_path=signal_path,
            now_ms=now,
        )

    strategy_id = str(authority.get("strategy_id") or "")
    if strategy_id in V2_FAMILY_STRATEGIES:
        if signal_generator is None:
            signal = generate_runtime_signal(authority, now_ms=now)
        else:
            signal = signal_generator(authority, factory=cfg, now_ms=now)
        network_called = False
        reason = "EXECUTABLE_V2_FAMILY_SIGNAL_REFRESHED"
        producer = "VERIFIED_NATIVE_SNAPSHOT_V2_FAMILY"
    elif strategy_id == "trend_momentum_v1":
        # This path remains for compatibility, but current terminal-strategy
        # authority rules make a terminal trend authority non-executable.
        generator = signal_generator or generate_live_signal
        signal = generator(authority, factory=cfg, now_ms=now)
        network_called = True
        reason = "EXECUTABLE_TREND_MOMENTUM_SIGNAL_REFRESHED"
        producer = "BINGX_LIVE_TREND_MOMENTUM"
    else:
        raise RuntimeError(f"ALPHA_PRODUCER_UNSUPPORTED_STRATEGY:{strategy_id or 'MISSING'}")

    if not isinstance(signal, Mapping):
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_GENERATOR_NOT_MAPPING")
    if signal.get("schema_version") != "zel.production_alpha_signal.v1":
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_SCHEMA_INVALID")
    if signal.get("state") != "PASS_ACTIVE_ALPHA_SIGNAL":
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_NOT_PASS")
    if signal.get("exchange_order_submitted") is not False:
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_EXCHANGE_SUBMISSION_FORBIDDEN")
    if str(signal.get("strategy_id") or "") != strategy_id:
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_STRATEGY_MISMATCH")
    if str(signal.get("alpha_id") or "") != str(authority.get("alpha_id") or ""):
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_ALPHA_MISMATCH")
    if str(signal.get("symbol") or "").replace("-", "").upper() != str(authority.get("symbol") or "").replace("-", "").upper():
        raise RuntimeError("ALPHA_SIGNAL_RUNNER_SIGNAL_SYMBOL_MISMATCH")

    atomic_json_write(signal_path, signal)
    return {
        "schema_version": SCHEMA,
        "state": "PASS_ACTIVE_ALPHA_SIGNAL_WRITTEN",
        "action": "hold",
        "reason": reason,
        "producer": producer,
        "observed_at_ms": now,
        "strategy_id": strategy_id,
        "alpha_id": signal.get("alpha_id"),
        "symbol": signal.get("symbol"),
        "signal": signal.get("signal"),
        "signal_receipt_sha256": signal.get("receipt_sha256"),
        "authority_path": str(authority_path),
        "signal_path": str(signal_path),
        "network_called": network_called,
        "signal_written": True,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL production alpha signal producer runner")
    parser.add_argument("--factory", type=Path, default=DEFAULT_FACTORY)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path(os.environ.get("ZEL_PRODUCTION_ALPHA_SIGNAL_RUNNER_RECEIPT_PATH", str(DEFAULT_RECEIPT))),
    )
    args = parser.parse_args(argv)
    result = run_once(factory=load_config(args.factory))
    atomic_json_write(args.receipt, result)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
