#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_break_keltner_reclaim_ownership_challenger_v1 as base

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_keltner_reclaim_latched_owner_v2.json"
BREAK9 = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_break_keltner_reclaim_latched_owner_v2_latest.json"
SCHEMA = "zel.a1.break.keltner_reclaim_latched_owner.receipt.v2"
INTERVAL_MS = 14_400_000


def latched_state_from_values(
    closes: Sequence[float], ema20: Sequence[float | None], ema50: Sequence[float | None]
) -> list[bool]:
    if not (len(closes) == len(ema20) == len(ema50)):
        raise RuntimeError("STATE_ARRAY_LENGTH_DRIFT")
    out: list[bool] = []
    armed = False
    for i, close in enumerate(closes):
        e20 = ema20[i]
        e50 = ema50[i]
        if e20 is None or e50 is None or not math.isfinite(float(e20)) or not math.isfinite(float(e50)):
            armed = False
            out.append(False)
            continue
        trend = float(e20) > float(e50)
        prev_below = False
        if i > 0 and ema20[i - 1] is not None:
            prev_below = float(closes[i - 1]) <= float(ema20[i - 1])
        reclaim = trend and float(close) > float(e20) and prev_below
        if not trend:
            armed = False
        if reclaim:
            armed = True
        out.append(armed)
    return out


