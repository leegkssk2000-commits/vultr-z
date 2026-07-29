from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

VERSION = "R7A4D_STRATEGY11_ALPHA_OVERFIT_SENTINEL_V1"
REQUIRED = ("INCUMBENT_CONTROL", "STOP065_PROFIT_CONTROL", "TIME48", "TIME54", "TIME60")
ACTIVE = ("TIME54", "TIME60")
PLATEAU = ("TIME48", "TIME54", "TIME60")
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "canonical_mutated": False,
    "registry_mutated": False,
    "sealed_holdback_read": False,
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    values = pd.to_numeric(frame["net_return_pct"], errors="raise").astype(float).to_numpy()
    wins = values[values > 0]
    losses = values[values < 0]
    ordered = frame.copy()
    ordered["exit_ts"] = pd.to_datetime(ordered["exit_ts"], utc=True)
    ordered = ordered.sort_values(["exit_ts", "trade_id"])
    sequence = ordered["net_return_pct"].astype(float).to_numpy()
    equity = np.cumsum(sequence)
    prior_peaks = np.maximum.accumulate(np.r_[0.0, equity])[:-1] if len(equity) else np.array([])
    drawdown = float(np.max(prior_peaks - equity)) if len(equity) else 0.0
    gross_loss = abs(float(losses.sum()))
    return {
        "trades": int(len(values)),
        "win_rate_pct": float((values > 0).mean() * 100.0) if len(values) else 0.0,
        "net_return_pct_sum": float(values.sum()),
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else 999.0,
        "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 999.0,
        "sequence_drawdown_pct": drawdown,
        "worst_trade_pct": float(values.min()) if len(values) else 0.0,
    }


