from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_CUMULATIVE_MATERIALIZER_V1"
SCHEMA = "zel.grid.cumulative_materializer.receipt.v1"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def stable_sha(grid: Any, value: Any) -> str:
    return grid.stable_sha(value)


def build(
    *,
    policy_path: Path,
    grid_tool_path: Path,
    base_tool_path: Path,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
    candidate_rows_out: Path,
    receipt_out: Path,
) -> dict[str, Any]:
    grid = load_module(grid_tool_path, f"zel_grid_materializer_grid_{os.getpid()}")
    base = load_module(base_tool_path, f"zel_grid_materializer_base_{os.getpid()}")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    strategy_id = str(policy["strategy_id"])
    terminal_path = terminal_root / "trades.jsonl.gz"
    terminal_rows = grid.read_terminal_grid_rows(terminal_path, strategy_id)
    terminal_event_digest = stable_sha(
        grid,
        sorted(str(row.get("event_id") or row.get("trade_id") or "") for row in terminal_rows),
    )
    terminal_checks = {
        "terminal_file_sha_match": grid.file_sha(terminal_path) == policy["expected_terminal_trades_sha256"],
        "terminal_trade_count_match": len(terminal_rows) == int(policy["expected_terminal_trade_count"]),
        "terminal_event_id_set_match": terminal_event_digest == policy["expected_terminal_event_id_set_sha256"],
    }

    with tempfile.TemporaryDirectory(prefix="zel-grid-cumulative-materializer-") as temp_dir:
        temp = Path(temp_dir)
        baseline_rows_path = temp / "baseline.jsonl.gz"
        baseline_meta_path = temp / "baseline_meta.json"
        candidate_rows_path = temp / "candidate.jsonl.gz"
        candidate_meta_path = temp / "candidate_meta.json"
        grid.run_child_process(
            variant="baseline",
            policy_path=policy_path,
            engine_path=engine_path,
            terminal_root=terminal_root,
            data_root=data_root,
            rows_out=baseline_rows_path,
            meta_out=baseline_meta_path,
        )
        grid.run_child_process(
            variant="candidate",
            policy_path=policy_path,
            engine_path=engine_path,
            terminal_root=terminal_root,
            data_root=data_root,
            rows_out=candidate_rows_path,
            meta_out=candidate_meta_path,
        )
        baseline_rows = grid.read_rows(baseline_rows_path)
        candidate_rows = grid.read_rows(candidate_rows_path)
        baseline_meta = json.loads(baseline_meta_path.read_text(encoding="utf-8"))
        candidate_meta = json.loads(candidate_meta_path.read_text(encoding="utf-8"))

    terminal_economic_digest = grid.economic_digest(terminal_rows)
    baseline_economic_digest = grid.economic_digest(baseline_rows)
    baseline_event_digest = stable_sha(grid, sorted(str(row.get("event_id") or "") for row in baseline_rows))
    baseline_censored = sum(int(row.get("censored_open_at_window_end") or 0) for row in baseline_meta.get("lane_receipts", []))
    candidate_censored = sum(int(row.get("censored_open_at_window_end") or 0) for row in candidate_meta.get("lane_receipts", []))
    baseline_parity = {
        "trade_count_match": len(baseline_rows) == len(terminal_rows),
        "event_id_set_match": baseline_event_digest == terminal_event_digest,
        "economic_digest_match": baseline_economic_digest == terminal_economic_digest,
        "source_sha_match": baseline_meta.get("source_root_sha256") == policy["canonical_source_sha256"],
        "lane_count_match": int(baseline_meta.get("lane_count") or 0) == 15,
        "lane_error_count_zero": sum(int(row.get("error_count") or 0) for row in baseline_meta.get("lane_receipts", [])) == 0,
        "censored_open_zero": baseline_censored == 0,
    }

    windows = [str(policy["selection_window"])] + [str(item) for item in policy["confirmation_windows"]]
    window_results: dict[str, Any] = {}
    all_gate_pass = True
    for window in windows:
        baseline_window = [row for row in baseline_rows if str(row.get("window_id")) == window]
        candidate_window = [row for row in candidate_rows if str(row.get("window_id")) == window]
        baseline_metrics = base.metrics(baseline_window)
        candidate_metrics = base.metrics(candidate_window)
        selection = window == str(policy["selection_window"])
        change, blockers = grid.metric_gate(
            base,
            baseline_metrics,
            candidate_metrics,
            min_retention_pct=float(policy["min_selection_retention_pct"]) if selection else None,
            min_trade_count=None if selection else int(policy["confirmation_min_trade_count"]),
            require_positive_net=selection,
        )
        window_results[window] = {
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "delta": change,
            "blockers": blockers,
            "pass": not blockers,
        }
        all_gate_pass = all_gate_pass and not blockers

    candidate_checks = {
        "candidate_lane_count_match": int(candidate_meta.get("lane_count") or 0) == 15,
        "candidate_lane_error_count_zero": sum(int(row.get("error_count") or 0) for row in candidate_meta.get("lane_receipts", [])) == 0,
        "candidate_censored_open_zero": candidate_censored == 0,
        "blocked_entry_signal_positive": int(candidate_meta.get("blocked_entry_signal_count") or 0) > 0,
        "candidate_source_sha_match": candidate_meta.get("source_root_sha256") == policy["canonical_source_sha256"],
        "candidate_digest_self_match": candidate_meta.get("economic_digest_sha256") == grid.economic_digest(candidate_rows),
    }
    parity_pass = all(terminal_checks.values()) and all(baseline_parity.values())
    candidate_pass = parity_pass and all(candidate_checks.values()) and all_gate_pass
    if not candidate_pass:
        raise RuntimeError(
            "GRID_CUMULATIVE_INCUMBENT_NOT_ACCEPTED:"
            + json.dumps(
                {
                    "terminal_checks": terminal_checks,
                    "baseline_parity": baseline_parity,
                    "candidate_checks": candidate_checks,
                    "windows": window_results,
                },
                sort_keys=True,
            )
        )

    candidate_rows_out.parent.mkdir(parents=True, exist_ok=True)
    grid.write_rows(candidate_rows_out, candidate_rows)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_GRID_CUMULATIVE_INCUMBENT_MATERIALIZED",
        "strategy_id": strategy_id,
        "candidate_id": policy["candidate_id"],
        "terminal_trade_file_sha256": grid.file_sha(terminal_path),
        "terminal_grid_trade_count": len(terminal_rows),
        "baseline_grid_trade_count": len(baseline_rows),
        "candidate_grid_trade_count": len(candidate_rows),
        "terminal_checks": terminal_checks,
        "baseline_parity": baseline_parity,
        "candidate_checks": candidate_checks,
        "baseline_censored_open_count": baseline_censored,
        "candidate_censored_open_count": candidate_censored,
        "baseline_meta": baseline_meta,
        "candidate_meta": candidate_meta,
        "terminal_economic_digest_sha256": terminal_economic_digest,
        "baseline_economic_digest_sha256": baseline_economic_digest,
        "candidate_economic_digest_sha256": grid.economic_digest(candidate_rows),
        "all_windows": {
            "baseline": base.metrics(baseline_rows),
            "candidate": base.metrics(candidate_rows),
            "delta": base.delta(base.metrics(baseline_rows), base.metrics(candidate_rows)),
        },
        "windows": window_results,
        "candidate_pass": True,
        "private_candidate_rows_sha256": grid.file_sha(candidate_rows_out),
        "private_candidate_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(grid, receipt)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def self_test() -> int:
    sample = {"a": 1, "b": [2, 3]}
    import hashlib
    encoded = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest()
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--grid-tool", type=Path)
    parser.add_argument("--base-tool", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--candidate-rows-out", type=Path)
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.policy,
        args.grid_tool,
        args.base_tool,
        args.engine,
        args.terminal_root,
        args.data_root,
        args.candidate_rows_out,
        args.receipt_out,
    )
    if any(value is None for value in required):
        parser.error("all runtime arguments required")
    receipt = build(
        policy_path=args.policy.resolve(),
        grid_tool_path=args.grid_tool.resolve(),
        base_tool_path=args.base_tool.resolve(),
        engine_path=args.engine.resolve(),
        terminal_root=args.terminal_root.resolve(),
        data_root=args.data_root.resolve(),
        candidate_rows_out=args.candidate_rows_out.resolve(),
        receipt_out=args.receipt_out.resolve(),
    )
    print(json.dumps({"state": receipt["state"], "candidate_grid_trade_count": receipt["candidate_grid_trade_count"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
