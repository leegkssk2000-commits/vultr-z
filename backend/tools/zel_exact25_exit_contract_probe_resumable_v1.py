from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_EXIT_CONTRACT_PROBE_RESUMABLE_V1"
SCHEMA = "zel.exact25.exit_contract_probe.resumable.receipt.v1"
CHECKPOINT_SCHEMA = "zel.exact25.exit_contract_probe.strategy_checkpoint.v1"
HEARTBEAT_SCHEMA = "zel.exact25.exit_contract_probe.heartbeat.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def metric_parts(summary: Mapping[str, Any]) -> dict[str, float]:
    sample_count = max(0, int(summary.get("sample_count") or 0))
    win_rate = finite(summary.get("win_rate_pct"))
    average_win = max(0.0, finite(summary.get("average_win_R")))
    average_loss = max(0.0, finite(summary.get("average_loss_abs_R")))
    net = finite(summary.get("net_R"))
    wins = max(0, min(sample_count, int(round(sample_count * win_rate / 100.0))))
    gross_win = average_win * wins
    gross_loss = max(0.0, gross_win - net)
    losses = int(round(gross_loss / average_loss)) if average_loss > 0 else 0
    losses = max(0, min(sample_count - wins, losses))
    return {
        "sample_count": float(sample_count),
        "wins": float(wins),
        "losses": float(losses),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
    }


def merge_metrics(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    parts = [metric_parts(summary) for summary in summaries]
    sample_count = int(sum(part["sample_count"] for part in parts))
    wins = int(sum(part["wins"] for part in parts))
    losses = int(sum(part["losses"] for part in parts))
    gross_win = sum(part["gross_win"] for part in parts)
    gross_loss = sum(part["gross_loss"] for part in parts)
    net = gross_win - gross_loss
    average_win = gross_win / wins if wins else 0.0
    average_loss = gross_loss / losses if losses else 0.0
    return {
        "sample_count": sample_count,
        "net_R": net,
        "profit_factor": gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0),
        "expectancy_R": net / sample_count if sample_count else 0.0,
        "win_rate_pct": wins / sample_count * 100.0 if sample_count else 0.0,
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss,
        "payoff_ratio": average_win / average_loss if average_loss else (999.0 if average_win else 0.0),
    }


