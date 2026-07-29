from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "supertrend_pullback"
VERSION = "R7A4D_STRATEGY11_SUPERTREND_SEED_REPAIR_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def corrected_supertrend(df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(length, min_periods=length).mean()
    hl2 = (high + low) / 2.0
    upperband = hl2 + multiplier * atr
    lowerband = hl2 - multiplier * atr
    final_upperband = pd.Series(index=df.index, dtype="float64")
    final_lowerband = pd.Series(index=df.index, dtype="float64")
    direction = pd.Series(index=df.index, dtype="float64")
    st = pd.Series(index=df.index, dtype="float64")

    valid_positions = [position for position, value in enumerate(atr.notna().tolist()) if value]
    if not valid_positions:
        return pd.DataFrame({"supertrend": st, "direction": direction, "atr": atr})
    start = valid_positions[0]
    final_upperband.iloc[start] = upperband.iloc[start]
    final_lowerband.iloc[start] = lowerband.iloc[start]
    direction.iloc[start] = 1.0
    st.iloc[start] = final_lowerband.iloc[start]

    for i in range(start + 1, len(df)):
        upper = upperband.iloc[i]
        lower = lowerband.iloc[i]
        prior_upper = final_upperband.iloc[i - 1]
        prior_lower = final_lowerband.iloc[i - 1]
        if pd.isna(upper) or pd.isna(lower) or pd.isna(prior_upper) or pd.isna(prior_lower):
            continue
        final_upperband.iloc[i] = upper if (upper < prior_upper or close.iloc[i - 1] > prior_upper) else prior_upper
        final_lowerband.iloc[i] = lower if (lower > prior_lower or close.iloc[i - 1] < prior_lower) else prior_lower
        if st.iloc[i - 1] == prior_upper:
            if close.iloc[i] <= final_upperband.iloc[i]:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1.0
            else:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1.0
        else:
            if close.iloc[i] >= final_lowerband.iloc[i]:
                st.iloc[i] = final_lowerband.iloc[i]
                direction.iloc[i] = 1.0
            else:
                st.iloc[i] = final_upperband.iloc[i]
                direction.iloc[i] = -1.0
    return pd.DataFrame({"supertrend": st, "direction": direction, "atr": atr})


def reason_trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    calls = 0
    for window_id in repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                result = exact._call_strategy(
                    strategy,
                    history,
                    {
                        "position_side": "",
                        "position_qty": 0.0,
                        "avg_entry": 0.0,
                        "add_count": 0,
                        "last_add_price": 0.0,
                    },
                )
                calls += 1
                reasons[str(result.get("why") or result.get("reason") or "UNSPECIFIED")] += 1
                actions[str(result.get("action") or "hold").lower()] += 1
    return {
        "call_count": calls,
        "reason_counts": dict(reasons.most_common()),
        "action_counts": dict(sorted(actions.items())),
        "indicator_nan_count": reasons.get("st_pullback_indicator_nan", 0),
    }


