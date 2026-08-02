from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_BLOCK_TREND_SHORT_V1"
SCHEMA = "zel.grid.block_trend_short.receipt.v1"


def reconstruct(
    base: Any,
    policy: Mapping[str, Any],
    *,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    strategy_id = str(policy["strategy_id"])
    trades_path = terminal_root / "trades.jsonl.gz"
    context_path = Path(str(policy["context_source_path"]))
    derive_path = Path(str(policy["derive_source_path"]))

    checks = {
        "terminal_trades_sha_match": base.file_sha(trades_path)
        == policy["expected_terminal_trades_sha256"],
        "context_source_sha_match": base.file_sha(context_path)
        == policy["context_source_sha256"],
        "derive_source_sha_match": base.file_sha(derive_path)
        == policy["derive_source_sha256"],
    }
    if not all(checks.values()):
        raise RuntimeError(f"SOURCE_IDENTITY_MISMATCH:{checks}")

    rows = base.read_rows(trades_path, strategy_id)
    event_digest = base.stable_sha(sorted(base.event_id(row) for row in rows))
    checks.update(
        {
            "trade_count_match": len(rows) == int(policy["expected_trade_count"]),
            "event_id_set_match": event_digest
            == policy["expected_event_id_set_sha256"],
        }
    )
    if not all(checks.values()):
        raise RuntimeError(f"LEDGER_IDENTITY_MISMATCH:{checks}")

    engine = base.load_module(engine_path, "zel_grid_block_trend_short_engine")
    context_module = base.load_module(
        context_path, "zel_grid_block_trend_short_context"
    )
    derive_module = base.load_module(
        derive_path, "zel_grid_block_trend_short_derive"
    )
    compute_context = getattr(context_module, "compute_context", None)
    derive_regime = getattr(derive_module, "derive_regime", None)
    if not callable(compute_context) or not callable(derive_regime):
        raise RuntimeError("CONTEXT_CALLABLE_MISSING")

    report = json.loads((terminal_root / "report.json").read_text())
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")

    engine.init_worker(str(Path(source_root_raw)), str(data_root), "1m")
    manifest = engine._WORKER_MANIFEST
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in files:
        if isinstance(row, Mapping):
            file_map[
                (
                    base.text(row, ("window_id", "window"), "unknown"),
                    base.text(row, ("symbol",)).upper(),
                )
            ] = row

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(base.window_id(row), base.symbol(row))].append(row)

    labels: dict[str, str] = {}
    facts: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    duplicate_timestamp_count = 0
    minimum_prefix_bars: int | None = None

    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            unmatched.extend(
                {
                    "event_sha256": base.stable_sha(base.event_id(row)),
                    "reason": "LANE_FILE_MISSING",
                }
                for row in lane_rows
            )
            continue

        frame = engine.frame_from_csv(base.resolve_path(data_root, file_row))
        index_by_epoch: dict[int, int] = {}
        duplicate_epochs: set[int] = set()
        for index, value in enumerate(frame["timestamp"].tolist()):
            current_epoch = base.epoch_ns(engine.pd, value)
            if current_epoch is None:
                continue
            if current_epoch in index_by_epoch:
                duplicate_epochs.add(current_epoch)
            index_by_epoch[current_epoch] = index
        duplicate_timestamp_count += len(duplicate_epochs)

        for row in lane_rows:
            current_event_id = base.event_id(row)
            entry_epoch = base.epoch_ns(
                engine.pd,
                row.get("entry_ts") or row.get("entry_time"),
            )
            index = index_by_epoch.get(entry_epoch) if entry_epoch is not None else None
            if index is None:
                unmatched.append(
                    {
                        "event_sha256": base.stable_sha(current_event_id),
                        "reason": "ENTRY_TIMESTAMP_NOT_FOUND",
                    }
                )
                continue

            prefix = frame.iloc[
                max(0, index - int(engine.FRAME_LIMIT) + 1) : index + 1
            ].copy()
            minimum_prefix_bars = (
                len(prefix)
                if minimum_prefix_bars is None
                else min(minimum_prefix_bars, len(prefix))
            )
            if base.epoch_ns(engine.pd, prefix["timestamp"].iloc[-1]) != entry_epoch:
                unmatched.append(
                    {
                        "event_sha256": base.stable_sha(current_event_id),
                        "reason": "PREFIX_LAST_BAR_NOT_ENTRY",
                    }
                )
                continue
            if len(prefix) < 14:
                unmatched.append(
                    {
                        "event_sha256": base.stable_sha(current_event_id),
                        "reason": "PREFIX_WARMUP_LT_14",
                    }
                )
                continue

            try:
                context = compute_context(
                    f"{lane[0]}:{lane[1]}", prefix, None, None, None
                )
                regime = str(derive_regime(context) or "missing")
            except Exception as exc:
                unmatched.append(
                    {
                        "event_sha256": base.stable_sha(current_event_id),
                        "reason": f"CONTEXT_ERROR:{type(exc).__name__}",
                    }
                )
                continue
            if regime not in {"range", "trend_long", "trend_short", "transition"}:
                unmatched.append(
                    {
                        "event_sha256": base.stable_sha(current_event_id),
                        "reason": f"REGIME_INVALID:{regime}",
                    }
                )
                continue

            labels[current_event_id] = regime
            facts[current_event_id] = {
                "entry_epoch_ns": entry_epoch,
                "prefix_bars": len(prefix),
                "regime": regime,
                "symbol": lane[1],
                "trend_direction": base.text(
                    context, ("trend_direction",), "missing"
                ),
                "trend_strength": base.number(context, ("trend_strength",)),
                "window_id": lane[0],
            }

    facts_digest = base.stable_sha(facts)
    checks.update(
        {
            "complete_reconstruction": len(labels) == len(rows) and not unmatched,
            "duplicate_timestamp_count_zero": duplicate_timestamp_count == 0,
            "facts_digest_match": facts_digest
            == policy["expected_facts_digest_sha256"],
        }
    )
    diagnostics = {
        "checks": checks,
        "duplicate_frame_timestamp_count": duplicate_timestamp_count,
        "entry_regime_counts": dict(Counter(labels.values())),
        "event_id_set_sha256": event_digest,
        "facts_digest_sha256": facts_digest,
        "minimum_prefix_bars": minimum_prefix_bars,
        "reconstructed_count": len(labels),
        "unmatched_count": len(unmatched),
        "unmatched_reason_counts": dict(Counter(row["reason"] for row in unmatched)),
    }
    return rows, labels, diagnostics


