from __future__ import annotations

import copy
import importlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

mx: Any = importlib.import_module(
    "backend.research.rebuild.a1_strategy_regime_alpha_matrix_v1"
)
life: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_lifecycle_overlay_v2"
)
v6: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_v6_recovered_180d_v1"
)
ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "priority_economic_program_v1.json"


def monthly(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    pnl: dict[str, float] = defaultdict(float)
    count: Counter[str] = Counter()
    for row in rows:
        key = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        pnl[key] += float(row["net_bps"])
        count[key] += 1
    return {key: {"T": count[key], "Net_bps": pnl[key]} for key in sorted(pnl)}


def concentration(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    vals = [float(row["net_bps"]) for row in rows]
    wins = sorted((v for v in vals if v > 0), reverse=True)
    net, gross_profit = sum(vals), sum(wins)
    return {
        "top1_over_net": wins[0] / net if wins and net > 0 else None,
        "top3_over_net": sum(wins[:3]) / net if net > 0 else None,
        "top1_over_gross_profit": wins[0] / gross_profit if gross_profit else None,
    }


def improved_active(
    ledger: list[dict[str, Any]],
    regmap: dict[tuple[str, str, int], str],
    bars: dict[str, list[dict[str, float | int]]],
    sid: str,
    regime: str,
    stale_bars: int,
    stale_mfe_r: float,
    name: str,
) -> list[dict[str, Any]]:
    base = copy.deepcopy(life.BASE_RULE[sid])
    base["stale_frac"] = 1.0
    base["stale_bars"] = stale_bars
    base["stale_mfe_r"] = stale_mfe_r
    out: list[dict[str, Any]] = []
    for trade in ledger:
        key = (f"{sid}_active5", str(trade["symbol"]), int(trade["signal_ts"]))
        if trade["strategy_id"] != sid or regmap.get(key) != regime:
            continue
        out.append(
            {
                "strategy": name,
                "symbol": str(trade["symbol"]),
                "signal_ts": int(trade["signal_ts"]),
                "exit_ts": int(trade["exit_ts"]),
                "net_bps": life.simulate(trade, bars[str(trade["symbol"])], base, {}),
            }
        )
    return out


def split(rows: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: (int(r["exit_ts"]), str(r["strategy"])))
    train = [row for row in ordered if int(row["signal_ts"]) <= cutoff]
    hold = [row for row in ordered if int(row["signal_ts"]) > cutoff]
    return {
        "full": mx.metrics(ordered),
        "train60_time": mx.metrics(train),
        "holdout40_time": mx.metrics(hold),
        "months": monthly(ordered),
        "concentration": concentration(ordered),
    }


def trade_frequency(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    start = min(int(row["signal_ts"]) for row in rows)
    end = max(int(row["exit_ts"]) for row in rows)
    days = max((end - start) / 86_400_000.0, 1e-9)
    return len(rows) / days


def scaled(rows: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["net_bps"] = weight * float(row["net_bps"])
        item["risk_weight"] = weight
        out.append(item)
    return out


def main() -> int:
    feat, cutoff, q = mx.build_features()
    strategies = mx.load_strategies()
    mx.attach_regimes(strategies, feat, q)
    regmap = {
        (str(row["strategy"]), str(row["symbol"]), int(row["signal_ts"])): str(
            row["regime"]
        )
        for rows in strategies.values()
        for row in rows
    }
    ledger = json.load(open(ROOT / "active5_v6_180d_ledger_v2.json"))["trades"]
    bars = v6.v5.local_1h_bars()

    hg = [
        dict(row, strategy="keltner_holygrail_30m")
        for row in strategies["keltner_holygrail_30m"]
        if row["regime"] == "PANIC_DISPERSION"
    ]
    break_imp = improved_active(
        ledger,
        regmap,
        bars,
        "break_and_continue",
        "TREND_DISPERSED",
        6,
        0.75,
        "break_and_continue_td_v2",
    )
    rider_imp = improved_active(
        ledger,
        regmap,
        bars,
        "trend_rider",
        "TREND_COHERENT",
        12,
        0.50,
        "trend_rider_coherent_v2",
    )
    squeeze = [
        dict(row, strategy="squeeze_native_30m")
        for row in strategies["squeeze_native_30m"]
        if row["regime"] == "PANIC_DISPERSION"
    ]

    hg_train = np.array(
        [float(row["net_bps"]) for row in hg if int(row["signal_ts"]) <= cutoff],
        dtype=float,
    )
    rider_train = np.array(
        [float(row["net_bps"]) for row in rider_imp if int(row["signal_ts"]) <= cutoff],
        dtype=float,
    )
    rider_weight = float(
        min(1.0, hg_train.std(ddof=1) / max(rider_train.std(ddof=1), 1e-9))
    )
    core_equal = hg + rider_imp
    core_risk_scaled = hg + scaled(rider_imp, rider_weight)

    candidates = {
        "keltner_holygrail_panic": split(hg, cutoff),
        "trend_rider_coherent_improved": split(rider_imp, cutoff),
        "break_trend_dispered_improved": split(break_imp, cutoff),
        "squeeze_panic": split(squeeze, cutoff),
    }
    portfolios = {
        "core_equal_hg_plus_rider": split(core_equal, cutoff),
        "core_train_vol_scaled": split(core_risk_scaled, cutoff),
    }
    for name, rows in (
        ("core_equal_hg_plus_rider", core_equal),
        ("core_train_vol_scaled", core_risk_scaled),
    ):
        freq = trade_frequency(rows)
        portfolios[name]["T_per_day"] = freq
        portfolios[name]["edge_density_bps_per_day"] = freq * float(
            portfolios[name]["full"]["Exp_bps_T"]
        )

    decisions = {
        "keltner_holygrail_panic": "KEEP_ALPHA_SLEEVE_NOT_LIVE_LOW_FREQUENCY_FRESH_FORWARD_REQUIRED",
        "trend_rider_coherent_improved": "KEEP_SECOND_CORE_SLEEVE_NOT_LIVE_CONCENTRATION_AND_STREAK_REMAIN",
        "break_trend_dispered_improved": "WATCH_ONLY_NOT_CORE_HOLDOUT_SINGLE_WIN_DOMINATED",
        "squeeze_panic": "WATCH_ONLY_NOT_CORE_EDGE_TOO_THIN_AND_CONCENTRATED",
        "crabel_orb": "FORWARD_WATCH_ONLY_REGIME_INSTABILITY",
        "turtle_exact": "NEXT_REBUILD_QUEUE",
        "microstructure": "QUEUE_AFTER_PASSIVE_EXECUTION_MODEL",
        "mean_reversion": "EMPTY_SLEEVE_NEW_ARCHITECTURE_REQUIRED",
    }

    out = {
        "schema": "zel.economic_trading_program.priority_survivor.v1",
        "state": "ECONOMIC_CORE_CANDIDATE_BUILT_NOT_PRODUCTION_AUTHORIZED",
        "objective": "build a profitable economic trading program, not maximize strategy count",
        "cutoff_ts": cutoff,
        "rules_frozen": {
            "break": "TREND_DISPERSED; full stale scratch at 6 bars when MFE<0.75R",
            "trend_rider": "TREND_COHERENT; full stale scratch at 12 bars when MFE<0.50R",
            "keltner_holygrail": "existing frozen PANIC_DISPERSION fee-BE/RR survivor unchanged",
        },
        "train_only_risk_scaling": {
            "method": "scale Trend Rider by train-only per-trade standard-deviation ratio versus Keltner/Holy-Grail",
            "trend_rider_weight": rider_weight,
        },
        "candidates": candidates,
        "portfolios": portfolios,
        "decisions": decisions,
        "economic_acceptance": {
            "required_before_live": [
                "fresh forward performance with frozen rules",
                "rolling walk-forward repeated positive economics",
                "monthly concentration reduced",
                "portfolio drawdown and loss-run limits satisfied",
                "realistic execution cost authority preserved",
            ],
            "live_trade_authority": "BLOCKED",
            "order_authority": "BLOCKED",
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "ECONOMIC_CORE="
        + json.dumps(
            {
                "trend_rider_weight": rider_weight,
                "equal": portfolios["core_equal_hg_plus_rider"]["full"],
                "scaled": portfolios["core_train_vol_scaled"]["full"],
                "scaled_hold": portfolios["core_train_vol_scaled"]["holdout40_time"],
                "T_per_day": portfolios["core_train_vol_scaled"]["T_per_day"],
                "edge_density": portfolios["core_train_vol_scaled"][
                    "edge_density_bps_per_day"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