def merge_group_maps(group_maps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    keys = sorted({str(key) for group_map in group_maps for key in group_map})
    return {
        key: merge_metrics(
            [
                group_map[key]
                for group_map in group_maps
                if key in group_map and isinstance(group_map[key], Mapping)
            ]
        )
        for key in keys
    }


def heartbeat(
    path: Path | None,
    *,
    state: str,
    fingerprint: str,
    completed: Sequence[str],
    current: str | None,
    expected_count: int,
    error: str | None = None,
) -> None:
    if path is None:
        return
    payload = {
        "schema_version": HEARTBEAT_SCHEMA,
        "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "input_fingerprint": fingerprint,
        "completed_strategy_ids": list(completed),
        "completed_count": len(completed),
        "expected_count": expected_count,
        "current_strategy_id": current,
        "error": error,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["receipt_sha256"] = stable_sha(payload)
    atomic_write_json(path, payload)


def run_with_periodic_heartbeat(
    callback: Any,
    *,
    heartbeat_out: Path | None,
    fingerprint: str,
    completed: Sequence[str],
    current: str,
    expected_count: int,
    interval_sec: float = 60.0,
) -> Any:
    stop = threading.Event()

    def emit() -> None:
        while not stop.wait(interval_sec):
            heartbeat(
                heartbeat_out,
                state="RUNNING_STRATEGY",
                fingerprint=fingerprint,
                completed=completed,
                current=current,
                expected_count=expected_count,
            )

    thread = threading.Thread(target=emit, name="zel-exit-probe-heartbeat", daemon=True)
    thread.start()
    try:
        return callback()
    finally:
        stop.set()
        thread.join(timeout=5.0)


def checkpoint_path(root: Path, strategy_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in strategy_id)
    return root / f"strategy-{safe}.json"


def validate_checkpoint(
    payload: Mapping[str, Any],
    *,
    fingerprint: str,
    strategy_id: str,
) -> dict[str, Any]:
    expected_checkpoint_sha = str(payload.get("checkpoint_sha256") or "")
    checkpoint_material = dict(payload)
    checkpoint_material.pop("checkpoint_sha256", None)
    if not expected_checkpoint_sha or expected_checkpoint_sha != stable_sha(checkpoint_material):
        raise RuntimeError(f"CHECKPOINT_SHA_MISMATCH:{strategy_id}")
    if payload.get("schema_version") != CHECKPOINT_SCHEMA:
        raise RuntimeError(f"CHECKPOINT_SCHEMA_MISMATCH:{strategy_id}")
    if payload.get("input_fingerprint") != fingerprint:
        raise RuntimeError(f"CHECKPOINT_FINGERPRINT_MISMATCH:{strategy_id}")
    if payload.get("strategy_id") != strategy_id:
        raise RuntimeError(f"CHECKPOINT_STRATEGY_MISMATCH:{strategy_id}")
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise RuntimeError(f"CHECKPOINT_RECEIPT_MISSING:{strategy_id}")
    expected_sha = str(payload.get("receipt_sha256") or "")
    actual_sha = stable_sha(receipt)
    if not expected_sha or expected_sha != actual_sha:
        raise RuntimeError(f"CHECKPOINT_RECEIPT_SHA_MISMATCH:{strategy_id}")
    if receipt.get("state") != "PASS_EXIT_CONTRACT_PROBE":
        raise RuntimeError(f"CHECKPOINT_NOT_PASS:{strategy_id}")
    if int(receipt.get("strategy_count") or 0) != 1:
        raise RuntimeError(f"CHECKPOINT_COUNT_MISMATCH:{strategy_id}")
    strategies = receipt.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 1:
        raise RuntimeError(f"CHECKPOINT_STRATEGY_RECEIPT_MISSING:{strategy_id}")
    if strategies[0].get("strategy_id") != strategy_id:
        raise RuntimeError(f"CHECKPOINT_INNER_STRATEGY_MISMATCH:{strategy_id}")
    if receipt.get("all_baseline_parity") is not True:
        raise RuntimeError(f"CHECKPOINT_BASELINE_PARITY_FAIL:{strategy_id}")
    return dict(receipt)


def build_final(
    receipts: Sequence[Mapping[str, Any]],
    *,
    selected: Sequence[str],
    fingerprint: str,
    checkpoint_dir: Path,
) -> dict[str, Any]:
    strategies = [dict(receipt["strategies"][0]) for receipt in receipts]
    portfolio_rows = [receipt["portfolio"] for receipt in receipts]
    by_exit_source = merge_group_maps(
        [row.get("by_exit_source") or {} for row in portfolio_rows]
    )
    by_time_bucket = merge_group_maps(
        [row.get("by_time_bucket") or {} for row in portfolio_rows]
    )
    early_by_exit_source = merge_group_maps(
        [row.get("early_0_5m_by_exit_source") or {} for row in portfolio_rows]
    )
    reason_counts: Counter[str] = Counter()
    for row in portfolio_rows:
        reason_counts.update(
            {
                str(key): int(value)
                for key, value in (row.get("reason_counts") or {}).items()
            }
        )
    source_loss_rank = sorted(
        (
            {"exit_source": source, **summary}
            for source, summary in early_by_exit_source.items()
        ),
        key=lambda row: finite(row.get("net_R")),
    )
    all_baseline_parity = all(
        all(bool(value) for value in (strategy.get("baseline_parity") or {}).values())
        for strategy in strategies
    )
    unknown_exit_count = int(reason_counts.get("unknown", 0))
    result = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EXIT_CONTRACT_PROBE_RESUMABLE",
        "input_fingerprint": fingerprint,
        "strategy_count": len(strategies),
        "expected_strategy_ids": list(selected),
        "completed_strategy_ids": [str(row.get("strategy_id")) for row in strategies],
        "trade_count": sum(int(receipt.get("trade_count") or 0) for receipt in receipts),
        "strategies": strategies,
        "portfolio": {
            "metrics": merge_metrics(
                [row.get("metrics") or {} for row in portfolio_rows]
            ),
            "by_exit_source": by_exit_source,
            "by_time_bucket": by_time_bucket,
            "early_0_5m_by_exit_source": early_by_exit_source,
            "early_0_5m_source_loss_rank": source_loss_rank,
            "reason_counts": dict(reason_counts),
        },
        "all_baseline_parity": all_baseline_parity,
        "unknown_exit_count": unknown_exit_count,
        "checkpoint": {
            "enabled": True,
            "directory": str(checkpoint_dir),
            "completed_count": len(strategies),
            "expected_count": len(selected),
            "strategy_level_atomic_checkpoint": True,
            "resume_enabled": True,
        },
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "BUILD_ONE_CAUSAL_EXIT_AXIS_FROM_EARLY_LOSS_RANK",
    }
    if len(strategies) != len(selected):
        raise RuntimeError("FINAL_STRATEGY_COUNT_MISMATCH")
    if [row.get("strategy_id") for row in strategies] != list(selected):
        raise RuntimeError("FINAL_STRATEGY_ORDER_MISMATCH")
    if not all_baseline_parity:
        raise RuntimeError("FINAL_BASELINE_PARITY_FAIL")
    result["receipt_sha256"] = stable_sha(result)
    return result


def run_resumable(
    *,
    probe_path: Path,
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_path: Path,
    source_owner_path: Path,
    execution_path: Path,
    checkpoint_dir: Path,
    heartbeat_out: Path | None,
    out: Path,
) -> dict[str, Any]:
    probe = load_module(probe_path, f"zel_exit_contract_probe_{os.getpid()}")
    source_owner = read_json(source_owner_path)
    if source_owner.get("state") != "PASS_EXACT25_SOURCE_OWNER_AUDIT":
        raise RuntimeError("SOURCE_OWNER_AUDIT_NOT_PASS")
    if int(source_owner.get("strategy_count") or 0) != 25:
        raise RuntimeError("SOURCE_OWNER_STRATEGY_COUNT_MISMATCH")
    if source_owner.get("quarantined_strategy_ids"):
        raise RuntimeError("SOURCE_OWNER_QUARANTINE_NOT_EMPTY")
    execution = read_json(execution_path)
    selected = [str(value) for value in execution.get("strategy_ids", [])]
    if not selected:
        raise RuntimeError("NO_STRATEGY_IDS")
    fingerprint = stable_sha(
        {
            "probe_sha256": file_sha(probe_path),
            "engine_sha256": file_sha(engine_path),
            "terminal_sha256": file_sha(terminal_path),
            "source_owner_sha256": file_sha(source_owner_path),
            "execution_sha256": file_sha(execution_path),
            "source_root": str(source_root.resolve()),
            "data_root": str(data_root.resolve()),
            "strategy_ids": selected,
        }
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    completed: list[str] = []
    heartbeat(
        heartbeat_out,
        state="STARTING",
        fingerprint=fingerprint,
        completed=completed,
        current=None,
        expected_count=len(selected),
    )
    try:
        for strategy_id in selected:
            path = checkpoint_path(checkpoint_dir, strategy_id)
            if path.exists():
                receipt = validate_checkpoint(
                    read_json(path),
                    fingerprint=fingerprint,
                    strategy_id=strategy_id,
                )
                receipts.append(receipt)
                completed.append(strategy_id)
                heartbeat(
                    heartbeat_out,
                    state="RESUMED_CHECKPOINT",
                    fingerprint=fingerprint,
                    completed=completed,
                    current=strategy_id,
                    expected_count=len(selected),
                )
                continue
            heartbeat(
                heartbeat_out,
                state="RUNNING_STRATEGY",
                fingerprint=fingerprint,
                completed=completed,
                current=strategy_id,
                expected_count=len(selected),
            )
            receipt = run_with_periodic_heartbeat(
                lambda: probe.run(
                    engine_path.resolve(),
                    source_root.resolve(),
                    data_root.resolve(),
                    terminal_path.resolve(),
                    [strategy_id],
                ),
                heartbeat_out=heartbeat_out,
                fingerprint=fingerprint,
                completed=tuple(completed),
                current=strategy_id,
                expected_count=len(selected),
            )
            if receipt.get("state") != "PASS_EXIT_CONTRACT_PROBE":
                raise RuntimeError(f"STRATEGY_PROBE_FAILED:{strategy_id}")
            payload = {
                "schema_version": CHECKPOINT_SCHEMA,
                "version": VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "input_fingerprint": fingerprint,
                "strategy_id": strategy_id,
                "receipt": receipt,
                "receipt_sha256": stable_sha(receipt),
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "action": "hold",
            }
            payload["checkpoint_sha256"] = stable_sha(payload)
            atomic_write_json(path, payload)
            receipts.append(dict(receipt))
            completed.append(strategy_id)
            heartbeat(
                heartbeat_out,
                state="CHECKPOINT_COMMITTED",
                fingerprint=fingerprint,
                completed=completed,
                current=strategy_id,
                expected_count=len(selected),
            )
        result = build_final(
            receipts,
            selected=selected,
            fingerprint=fingerprint,
            checkpoint_dir=checkpoint_dir,
        )
        atomic_write_json(out, result)
        heartbeat(
            heartbeat_out,
            state="PASS",
            fingerprint=fingerprint,
            completed=completed,
            current=None,
            expected_count=len(selected),
        )
        return result
    except Exception as exc:
        heartbeat(
            heartbeat_out,
            state="FAIL",
            fingerprint=fingerprint,
            completed=completed,
            current=selected[len(completed)] if len(completed) < len(selected) else None,
            expected_count=len(selected),
            error=f"{type(exc).__name__}:{exc}",
        )
        raise


def self_test() -> int:
    merged = merge_metrics(
        [
            {
                "sample_count": 2,
                "net_R": 1.0,
                "win_rate_pct": 50.0,
                "average_win_R": 2.0,
                "average_loss_abs_R": 1.0,
            },
            {
                "sample_count": 2,
                "net_R": -0.5,
                "win_rate_pct": 50.0,
                "average_win_R": 0.5,
                "average_loss_abs_R": 1.0,
            },
        ]
    )
    assert merged["sample_count"] == 4
    assert abs(merged["net_R"] - 0.5) <= 1e-12
    assert checkpoint_path(Path("/tmp/x"), "a/b").name == "strategy-a_b.json"
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--heartbeat-out", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.probe,
        args.engine,
        args.source_root,
        args.data_root,
        args.terminal,
        args.source_owner,
        args.execution,
        args.checkpoint_dir,
        args.out,
    )
    if any(value is None for value in required):
        parser.error(
            "probe, engine, source-root, data-root, terminal, source-owner, execution, "
            "checkpoint-dir and out are required"
        )
    result = run_resumable(
        probe_path=args.probe.resolve(),
        engine_path=args.engine.resolve(),
        source_root=args.source_root.resolve(),
        data_root=args.data_root.resolve(),
        terminal_path=args.terminal.resolve(),
        source_owner_path=args.source_owner.resolve(),
        execution_path=args.execution.resolve(),
        checkpoint_dir=args.checkpoint_dir.resolve(),
        heartbeat_out=args.heartbeat_out.resolve() if args.heartbeat_out else None,
        out=args.out.resolve(),
    )
    print(
        json.dumps(
            {
                "state": result["state"],
                "strategy_count": result["strategy_count"],
                "trade_count": result["trade_count"],
                "unknown_exit_count": result["unknown_exit_count"],
                "checkpoint": result["checkpoint"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
