from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.strategy11_feature_library_v1 import GateSpec
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

prior = replay.prior
repair = replay.repair
p = replay.p
exact = replay.exact
base = replay.base

VERSION = "R7A4D_STRATEGY11_TREND_MA_MACD_EXIT_AXIS_V1"
STRATEGY_ID = "trend_ma_macd"
SOURCE_VARIANT_ID = "SF__OBV_POSITIVE"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def find_source_variant(root: Path) -> Path:
    matches = sorted(root.glob(f"batch-*/{STRATEGY_ID}/{SOURCE_VARIANT_ID}/summary.json"))
    if len(matches) != 1:
        raise RuntimeError(f"SOURCE_VARIANT_MATCH:{len(matches)}")
    return matches[0]


def relation(row: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    normal = row.get("loss_metrics") or {}
    control_normal = control.get("loss_metrics") or {}
    stress = (row.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}
    checks = {
        "trade_count_preserved": int(row.get("trade_count") or 0) >= int(control.get("trade_count") or 0),
        "net_nonworse": metric(row.get("net_return_pct_sum")) >= metric(control.get("net_return_pct_sum")),
        "pf_nonworse": metric(row.get("net_profit_factor")) >= metric(control.get("net_profit_factor")),
        "payoff_nonworse": metric(row.get("payoff_ratio")) >= metric(control.get("payoff_ratio")),
        "dd_nonworse": metric(row.get("max_drawdown_pct")) <= metric(control.get("max_drawdown_pct")),
        "avg_loss_nonworse": metric(normal.get("avg_loss_R"), -math.inf) >= metric(control_normal.get("avg_loss_R"), -math.inf),
        "worst_loss_l090": metric(normal.get("normal_worst_net_loss_R"), -math.inf) >= -0.90,
        "stress_worst_loss_l090": metric(stress.get("normal_worst_net_loss_R"), -math.inf) >= -0.95,
        "positive_windows_preserved": metric(row.get("positive_fresh_windows_pct")) >= metric(control.get("positive_fresh_windows_pct")),
        "parity_pass": row.get("parity", {}).get("state") == "PASS",
        "duplicate_zero": int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
    }
    improvements = {
        "net_delta_pct": metric(row.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "pf_delta": metric(row.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff_delta": metric(row.get("payoff_ratio")) - metric(control.get("payoff_ratio")),
        "dd_delta_pct_points": metric(row.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
        "avg_loss_delta_r": metric(normal.get("avg_loss_R"), -math.inf) - metric(control_normal.get("avg_loss_R"), -math.inf),
    }
    primary_improved = sum(
        improvements[key] > 0.0 for key in ("net_delta_pct", "pf_delta", "payoff_delta", "avg_loss_delta_r")
    ) + int(improvements["dd_delta_pct_points"] < 0.0)
    hard_pass = all(checks.values()) and primary_improved >= 2
    return {
        "state": "PASS_DIAGNOSTIC_PARETO" if hard_pass else "NO_DIAGNOSTIC_PARETO",
        "checks": checks,
        "deltas": improvements,
        "primary_improved_count": primary_improved,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "promotion_authority": False,
    }


def trade_path_diagnostics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for trade in trades:
        rows.append({
            "trade_id": trade.get("trade_id"),
            "window_id": trade.get("window_id"),
            "symbol": trade.get("symbol"),
            "bars_held": int(trade.get("bars_held") or 0),
            "bars_to_mfe": int(trade.get("bars_to_mfe") or 0),
            "bars_to_mae": int(trade.get("bars_to_mae") or 0),
            "mfe_r": trade.get("mfe_r"),
            "mae_r": trade.get("mae_r"),
            "net_loss_r": trade.get("net_loss_r"),
            "net_return_pct": trade.get("net_return_pct"),
            "exit_reason": trade.get("exit_reason"),
        })
    losing = [row for row in rows if metric(row.get("net_return_pct")) < 0.0]
    winning = [row for row in rows if metric(row.get("net_return_pct")) > 0.0]
    losing_bars = sorted(row["bars_held"] for row in losing)
    return {
        "trade_count": len(rows),
        "win_count": len(winning),
        "loss_count": len(losing),
        "winning_mfe_r": sorted(metric(row.get("mfe_r")) for row in winning),
        "losing_mfe_r": sorted(metric(row.get("mfe_r")) for row in losing),
        "losing_bars_held": losing_bars,
        "median_losing_bars": losing_bars[len(losing_bars) // 2] if losing_bars else None,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source_summary = strict_json(find_source_variant(args.replay_root.resolve()))
    config = source_summary["candidate_config"]
    if config.get("strategy_id") != STRATEGY_ID or config.get("candidate_id") != SOURCE_VARIANT_ID:
        raise RuntimeError("SOURCE_VARIANT_IDENTITY_MISMATCH")
    gate = GateSpec(**dict(config["gate"]))
    exit_spec = exact._exit_from({"exit": config["exit"]})
    surgery = p.surgery_from(config.get("surgery"))
    symbols = tuple(str(value) for value in config["symbols"])

    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(args.root.resolve())
    registry_row = registry[STRATEGY_ID]
    strategy = base._load_canonical_strategy(args.root.resolve(), STRATEGY_ID, registry_row)
    source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    policy = strict_json(args.policy.resolve())
    stage = policy["loss_ladder"][0]

    variants = {
        "CONTROL_TRAIL1R_ATR1": exit_spec,
        "BE075": replace(exit_spec, exit_id=f"{exit_spec.exit_id}_BE075", breakeven_r=0.75),
        "TRAIL075_ATR075": replace(
            exit_spec,
            exit_id=f"{exit_spec.exit_id}_TRAIL075_ATR075",
            trail_activate_r=0.75,
            trail_atr_mult=0.75,
        ),
        "TIME8": replace(exit_spec, exit_id=f"{exit_spec.exit_id}_TIME8", time_stop_bars=8),
    }

    results: dict[str, Any] = {}
    for variant_id, variant_exit in variants.items():
        variant_config = {
            "strategy_id": STRATEGY_ID,
            "source_variant_id": SOURCE_VARIANT_ID,
            "variant_id": variant_id,
            "axis": "CONTROL" if variant_id.startswith("CONTROL") else (
                "BREAKEVEN" if variant_id.startswith("BE") else "MFE_TRAILING" if variant_id.startswith("TRAIL") else "TIME_STOP"
            ),
            "gate": config["gate"],
            "exit": variant_exit.__dict__,
            "surgery": config.get("surgery"),
            "symbols": list(symbols),
        }
        row = replay.evaluate(
            variant_id=variant_id,
            config=variant_config,
            exit_spec=variant_exit,
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
            strategy_source_sha=source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            normal_cap_r=float(stage["normal_worst_net_loss_R_min"]),
            stress_cap_r=float(stage["stress_worst_net_loss_R_min"]),
            out=args.out.resolve() / STRATEGY_ID,
        )
        results[variant_id] = row

    control = results["CONTROL_TRAIL1R_ATR1"]
    source_trades = strict_json(
        find_source_variant(args.replay_root.resolve()).parent / "replay-A.json"
    )["trades"]
    path_diagnostics = trade_path_diagnostics(source_trades)
    candidate_rows = []
    for variant_id, row in results.items():
        if variant_id == "CONTROL_TRAIL1R_ATR1":
            continue
        candidate_rows.append({
            "variant_id": variant_id,
            "axis": row["candidate_config"]["axis"],
            "trade_count": row.get("trade_count"),
            "win_rate_pct": row.get("win_rate_pct"),
            "net_pct": row.get("net_return_pct_sum"),
            "profit_factor": row.get("net_profit_factor"),
            "payoff": row.get("payoff_ratio"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "avg_loss_r": (row.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (row.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "stress_worst_loss_r": ((row.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "relation": relation(row, control),
            "summary_sha": stable_sha(row),
        })
    candidate_rows.sort(key=lambda row: (
        row["relation"]["state"] != "PASS_DIAGNOSTIC_PARETO",
        -metric(row.get("net_pct")),
        -metric(row.get("profit_factor")),
        -metric(row.get("payoff")),
    ))
    diagnostic_survivors = [row for row in candidate_rows if row["relation"]["state"] == "PASS_DIAGNOSTIC_PARETO"]
    result = {
        "schema_version": "strategy11.trend_ma_macd_exit_axis.v1",
        "version": VERSION,
        "state": "PASS_EXIT_AXIS_DIAGNOSTIC_COMPLETE",
        "strategy_id": STRATEGY_ID,
        "source_variant_id": SOURCE_VARIANT_ID,
        "source_summary_sha": stable_sha(source_summary),
        "strategy_source_sha": source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "control": {
            "trade_count": control.get("trade_count"),
            "net_pct": control.get("net_return_pct_sum"),
            "profit_factor": control.get("net_profit_factor"),
            "payoff": control.get("payoff_ratio"),
            "max_drawdown_pct": control.get("max_drawdown_pct"),
            "avg_loss_r": (control.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (control.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "summary_sha": stable_sha(control),
        },
        "path_diagnostics": path_diagnostics,
        "candidates": candidate_rows,
        "diagnostic_survivor_ids": [row["variant_id"] for row in diagnostic_survivors],
        "next": "GROQ_AND_WORKERS_AI_REVIEW_THEN_L090_REPLAY" if diagnostic_survivors else "WAIT_NEW_EVIDENCE_OR_DIFFERENT_CAUSAL_AXIS",
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    atomic_json(args.out.resolve() / "final.json", result)
    print(result["state"], result["diagnostic_survivor_ids"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
