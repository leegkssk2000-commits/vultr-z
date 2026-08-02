from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_GRID_BLOCK_TREND_SHORT_EXACT_REPLAY_V1"
SCHEMA = "zel.grid.block_trend_short.exact_replay.receipt.v1"

ECONOMIC_FIELDS = (
    "event_id",
    "position_id",
    "strategy_id",
    "owner_sha256",
    "symbol",
    "interval",
    "data_interval",
    "window_id",
    "side",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "qty",
    "original_qty",
    "initial_risk_usdt",
    "gross_pnl_usdt",
    "realized_R",
    "realized_R_including_funding_estimate",
    "fee",
    "slippage",
    "funding_pnl_estimate_usdt",
    "funding_event_count",
    "exit_reason",
    "MFE_R",
    "MAE_R",
    "time_exposure_min",
    "add_count",
    "partial_count",
    "data_source_sha256",
)


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalized_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, 12)
    return value


def economic_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: normalized_number(row.get(field))
        for field in ECONOMIC_FIELDS
        if field in row
    }


def economic_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (economic_row(row) for row in rows),
        key=lambda row: (
            str(row.get("event_id") or ""),
            str(row.get("entry_ts") or ""),
            str(row.get("exit_ts") or ""),
        ),
    )
    return stable_sha(ordered)