def leave_one_out(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for value in sorted(map(str, frame[column].dropna().unique())):
        rows[value] = metrics(frame[frame[column].astype(str) != value])
    return {
        "dimension": column,
        "rows": rows,
        "minimum_net_return_pct_sum": min((float(row["net_return_pct_sum"]) for row in rows.values()), default=0.0),
        "minimum_profit_factor": min((float(row["profit_factor"]) for row in rows.values()), default=0.0),
    }


def bootstrap(frame: pd.DataFrame, iterations: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    groups = [group["net_return_pct"].astype(float).to_numpy() for _, group in frame.groupby("window_id", sort=True)]
    nets: list[float] = []
    pfs: list[float] = []
    wrs: list[float] = []
    for _ in range(iterations):
        values = np.concatenate([rng.choice(group, size=len(group), replace=True) for group in groups])
        wins = values[values > 0]
        losses = values[values < 0]
        gross_loss = abs(float(losses.sum()))
        nets.append(float(values.sum()))
        pfs.append(float(wins.sum() / gross_loss) if gross_loss > 0 else 999.0)
        wrs.append(float((values > 0).mean() * 100.0))
    return {
        "iterations": iterations,
        "seed": seed,
        "probability_net_positive": float(np.mean(np.asarray(nets) > 0.0)),
        "net_q05": float(np.quantile(nets, 0.05)),
        "net_q50": float(np.quantile(nets, 0.50)),
        "profit_factor_q05": float(np.quantile(pfs, 0.05)),
        "win_rate_q05": float(np.quantile(wrs, 0.05)),
    }


def permutation_drawdown(frame: pd.DataFrame, iterations: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    values = frame["net_return_pct"].astype(float).to_numpy()
    drawdowns: list[float] = []
    for _ in range(iterations):
        sequence = rng.permutation(values)
        equity = np.cumsum(sequence)
        prior_peaks = np.maximum.accumulate(np.r_[0.0, equity])[:-1]
        drawdowns.append(float(np.max(prior_peaks - equity)))
    return {
        "iterations": iterations,
        "seed": seed,
        "drawdown_q50": float(np.quantile(drawdowns, 0.50)),
        "drawdown_q95": float(np.quantile(drawdowns, 0.95)),
        "drawdown_q99": float(np.quantile(drawdowns, 0.99)),
    }


def frame_for(root: Path, variant: str) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    directory = root / variant
    replay_a_path = directory / "replay-A.json"
    replay_b_path = directory / "replay-B.json"
    summary = load(directory / "summary.json")
    replay_a = load(replay_a_path)
    replay_b = load(replay_b_path)
    if sha256(replay_a_path) != sha256(replay_b_path):
        raise ValueError(f"PARITY_SHA_MISMATCH:{variant}")
    trades = replay_a.get("trades")
    if not isinstance(trades, list) or not trades:
        raise ValueError(f"TRADES_MISSING:{variant}")
    frame = pd.DataFrame(trades)
    required = {"trade_id", "symbol", "window_id", "exit_ts", "net_return_pct", "source_run_id", "source_head_sha", "strategy_source_sha", "candidate_config_sha"}
    if not required.issubset(frame.columns):
        raise ValueError(f"TRADE_LINEAGE_MISSING:{variant}:{sorted(required - set(frame.columns))}")
    if frame["trade_id"].duplicated().any():
        raise ValueError(f"DUPLICATE_TRADE_ID:{variant}")
    if summary.get("parity", {}).get("state") != "PASS" or int(summary.get("parity", {}).get("duplicate_trade_count") or 0) != 0:
        raise ValueError(f"SUMMARY_PARITY_FAIL:{variant}")
    return frame, summary, replay_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--iterations", type=int, default=5000)
    args = parser.parse_args()

    root = Path(args.artifact_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    authority = load(root / "summary.json")
    if authority.get("state") != "PASS_MULTIOBJECTIVE_RESEARCH_CANDIDATES":
        raise ValueError("ALPHA_AUTHORITY_STATE_INVALID")
    if authority.get("same_dataset_generation_budget_exhausted") is not True:
        raise ValueError("GENERATION_BUDGET_NOT_EXHAUSTED")
    if authority.get("active_candidate_queue") != ["TIME54", "TIME60"]:
        raise ValueError("ACTIVE_QUEUE_UNEXPECTED")

    variants: dict[str, Any] = {}
    frames: dict[str, pd.DataFrame] = {}
    for index, variant in enumerate(REQUIRED):
        frame, summary, replay = frame_for(root, variant)
        frames[variant] = frame
        variants[variant] = {
            "summary_sha256": sha256(root / variant / "summary.json"),
            "replay_sha256": sha256(root / variant / "replay-A.json"),
            "metrics": metrics(frame),
            "leave_one_window_out": leave_one_out(frame, "window_id"),
            "leave_one_symbol_out": leave_one_out(frame, "symbol"),
            "bootstrap": bootstrap(frame, args.iterations, 1700 + index),
            "trade_order_permutation": permutation_drawdown(frame, args.iterations, 2300 + index),
            "strict_pass": bool(summary.get("multiobjective", {}).get("strict", {}).get("pass")),
            "stress_worst_net_loss_R": float(summary.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}).get("worst_net_loss_R", math.nan)),
            "normal_worst_net_loss_R": float(summary.get("loss_metrics", {}).get("worst_net_loss_R", math.nan)),
        }

    plateau_net = [float(variants[name]["metrics"]["net_return_pct_sum"]) for name in PLATEAU]
    plateau_pf = [float(variants[name]["metrics"]["profit_factor"]) for name in PLATEAU]
    incumbent_dd95 = float(variants["INCUMBENT_CONTROL"]["trade_order_permutation"]["drawdown_q95"])
    checks: dict[str, bool] = {
        "adjacent_time_plateau_strict_pass": all(bool(variants[name]["strict_pass"]) for name in PLATEAU),
        "adjacent_time_plateau_net_within_5pct": min(plateau_net) / max(plateau_net) >= 0.95,
        "adjacent_time_plateau_pf_within_20pct": min(plateau_pf) / max(plateau_pf) >= 0.80,
    }
    for name in ACTIVE:
        checks[f"{name}_leave_one_window_positive"] = float(variants[name]["leave_one_window_out"]["minimum_net_return_pct_sum"]) > 0.0 and float(variants[name]["leave_one_window_out"]["minimum_profit_factor"]) > 1.0
        checks[f"{name}_leave_one_symbol_positive"] = float(variants[name]["leave_one_symbol_out"]["minimum_net_return_pct_sum"]) > 0.0 and float(variants[name]["leave_one_symbol_out"]["minimum_profit_factor"]) > 1.0
        checks[f"{name}_bootstrap_positive"] = float(variants[name]["bootstrap"]["probability_net_positive"]) >= 0.95 and float(variants[name]["bootstrap"]["profit_factor_q05"]) > 1.0
        checks[f"{name}_permuted_dd_below_incumbent"] = float(variants[name]["trade_order_permutation"]["drawdown_q95"]) <= incumbent_dd95
        checks[f"{name}_loss_stress_pass"] = float(variants[name]["normal_worst_net_loss_R"]) >= -0.75 and float(variants[name]["stress_worst_net_loss_R"]) >= -0.75

    passed = all(checks.values())
    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_ALPHA_OVERFIT_SENTINEL_ROBUST_PLATEAU" if passed else "HOLD_ALPHA_OVERFIT_SENTINEL_FRAGILE",
        "strategy_id": "alpha_combo",
        "diagnostic_only": True,
        "new_candidate_created": False,
        "generation_budget_consumed": False,
        "authority_artifact_sha256": sha256(root / "summary.json"),
        "checks": checks,
        "variants": variants,
        "decision": {
            "candidate_queue": list(ACTIVE) if passed else [],
            "retain_incumbent": True,
            "rollback_definition": "Discard research candidate queue and retain INCUMBENT_CONTROL; no runtime or deployed strategy was changed.",
            "recommended_action": "RETAIN_TIME54_TIME60_QUEUE_AND_WAIT_W1" if passed else "ROLLBACK_RESEARCH_QUEUE_TO_INCUMBENT_AND_WAIT_W1",
            "next": "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION",
            "further_same_dataset_parameter_search": "FORBIDDEN",
        },
        **SAFETY,
    }
    (out / "alpha_overfit_sentinel.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
