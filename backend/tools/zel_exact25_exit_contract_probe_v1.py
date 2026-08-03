from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_EXIT_CONTRACT_PROBE_V1"
SCHEMA = "zel.exact25.exit_contract_probe.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def exit_reason(row: Mapping[str, Any]) -> str:
    for key in (
        "exit_reason", "reason", "close_reason", "exit_type", "close_type",
        "trigger_reason", "event_reason",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return "unknown"


def exit_source(reason: str) -> str:
    text = reason.lower()
    if text.startswith("strategy_"):
        return "STRATEGY_ACTION_EXIT"
    if any(token in text for token in ("stop", "sl", "liquid", "loss_cap", "hard_loss")):
        return "HARD_RISK_EXIT"
    if any(token in text for token in ("take_profit", "takeprofit", "tp", "target")):
        return "TAKE_PROFIT_EXIT"
    if any(token in text for token in ("trail", "mfe", "runner")):
        return "TRAILING_OR_RUNNER_EXIT"
    if any(token in text for token in ("time", "timeout", "max_hold", "expiry")):
        return "TIME_EXIT"
    if any(token in text for token in ("break_even", "breakeven", "scratch", "be_")):
        return "BREAKEVEN_OR_SCRATCH_EXIT"
    return "OTHER_PRICE_EXIT"


def time_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 5:
        return "0-5m"
    if value <= 15:
        return "5-15m"
    if value <= 30:
        return "15-30m"
    if value <= 60:
        return "30-60m"
    if value <= 120:
        return "60-120m"
    return ">120m"


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [
        float(value)
        for row in rows
        if (value := finite(row.get("realized_R_including_funding_estimate"))) is not None
    ]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    return {
        "sample_count": len(values),
        "net_R": sum(values),
        "profit_factor": gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0),
        "expectancy_R": sum(values) / len(values) if values else 0.0,
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss_abs,
        "payoff_ratio": average_win / average_loss_abs if average_loss_abs else (999.0 if average_win else 0.0),
    }


def group_metrics(rows: Sequence[Mapping[str, Any]], key_fn: Any) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    return {key: metrics(value) for key, value in sorted(groups.items())}


