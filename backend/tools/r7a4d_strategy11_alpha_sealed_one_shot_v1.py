from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
COST_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_cost_aware_stop_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_SEALED_ONE_SHOT_V1"
ALL_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")


def load_cost() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_cost_for_sealed"
        spec = importlib.util.spec_from_file_location(name, COST_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("COST_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


cost = load_cost()
ref = cost.ref
v1 = cost.v1
p = cost.p
exact = cost.exact
base = cost.base


def strict_json(path: Path) -> Any:
    return ref.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return ref.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    ref.atomic_json(path, payload)


def load_role_data(data_root: Path, funding_root: Path, roles: Sequence[str], *, sealed_required: bool) -> tuple[dict[tuple[str, str], pd.DataFrame], dict[tuple[str, str], pd.DataFrame], dict[str, list[dict[str, Any]]], Mapping[str, Any], dict[tuple[str, str], str]]:
    manifest = strict_json(data_root / "manifest.json")
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        raise RuntimeError("DATA_MANIFEST_NOT_PASS")
    if sealed_required:
        if manifest.get("sealed") is not True or manifest.get("one_shot_only") is not True or manifest.get("repair_read_allowed") is not False:
            raise RuntimeError("SEALED_CONTRACT_INVALID")
        if manifest.get("kind") != "SEALED_FINAL_HOLDBACK":
            raise RuntimeError("SEALED_KIND_INVALID")
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    features: dict[tuple[str, str], pd.DataFrame] = {}
    shas: dict[tuple[str, str], str] = {}
    selected = set(roles)
    for row in manifest.get("files", []):
        if not isinstance(row, Mapping) or row.get("state") != "PASS":
            continue
        role, symbol = str(row["window_id"]), str(row["symbol"])
        if role not in selected:
            continue
        path = data_root.parent / str(row["path"])
        if p.sha256(path) != row.get("sha256"):
            raise RuntimeError(f"MARKET_SHA_MISMATCH:{role}:{symbol}")
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        frame["ts"] = frame["timestamp_ms"]
        frames[(role, symbol)] = frame
        features[(role, symbol)] = exact.compute_feature_frame(frame)
        shas[(role, symbol)] = str(row["sha256"])
    missing = [(role, symbol) for role in roles for symbol in ALL_SYMBOLS if (role, symbol) not in frames]
    if missing:
        raise RuntimeError("ROLE_DATA_MISSING:" + ",".join(f"{role}:{symbol}" for role, symbol in missing))
    funding: dict[str, list[dict[str, Any]]] = {}
    for symbol in ALL_SYMBOLS:
        payload = strict_json(funding_root / "funding" / f"{symbol}.json")
        funding[symbol] = [dict(row) for row in payload.get("rows", []) if isinstance(row, Mapping)]
    return frames, features, funding, manifest, shas


def replay_roles(*, variant_id: str, exit_spec: Any, strategy: Any, gate: Any, surgery: Any,
                 symbols: tuple[str, ...], roles: Sequence[str], frames: Mapping[tuple[str, str], pd.DataFrame],
                 features: Mapping[tuple[str, str], pd.DataFrame], funding: Mapping[str, list[dict[str, Any]]],
                 quantiles: Mapping[str, Mapping[str, float]], manifest: Mapping[str, Any], market_shas: Mapping[tuple[str, str], str],
                 strategy_source_sha: str, candidate_sha: str, source_run_id: str, source_head_sha: str,
                 cost_multiplier: float, funding_scenario: str, latency_scenario: str) -> list[dict[str, Any]]:
    cost_bps = metric(manifest.get("combined_fee_slippage_bps_per_side"), 4.0) * cost_multiplier
    delay = 1 if latency_scenario == "NEXT_BAR_OPEN" else 2
    warmup_bars = int(manifest["warmup_bars"])
    raw: list[dict[str, Any]] = []
    for role in roles:
        for symbol in symbols:
            replay = p.replay_evidence(
                frames[(role, symbol)], features[(role, symbol)], strategy, gate, exit_spec, surgery,
                window_id=role, symbol=symbol, warmup_bars=warmup_bars, history_bars=220,
                cost_bps_per_side=cost_bps, entry_delay_bars=delay,
            )
            for trade in replay["trades"]:
                raw.append(v1.enrich_trade(
                    trade,
                    candidate_sha=candidate_sha,
                    strategy_source_sha=strategy_source_sha,
                    market_sha=market_shas[(role, symbol)],
                    source_run_id=source_run_id,
                    source_head_sha=source_head_sha,
                ))
    adjusted = p.apply_funding(raw, funding, funding_scenario, quantiles)
    enriched: list[dict[str, Any]] = []
    stop_mult = float(exit_spec.stop_mult)
    for trade in adjusted:
        role, symbol = str(trade["window_id"]), str(trade["symbol"])
        row = v1.enrich_trade(
            trade,
            candidate_sha=candidate_sha,
            strategy_source_sha=strategy_source_sha,
            market_sha=market_shas[(role, symbol)],
            source_run_id=source_run_id,
            source_head_sha=source_head_sha,
        )
        candidate_risk_pct = metric(row.get("risk_pct"))
        reference_risk_pct = candidate_risk_pct / stop_mult if stop_mult > 0.0 else 0.0
        row["candidate_risk_pct"] = candidate_risk_pct
        row["reference_risk_pct"] = reference_risk_pct
        row["net_reference_R"] = metric(row.get("net_return_pct")) / reference_risk_pct if reference_risk_pct > 0.0 else None
        row["reference_r_lock"] = "INCUMBENT_RAW_RISK_PCT"
        enriched.append(row)
    return v1.sorted_ledger(enriched)


def evaluate_variant(*, variant_id: str, exit_spec: Any, strategy: Any, gate: Any, surgery: Any,
                     symbols: tuple[str, ...], roles: Sequence[str], frames: Mapping[tuple[str, str], pd.DataFrame],
                     features: Mapping[tuple[str, str], pd.DataFrame], funding: Mapping[str, list[dict[str, Any]]],
                     quantiles: Mapping[str, Mapping[str, float]], manifest: Mapping[str, Any], market_shas: Mapping[tuple[str, str], str],
                     strategy_source_sha: str, source_run_id: str, source_head_sha: str, cap_r: float, out: Path) -> dict[str, Any]:
    config = {"variant_id": variant_id, "exit": asdict(exit_spec), "roles": list(roles)}
    candidate_sha = v1.stable_sha(config)
    ledgers: list[list[dict[str, Any]]] = []
    for replay_name in ("A", "B"):
        trades = replay_roles(
            variant_id=variant_id, exit_spec=exit_spec, strategy=strategy, gate=gate, surgery=surgery,
            symbols=symbols, roles=roles, frames=frames, features=features, funding=funding,
            quantiles=quantiles, manifest=manifest, market_shas=market_shas,
            strategy_source_sha=strategy_source_sha, candidate_sha=candidate_sha,
            source_run_id=source_run_id, source_head_sha=source_head_sha,
            cost_multiplier=1.0, funding_scenario="OBSERVED", latency_scenario="NEXT_BAR_OPEN",
        )
        ledgers.append(trades)
        atomic_json(out / variant_id / f"replay-{replay_name}.json", {"variant_id": variant_id, "roles": list(roles), "trades": trades})
    sha_a, sha_b = v1.ledger_sha(ledgers[0]), v1.ledger_sha(ledgers[1])
    duplicates = len(ledgers[0]) - len({row["trade_id"] for row in ledgers[0]})
    stats = p.combine_stats(ledgers[0])
    per_window = {role: p.combine_stats([row for row in ledgers[0] if row.get("window_id") == role]) for role in roles}
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0.0 for row in per_window.values())
    stop_mult = float(exit_spec.stop_mult)
    losses = ref.reference_loss_metrics(ledgers[0], cap_r, stop_mult)
    stress_trades = replay_roles(
        variant_id=variant_id, exit_spec=exit_spec, strategy=strategy, gate=gate, surgery=surgery,
        symbols=symbols, roles=roles, frames=frames, features=features, funding=funding,
        quantiles=quantiles, manifest=manifest, market_shas=market_shas,
        strategy_source_sha=strategy_source_sha, candidate_sha=candidate_sha,
        source_run_id=source_run_id, source_head_sha=source_head_sha,
        cost_multiplier=2.0, funding_scenario="ADVERSE_P95", latency_scenario="PLUS_ONE_BAR",
    )
    stress_losses = ref.reference_loss_metrics(stress_trades, cap_r, stop_mult)
    returns = [float(row["net_return_pct"]) for row in ledgers[0]]
    bootstrap = p.block_bootstrap(returns, 2000, 0.95, seed=int(v1.stable_sha(config)[:8], 16))
    dsr = p.deflated_sharpe(returns, trials=25)
    payload = {
        "variant_id": variant_id,
        "candidate_config_sha": candidate_sha,
        "exit": asdict(exit_spec),
        "roles": list(roles),
        "trade_count": int(stats.get("trade_count") or 0),
        "win_rate_pct": stats.get("win_rate_pct"),
        "net_return_pct_sum": stats.get("net_return_pct_sum"),
        "net_profit_factor": stats.get("net_profit_factor"),
        "payoff_ratio": stats.get("payoff_ratio"),
        "max_drawdown_pct": stats.get("max_drawdown_pct"),
        "positive_windows": positive_windows,
        "positive_windows_pct": positive_windows / len(roles) * 100.0,
        "window_stats": per_window,
        "loss_metrics": losses,
        "stress_2x_p95_plus_one": {
            "trade_count": len(stress_trades),
            "stats": p.combine_stats(stress_trades),
            "loss_metrics": stress_losses,
        },
        "bootstrap": bootstrap,
        "deflated_sharpe": dsr,
        "parity": {
            "state": "PASS" if sha_a == sha_b and duplicates == 0 else "HOLD",
            "replay_a_sha256": sha_a,
            "replay_b_sha256": sha_b,
            "duplicate_trade_count": duplicates,
            "trade_count_a": len(ledgers[0]),
            "trade_count_b": len(ledgers[1]),
            "reference_r_lock": "PASS",
        },
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
    }
    atomic_json(out / variant_id / "summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "sealed"), required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--funding-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--winner-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    data_root = Path(args.data_root).resolve()
    funding_root = Path(args.funding_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    winner_path = Path(args.winner_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    winner_summary = strict_json(winner_path)
    ssot = strict_json(ssot_path)

    if winner_summary.get("strategy_id") != "alpha_combo" or winner_summary.get("state") != "PASS_TO_SEALED":
        raise RuntimeError("WINNER_AUTHORITY_INVALID")
    if winner_summary.get("winner") != "STOP_MULT_065_REFERENCE_R":
        raise RuntimeError("WINNER_ID_INVALID")
    if winner_summary.get("eligible_for_sealed_one_shot") != ["STOP_MULT_065_REFERENCE_R"]:
        raise RuntimeError("SEALED_ELIGIBILITY_INVALID")
    if winner_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("SEALED_ALREADY_READ")

    roles = ("F1", "F2") if args.mode == "preflight" else ("Z1", "Z2")
    sealed_required = args.mode == "sealed"
    frames, features, funding, manifest, market_shas = load_role_data(data_root, funding_root, roles, sealed_required=sealed_required)
    quantiles = p.funding_rate_quantiles(funding)

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    winner_exit = replace(base_exit, exit_id="RR150_STOP065_REFERENCE_R", stop_mult=0.65)
    surgery = p.surgery_from(baseline_summary.get("surgery"))
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)
    cap_r = float(ssot["loss_budget"]["net_loss_cap_r"])

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        ("STOP_MULT_065_REFERENCE_R", winner_exit),
    ]
    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"SEALED_{args.mode.upper()}_START variant={variant_id}", flush=True)
        rows.append(evaluate_variant(
            variant_id=variant_id, exit_spec=exit_spec, strategy=strategy, gate=gate, surgery=surgery,
            symbols=symbols, roles=roles, frames=frames, features=features, funding=funding,
            quantiles=quantiles, manifest=manifest, market_shas=market_shas,
            strategy_source_sha=strategy_source_sha, source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha, cap_r=cap_r, out=out,
        ))
        print(f"SEALED_{args.mode.upper()}_END variant={variant_id}", flush=True)

    incumbent, challenger = rows
    if args.mode == "preflight":
        passed = all(row["parity"]["state"] == "PASS" for row in rows)
        final = {
            "schema_version": "1.0", "version": VERSION, "mode": "PREFLIGHT", "state": "PASS" if passed else "HOLD",
            "strategy_id": "alpha_combo", "roles": list(roles), "variants": rows,
            "sealed_holdback_read": False, "canonical_mutated": False, "registry_mutated": False,
            "execution_allowed": False, "next": "SEALED_HOLDBACK_ONE_SHOT" if passed else "REPAIR_PREFLIGHT",
        }
        atomic_json(out / "summary.json", final)
        return 0

    promotion = ssot["promotion"]
    deltas = {
        "net": metric(challenger["net_return_pct_sum"]) - metric(incumbent["net_return_pct_sum"]),
        "pf": metric(challenger["net_profit_factor"]) - metric(incumbent["net_profit_factor"]),
        "payoff": metric(challenger["payoff_ratio"]) - metric(incumbent["payoff_ratio"]),
    }
    thresholds = {
        "net": float(promotion["min_delta_net_pct_points"]),
        "pf": float(promotion["min_delta_profit_factor"]),
        "payoff": float(promotion["min_delta_payoff_ratio"]),
    }
    improved = sum(deltas[key] >= thresholds[key] for key in deltas)
    nonworse = all(value >= 0.0 for value in deltas.values())
    retention = challenger["trade_count"] / max(1, incumbent["trade_count"]) * 100.0
    normal_cap = challenger["loss_metrics"]["loss_cap_breach_count"] == 0 and metric(challenger["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    stress_cap = challenger["stress_2x_p95_plus_one"]["loss_metrics"]["loss_cap_breach_count"] == 0 and metric(challenger["stress_2x_p95_plus_one"]["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    avg_loss_nonworse = metric(challenger["loss_metrics"]["avg_loss_R"], -math.inf) >= metric(incumbent["loss_metrics"]["avg_loss_R"], -math.inf)
    min_trades = math.ceil(int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"]) * len(roles) / 3)
    passes = (
        challenger["parity"]["state"] == "PASS"
        and challenger["trade_count"] >= min_trades
        and normal_cap and stress_cap and avg_loss_nonworse
        and metric(challenger["max_drawdown_pct"], math.inf) <= metric(incumbent["max_drawdown_pct"], math.inf)
        and retention >= float(promotion["min_trade_retention_pct"])
        and challenger["positive_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
        and improved >= int(promotion["min_improved_primary_metrics"])
        and nonworse
        and challenger["bootstrap"].get("state") == "PASS"
        and challenger["deflated_sharpe"].get("state") == "PASS"
    )
    challenger["comparison_to_incumbent"] = {
        "delta_net_pct_points": deltas["net"], "delta_profit_factor": deltas["pf"],
        "delta_payoff_ratio": deltas["payoff"], "improved_primary_metrics": improved,
        "trade_retention_pct": retention, "normal_loss_cap_pass": normal_cap,
        "stress_loss_cap_pass": stress_cap, "average_loss_nonworse": avg_loss_nonworse,
        "min_sealed_trades": min_trades, "pass_core_candidate": passes,
    }
    atomic_json(out / challenger["variant_id"] / "summary.json", challenger)

    blockers: list[str] = []
    if challenger["trade_count"] < min_trades:
        blockers.append(f"SEALED_TRADES_LT_MIN:{challenger['trade_count']}<{min_trades}")
    if challenger["positive_windows_pct"] < float(promotion["min_positive_fresh_windows_pct"]):
        blockers.append("SEALED_POSITIVE_WINDOWS_LT_MIN")
    if not normal_cap:
        blockers.append("SEALED_NORMAL_LOSS_CAP_FAIL")
    if not stress_cap:
        blockers.append("SEALED_STRESS_LOSS_CAP_FAIL")
    if metric(challenger["max_drawdown_pct"], math.inf) > metric(incumbent["max_drawdown_pct"], math.inf):
        blockers.append("SEALED_DD_WORSE")
    if improved < int(promotion["min_improved_primary_metrics"]):
        blockers.append("SEALED_ECONOMIC_IMPROVEMENT_LT_MIN")
    if not nonworse:
        blockers.append("SEALED_PRIMARY_METRIC_DEGRADATION")

    final = {
        "schema_version": "1.0", "version": VERSION, "mode": "SEALED_ONE_SHOT",
        "state": "CORE_CANDIDATE" if passes else "SEALED_REJECT_ROLLBACK",
        "classification": "CORE_CANDIDATE" if passes else "NEAR_MISS_REPAIR_EXHAUSTED",
        "strategy_id": "alpha_combo", "winner": "STOP_MULT_065_REFERENCE_R" if passes else None,
        "winner_candidate_config_sha": winner_summary.get("winner_candidate_config_sha") if passes else None,
        "source_run_id": args.source_run_id, "source_head_sha": args.source_head_sha,
        "winner_authority_run_id": "30278422559", "winner_summary_sha256": p.sha256(winner_path),
        "sealed_manifest_sha256": p.sha256(data_root / "manifest.json"),
        "sealed_window_count": len(roles), "sealed_one_shot_consumed": True,
        "variants": rows, "blockers": blockers, "canonical_mutated": False,
        "registry_mutated": False, "execution_allowed": False,
        "shadow_allowed": False, "next": "ADVANCE_TURTLE_TREND_REVIEW",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "BLOCKERS": blockers, "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
