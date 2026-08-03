from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_COST_FLOOR_SCREEN_RESUMABLE_V1"
SCHEMA = "zel.exact25.cost_floor_screen.resumable.receipt.v1"
CHECKPOINT_SCHEMA = "zel.exact25.cost_floor_screen.checkpoint.v1"
HEARTBEAT_SCHEMA = "zel.exact25.cost_floor_screen.heartbeat.v1"


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
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
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


def finite(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def row_integrity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [str(row.get("event_id") or row.get("position_id") or "") for row in rows]
    duplicate_count = len(ids) - len(set(ids))
    unknown_exit_count = sum(
        1
        for row in rows
        if str(row.get("exit_reason") or row.get("reason") or "unknown").strip().lower()
        in {"", "unknown", "none", "null"}
    )
    required_cost_fields = (
        "fee",
        "slippage",
        "funding_pnl_estimate_usdt",
        "realized_R_including_funding_estimate",
    )
    missing_cost_lineage_count = sum(
        1
        for row in rows
        if any(not finite(row.get(field)) for field in required_cost_fields)
    )
    return {
        "trade_count": len(rows),
        "duplicate_trade_count": duplicate_count,
        "unknown_exit_count": unknown_exit_count,
        "missing_cost_lineage_count": missing_cost_lineage_count,
        "cost_lineage_complete": missing_cost_lineage_count == 0,
    }


def checkpoint_path(root: Path, kind: str, ordinal: int | None = None) -> Path:
    if ordinal is None:
        return root / f"{kind}.json"
    return root / f"{kind}-{ordinal:02d}.json"


def checkpoint_payload(
    *, kind: str, fingerprint: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema_version": CHECKPOINT_SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "input_fingerprint": fingerprint,
        "body": dict(body),
        "body_sha256": stable_sha(body),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["checkpoint_sha256"] = stable_sha(payload)
    return payload


def validate_checkpoint(
    path: Path, *, fingerprint: str, kind: str
) -> dict[str, Any]:
    payload = read_json(path)
    expected = str(payload.get("checkpoint_sha256") or "")
    material = dict(payload)
    material.pop("checkpoint_sha256", None)
    if not expected or stable_sha(material) != expected:
        raise RuntimeError(f"CHECKPOINT_SHA_MISMATCH:{path.name}")
    if payload.get("schema_version") != CHECKPOINT_SCHEMA:
        raise RuntimeError(f"CHECKPOINT_SCHEMA_MISMATCH:{path.name}")
    if payload.get("input_fingerprint") != fingerprint:
        raise RuntimeError(f"CHECKPOINT_FINGERPRINT_MISMATCH:{path.name}")
    if payload.get("kind") != kind:
        raise RuntimeError(f"CHECKPOINT_KIND_MISMATCH:{path.name}")
    body = payload.get("body")
    if not isinstance(body, Mapping):
        raise RuntimeError(f"CHECKPOINT_BODY_MISSING:{path.name}")
    if stable_sha(body) != payload.get("body_sha256"):
        raise RuntimeError(f"CHECKPOINT_BODY_SHA_MISMATCH:{path.name}")
    return dict(body)


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
        "completed_units": list(completed),
        "completed_count": len(completed),
        "expected_count": expected_count,
        "current_unit": current,
        "error": error,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["receipt_sha256"] = stable_sha(payload)
    atomic_write_json(path, payload)


def run_with_heartbeat(
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
                state="RUNNING",
                fingerprint=fingerprint,
                completed=completed,
                current=current,
                expected_count=expected_count,
            )

    thread = threading.Thread(target=emit, daemon=True)
    thread.start()
    try:
        return callback()
    finally:
        stop.set()
        thread.join(timeout=5.0)


def validate_external_receipts(
    source_owner: Mapping[str, Any], cost_audit: Mapping[str, Any]
) -> None:
    if source_owner.get("state") != "PASS_EXACT25_SOURCE_OWNER_AUDIT":
        raise RuntimeError("SOURCE_OWNER_AUDIT_NOT_PASS")
    if int(source_owner.get("strategy_count") or 0) != 25:
        raise RuntimeError("SOURCE_OWNER_STRATEGY_COUNT_MISMATCH")
    if source_owner.get("quarantined_strategy_ids"):
        raise RuntimeError("SOURCE_OWNER_QUARANTINE_NOT_EMPTY")
    if cost_audit.get("accounting_integrity_pass") is not True:
        raise RuntimeError("COST_ACCOUNTING_INTEGRITY_NOT_PASS")
    if cost_audit.get("selected_route") != "COST_GEOMETRY_AND_TURNOVER_REDESIGN":
        raise RuntimeError("COST_ROUTE_CONFIRMATION_MISMATCH")


def baseline_body(
    cost_screen: Any,
    engine: Any,
    policy: Mapping[str, Any],
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
) -> dict[str, Any]:
    strategy_id = str(policy["strategy_id"])
    card, rows, meta = cost_screen.screen.run_replay(
        engine_path, source_root, data_root, strategy_id
    )
    immutable_rows = cost_screen.screen.read_terminal_rows(
        terminal_root / "trades.jsonl.gz", strategy_id
    )
    report = read_json(terminal_root / "report.json")
    terminal_card = next(
        row
        for row in report.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id") == strategy_id
    )
    metrics = card["closed_metrics_including_funding_estimate"]
    terminal_metrics = terminal_card["closed_metrics_including_funding_estimate"]
    integrity = row_integrity(rows)
    immutable_integrity = row_integrity(immutable_rows)
    parity = {
        "trade_count": len(rows) == len(immutable_rows),
        "economic_digest": cost_screen.screen.economic_digest(rows)
        == cost_screen.screen.economic_digest(immutable_rows),
        "net_R": abs(
            float(metrics.get("net_R") or 0.0)
            - float(terminal_metrics.get("net_R") or 0.0)
        )
        <= 1e-9,
        "profit_factor": abs(
            float(metrics.get("profit_factor") or 0.0)
            - float(terminal_metrics.get("profit_factor") or 0.0)
        )
        <= 1e-9,
        "max_drawdown_R": abs(
            float(metrics.get("max_drawdown_R") or 0.0)
            - float(terminal_metrics.get("max_drawdown_R") or 0.0)
        )
        <= 1e-9,
        "errors_zero": int(meta.get("error_count") or 0) == 0,
        "censored_zero": int(meta.get("censored_open_count") or 0) == 0,
        "duplicates_zero": integrity["duplicate_trade_count"] == 0,
        "unknown_exits_zero": integrity["unknown_exit_count"] == 0,
        "cost_lineage_complete": integrity["cost_lineage_complete"] is True,
        "immutable_duplicates_zero": immutable_integrity["duplicate_trade_count"] == 0,
        "immutable_unknown_exits_zero": immutable_integrity["unknown_exit_count"] == 0,
        "immutable_cost_lineage_complete": immutable_integrity["cost_lineage_complete"] is True,
    }
    if not all(parity.values()):
        raise RuntimeError(f"BASELINE_PARITY_FAIL:{parity}")
    return {
        "strategy_id": strategy_id,
        "baseline_parity": parity,
        "baseline": cost_screen.by_window(engine, rows),
        "baseline_integrity": integrity,
        "immutable_integrity": immutable_integrity,
        "baseline_economic_digest_sha256": cost_screen.screen.economic_digest(rows),
        "immutable_economic_digest_sha256": cost_screen.screen.economic_digest(immutable_rows),
    }


def candidate_body(
    cost_screen: Any,
    engine: Any,
    policy: Mapping[str, Any],
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    baseline: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = str(policy["strategy_id"])
    original_wrapper = cost_screen.screen.FilteredOwner
    cost_screen.screen.FilteredOwner = cost_screen.RiskDistanceOwner
    try:
        _card, rows, meta = cost_screen.screen.run_replay(
            engine_path,
            source_root,
            data_root,
            strategy_id,
            str(policy["axis_id"]),
            config,
        )
    finally:
        cost_screen.screen.FilteredOwner = original_wrapper
    windows = cost_screen.by_window(engine, rows)
    gate_policy = policy["positive_gate"]
    w1_ok, w1_blockers, w1_retention = cost_screen.gate(
        windows["1m_w1"],
        int(baseline["baseline"]["1m_w1"]["sample_count"] or 0),
        int(gate_policy["minimum_w1_trade_count"]),
        gate_policy,
    )
    integrity = row_integrity(rows)
    operational_ok = (
        int(meta.get("error_count") or 0) <= int(gate_policy["error_count_max"])
        and int(meta.get("censored_open_count") or 0)
        <= int(gate_policy["censored_open_count_max"])
        and int(meta.get("blocked_entry_count") or 0) > 0
        and int(meta.get("unknown_side_count") or 0) == 0
        and integrity["duplicate_trade_count"] == 0
        and integrity["unknown_exit_count"] == 0
        and integrity["cost_lineage_complete"] is True
    )
    blockers = list(w1_blockers)
    if int(meta.get("error_count") or 0) > int(gate_policy["error_count_max"]):
        blockers.append("ERROR_COUNT_ABOVE_MAX")
    if int(meta.get("censored_open_count") or 0) > int(
        gate_policy["censored_open_count_max"]
    ):
        blockers.append("CENSORED_OPEN_ABOVE_MAX")
    if int(meta.get("blocked_entry_count") or 0) == 0:
        blockers.append("AXIS_NOT_EXERCISED")
    if int(meta.get("unknown_side_count") or 0) != 0:
        blockers.append("UNKNOWN_SIDE")
    if integrity["duplicate_trade_count"]:
        blockers.append("DUPLICATE_TRADES")
    if integrity["unknown_exit_count"]:
        blockers.append("UNKNOWN_EXITS")
    if not integrity["cost_lineage_complete"]:
        blockers.append("COST_LINEAGE_INCOMPLETE")
    return {
        "config": dict(config),
        "config_sha256": stable_sha(config),
        "metrics": windows,
        "counters": dict(meta),
        "integrity": integrity,
        "economic_digest_sha256": cost_screen.screen.economic_digest(rows),
        "w1_pass": w1_ok and operational_ok,
        "w1_blockers": blockers,
        "w1_retention_pct": w1_retention,
        "operational_integrity_pass": operational_ok,
    }


def build_receipt(
    cost_screen: Any,
    policy: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    fingerprint: str,
    checkpoint_dir: Path,
    source_owner: Mapping[str, Any],
    cost_audit: Mapping[str, Any],
) -> dict[str, Any]:
    eligible = [row for row in candidates if row.get("w1_pass") is True]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["metrics"]["1m_w1"].get("net_R") or 0.0),
            float(row["metrics"]["1m_w1"].get("profit_factor") or 0.0),
            float(row["metrics"]["1m_w1"].get("payoff_ratio") or 0.0),
        ),
        default=None,
    )
    confirmation: dict[str, Any] = {}
    all_pass = selected is not None
    gate_policy = policy["positive_gate"]
    if selected is not None:
        for window in ("1m_w2", "1m_w3"):
            passed, blockers, retention = cost_screen.gate(
                selected["metrics"][window],
                int(baseline["baseline"][window]["sample_count"] or 0),
                int(gate_policy["minimum_confirmation_trade_count"]),
                gate_policy,
            )
            confirmation[window] = {
                "pass": passed,
                "blockers": blockers,
                "retention_pct": retention,
                "baseline": baseline["baseline"][window],
                "candidate": selected["metrics"][window],
            }
            all_pass = bool(all_pass and passed)
        passed, blockers, retention = cost_screen.gate(
            selected["metrics"]["all"],
            int(baseline["baseline"]["all"]["sample_count"] or 0),
            int(gate_policy["minimum_confirmation_trade_count"]),
            gate_policy,
        )
        confirmation["all"] = {
            "pass": passed,
            "blockers": blockers,
            "retention_pct": retention,
            "baseline": baseline["baseline"]["all"],
            "candidate": selected["metrics"]["all"],
        }
        all_pass = bool(all_pass and passed)
    survivor = bool(
        selected is not None
        and all(baseline["baseline_parity"].values())
        and selected.get("operational_integrity_pass") is True
        and all_pass
    )
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_COST_FLOOR_SCREEN_RESUMABLE_COMPLETE",
        "input_fingerprint": fingerprint,
        "strategy_id": policy["strategy_id"],
        "axis_id": policy["axis_id"],
        "parent_route": policy["parent_route"],
        "source_owner_receipt_sha256": source_owner.get("receipt_sha256"),
        "cost_audit_receipt_sha256": cost_audit.get("receipt_sha256"),
        "baseline_parity": baseline["baseline_parity"],
        "baseline": baseline["baseline"],
        "baseline_integrity": baseline["baseline_integrity"],
        "candidate_count": len(candidates),
        "candidates": [dict(row) for row in candidates],
        "selected_config": selected["config"] if selected else None,
        "selected_config_sha256": selected["config_sha256"] if selected else None,
        "selection_protocol": {
            "select_on_w1_only": True,
            "freeze_selected_config_for_w2_w3": True,
            "w2_w3_retuning_performed": False,
            "entry_time_information_only": True,
            "future_MFE_MAE_forbidden": True,
        },
        "confirmation": confirmation,
        "survivor": survivor,
        "survivor_state": (
            "PASS_POSITIVE_W1_W2_W3_COST_FLOOR_SURVIVOR"
            if survivor
            else "HOLD_NO_POSITIVE_COST_FLOOR_SURVIVOR"
        ),
        "checkpoint": {
            "directory": str(checkpoint_dir),
            "baseline_checkpoint": True,
            "candidate_checkpoint_count": len(candidates),
            "expected_candidate_count": len(policy["candidate_configs"]),
            "resume_enabled": True,
            "atomic_checkpoint": True,
        },
        "entry_time_information_only": True,
        "future_MFE_MAE_used": False,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "SEAL_RESEARCH_HOLDBACK_AND_INTERACTION_TEST"
            if survivor
            else "ADVANCE_NEXT_COST_GEOMETRY_AXIS_OR_STRATEGY"
        ),
    }
    if len(candidates) != len(policy["candidate_configs"]):
        raise RuntimeError("FINAL_CANDIDATE_COUNT_MISMATCH")
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def run(
    *,
    screen_path: Path,
    indicator_helper_path: Path,
    engine_path: Path,
    policy_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
    source_owner_path: Path,
    cost_audit_path: Path,
    checkpoint_dir: Path,
    heartbeat_out: Path | None,
    out: Path,
) -> dict[str, Any]:
    cost_screen = load_module(screen_path, f"zel_cost_floor_screen_{os.getpid()}")
    policy = read_json(policy_path)
    source_owner = read_json(source_owner_path)
    cost_audit = read_json(cost_audit_path)
    validate_external_receipts(source_owner, cost_audit)
    fingerprint = stable_sha(
        {
            "screen_sha256": file_sha(screen_path),
            "indicator_helper_sha256": file_sha(indicator_helper_path),
            "engine_sha256": file_sha(engine_path),
            "policy_sha256": file_sha(policy_path),
            "terminal_report_sha256": file_sha(terminal_root / "report.json"),
            "terminal_trades_sha256": file_sha(terminal_root / "trades.jsonl.gz"),
            "source_owner_sha256": file_sha(source_owner_path),
            "cost_audit_sha256": file_sha(cost_audit_path),
            "source_root": str(source_root.resolve()),
            "data_root": str(data_root.resolve()),
        }
    )
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    expected_count = 1 + len(policy["candidate_configs"])
    completed: list[str] = []
    heartbeat(
        heartbeat_out,
        state="STARTING",
        fingerprint=fingerprint,
        completed=completed,
        current=None,
        expected_count=expected_count,
    )
    engine = cost_screen.screen.load_module(
        engine_path, f"zel_cost_floor_engine_resumable_{os.getpid()}"
    )
    try:
        baseline_path = checkpoint_path(checkpoint_dir, "baseline")
        if baseline_path.exists():
            baseline = validate_checkpoint(
                baseline_path, fingerprint=fingerprint, kind="baseline"
            )
        else:
            baseline = run_with_heartbeat(
                lambda: baseline_body(
                    cost_screen,
                    engine,
                    policy,
                    engine_path,
                    source_root,
                    data_root,
                    terminal_root,
                ),
                heartbeat_out=heartbeat_out,
                fingerprint=fingerprint,
                completed=completed,
                current="baseline",
                expected_count=expected_count,
            )
            atomic_write_json(
                baseline_path,
                checkpoint_payload(
                    kind="baseline", fingerprint=fingerprint, body=baseline
                ),
            )
        completed.append("baseline")
        heartbeat(
            heartbeat_out,
            state="CHECKPOINT_COMMITTED",
            fingerprint=fingerprint,
            completed=completed,
            current="baseline",
            expected_count=expected_count,
        )
        candidates: list[dict[str, Any]] = []
        for ordinal, config in enumerate(policy["candidate_configs"], 1):
            unit = f"candidate-{ordinal:02d}"
            path = checkpoint_path(checkpoint_dir, "candidate", ordinal)
            if path.exists():
                body = validate_checkpoint(path, fingerprint=fingerprint, kind=unit)
            else:
                body = run_with_heartbeat(
                    lambda config=config: candidate_body(
                        cost_screen,
                        engine,
                        policy,
                        engine_path,
                        source_root,
                        data_root,
                        baseline,
                        config,
                    ),
                    heartbeat_out=heartbeat_out,
                    fingerprint=fingerprint,
                    completed=completed,
                    current=unit,
                    expected_count=expected_count,
                )
                if body.get("config_sha256") != stable_sha(config):
                    raise RuntimeError(f"CANDIDATE_CONFIG_SHA_MISMATCH:{ordinal}")
                atomic_write_json(
                    path,
                    checkpoint_payload(kind=unit, fingerprint=fingerprint, body=body),
                )
            candidates.append(dict(body))
            completed.append(unit)
            heartbeat(
                heartbeat_out,
                state="CHECKPOINT_COMMITTED",
                fingerprint=fingerprint,
                completed=completed,
                current=unit,
                expected_count=expected_count,
            )
        receipt = build_receipt(
            cost_screen,
            policy,
            baseline,
            candidates,
            fingerprint=fingerprint,
            checkpoint_dir=checkpoint_dir,
            source_owner=source_owner,
            cost_audit=cost_audit,
        )
        atomic_write_json(out, receipt)
        heartbeat(
            heartbeat_out,
            state="PASS",
            fingerprint=fingerprint,
            completed=completed,
            current=None,
            expected_count=expected_count,
        )
        return receipt
    except Exception as exc:
        heartbeat(
            heartbeat_out,
            state="FAIL",
            fingerprint=fingerprint,
            completed=completed,
            current=None,
            expected_count=expected_count,
            error=f"{type(exc).__name__}:{exc}",
        )
        raise