def run(immutable_break_source: Path, output: Path, *, bars_override: Mapping[str, list[dict[str, float]]] | None = None) -> dict[str, Any]:
    contract = base.read(CONTRACT)
    if contract.get("schema_version") != "zel.a1.break.keltner_reclaim_latched_owner.contract.v2":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_DEVELOPMENT_REPLAY_BEFORE_RESULT":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    imm = contract.get("immutability") or {}
    if any(bool(imm.get(k)) for k in ("new_trade_admission", "cost_rededuction", "future_bar_access", "threshold_sweep", "post_result_retune", "historical_backfill_to_g4")):
        raise RuntimeError("IMMUTABILITY_FALSE_RULE_DRIFT")
    if not bool(imm.get("this_is_final_reclaim_persistence_variant")):
        raise RuntimeError("FINAL_VARIANT_LOCK_REQUIRED")

    arch = contract.get("architecture") or {}
    machine = arch.get("state_machine") or {}
    if bool(machine.get("numeric_threshold_added")) or bool(machine.get("ttl_or_hold_window_added")):
        raise RuntimeError("PARAMETER_SEARCH_FORBIDDEN")
    if str(arch.get("changed_axis")) != "ENTRY_ADMISSION_STATE_PERSISTENCE_ONLY":
        raise RuntimeError("ARCHITECTURE_AXIS_DRIFT")

    parent = [dict(x) for x in base.read(BREAK9).get("trades") or [] if isinstance(x, Mapping)]
    immutable = base.read(immutable_break_source)
    expected_t = int((contract.get("parent_authority") or {}).get("frozen_parent_T") or 0)
    base.validate_parent(parent, immutable, expected_t)

    min_signal = min(int(x["signal_ts"]) for x in parent)
    max_signal = max(int(x["signal_ts"]) for x in parent)
    symbols = sorted({str(x["symbol"]) for x in parent})
    bars_by_symbol = dict(bars_override or {})
    if not bars_by_symbol:
        bars_by_symbol = {symbol: base.child_eval._bars(symbol, "4h", min_signal, max_signal + INTERVAL_MS) for symbol in symbols}
    if set(bars_by_symbol) != set(symbols):
        raise RuntimeError("BAR_SYMBOL_SET_DRIFT")

    feature_spec = {"features": list(arch.get("features") or [])}
    states: dict[str, list[bool]] = {}
    source_summary: dict[str, Any] = {}
    for symbol in symbols:
        bars = bars_by_symbol[symbol]
        if len(bars) < 60:
            raise RuntimeError(f"INSUFFICIENT_4H_HISTORY:{symbol}:{len(bars)}")
        ts = [int(x["ts"]) for x in bars]
        if ts != sorted(ts) or len(ts) != len(set(ts)):
            raise RuntimeError(f"BAR_ORDER_OR_DUPLICATE:{symbol}")
        features, _ = base.child_eval._features(bars, feature_spec)
        states[symbol] = latched_state_from_values(
            [float(x["close"]) for x in bars], list(features["ema20"]), list(features["ema50"])
        )
        source_summary[symbol] = {
            "closed_4h_bars": len(bars),
            "first_open_ts": ts[0],
            "last_open_ts": ts[-1],
            "state_true_bars": sum(1 for x in states[symbol] if x),
            "bars_sha256": base.stable(bars),
        }

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for row in parent:
        symbol = str(row["symbol"])
        bars = bars_by_symbol[symbol]
        idx = base.transplant.available_bar_index(bars, int(row["signal_ts"]))
        ok = bool(idx is not None and idx >= 50 and states[symbol][idx])
        refs.append({
            "trade_key": list(base.transplant.trade_key(row)),
            "feature_bar_open_ts": None if idx is None else int(bars[idx]["ts"]),
            "ownership_armed": ok,
        })
        (accepted if ok else rejected).append(dict(row))

    parent_keys = {base.transplant.trade_key(x) for x in parent}
    accepted_keys = [base.transplant.trade_key(x) for x in accepted]
    if len(accepted_keys) != len(set(accepted_keys)) or not set(accepted_keys).issubset(parent_keys):
        raise RuntimeError("ACCEPTED_PARENT_IDENTITY_INVALID")

    parent_metrics = base.transplant.metric_plus(parent)
    metrics = base.transplant.metric_plus(accepted)
    retention = len(accepted) / len(parent) * 100.0
    rejected_wins = sum(1 for x in rejected if float(x["net_bps"]) > 0)
    rejected_losses = sum(1 for x in rejected if float(x["net_bps"]) < 0)
    wr_harm = 0.0 if metrics.get("win_rate") is None else max(0.0, (float(parent_metrics["win_rate"]) - float(metrics["win_rate"])) * 100.0)
    cell: dict[str, Any] = {
        "challenger_id": arch.get("challenger_id"),
        "parent_lane_id": "break_and_continue_main",
        "parent_strategy_id": "break_and_continue",
        "parent_metrics": parent_metrics,
        "metrics": metrics,
        "retention_pct": retention,
        "rejected_T": len(rejected),
        "rejected_wins": rejected_wins,
        "rejected_losses": rejected_losses,
        "rejection_loss_precision": (rejected_losses / len(rejected)) if rejected else None,
        "win_rate_harm_pp": wr_harm,
        "delta_vs_parent": {k: base.transplant.delta(metrics, parent_metrics, k) for k in ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff", "win_rate", "drawdown_bps")},
        "accepted_trade_keys": [list(x) for x in accepted_keys],
        "rejected_trade_keys": [list(base.transplant.trade_key(x)) for x in rejected],
        "feature_state_refs_sha256": base.stable(refs),
        "native_parent_payload_preserved": True,
        "new_trade_admission": False,
        "parent_exit_mutated": False,
        "cost_rededucted": False,
    }
    eligible, checks, failed = base.economic_gate(cell, contract["development_gate"])
    cell["development_gate_pass"] = eligible
    cell["development_checks"] = checks
    cell["failed_development_checks"] = failed

    state = "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER" if eligible else "FALSIFIED_RECLAIM_FAMILY_EXHAUSTED_FOR_BREAK"
    deterministic = {
        "contract_sha256": base.file_sha(CONTRACT),
        "parent_sha256": base.file_sha(BREAK9),
        "immutable_source_receipt_sha256": immutable.get("receipt_sha256"),
        "source_summary": source_summary,
        "cell": cell,
    }
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_master_sha": base.git_head(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": base.file_sha(CONTRACT),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": base.file_sha(Path(__file__).resolve()),
        "prior_attempt_path": "backend/research/rebuild/a1_break_keltner_reclaim_ownership_challenger_latest.json",
        "prior_attempt_credit_to_g4_T": 0,
        "development_T_credit_to_g4": 0,
        "new_g4_activation_created": False,
        "new_g4_cohort_created": False,
        "fresh_g4_T": 0,
        "source_summary": source_summary,
        "cell": cell,
        "next": "FREEZE_NEW_G4_CHALLENGER_WITH_FRESH_BOUNDARY" if eligible else "STOP_RECLAIM_FAMILY_AND_REQUIRE_DIFFERENT_CAUSAL_ARCHITECTURE",
        "deterministic_result_sha256": base.stable(deterministic),
        **base.AUTH,
    }
    receipt = dict(result)
    receipt.pop("observed_at_utc", None)
    receipt.pop("source_master_sha", None)
    result["receipt_sha256"] = base.stable(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    closes = [9.0, 9.5, 10.2, 9.8, 9.7, 10.4, 10.2]
    ema20 = [10.0, 10.0, 10.0, 10.1, 10.2, 10.1, 10.2]
    ema50 = [9.0, 9.0, 9.0, 9.0, 10.3, 9.0, 9.0]
    state = latched_state_from_values(closes, ema20, ema50)
    assert state == [False, False, True, True, False, True, True], state
    print("PASS_A1_BREAK_KELTNER_RECLAIM_LATCHED_OWNER_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--immutable-break-source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_keltner_reclaim_latched_owner_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.immutable_break_source is None:
        raise SystemExit("--immutable-break-source required")
    result = run(args.immutable_break_source, args.out)
    m=result['cell']['metrics']
    print(json.dumps({
        "state": result["state"], "T": m["trades"], "wins": m["wins"], "losses": m["losses"],
        "retention_pct": result['cell']['retention_pct'], "net_pnl_bps": m["net_pnl_bps"],
        "net_expectancy_bps": m["net_expectancy_bps"], "profit_factor": m["profit_factor"],
        "failed_checks": result['cell']['failed_development_checks'], "deterministic_result_sha256": result['deterministic_result_sha256']
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