def run(
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_path: Path,
    strategy_ids: Sequence[str],
) -> dict[str, Any]:
    engine = load_module(engine_path, f"zel_exit_contract_engine_{os.getpid()}")
    engine.init_worker(str(source_root), str(data_root), "1m")
    registry = engine._WORKER_REGISTRY
    manifest = engine._WORKER_MANIFEST
    funding = engine._WORKER_FUNDING
    if not isinstance(registry, Mapping) or not isinstance(manifest, Mapping):
        raise RuntimeError("ENGINE_WORKER_STATE_MISSING")
    terminal = read_json(terminal_path)
    scorecards = {
        str(row.get("strategy_id")): row
        for row in terminal.get("scorecards", [])
        if isinstance(row, Mapping) and row.get("strategy_id")
    }
    selected = list(strategy_ids) if strategy_ids else [
        strategy_id
        for strategy_id, row in scorecards.items()
        if int(row.get("close_count") or 0) > 0
    ]
    missing = sorted(set(selected) - set(registry))
    if missing:
        raise RuntimeError(f"STRATEGIES_NOT_IN_REGISTRY:{missing}")

    strategy_receipts: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    market_files = [
        row
        for row in manifest.get("files", [])
        if isinstance(row, Mapping)
        and row.get("kind") == "market"
        and row.get("interval") == "1m"
    ]
    for strategy_id in selected:
        owner = registry[strategy_id]
        lanes: list[dict[str, Any]] = []
        for file_row in sorted(
            market_files,
            key=lambda row: (str(row["window_id"]), str(row["symbol"])),
        ):
            frame = engine.frame_from_csv(data_root / str(file_row["path"]))
            lanes.append(
                engine.replay_lane(
                    strategy_id,
                    owner,
                    file_row,
                    frame,
                    funding.get(str(file_row["symbol"]), []),
                )
            )
        result = {
            "strategy_id": strategy_id,
            "owner_sha256": str(getattr(owner, "owner_sha256", "")),
            "lanes": lanes,
        }
        card, rows = engine.aggregate_strategy(result)
        terminal_card = scorecards.get(strategy_id) or {}
        current_metrics = card["closed_metrics_including_funding_estimate"]
        terminal_metrics = terminal_card.get("closed_metrics_including_funding_estimate") or {}
        parity = {
            "close_count": len(rows) == int(terminal_card.get("close_count") or 0),
            "net_R": abs(float(current_metrics.get("net_R") or 0.0) - float(terminal_metrics.get("net_R") or 0.0)) <= 1e-9,
            "profit_factor": abs(float(current_metrics.get("profit_factor") or 0.0) - float(terminal_metrics.get("profit_factor") or 0.0)) <= 1e-9,
            "errors_zero": int(card.get("error_count") or 0) == 0,
            "censored_zero": int(card.get("censored_open_at_window_end") or 0) == 0,
        }
        enriched = []
        for row in rows:
            reason = exit_reason(row)
            enriched.append(
                {
                    **row,
                    "_exit_reason": reason,
                    "_exit_source": exit_source(reason),
                    "_time_bucket": time_bucket(finite(row.get("time_exposure_min"))),
                }
            )
        all_rows.extend(enriched)
        strategy_receipts.append(
            {
                "strategy_id": strategy_id,
                "owner_sha256": str(getattr(owner, "owner_sha256", "")),
                "baseline_parity": parity,
                "metrics": metrics(enriched),
                "strategy_exit_count": int(card.get("strategy_exit_count") or 0),
                "reason_counts": dict(Counter(row["_exit_reason"] for row in enriched)),
                "source_counts": dict(Counter(row["_exit_source"] for row in enriched)),
                "by_exit_source": group_metrics(enriched, lambda row: row["_exit_source"]),
                "by_time_bucket": group_metrics(enriched, lambda row: row["_time_bucket"]),
                "early_0_5m_by_exit_source": group_metrics(
                    [row for row in enriched if row["_time_bucket"] == "0-5m"],
                    lambda row: row["_exit_source"],
                ),
                "row_key_union": sorted({key for row in rows for key in row}),
            }
        )

    early_rows = [row for row in all_rows if row["_time_bucket"] == "0-5m"]
    source_loss_rank = sorted(
        (
            {
                "exit_source": source,
                **summary,
            }
            for source, summary in group_metrics(
                early_rows, lambda row: row["_exit_source"]
            ).items()
        ),
        key=lambda row: float(row["net_R"]),
    )
    result = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EXIT_CONTRACT_PROBE",
        "strategy_count": len(strategy_receipts),
        "trade_count": len(all_rows),
        "strategies": strategy_receipts,
        "portfolio": {
            "metrics": metrics(all_rows),
            "by_exit_source": group_metrics(all_rows, lambda row: row["_exit_source"]),
            "by_time_bucket": group_metrics(all_rows, lambda row: row["_time_bucket"]),
            "early_0_5m_by_exit_source": group_metrics(
                early_rows, lambda row: row["_exit_source"]
            ),
            "early_0_5m_source_loss_rank": source_loss_rank,
            "reason_counts": dict(Counter(row["_exit_reason"] for row in all_rows)),
        },
        "all_baseline_parity": all(
            all(row["baseline_parity"].values()) for row in strategy_receipts
        ),
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
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> int:
    assert exit_source("strategy_exit") == "STRATEGY_ACTION_EXIT"
    assert exit_source("hard_stop_loss") == "HARD_RISK_EXIT"
    assert exit_source("take_profit") == "TAKE_PROFIT_EXIT"
    assert time_bucket(4.0) == "0-5m"
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--strategy", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (args.engine, args.source_root, args.data_root, args.terminal)
    if any(value is None for value in required):
        parser.error("engine, source-root, data-root and terminal are required")
    receipt = run(
        args.engine.resolve(),
        args.source_root.resolve(),
        args.data_root.resolve(),
        args.terminal.resolve(),
        args.strategy,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
