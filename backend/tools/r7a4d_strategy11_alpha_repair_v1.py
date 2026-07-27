from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_PATH = ROOT / "backend/tools/r7a4d_strategy11_evidence_pipeline_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_REPAIR_V1"
FRESH_ROLES = ("F1", "F2", "F3")


def load_pipeline() -> Any:
    name = "r7a4d_strategy11_evidence_pipeline_for_alpha_repair_v1"
    spec = importlib.util.spec_from_file_location(name, PIPELINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PIPELINE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = load_pipeline()
exact = p.exact
base = p.base


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def metric(value: Any, default: float = 0.0) -> float:
    return float(value) if finite(value) else default


def market_sha_map(manifest: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for row in manifest.get("files", []):
        if isinstance(row, Mapping) and row.get("state") == "PASS":
            result[(str(row["window_id"]), str(row["symbol"]))] = str(row["sha256"])
    return result


def enrich_trade(
    trade: Mapping[str, Any],
    *,
    candidate_sha: str,
    strategy_source_sha: str,
    market_sha: str,
    source_run_id: str,
    source_head_sha: str,
) -> dict[str, Any]:
    row = dict(trade)
    identity = {
        "window_id": row.get("window_id"),
        "symbol": row.get("symbol"),
        "entry_ts": row.get("entry_ts"),
        "exit_ts": row.get("exit_ts"),
        "entry_price": row.get("entry_price"),
        "exit_price": row.get("exit_price"),
        "exit_reason": row.get("exit_reason"),
        "candidate_config_sha": candidate_sha,
    }
    row["trade_id"] = stable_sha(identity)
    row["strategy_source_sha"] = strategy_source_sha
    row["candidate_config_sha"] = candidate_sha
    row["market_file_sha256"] = market_sha
    row["source_run_id"] = source_run_id
    row["source_head_sha"] = source_head_sha
    risk_pct = metric(row.get("risk_pct"))
    row["net_loss_r"] = metric(row.get("net_return_pct")) / risk_pct if risk_pct > 0 else None
    return row


def sorted_ledger(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        trades,
        key=lambda row: (
            str(row.get("window_id")),
            str(row.get("symbol")),
            str(row.get("entry_ts")),
            str(row.get("exit_ts")),
            str(row.get("trade_id")),
        ),
    )


def ledger_sha(trades: list[dict[str, Any]]) -> str:
    return stable_sha(sorted_ledger(trades))


def loss_metrics(trades: list[dict[str, Any]], cap_r: float) -> dict[str, Any]:
    wins: list[float] = []
    losses: list[float] = []
    normal_losses: list[float] = []
    unavoidable: list[float] = []
    for trade in trades:
        risk_pct = metric(trade.get("risk_pct"))
        if risk_pct <= 0:
            continue
        value = metric(trade.get("net_return_pct")) / risk_pct
        if value > 0:
            wins.append(value)
        elif value < 0:
            losses.append(value)
            if bool(trade.get("path_ambiguous")):
                unavoidable.append(value)
            else:
                normal_losses.append(value)
    return {
        "avg_win_R": sum(wins) / len(wins) if wins else None,
        "avg_loss_R": sum(losses) / len(losses) if losses else None,
        "worst_net_loss_R": min(losses) if losses else None,
        "normal_worst_net_loss_R": min(normal_losses) if normal_losses else None,
        "loss_cap_breach_count": sum(value < cap_r for value in normal_losses),
        "unavoidable_execution_breach_count": sum(value < cap_r for value in unavoidable),
        "loss_count": len(losses),
        "win_count": len(wins),
    }


def replay_once(
    *,
    variant_id: str,
    exit_spec: Any,
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], pd.DataFrame],
    features: Mapping[tuple[str, str], pd.DataFrame],
    funding: Mapping[str, list[dict[str, Any]]],
    quantiles: Mapping[str, Mapping[str, float]],
    manifest: Mapping[str, Any],
    market_shas: Mapping[tuple[str, str], str],
    strategy_source_sha: str,
    candidate_sha: str,
    source_run_id: str,
    source_head_sha: str,
    cost_multiplier: float,
    funding_scenario: str,
    latency_scenario: str,
) -> list[dict[str, Any]]:
    cost_bps = metric(manifest.get("combined_fee_slippage_bps_per_side"), 4.0) * cost_multiplier
    delay = 1 if latency_scenario == "NEXT_BAR_OPEN" else 2
    warmup_bars = int(manifest["warmup_bars"])
    raw: list[dict[str, Any]] = []
    for role in FRESH_ROLES:
        for symbol in symbols:
            replay = p.replay_evidence(
                frames[(role, symbol)],
                features[(role, symbol)],
                strategy,
                gate,
                exit_spec,
                surgery,
                window_id=role,
                symbol=symbol,
                warmup_bars=warmup_bars,
                history_bars=220,
                cost_bps_per_side=cost_bps,
                entry_delay_bars=delay,
            )
            for trade in replay["trades"]:
                raw.append(
                    enrich_trade(
                        trade,
                        candidate_sha=candidate_sha,
                        strategy_source_sha=strategy_source_sha,
                        market_sha=market_shas[(role, symbol)],
                        source_run_id=source_run_id,
                        source_head_sha=source_head_sha,
                    )
                )
    adjusted = p.apply_funding(raw, funding, funding_scenario, quantiles)
    enriched: list[dict[str, Any]] = []
    for trade in adjusted:
        role = str(trade["window_id"])
        symbol = str(trade["symbol"])
        enriched.append(
            enrich_trade(
                trade,
                candidate_sha=candidate_sha,
                strategy_source_sha=strategy_source_sha,
                market_sha=market_shas[(role, symbol)],
                source_run_id=source_run_id,
                source_head_sha=source_head_sha,
            )
        )
    return sorted_ledger(enriched)


