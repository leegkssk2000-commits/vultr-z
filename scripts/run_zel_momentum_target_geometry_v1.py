#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from pathlib import Path
from statistics import fmean
from typing import Any

SOURCE_TARGET_R = 1.6
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")


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
    spec = importlib.util.spec_from_file_location("zel_momentum_feature_contribution_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load feature contribution runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def locate_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix) and not name.endswith("/")]
    if len(matches) != 1:
        raise ValueError(f"expected one {suffix}, found {matches}")
    return matches[0]


def read_source_artifact(path: Path, expected_variant: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        receipt_name = locate_member(archive, "cost_geometry_receipt.json")
        trades_name = locate_member(archive, "cost_geometry_trades.csv.gz")
        receipt = json.loads(archive.read(receipt_name))
        compressed = archive.read(trades_name)

    rows: list[dict[str, Any]] = []
    with gzip.GzipFile(fileobj=__import__("io").BytesIO(compressed), mode="rb") as handle:
        text = __import__("io").TextIOWrapper(handle, encoding="utf-8", newline="")
        for row in csv.DictReader(text):
            if row["variant_id"] != expected_variant:
                continue
            rows.append({
                "trade_id": row["trade_id"],
                "variant_id": row["variant_id"],
                "symbol": row["symbol"],
                "signal_ts": int(row["signal_ts"]),
                "entry_ts": int(row["entry_ts"]),
                "exit_ts": int(row["exit_ts"]),
                "entry_price": float(row["entry_price"]),
                "stop_price": float(row["stop_price"]),
                "target_price": float(row["target_price"]),
                "planned_risk": float(row["planned_risk"]),
                "gross_R": float(row["gross_R"]),
                "cost_R": float(row["cost_R"]),
                "net_R": float(row["net_R"]),
                "exit_reason": row["exit_reason"],
                "intent_sha256": row["intent_sha256"],
                "strategy_source_sha256": row["strategy_source_sha256"],
                "feature_schema_sha256": row["feature_schema_sha256"],
                "config_sha256": row["config_sha256"],
            })
    return receipt, sorted(rows, key=lambda row: (row["entry_ts"], row["symbol"], row["trade_id"]))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["exit_ts"], row["symbol"], row["trade_id"]))
    net_values = [float(row["net_R"]) for row in ordered]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    avg_win = fmean(wins) if wins else 0.0
    avg_loss = fmean(losses) if losses else 0.0
    return {
        "trades": len(ordered),
        "win_rate_pct": len(wins) / len(ordered) * 100.0 if ordered else 0.0,
        "net_R": sum(net_values),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "payoff": avg_win / abs(avg_loss) if avg_loss < 0 else None,
        "expectancy_R": fmean(net_values) if net_values else 0.0,
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "max_drawdown_R": max_drawdown,
        "target_exits": sum(row["exit_reason"] == "TARGET" for row in ordered),
        "stop_exits": sum(row["exit_reason"] in {"STOP", "STOP_FIRST"} for row in ordered),
        "timeout_exits": sum(row["exit_reason"] == "TIMEOUT" for row in ordered),
    }


def count_same_symbol_overlap(rows: list[dict[str, Any]]) -> int:
    count = 0
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], []).append(row)
    for symbol_rows in by_symbol.values():
        last_exit = -1
        for row in sorted(symbol_rows, key=lambda item: (item["entry_ts"], item["trade_id"])):
            if row["entry_ts"] <= last_exit:
                count += 1
            last_exit = max(last_exit, row["exit_ts"])
    return count


def assert_close(left: float, right: float, tolerance: float = 1e-9) -> None:
    if not math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError((left, right))