def write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    dict(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RuntimeError("INTERNAL_ROW_NOT_OBJECT")
                rows.append(value)
    return rows


def read_terminal_grid_rows(path: Path, strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"TERMINAL_ROW_NOT_OBJECT:{line_number}")
            current_strategy = str(
                row.get("strategy_id")
                or row.get("strategy")
                or row.get("strategy_name")
                or ""
            )
            if current_strategy == strategy_id:
                rows.append(row)
    return rows


def source_report_root(terminal_root: Path) -> Path:
    report = json.loads((terminal_root / "report.json").read_text(encoding="utf-8"))
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    root = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(root, str) or not root:
        raise RuntimeError("TERMINAL_SOURCE_ROOT_MISSING")
    return Path(root)


def copy_exact_source(source_root: Path, destination: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {".git", ".venv", "venv", "__pycache__", "node_modules"}
        }

    shutil.copytree(source_root, destination, symlinks=True, ignore=ignore)


class GatedOwner:
    def __init__(
        self,
        *,
        base_owner: Any,
        producer: Any,
        compute_context: Any,
        derive_regime: Any,
        token: str,
        blocked_regime: str,
    ) -> None:
        self.base_owner = base_owner
        self.producer = producer
        self.compute_context = compute_context
        self.derive_regime = derive_regime
        self.token = token
        self.blocked_regime = blocked_regime
        self.owner_sha256 = stable_sha(
            {
                "base_owner_sha256": str(getattr(base_owner, "owner_sha256", "")),
                "gate": "BLOCK_ENTRY_REGIME",
                "blocked_regime": blocked_regime,
                "version": VERSION,
            }
        )
        self.valid_entry_signal_count = 0
        self.blocked_entry_signal_count = 0
        self.signal_regime_counts: Counter[str] = Counter()

    def strategy(
        self,
        current: Any,
        state: Any = None,
        risk_action: str = "hold",
    ) -> dict[str, Any]:
        result = self.base_owner.strategy(
            current,
            state=state,
            risk_action=risk_action,
        )
        if not isinstance(result, dict):
            return result
        if state is not None:
            return result

        current_price = float(current["close"].iloc[-1])
        if self.producer.valid_entry(result, current_price) is None:
            return result

        self.valid_entry_signal_count += 1
        context = self.compute_context(self.token, current, None, None, None)
        regime = str(self.derive_regime(context) or "missing")
        self.signal_regime_counts[regime] += 1
        if regime != self.blocked_regime:
            return result

        self.blocked_entry_signal_count += 1
        return {
            "action": "hold",
            "reason": f"research_gate_block_entry_regime_{self.blocked_regime}",
            "research_only": True,
        }


def run_variant(
    *,
    variant: str,
    policy: Mapping[str, Any],
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
    rows_out: Path,
    meta_out: Path,
) -> int:
    strategy_id = str(policy["strategy_id"])
    source_root = source_report_root(terminal_root)
    source_relative = Path(str(policy["canonical_source_relative_path"]))
    source_path = source_root / source_relative
    source_sha = file_sha(source_path)
    if source_sha != policy["canonical_source_sha256"]:
        raise RuntimeError(f"CANONICAL_SOURCE_SHA_MISMATCH:{source_sha}")

    context_path = Path(str(policy["context_source_path"]))
    derive_path = Path(str(policy["derive_source_path"]))
    if file_sha(context_path) != policy["context_source_sha256"]:
        raise RuntimeError("CONTEXT_SOURCE_SHA_MISMATCH")
    if file_sha(derive_path) != policy["derive_source_sha256"]:
        raise RuntimeError("DERIVE_SOURCE_SHA_MISMATCH")

    with tempfile.TemporaryDirectory(prefix=f"zel-grid-exact-{variant}-") as temp_dir:
        copied_root = Path(temp_dir) / "source"
        copy_exact_source(source_root, copied_root)
        copied_source_sha = file_sha(copied_root / source_relative)
        if copied_source_sha != source_sha:
            raise RuntimeError("COPIED_SOURCE_SHA_MISMATCH")

        engine = load_module(
            engine_path,
            f"zel_grid_exact_engine_{variant}_{os.getpid()}",
        )
        engine.init_worker(str(copied_root), str(data_root), "1m")
        registry = engine._WORKER_REGISTRY
        manifest = engine._WORKER_MANIFEST
        funding = engine._WORKER_FUNDING
        producer = engine._WORKER_PRODUCER
        if not isinstance(registry, Mapping) or strategy_id not in registry:
            raise RuntimeError("GRID_OWNER_MISSING")
        if not isinstance(manifest, Mapping) or not isinstance(funding, Mapping):
            raise RuntimeError("WORKER_STATE_INCOMPLETE")

        base_owner = registry[strategy_id]
        base_owner_sha = str(getattr(base_owner, "owner_sha256", ""))
        compute_context = derive_regime = None
        if variant == "candidate":
            context_module = load_module(
                context_path,
                f"zel_grid_exact_context_{os.getpid()}",
            )
            derive_module = load_module(
                derive_path,
                f"zel_grid_exact_derive_{os.getpid()}",
            )
            compute_context = getattr(context_module, "compute_context", None)
            derive_regime = getattr(derive_module, "derive_regime", None)
            if not callable(compute_context) or not callable(derive_regime):
                raise RuntimeError("CONTEXT_CALLABLE_MISSING")

        files = [
            row
            for row in manifest.get("files", [])
            if isinstance(row, Mapping)
            and row.get("kind") == "market"
            and row.get("interval") == "1m"
        ]
        closed_rows: list[dict[str, Any]] = []
        lane_receipts: list[dict[str, Any]] = []
        valid_entry_signals = blocked_entry_signals = 0
        signal_regime_counts: Counter[str] = Counter()

        for file_row in sorted(
            files,
            key=lambda row: (str(row["window_id"]), str(row["symbol"])),
        ):
            frame_path = data_root / str(file_row["path"])
            frame = engine.frame_from_csv(frame_path)
            owner: Any = base_owner
            wrapper: GatedOwner | None = None
            if variant == "candidate":
                wrapper = GatedOwner(
                    base_owner=base_owner,
                    producer=producer,
                    compute_context=compute_context,
                    derive_regime=derive_regime,
                    token=f"{file_row['window_id']}:{file_row['symbol']}",
                    blocked_regime=str(policy["blocked_entry_regime"]),
                )
                owner = wrapper

            lane = engine.replay_lane(
                strategy_id,
                owner,
                file_row,
                frame,
                funding.get(str(file_row["symbol"]), []),
            )
            closed_rows.extend(list(lane.get("closed_rows") or []))
            lane_receipts.append(
                {
                    "window_id": file_row["window_id"],
                    "symbol": file_row["symbol"],
                    "bar_count": lane.get("bar_count"),
                    "open_count": lane.get("open_count"),
                    "close_count": lane.get("close_count"),
                    "censored_open_at_window_end": lane.get(
                        "censored_open_at_window_end"
                    ),
                    "error_count": lane.get("error_count"),
                }
            )
            if wrapper is not None:
                valid_entry_signals += wrapper.valid_entry_signal_count
                blocked_entry_signals += wrapper.blocked_entry_signal_count
                signal_regime_counts.update(wrapper.signal_regime_counts)

        write_rows(rows_out, closed_rows)
        meta = {
            "variant": variant,
            "source_root_sha256": source_sha,
            "copied_source_sha256": copied_source_sha,
            "base_owner_sha256": base_owner_sha,
            "variant_owner_sha256": (
                stable_sha(
                    {
                        "base_owner_sha256": base_owner_sha,
                        "gate": "BLOCK_ENTRY_REGIME",
                        "blocked_regime": policy["blocked_entry_regime"],
                        "version": VERSION,
                    }
                )
                if variant == "candidate"
                else base_owner_sha
            ),
            "lane_count": len(lane_receipts),
            "lane_receipts": lane_receipts,
            "trade_count": len(closed_rows),
            "economic_digest_sha256": economic_digest(closed_rows),
            "valid_entry_signal_count": valid_entry_signals,
            "blocked_entry_signal_count": blocked_entry_signals,
            "signal_regime_counts": dict(sorted(signal_regime_counts.items())),
            "source_copy_deleted_after_process": True,
            "canonical_mutated": False,
            "runtime_mutated": False,
            "formal_ledger_mutated": False,
        }
        meta_out.write_text(
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


def metric_gate(
    base_tool: Any,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    min_retention_pct: float | None = None,
    min_trade_count: int | None = None,
    require_positive_net: bool,
) -> tuple[dict[str, Any], list[str]]:
    change = base_tool.delta(baseline, candidate)
    blockers: list[str] = []
    if min_retention_pct is not None and change["retention_pct"] < min_retention_pct:
        blockers.append("RETENTION_BELOW_MIN")
    if min_trade_count is not None and int(candidate["trade_count"]) < min_trade_count:
        blockers.append("TRADE_COUNT_BELOW_MIN")
    if require_positive_net:
        if change["delta_net_R"] <= 0:
            blockers.append("NET_R_NOT_IMPROVED")
    elif change["delta_net_R"] < 0:
        blockers.append("NET_R_WORSE")
    if change["delta_max_drawdown_R"] < 0:
        blockers.append("MAX_DD_WORSE")
    if change["delta_profit_factor"] is None or change["delta_profit_factor"] < 0:
        blockers.append("PROFIT_FACTOR_WORSE_OR_UNDEFINED")
    return change, blockers


def run_child_process(
    *,
    variant: str,
    policy_path: Path,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
    rows_out: Path,
    meta_out: Path,
) -> None:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--internal-variant",
        variant,
        "--policy",
        str(policy_path),
        "--engine",
        str(engine_path),
        "--terminal-root",
        str(terminal_root),
        "--data-root",
        str(data_root),
        "--internal-rows-out",
        str(rows_out),
        "--internal-meta-out",
        str(meta_out),
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=3600,
    )
    if completed.returncode != 0:
        tail = "\n".join(completed.stdout.splitlines()[-30:])
        raise RuntimeError(f"VARIANT_FAILED:{variant}:{tail}")


def evaluate(
    policy: Mapping[str, Any],
    *,
    policy_path: Path,
    base_tool_path: Path,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    base_tool = load_module(
        base_tool_path,
        f"zel_grid_exact_base_{os.getpid()}",
    )
    strategy_id = str(policy["strategy_id"])
    terminal_path = terminal_root / "trades.jsonl.gz"
    terminal_rows = read_terminal_grid_rows(terminal_path, strategy_id)
    terminal_event_digest = stable_sha(
        sorted(str(row.get("event_id") or row.get("trade_id") or "") for row in terminal_rows)
    )
    terminal_checks = {
        "terminal_file_sha_match": file_sha(terminal_path)
        == policy["expected_terminal_trades_sha256"],
        "terminal_trade_count_match": len(terminal_rows)
        == int(policy["expected_terminal_trade_count"]),
        "terminal_event_id_set_match": terminal_event_digest
        == policy["expected_terminal_event_id_set_sha256"],
    }

    with tempfile.TemporaryDirectory(prefix="zel-grid-exact-orchestrator-") as temp_dir:
        temp = Path(temp_dir)
        baseline_rows_path = temp / "baseline.jsonl.gz"
        baseline_meta_path = temp / "baseline_meta.json"
        candidate_rows_path = temp / "candidate.jsonl.gz"
        candidate_meta_path = temp / "candidate_meta.json"

        run_child_process(
            variant="baseline",
            policy_path=policy_path,
            engine_path=engine_path,
            terminal_root=terminal_root,
            data_root=data_root,
            rows_out=baseline_rows_path,
            meta_out=baseline_meta_path,
        )
        run_child_process(
            variant="candidate",
            policy_path=policy_path,
            engine_path=engine_path,
            terminal_root=terminal_root,
            data_root=data_root,
            rows_out=candidate_rows_path,
            meta_out=candidate_meta_path,
        )

        baseline_rows = read_rows(baseline_rows_path)
        candidate_rows = read_rows(candidate_rows_path)
        baseline_meta = json.loads(baseline_meta_path.read_text(encoding="utf-8"))
        candidate_meta = json.loads(candidate_meta_path.read_text(encoding="utf-8"))

    terminal_economic_digest = economic_digest(terminal_rows)
    baseline_economic_digest = economic_digest(baseline_rows)
    baseline_event_digest = stable_sha(
        sorted(str(row.get("event_id") or "") for row in baseline_rows)
    )
    baseline_parity = {
        "trade_count_match": len(baseline_rows) == len(terminal_rows),
        "event_id_set_match": baseline_event_digest == terminal_event_digest,
        "economic_digest_match": baseline_economic_digest == terminal_economic_digest,
        "source_sha_match": baseline_meta.get("source_root_sha256")
        == policy["canonical_source_sha256"],
        "lane_count_match": int(baseline_meta.get("lane_count") or 0) == 15,
        "lane_error_count_zero": sum(
            int(row.get("error_count") or 0)
            for row in baseline_meta.get("lane_receipts", [])
        )
        == 0,
    }

    windows = [str(policy["selection_window"])] + [
        str(window) for window in policy["confirmation_windows"]
    ]
    window_results: dict[str, Any] = {}
    all_gate_pass = True
    for window in windows:
        baseline_window_rows = [
            row for row in baseline_rows if str(row.get("window_id")) == window
        ]
        candidate_window_rows = [
            row for row in candidate_rows if str(row.get("window_id")) == window
        ]
        baseline_metrics = base_tool.metrics(baseline_window_rows)
        candidate_metrics = base_tool.metrics(candidate_window_rows)
        is_selection = window == str(policy["selection_window"])
        change, blockers = metric_gate(
            base_tool,
            baseline_metrics,
            candidate_metrics,
            min_retention_pct=(
                float(policy["min_selection_retention_pct"])
                if is_selection
                else None
            ),
            min_trade_count=(
                None if is_selection else int(policy["confirmation_min_trade_count"])
            ),
            require_positive_net=is_selection,
        )
        window_results[window] = {
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "delta": change,
            "blockers": blockers,
            "pass": not blockers,
        }
        all_gate_pass = all_gate_pass and not blockers

    baseline_all = base_tool.metrics(baseline_rows)
    candidate_all = base_tool.metrics(candidate_rows)
    candidate_checks = {
        "candidate_lane_count_match": int(candidate_meta.get("lane_count") or 0) == 15,
        "candidate_lane_error_count_zero": sum(
            int(row.get("error_count") or 0)
            for row in candidate_meta.get("lane_receipts", [])
        )
        == 0,
        "blocked_entry_signal_positive": int(
            candidate_meta.get("blocked_entry_signal_count") or 0
        )
        > 0,
        "candidate_source_sha_match": candidate_meta.get("source_root_sha256")
        == policy["canonical_source_sha256"],
    }

    parity_pass = all(terminal_checks.values()) and all(baseline_parity.values())
    candidate_pass = parity_pass and all(candidate_checks.values()) and all_gate_pass
    if candidate_pass:
        state = "PASS_GRID_BLOCK_TREND_SHORT_EXACT_REPLAY_READY"
        next_step = "ROUTE_TO_NEW_SEALED_HOLDBACK_WITHOUT_RUNTIME_PROMOTION"
    elif not parity_pass:
        state = "HOLD_GRID_BLOCK_TREND_SHORT_BASELINE_PARITY_FAILED"
        next_step = "RESOLVE_SINGLE_BASELINE_PARITY_CAUSE"
    else:
        state = "HOLD_GRID_BLOCK_TREND_SHORT_EXACT_REPLAY_REJECTED"
        next_step = "RETAIN_INCUMBENT_AND_ROUTE_NEXT_SINGLE_AXIS_HYPOTHESIS"

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": state,
        "strategy_id": strategy_id,
        "candidate_id": policy["candidate_id"],
        "blocked_entry_regime": policy["blocked_entry_regime"],
        "parent_candidate_receipt_sha256": policy[
            "expected_parent_candidate_receipt_sha256"
        ],
        "terminal_checks": terminal_checks,
        "baseline_parity": baseline_parity,
        "candidate_checks": candidate_checks,
        "baseline_meta": baseline_meta,
        "candidate_meta": candidate_meta,
        "terminal_economic_digest_sha256": terminal_economic_digest,
        "baseline_economic_digest_sha256": baseline_economic_digest,
        "candidate_economic_digest_sha256": economic_digest(candidate_rows),
        "all_windows": {
            "baseline": baseline_all,
            "candidate": candidate_all,
            "delta": base_tool.delta(baseline_all, candidate_all),
        },
        "windows": window_results,
        "candidate_pass": candidate_pass,
        "selected_research_fork": policy["candidate_id"] if candidate_pass else None,
        "temporary_raw_rows_deleted": True,
        "source_copy_deleted": True,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": next_step,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    rows = [
        {
            "event_id": "a",
            "strategy_id": "grid_rebalance",
            "realized_R": 1.0,
            "entry_price": 10.0,
        },
        {
            "event_id": "b",
            "strategy_id": "grid_rebalance",
            "realized_R": -0.5,
            "entry_price": 11.0,
        },
    ]
    assert economic_digest(rows) == economic_digest(list(reversed(rows)))
    changed = [dict(rows[0]), dict(rows[1], realized_R=-0.6)]
    assert economic_digest(rows) != economic_digest(changed)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument(
        "--base-tool",
        type=Path,
        default=Path(__file__).with_name("zel_grid_entry_regime_fork_v1.py"),
    )
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(
            "/opt/zel/research-runtime/data-b-v2/"
            "zel_historical_oos_exact25_replay_v1.py"
        ),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/opt/zel/historical-oos-v1"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--internal-variant",
        choices=("baseline", "candidate"),
    )
    parser.add_argument("--internal-rows-out", type=Path)
    parser.add_argument("--internal-meta-out", type=Path)
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.policy:
        parser.error("--policy required")
    policy = json.loads(args.policy.read_text(encoding="utf-8"))

    if args.internal_variant:
        if not args.internal_rows_out or not args.internal_meta_out:
            parser.error("internal output paths required")
        return run_variant(
            variant=args.internal_variant,
            policy=policy,
            engine_path=args.engine,
            terminal_root=args.terminal_root,
            data_root=args.data_root,
            rows_out=args.internal_rows_out,
            meta_out=args.internal_meta_out,
        )

    receipt = evaluate(
        policy,
        policy_path=args.policy,
        base_tool_path=args.base_tool,
        engine_path=args.engine,
        terminal_root=args.terminal_root,
        data_root=args.data_root,
    )
    encoded = (
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
