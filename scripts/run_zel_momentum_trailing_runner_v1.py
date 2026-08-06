#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import math
import sys
import zipfile
from pathlib import Path
from statistics import fmean
from typing import Any

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
MAX_HOLD_BARS = 12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_feature_runner(repo_root: Path):
    path = repo_root / "scripts/run_zel_momentum_feature_contribution_v1.py"
    spec = importlib.util.spec_from_file_location("zel_feature_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("feature runner unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def locate_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix) and not name.endswith("/")]
    if len(matches) != 1:
        raise ValueError(f"expected one {suffix}, found {matches}")
    return matches[0]


def is_disabled_fraction(raw: str) -> bool:
    return raw.strip() in {"", "None", "null", "nan"}


def read_source_artifact(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        receipt = json.loads(archive.read(locate_member(archive, "partial_exit_receipt.json")))
        compressed = archive.read(locate_member(archive, "partial_exit_trades.csv.gz"))

    rows: list[dict[str, Any]] = []
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as handle:
        text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
        for row in csv.DictReader(text):
            if not is_disabled_fraction(row["partial_fraction"]):
                continue
            rows.append({
                "trade_id": row["trade_id"],
                "symbol": row["symbol"],
                "signal_ts": int(row["signal_ts"]),
                "entry_ts": int(row["entry_ts"]),
                "exit_ts": int(row["exit_ts"]),
                "entry_price": float(row["entry_price"]),
                "entry_reference": float(row["entry_reference"]),
                "stop_price": float(row["original_stop_price"]),
                "target_price": float(row["target_price"]),
                "planned_risk": float(row["planned_risk"]),
                "gross_R": float(row["gross_R"]),
                "cost_R": float(row["cost_R"]),
                "net_R": float(row["net_R"]),
                "exit_reason": row["exit_reason"],
                "source_intent_sha256": row["source_intent_sha256"],
                "strategy_source_sha256": row["strategy_source_sha256"],
                "feature_schema_sha256": row["feature_schema_sha256"],
                "config_sha256": row["config_sha256"],
            })
    return receipt, sorted(rows, key=lambda row: (row["entry_ts"], row["symbol"], row["trade_id"]))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["exit_ts"], row["symbol"], row["trade_id"]))
    values = [float(row["net_R"]) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    avg_win = fmean(wins) if wins else 0.0
    avg_loss = fmean(losses) if losses else 0.0
    return {
        "trades": len(ordered),
        "win_rate_pct": len(wins) / len(ordered) * 100.0 if ordered else 0.0,
        "net_R": sum(values),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "payoff": avg_win / abs(avg_loss) if avg_loss < 0 else None,
        "expectancy_R": fmean(values) if values else 0.0,
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "max_drawdown_R": max_drawdown,
        "target_exits": sum(row["exit_reason"] == "TARGET" for row in ordered),
        "original_stop_exits": sum(row["exit_reason"] in {"STOP", "STOP_FIRST"} for row in ordered),
        "trailing_stop_exits": sum(row["exit_reason"] in {"TRAILING_STOP", "TRAILING_STOP_FIRST"} for row in ordered),
        "timeout_exits": sum(row["exit_reason"] == "TIMEOUT" for row in ordered),
        "trailing_armed": sum(bool(row["trailing_armed"]) for row in ordered),
    }


def count_same_symbol_overlap(rows: list[dict[str, Any]]) -> int:
    conflicts = 0
    for symbol in SYMBOLS:
        last_exit = -1
        symbol_rows = sorted(
            (row for row in rows if row["symbol"] == symbol),
            key=lambda row: (row["entry_ts"], row["trade_id"]),
        )
        for row in symbol_rows:
            conflicts += row["entry_ts"] <= last_exit
            last_exit = max(last_exit, row["exit_ts"])
    return conflicts


def simulate_policy(
    source_rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Any]],
    index_by_symbol: dict[str, dict[int, int]],
    variant: dict[str, Any],
    all_in_cost_pct: float,
) -> list[dict[str, Any]]:
    variant_id = str(variant["variant_id"])
    arm_r = None if variant["arm_r"] is None else float(variant["arm_r"])
    trail_r = None if variant["trail_r"] is None else float(variant["trail_r"])
    target_r = float(variant["target_r"])
    disabled = variant_id == "TRAILING_DISABLED"
    output: list[dict[str, Any]] = []

    for source in source_rows:
        base = {
            "trade_id": hashlib.sha256(f"{variant_id}|{source['trade_id']}".encode("utf-8")).hexdigest(),
            "source_trade_id": source["trade_id"],
            "variant_id": variant_id,
            "arm_r": arm_r,
            "trail_r": trail_r,
            "target_r": target_r,
            "symbol": source["symbol"],
            "signal_ts": source["signal_ts"],
            "entry_ts": source["entry_ts"],
            "entry_price": source["entry_price"],
            "entry_reference": source["entry_reference"],
            "original_stop_price": source["stop_price"],
            "planned_risk": source["planned_risk"],
            "source_intent_sha256": source["source_intent_sha256"],
            "strategy_source_sha256": source["strategy_source_sha256"],
            "feature_schema_sha256": source["feature_schema_sha256"],
            "config_sha256": source["config_sha256"],
        }
        if disabled:
            output.append(base | {
                "exit_ts": source["exit_ts"],
                "target_price": source["target_price"],
                "active_stop_at_exit": source["stop_price"],
                "trailing_armed": False,
                "armed_after_ts": None,
                "highest_closed_high": None,
                "gross_R": source["gross_R"],
                "cost_R": source["cost_R"],
                "net_R": source["net_R"],
                "exit_reason": source["exit_reason"],
            })
            continue

        bars = bars_by_symbol[source["symbol"]]
        entry_index = index_by_symbol[source["symbol"]].get(source["entry_ts"])
        if entry_index is None or entry_index + MAX_HOLD_BARS > len(bars):
            raise ValueError(f"missing frozen entry horizon: {source['symbol']}/{source['entry_ts']}")

        target_price = source["entry_reference"] + target_r * source["planned_risk"]
        active_stop = source["stop_price"]
        trailing_armed = False
        armed_after_ts: int | None = None
        highest_closed_high: float | None = None
        exit_index = entry_index + MAX_HOLD_BARS - 1
        exit_price = bars[exit_index].close
        exit_reason = "TIMEOUT"

        for cursor in range(entry_index, entry_index + MAX_HOLD_BARS):
            bar = bars[cursor]
            stop_hit = bar.low <= active_stop
            target_hit = bar.high >= target_price
            if stop_hit:
                exit_price = active_stop
                exit_index = cursor
                if trailing_armed:
                    exit_reason = "TRAILING_STOP_FIRST" if target_hit else "TRAILING_STOP"
                else:
                    exit_reason = "STOP_FIRST" if target_hit else "STOP"
                break
            if target_hit:
                exit_price = target_price
                exit_index = cursor
                exit_reason = "TARGET"
                break

            if arm_r is not None and trail_r is not None:
                arm_threshold = source["entry_reference"] + arm_r * source["planned_risk"]
                if not trailing_armed and bar.close >= arm_threshold:
                    trailing_armed = True
                    armed_after_ts = bar.ts
                    highest_closed_high = bar.high
                elif trailing_armed:
                    highest_closed_high = max(float(highest_closed_high), bar.high)

                if trailing_armed:
                    candidate_stop = float(highest_closed_high) - trail_r * source["planned_risk"]
                    active_stop = max(source["stop_price"], candidate_stop)

        gross_r = (exit_price - source["entry_price"]) / source["planned_risk"]
        cost_r = (source["entry_price"] * (all_in_cost_pct / 100.0)) / source["planned_risk"]
        output.append(base | {
            "exit_ts": bars[exit_index].ts,
            "target_price": target_price,
            "active_stop_at_exit": active_stop,
            "trailing_armed": trailing_armed,
            "armed_after_ts": armed_after_ts,
            "highest_closed_high": highest_closed_high,
            "gross_R": gross_r,
            "cost_R": cost_r,
            "net_R": gross_r - cost_r,
            "exit_reason": exit_reason,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.repo_root = args.repo_root.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.repo_root))

    from backend.research import zel_feature_strategy_ssot_v1 as strategy

    engine = load_feature_runner(args.repo_root)
    plan_path = args.repo_root / "backend/research/zel_momentum_trailing_runner_plan_v1.json"
    disposition_path = args.repo_root / "backend/research/zel_momentum_partial_exit_disposition_v1.json"
    manifest_path = args.inputs / "materialized_manifest.json"
    cost_path = args.inputs / "cost_binding.json"
    plan = json.loads(plan_path.read_text())
    disposition = json.loads(disposition_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    cost = json.loads(cost_path.read_text())

    if plan.get("state") != "PASS_TRAILING_RUNNER_PLAN_SEALED_RESEARCH_ONLY":
        raise SystemExit("trailing runner plan not sealed")
    if disposition.get("state") != "FAIL_PARTIAL_EXIT_NO_SURVIVOR":
        raise SystemExit("partial-exit disposition mismatch")
    if sha256_file(args.source_artifact) != disposition["source_artifact_sha256"]:
        raise SystemExit("partial-exit artifact SHA mismatch")
    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("materialized input state mismatch")

    receipt, source_rows = read_source_artifact(args.source_artifact)
    if receipt.get("receipt_sha256") != plan["source_receipt_sha256"]:
        raise SystemExit("partial-exit receipt mismatch")
    if len(source_rows) != int(plan["frozen_entry_count"]):
        raise SystemExit("frozen entry count mismatch")
    if len({row["trade_id"] for row in source_rows}) != len(source_rows):
        raise SystemExit("duplicate frozen source trade")

    bars_by_symbol = {
        symbol: engine.read_bars(
            args.inputs / "market/5m/research" / f"{symbol}.csv.gz",
            strategy.Bar,
            strategy.FIVE_MIN_MS,
        )
        for symbol in SYMBOLS
    }
    index_by_symbol = {
        symbol: {bar.ts: index for index, bar in enumerate(bars)}
        for symbol, bars in bars_by_symbol.items()
    }
    all_in_cost_pct = float(cost["all_in_cost_pct"])

    results: list[dict[str, Any]] = []
    ledgers: dict[str, list[dict[str, Any]]] = {}
    for variant in plan["policy_candidates"]:
        rows = simulate_policy(source_rows, bars_by_symbol, index_by_symbol, variant, all_in_cost_pct)
        metrics = summarize(rows)
        metrics.update({
            "variant_id": variant["variant_id"],
            "arm_r": variant["arm_r"],
            "trail_r": variant["trail_r"],
            "target_r": variant["target_r"],
            "entry_retention_pct": len(rows) / len(source_rows) * 100.0,
            "same_symbol_overlap_conflicts": count_same_symbol_overlap(rows),
            "duplicates": len(rows) - len({row["trade_id"] for row in rows}),
        })
        results.append(metrics)
        ledgers[variant["variant_id"]] = rows

    base = next(row for row in results if row["variant_id"] == "TRAILING_DISABLED")
    source_metrics = disposition["best_control"]
    assert int(base["trades"]) == int(source_metrics["trades"])
    for key in ("net_R", "win_rate_pct", "profit_factor", "payoff", "expectancy_R", "max_drawdown_R"):
        if not math.isclose(float(base[key]), float(source_metrics[key]), rel_tol=1e-9, abs_tol=1e-9):
            raise AssertionError((key, base[key], source_metrics[key]))

    gates = plan["hard_gates"]
    survivors: list[str] = []
    for row in results:
        row["hard_gate"] = {
            "trades": int(row["trades"]) == int(gates["trades_eq"]),
            "entry_retention": math.isclose(
                float(row["entry_retention_pct"]),
                float(gates["entry_retention_pct_eq"]),
                abs_tol=1e-12,
            ),
            "net_R": float(row["net_R"]) > float(gates["net_R_gt"]),
            "profit_factor": row["profit_factor"] is not None and float(row["profit_factor"]) >= float(gates["profit_factor_gte"]),
            "expectancy_R": float(row["expectancy_R"]) > float(gates["expectancy_R_gt"]),
            "payoff": row["payoff"] is not None and float(row["payoff"]) >= float(gates["payoff_gte"]),
            "max_drawdown": float(row["max_drawdown_R"]) < float(gates["max_drawdown_R_lt_source"]),
        }
        row["hard_gate_pass"] = all(row["hard_gate"].values())
        if row["hard_gate_pass"]:
            survivors.append(row["variant_id"])

    ranking = [
        row["variant_id"]
        for row in sorted(
            results,
            key=lambda row: (
                float(row["net_R"]),
                float(row["profit_factor"] or 0.0),
                -float(row["max_drawdown_R"]),
            ),
            reverse=True,
        )
    ]
    integrity = {
        "errors": 0,
        "duplicates": sum(int(row["duplicates"]) for row in results),
        "source_entry_rows": len(source_rows),
        "base_metric_parity": True,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    if integrity["duplicates"] != 0:
        raise SystemExit("duplicate trailing-runner trades")

    state = (
        "PASS_TRAILING_RUNNER_COUNTERFACTUAL_SURVIVOR_FOUND_SEQUENCE_REQUIRED"
        if survivors
        else "PASS_TRAILING_RUNNER_COUNTERFACTUAL_NO_SURVIVOR"
    )
    next_gate = plan["next_if_survivor"] if survivors else plan["next_if_no_survivor"]
    output = {
        "schema_version": "zel.momentum.trailing_runner_receipt.v1",
        "state": state,
        "strategy_id": plan["strategy_id"],
        "single_causal_axis": plan["single_causal_axis"],
        "source_variant_id": plan["source_variant_id"],
        "source_artifact_sha256": sha256_file(args.source_artifact),
        "source_receipt_sha256": receipt["receipt_sha256"],
        "references": {
            "plan_sha256": sha256_file(plan_path),
            "disposition_sha256": sha256_file(disposition_path),
            "materialized_manifest_sha256": sha256_file(manifest_path),
            "cost_binding_sha256": sha256_file(cost_path),
        },
        "results": results,
        "research_ranking": ranking,
        "hard_gate_survivors": survivors,
        "integrity": integrity,
        "selection_authority": False,
        "promotion_authority": False,
        "next_gate": next_gate,
        "action": "hold" if survivors else "route_change",
    }
    output["receipt_sha256"] = canonical_sha256(output)
    (args.output / "trailing_runner_receipt.json").write_text(
        json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    with gzip.open(args.output / "trailing_runner_trades.csv.gz", "wt", newline="") as handle:
        fieldnames = [
            "trade_id", "source_trade_id", "variant_id", "arm_r", "trail_r", "target_r",
            "symbol", "signal_ts", "entry_ts", "exit_ts", "entry_price", "entry_reference",
            "original_stop_price", "active_stop_at_exit", "target_price", "planned_risk",
            "trailing_armed", "armed_after_ts", "highest_closed_high", "gross_R", "cost_R",
            "net_R", "exit_reason", "source_intent_sha256", "strategy_source_sha256",
            "feature_schema_sha256", "config_sha256",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for variant_id in ranking:
            writer.writerows(ledgers[variant_id])

    print(json.dumps({
        "state": state,
        "survivors": survivors,
        "top3": ranking[:3],
        "next_gate": next_gate,
        "receipt": output["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