def simulate_target(
    source_rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Any]],
    index_by_symbol: dict[str, dict[int, int]],
    target_r: float,
    max_hold_bars: int,
    all_in_cost_pct: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in source_rows:
        symbol = source["symbol"]
        bars = bars_by_symbol[symbol]
        entry_index = index_by_symbol[symbol].get(source["entry_ts"])
        if entry_index is None or entry_index + max_hold_bars > len(bars):
            raise ValueError(f"missing frozen entry horizon: {symbol}/{source['entry_ts']}")

        entry_reference = source["target_price"] - SOURCE_TARGET_R * source["planned_risk"]
        target_price = entry_reference + target_r * source["planned_risk"]
        stop_price = source["stop_price"]
        exit_index = entry_index + max_hold_bars - 1
        exit_price = bars[exit_index].close
        exit_reason = "TIMEOUT"
        for cursor in range(entry_index, entry_index + max_hold_bars):
            bar = bars[cursor]
            stop_hit = bar.low <= stop_price
            target_hit = bar.high >= target_price
            if stop_hit:
                exit_price = stop_price
                exit_index = cursor
                exit_reason = "STOP_FIRST" if target_hit else "STOP"
                break
            if target_hit:
                exit_price = target_price
                exit_index = cursor
                exit_reason = "TARGET"
                break

        gross_r = (exit_price - source["entry_price"]) / source["planned_risk"]
        cost_r = (source["entry_price"] * (all_in_cost_pct / 100.0)) / source["planned_risk"]
        output.append({
            "trade_id": hashlib.sha256(
                f"TARGET_R_{target_r:g}|{source['trade_id']}".encode("utf-8")
            ).hexdigest(),
            "source_trade_id": source["trade_id"],
            "target_r": target_r,
            "symbol": symbol,
            "signal_ts": source["signal_ts"],
            "entry_ts": source["entry_ts"],
            "exit_ts": bars[exit_index].ts,
            "entry_price": source["entry_price"],
            "entry_reference": entry_reference,
            "stop_price": stop_price,
            "target_price": target_price,
            "planned_risk": source["planned_risk"],
            "gross_R": gross_r,
            "cost_R": cost_r,
            "net_R": gross_r - cost_r,
            "exit_reason": exit_reason,
            "source_intent_sha256": source["intent_sha256"],
            "strategy_source_sha256": source["strategy_source_sha256"],
            "feature_schema_sha256": source["feature_schema_sha256"],
            "config_sha256": source["config_sha256"],
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
    plan_path = args.repo_root / "backend/research/zel_momentum_target_geometry_plan_v1.json"
    disposition_path = args.repo_root / "backend/research/zel_momentum_cost_geometry_disposition_v1.json"
    manifest_path = args.inputs / "materialized_manifest.json"
    cost_path = args.inputs / "cost_binding.json"
    plan = json.loads(plan_path.read_text())
    disposition = json.loads(disposition_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    cost = json.loads(cost_path.read_text())

    if plan.get("state") != "PASS_TARGET_GEOMETRY_PLAN_SEALED_RESEARCH_ONLY":
        raise SystemExit("target geometry plan not sealed")
    if disposition.get("state") != "FAIL_THRESHOLD_ONLY_NO_RETENTION_COMPLIANT_SURVIVOR":
        raise SystemExit("cost geometry disposition mismatch")
    if sha256_file(args.source_artifact) != disposition["source_artifact_sha256"]:
        raise SystemExit("cost geometry artifact SHA mismatch")
    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("materialized input state mismatch")

    receipt, source_rows = read_source_artifact(args.source_artifact, plan["source_variant_id"])
    if receipt.get("receipt_sha256") != plan["source_receipt_sha256"]:
        raise SystemExit("cost geometry receipt mismatch")
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
    max_hold_bars = int(plan["frozen_contract"]["max_hold_bars"])
    all_in_cost_pct = float(cost["all_in_cost_pct"])

    results: list[dict[str, Any]] = []
    ledgers: dict[str, list[dict[str, Any]]] = {}
    for target_r in plan["target_r_candidates"]:
        variant_id = f"TARGET_R_{float(target_r):g}"
        rows = simulate_target(
            source_rows,
            bars_by_symbol,
            index_by_symbol,
            float(target_r),
            max_hold_bars,
            all_in_cost_pct,
        )
        metrics = summarize(rows)
        metrics["variant_id"] = variant_id
        metrics["target_r"] = float(target_r)
        metrics["entry_retention_pct"] = len(rows) / len(source_rows) * 100.0
        metrics["same_symbol_overlap_conflicts"] = count_same_symbol_overlap(rows)
        metrics["duplicates"] = len(rows) - len({row["trade_id"] for row in rows})
        results.append(metrics)
        ledgers[variant_id] = rows

    source_metrics = disposition["frozen_entry_control"]
    base = next(row for row in results if row["target_r"] == SOURCE_TARGET_R)
    assert int(base["trades"]) == int(source_metrics["trades"])
    assert_close(float(base["net_R"]), float(source_metrics["net_R"]), tolerance=1e-8)
    assert_close(float(base["win_rate_pct"]), float(source_metrics["win_rate_pct"]), tolerance=1e-8)
    assert_close(float(base["profit_factor"]), float(source_metrics["profit_factor"]), tolerance=1e-8)
    assert_close(float(base["payoff"]), float(source_metrics["payoff"]), tolerance=1e-8)
    assert_close(float(base["expectancy_R"]), float(source_metrics["expectancy_R"]), tolerance=1e-8)
    assert_close(float(base["max_drawdown_R"]), float(source_metrics["max_drawdown_R"]), tolerance=1e-8)

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

    ranking = [row["variant_id"] for row in sorted(
        results,
        key=lambda row: (
            float(row["net_R"]),
            float(row["profit_factor"] or 0.0),
            -float(row["max_drawdown_R"]),
        ),
        reverse=True,
    )]
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
        raise SystemExit("duplicate target geometry trades")

    state = (
        "PASS_TARGET_GEOMETRY_COUNTERFACTUAL_SURVIVOR_FOUND_SEQUENCE_REQUIRED"
        if survivors
        else "PASS_TARGET_GEOMETRY_COUNTERFACTUAL_NO_SURVIVOR"
    )
    next_gate = plan["next_if_survivor"] if survivors else plan["next_if_no_survivor"]
    output = {
        "schema_version": "zel.momentum.target_geometry_receipt.v1",
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
    (args.output / "target_geometry_receipt.json").write_text(
        json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    with gzip.open(args.output / "target_geometry_trades.csv.gz", "wt", newline="") as handle:
        fieldnames = [
            "trade_id", "source_trade_id", "target_r", "symbol", "signal_ts", "entry_ts", "exit_ts",
            "entry_price", "entry_reference", "stop_price", "target_price", "planned_risk", "gross_R",
            "cost_R", "net_R", "exit_reason", "source_intent_sha256", "strategy_source_sha256",
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