def comparison(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    candidate_loss = candidate.get("loss_metrics") or {}
    candidate_stress = (candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}
    checks = {
        "trades_recovered": int(candidate.get("trade_count") or 0) > int(control.get("trade_count") or 0),
        "net_positive": metric(candidate.get("net_return_pct_sum")) > 0.0,
        "pf_above_one": metric(candidate.get("net_profit_factor")) > 1.0,
        "minimum_trades": int(candidate.get("trade_count") or 0) >= 5,
        "positive_window_breadth": metric(candidate.get("positive_fresh_windows_pct")) >= 70.0,
        "worst_loss_l090": metric(candidate_loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.90,
        "stress_worst_l095": metric(candidate_stress.get("normal_worst_net_loss_R"), -math.inf) >= -0.95,
        "parity_pass": candidate.get("parity", {}).get("state") == "PASS",
        "duplicate_zero": int(candidate.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
    }
    return {
        "state": "PASS_DIAGNOSTIC_REPAIR" if all(checks.values()) else "PARTIAL_REPAIR_ONLY",
        "checks": checks,
        "trade_delta": int(candidate.get("trade_count") or 0) - int(control.get("trade_count") or 0),
        "net_delta_pct_points": metric(candidate.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "ai_review_state": "WAIT_GROQ_QUOTA",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    baseline_summary = json.loads(prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID).read_text(encoding="utf-8"))
    source_config = baseline_summary["candidate"]
    gate = exact._gate_from(source_config)
    if gate.required or gate.forbidden:
        raise RuntimeError("EXPECTED_BASE_GATE")
    exit_spec = exact._exit_from(source_config)
    surgery = p.surgery_from(baseline_summary.get("surgery"))
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(args.root.resolve())
    strategy_source_sha = str(registry[STRATEGY_ID]["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(args.root.resolve(), STRATEGY_ID, registry[STRATEGY_ID])
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    normal_cap = float(policy["loss_ladder"][0]["normal_worst_net_loss_R_min"])
    stress_cap = float(policy["loss_ladder"][0]["stress_worst_net_loss_R_min"])

    before_trace = reason_trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)
    common = {
        "strategy": strategy,
        "gate": gate,
        "surgery": surgery,
        "symbols": symbols,
        "frames": frames,
        "features": features,
        "funding": funding,
        "quantiles": quantiles,
        "manifest": manifest,
        "market_shas": market_shas,
        "strategy_source_sha": strategy_source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "normal_cap_r": normal_cap,
        "stress_cap_r": stress_cap,
        "out": args.out.resolve() / STRATEGY_ID,
    }
    control = replay.evaluate(
        variant_id="CONTROL_BROKEN_SUPERTREND_SEED",
        config={**source_config, "candidate_id": "CONTROL_BROKEN_SUPERTREND_SEED", "axis": "CONTROL"},
        exit_spec=exit_spec,
        **common,
    )

    original_supertrend = strategy.__globals__.get("_supertrend")
    if not callable(original_supertrend):
        raise RuntimeError("SUPERTREND_GLOBAL_NOT_CALLABLE")
    original_sha = stable_sha({"module": original_supertrend.__module__, "name": original_supertrend.__name__})
    strategy.__globals__["_supertrend"] = corrected_supertrend
    after_trace = reason_trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)
    candidate_config = {
        **source_config,
        "candidate_id": "FIX_FIRST_VALID_ATR_SEED",
        "axis": "INDICATOR_INITIALIZATION",
        "repair": {
            "function": "_supertrend",
            "change": "INITIALIZE_AT_FIRST_VALID_ATR_POSITION",
            "change_budget": 1,
            "original_function_identity_sha": original_sha,
        },
    }
    candidate = replay.evaluate(
        variant_id="FIX_FIRST_VALID_ATR_SEED",
        config=candidate_config,
        exit_spec=exit_spec,
        **common,
    )
    relation = comparison(candidate, control)
    result = {
        "schema_version": "strategy11.supertrend_seed_repair.v1",
        "version": VERSION,
        "state": "PASS_SUPERTREND_SEED_DIAGNOSTIC_COMPLETE",
        "strategy_id": STRATEGY_ID,
        "strategy_source_sha": strategy_source_sha,
        "before_trace": before_trace,
        "after_trace": after_trace,
        "repair": candidate_config["repair"],
        "control": {
            "trade_count": control.get("trade_count"),
            "net_pct": control.get("net_return_pct_sum"),
            "summary_sha": stable_sha(control),
        },
        "candidate": {
            "trade_count": candidate.get("trade_count"),
            "win_rate_pct": candidate.get("win_rate_pct"),
            "net_pct": candidate.get("net_return_pct_sum"),
            "profit_factor": candidate.get("net_profit_factor"),
            "payoff": candidate.get("payoff_ratio"),
            "max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "avg_loss_r": (candidate.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (candidate.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "stress_worst_loss_r": ((candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "relation": relation,
            "summary_sha": stable_sha(candidate),
        },
        "canonical_source_modified": False,
        "registry_modified": False,
        "next": "CANONICAL_MINIMAL_PATCH_REVIEW" if relation["state"] == "PASS_DIAGNOSTIC_REPAIR" else "TRACE_NEXT_INTERNAL_TRIGGER_AFTER_NAN_REPAIR",
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    atomic_json(args.out.resolve() / "final.json", result)
    print(result["state"], before_trace["indicator_nan_count"], after_trace["indicator_nan_count"], candidate.get("trade_count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