def gate_delta(
    base: Any,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    min_retention_pct: float | None = None,
    min_trade_count: int | None = None,
    require_positive_net: bool,
) -> tuple[dict[str, Any], list[str]]:
    change = base.delta(baseline, candidate)
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


def evaluate(
    policy: Mapping[str, Any],
    *,
    base_tool: Path,
    engine_path: Path,
    terminal_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    base = __import__("importlib.util").util.spec_from_file_location(
        "zel_grid_entry_regime_parent", base_tool
    )
    if base is None or base.loader is None:
        raise RuntimeError("BASE_TOOL_IMPORT_SPEC_FAILED")
    parent = __import__("importlib.util").util.module_from_spec(base)
    base.loader.exec_module(parent)

    rows, labels, diagnostics = reconstruct(
        parent,
        policy,
        engine_path=engine_path,
        terminal_root=terminal_root,
        data_root=data_root,
    )
    blocked_regime = str(policy["blocked_entry_regime"])
    candidate_rows = [
        row for row in rows if labels.get(parent.event_id(row)) != blocked_regime
    ]

    baseline_all = parent.metrics(rows)
    candidate_all = parent.metrics(candidate_rows)
    window_results: dict[str, Any] = {}

    selection_window = str(policy["selection_window"])
    selection_base_rows = [row for row in rows if parent.window_id(row) == selection_window]
    selection_candidate_rows = [
        row
        for row in selection_base_rows
        if labels.get(parent.event_id(row)) != blocked_regime
    ]
    selection_base = parent.metrics(selection_base_rows)
    selection_candidate = parent.metrics(selection_candidate_rows)
    selection_delta, selection_blockers = gate_delta(
        parent,
        selection_base,
        selection_candidate,
        min_retention_pct=float(policy["min_selection_retention_pct"]),
        require_positive_net=True,
    )
    window_results[selection_window] = {
        "baseline": selection_base,
        "candidate": selection_candidate,
        "delta": selection_delta,
        "blockers": selection_blockers,
        "pass": not selection_blockers,
    }

    confirmation_pass = True
    for window in policy["confirmation_windows"]:
        window = str(window)
        base_rows = [row for row in rows if parent.window_id(row) == window]
        kept_rows = [
            row for row in base_rows if labels.get(parent.event_id(row)) != blocked_regime
        ]
        base_metrics = parent.metrics(base_rows)
        candidate_metrics = parent.metrics(kept_rows)
        change, blockers = gate_delta(
            parent,
            base_metrics,
            candidate_metrics,
            min_trade_count=int(policy["confirmation_min_trade_count"]),
            require_positive_net=False,
        )
        window_results[window] = {
            "baseline": base_metrics,
            "candidate": candidate_metrics,
            "delta": change,
            "blockers": blockers,
            "pass": not blockers,
        }
        confirmation_pass = confirmation_pass and not blockers

    all_checks_pass = all(diagnostics["checks"].values())
    candidate_pass = (
        all_checks_pass
        and not selection_blockers
        and confirmation_pass
    )
    state = (
        "PASS_GRID_BLOCK_TREND_SHORT_CANDIDATE_READY"
        if candidate_pass
        else "HOLD_GRID_BLOCK_TREND_SHORT_REJECTED"
    )
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": state,
        "candidate_id": policy["candidate_id"],
        "blocked_entry_regime": blocked_regime,
        "parent_receipt_sha256": policy["expected_parent_receipt_sha256"],
        "diagnostics": diagnostics,
        "all_windows": {
            "baseline": baseline_all,
            "candidate": candidate_all,
            "delta": parent.delta(baseline_all, candidate_all),
        },
        "windows": window_results,
        "candidate_pass": candidate_pass,
        "selected_research_fork": policy["candidate_id"] if candidate_pass else None,
        "incumbent_mutated": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "context_facts_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "STAGE_BLOCK_TREND_SHORT_IN_TMP_EXACT_SOURCE_REPLAY"
            if candidate_pass
            else "RETAIN_INCUMBENT_AND_ROUTE_NEXT_SINGLE_AXIS_HYPOTHESIS"
        ),
    }
    receipt["receipt_sha256"] = parent.stable_sha(receipt)
    return receipt


def self_test() -> int:
    class Base:
        @staticmethod
        def delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "delta_net_R": candidate["net_R"] - base["net_R"],
                "delta_max_drawdown_R": candidate["max_drawdown_R"] - base["max_drawdown_R"],
                "delta_profit_factor": candidate["profit_factor"] - base["profit_factor"],
                "retention_pct": candidate["trade_count"] / base["trade_count"] * 100,
            }

    base = {"trade_count": 100, "net_R": -10.0, "profit_factor": 0.5, "max_drawdown_R": -12.0}
    candidate = {"trade_count": 61, "net_R": -2.0, "profit_factor": 0.7, "max_drawdown_R": -5.0}
    _, blockers = gate_delta(Base, base, candidate, min_retention_pct=60.0, require_positive_net=True)
    assert not blockers, blockers
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--base-tool", type=Path, default=Path(__file__).with_name("zel_grid_entry_regime_fork_v1.py"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy:
        parser.error("--policy required")
    policy = json.loads(args.policy.read_text())
    receipt = evaluate(
        policy,
        base_tool=args.base_tool,
        engine_path=args.engine,
        terminal_root=args.terminal_root,
        data_root=args.data_root,
    )
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