def self_test() -> int:
    rows = [
        {
            "event_id": "a",
            "exit_reason": "take_profit",
            "fee": 1.0,
            "slippage": 0.1,
            "funding_pnl_estimate_usdt": 0.0,
            "realized_R_including_funding_estimate": 1.2,
        }
    ]
    integrity = row_integrity(rows)
    assert integrity["duplicate_trade_count"] == 0
    assert integrity["unknown_exit_count"] == 0
    assert integrity["cost_lineage_complete"] is True
    payload = checkpoint_payload(kind="baseline", fingerprint="a" * 64, body={"x": 1})
    assert payload["checkpoint_sha256"]
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", type=Path)
    parser.add_argument("--indicator-helper", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--cost-audit", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--heartbeat-out", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.screen,
        args.indicator_helper,
        args.engine,
        args.policy,
        args.source_root,
        args.data_root,
        args.terminal_root,
        args.source_owner,
        args.cost_audit,
        args.checkpoint_dir,
        args.out,
    )
    if any(value is None for value in required):
        parser.error("all runtime paths except heartbeat-out are required")
    receipt = run(
        screen_path=args.screen.resolve(),
        indicator_helper_path=args.indicator_helper.resolve(),
        engine_path=args.engine.resolve(),
        policy_path=args.policy.resolve(),
        source_root=args.source_root.resolve(),
        data_root=args.data_root.resolve(),
        terminal_root=args.terminal_root.resolve(),
        source_owner_path=args.source_owner.resolve(),
        cost_audit_path=args.cost_audit.resolve(),
        checkpoint_dir=args.checkpoint_dir.resolve(),
        heartbeat_out=args.heartbeat_out.resolve() if args.heartbeat_out else None,
        out=args.out.resolve(),
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "strategy_id": receipt["strategy_id"],
                "candidate_count": receipt["candidate_count"],
                "survivor": receipt["survivor"],
                "checkpoint": receipt["checkpoint"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