def evaluate_variant(
    *,
    variant_id: str,
    exit_spec: Any,
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], pd.DataFrame],
    features: Mapping[tuple[str, str], pd.DataFrame],
    funding: Mapping[str, list[dict[str, Any]]],
    quantiles: Mapping[str, Mapping[str, float]],
    manifest: Mapping[str, Any],
    market_shas: Mapping[tuple[str, str], str],
    strategy_source_sha: str,
    source_run_id: str,
    source_head_sha: str,
    cap_r: float,
    out: Path,
) -> dict[str, Any]:
    config = {"variant_id": variant_id, "exit": asdict(exit_spec)}
    candidate_sha = stable_sha(config)
    ledgers: list[list[dict[str, Any]]] = []
    for replay_name in ("A", "B"):
        trades = replay_once(
            variant_id=variant_id,
            exit_spec=exit_spec,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=strategy_source_sha,
            candidate_sha=candidate_sha,
            source_run_id=source_run_id,
            source_head_sha=source_head_sha,
            cost_multiplier=1.0,
            funding_scenario="OBSERVED",
            latency_scenario="NEXT_BAR_OPEN",
        )
        ledgers.append(trades)
        atomic_json(out / variant_id / f"replay-{replay_name}.json", {"variant_id": variant_id, "trades": trades})
    sha_a, sha_b = ledger_sha(ledgers[0]), ledger_sha(ledgers[1])
    parity = sha_a == sha_b
    duplicates = len(ledgers[0]) - len({row["trade_id"] for row in ledgers[0]})
    stats = p.combine_stats(ledgers[0])
    per_window = {
        role: p.combine_stats([row for row in ledgers[0] if row.get("window_id") == role])
        for role in FRESH_ROLES
    }
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0 for row in per_window.values())
    losses = loss_metrics(ledgers[0], cap_r)
    stress_trades = replay_once(
        variant_id=variant_id,
        exit_spec=exit_spec,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        frames=frames,
        features=features,
        funding=funding,
        quantiles=quantiles,
        manifest=manifest,
        market_shas=market_shas,
        strategy_source_sha=strategy_source_sha,
        candidate_sha=candidate_sha,
        source_run_id=source_run_id,
        source_head_sha=source_head_sha,
        cost_multiplier=2.0,
        funding_scenario="ADVERSE_P95",
        latency_scenario="PLUS_ONE_BAR",
    )
    stress_losses = loss_metrics(stress_trades, cap_r)
    payload = {
        "variant_id": variant_id,
        "candidate_config_sha": candidate_sha,
        "exit": asdict(exit_spec),
        "trade_count": int(stats.get("trade_count") or 0),
        "win_rate_pct": stats.get("win_rate_pct"),
        "net_return_pct_sum": stats.get("net_return_pct_sum"),
        "net_profit_factor": stats.get("net_profit_factor"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "max_drawdown_pct": stats.get("max_drawdown_pct"),
        "positive_fresh_windows": positive_windows,
        "positive_fresh_windows_pct": positive_windows / len(FRESH_ROLES) * 100.0,
        "loss_metrics": losses,
        "stress_2x_p95_plus_one": {
            "trade_count": len(stress_trades),
            "stats": p.combine_stats(stress_trades),
            "loss_metrics": stress_losses,
        },
        "parity": {
            "state": "PASS" if parity and duplicates == 0 else "HOLD",
            "replay_a_sha256": sha_a,
            "replay_b_sha256": sha_b,
            "duplicate_trade_count": duplicates,
            "trade_count_a": len(ledgers[0]),
            "trade_count_b": len(ledgers[1]),
        },
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
    }
    atomic_json(out / variant_id / "summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ssot = strict_json(Path(args.ssot).resolve())
    baseline_summary = strict_json(Path(args.baseline_summary).resolve())
    if baseline_summary.get("strategy_id") != "alpha_combo" or baseline_summary.get("state") != "PASS":
        raise RuntimeError("ALPHA_BASELINE_NOT_PASS")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline_summary.get("surgery"))
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    engine = registry_row["canonical_engine"]
    strategy_source_sha = str(engine["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)

    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = market_sha_map(manifest)
    cap_r = float(ssot["loss_budget"]["net_loss_cap_r"])

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        ("STOP_MULT_085", replace(base_exit, exit_id="RR150_STOP085", stop_mult=0.85)),
        ("BREAKEVEN_075R", replace(base_exit, exit_id="RR150_BE075", breakeven_r=0.75)),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"REPAIR_START variant={variant_id}", flush=True)
        rows.append(
            evaluate_variant(
                variant_id=variant_id,
                exit_spec=exit_spec,
                strategy=strategy,
                gate=gate,
                surgery=surgery,
                symbols=symbols,
                frames=frames,
                features=features,
                funding=funding,
                quantiles=quantiles,
                manifest=manifest,
                market_shas=market_shas,
                strategy_source_sha=strategy_source_sha,
                source_run_id=args.source_run_id,
                source_head_sha=args.source_head_sha,
                cap_r=cap_r,
                out=out,
            )
        )
        print(f"REPAIR_END variant={variant_id}", flush=True)

    baseline = rows[0]
    promotion = ssot["promotion"]
    eligible: list[str] = []
    for row in rows[1:]:
        primary = {
            "net": metric(row["net_return_pct_sum"]) - metric(baseline["net_return_pct_sum"]),
            "pf": metric(row["net_profit_factor"]) - metric(baseline["net_profit_factor"]),
            "payoff": metric(row["payoff_ratio"]) - metric(baseline["payoff_ratio"]),
        }
        thresholds = {
            "net": float(promotion["min_delta_net_pct_points"]),
            "pf": float(promotion["min_delta_profit_factor"]),
            "payoff": float(promotion["min_delta_payoff_ratio"]),
        }
        improved = sum(primary[key] >= thresholds[key] for key in primary)
        nonworse = all(primary[key] >= 0.0 or primary[key] >= thresholds[key] for key in primary)
        retention = row["trade_count"] / max(1, baseline["trade_count"]) * 100.0
        normal_cap = (
            row["loss_metrics"]["loss_cap_breach_count"] == 0
            and metric(row["loss_metrics"]["normal_worst_net_loss_R"], 0.0) >= cap_r
        )
        stress_cap = row["stress_2x_p95_plus_one"]["loss_metrics"]["loss_cap_breach_count"] == 0
        passes = (
            row["parity"]["state"] == "PASS"
            and normal_cap
            and stress_cap
            and metric(row["max_drawdown_pct"]) <= metric(baseline["max_drawdown_pct"])
            and retention >= float(promotion["min_trade_retention_pct"])
            and row["positive_fresh_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
            and improved >= int(promotion["min_improved_primary_metrics"])
            and nonworse
        )
        row["comparison_to_incumbent"] = {
            "delta_net_pct_points": primary["net"],
            "delta_profit_factor": primary["pf"],
            "delta_payoff_ratio": primary["payoff"],
            "improved_primary_metrics": improved,
            "trade_retention_pct": retention,
            "normal_loss_cap_pass": normal_cap,
            "stress_loss_cap_pass": stress_cap,
            "pass_to_sealed": passes,
        }
        if passes:
            eligible.append(str(row["variant_id"]))

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if eligible else "HOLD",
        "strategy_id": "alpha_combo",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "strategy_source_sha": strategy_source_sha,
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "ssot_sha256": p.sha256(Path(args.ssot).resolve()),
        "baseline_summary_sha256": p.sha256(Path(args.baseline_summary).resolve()),
        "variants": rows,
        "eligible_for_sealed_one_shot": eligible,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if eligible else "ITERATION_2_PARTIAL_OR_TRAILING",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "ELIGIBLE": eligible}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
