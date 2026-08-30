#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as transplant
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_keltner_reclaim_ownership_challenger_v1.json"
BREAK9 = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_break_keltner_reclaim_ownership_challenger_latest.json"
SCHEMA = "zel.a1.break.keltner_reclaim_ownership_challenger.receipt.v1"
INTERVAL_MS = 14_400_000

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def ownership_state_from_values(
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
        above = float(close) > float(e20)
        prev_below = False
        if i > 0 and ema20[i - 1] is not None:
            prev_below = float(closes[i - 1]) <= float(ema20[i - 1])
        reclaim = trend and above and prev_below
        if not trend or not above:
            armed = False
        if reclaim:
            armed = True
        out.append(armed)
    return out


def state_for_bars(bars: list[dict[str, float]], features: Mapping[str, Sequence[float | None]]) -> list[bool]:
    return ownership_state_from_values(
        [float(x["close"]) for x in bars],
        list(features["ema20"]),
        list(features["ema50"]),
    )


def validate_parent(rows: list[dict[str, Any]], source: Mapping[str, Any], expected_t: int) -> None:
    transplant.validate_trade_rows(rows, "break_and_continue_main", expected_t)
    source_rows = [dict(x) for x in source.get("trades") or [] if isinstance(x, Mapping)]
    source_keys = {transplant.trade_key(x) for x in source_rows}
    if not {transplant.trade_key(x) for x in rows}.issubset(source_keys):
        raise RuntimeError("BREAK9_NOT_SUBSET_OF_IMMUTABLE_SOURCE")


def economic_gate(cell: Mapping[str, Any], gate: Mapping[str, Any]) -> tuple[bool, dict[str, bool], list[str]]:
    m = cell["metrics"]
    base = cell["parent_metrics"]
    pf = m.get("profit_factor")
    payoff = m.get("payoff")
    improvements = {
        "net_pnl_bps": float(m.get("net_pnl_bps") or 0.0) > float(base.get("net_pnl_bps") or 0.0),
        "net_expectancy_bps": m.get("net_expectancy_bps") is not None and float(m["net_expectancy_bps"]) > float(base.get("net_expectancy_bps") or 0.0),
        "profit_factor": pf is not None and base.get("profit_factor") is not None and float(pf) > float(base["profit_factor"]),
        "drawdown_bps": float(m.get("drawdown_bps") or 0.0) < float(base.get("drawdown_bps") or 0.0),
    }
    checks = {
        "sample_minimum": int(m.get("trades") or 0) >= int(gate["minimum_closed_T"]),
        "retention_minimum": float(cell.get("retention_pct") or 0.0) >= float(gate["minimum_retention_pct"]),
        "net_pnl_positive": float(m.get("net_pnl_bps") or 0.0) > float(gate["minimum_net_pnl_bps_exclusive"]),
        "net_expectancy_positive": m.get("net_expectancy_bps") is not None and float(m["net_expectancy_bps"]) > float(gate["minimum_net_expectancy_bps_exclusive"]),
        "profit_factor_minimum": pf is not None and float(pf) >= float(gate["minimum_profit_factor"]),
        "payoff_minimum": payoff is not None and float(payoff) >= float(gate["minimum_payoff_ratio"]),
        "win_rate_harm_maximum": float(cell.get("win_rate_harm_pp") or 0.0) <= float(gate["maximum_win_rate_harm_pp"]),
        "economic_improvement": any(improvements.values()),
    }
    failed = [k for k, value in checks.items() if not value]
    return not failed, checks, failed


def run(immutable_break_source: Path, output: Path, *, bars_override: Mapping[str, list[dict[str, float]]] | None = None) -> dict[str, Any]:
    contract = read(CONTRACT)
    if contract.get("schema_version") != "zel.a1.break.keltner_reclaim_ownership_challenger.contract.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_DEVELOPMENT_REPLAY_BEFORE_RESULT":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    imm = contract.get("immutability") or {}
    expected_false = ("new_trade_admission", "cost_rededuction", "future_bar_access", "threshold_sweep", "post_result_retune", "historical_backfill_to_g4")
    if any(bool(imm.get(k)) for k in expected_false):
        raise RuntimeError("IMMUTABILITY_FALSE_RULE_DRIFT")
    expected_true = ("parent_symbol_inherited", "parent_side_inherited", "parent_rr_unchanged", "parent_tp_unchanged", "parent_sl_unchanged", "parent_timeout_unchanged", "parent_exit_unchanged", "parent_realized_cost_unchanged")
    if any(not bool(imm.get(k)) for k in expected_true):
        raise RuntimeError("IMMUTABILITY_TRUE_RULE_DRIFT")

    arch = contract.get("architecture") or {}
    machine = arch.get("state_machine") or {}
    if bool(machine.get("numeric_threshold_added")) or bool(machine.get("ttl_or_hold_window_added")):
        raise RuntimeError("OUTCOME_FITTED_COMPLEXITY_FORBIDDEN")
    if str(arch.get("changed_axis")) != "ENTRY_ADMISSION_ONLY" or str(arch.get("bar_interval")) != "4h":
        raise RuntimeError("ARCHITECTURE_AXIS_DRIFT")

    parent = [dict(x) for x in read(BREAK9).get("trades") or [] if isinstance(x, Mapping)]
    immutable = read(immutable_break_source)
    expected_t = int((contract.get("parent_authority") or {}).get("frozen_parent_T") or 0)
    validate_parent(parent, immutable, expected_t)

    min_signal = min(int(x["signal_ts"]) for x in parent)
    max_signal = max(int(x["signal_ts"]) for x in parent)
    symbols = sorted({str(x["symbol"]) for x in parent})
    bars_by_symbol = dict(bars_override or {})
    if not bars_by_symbol:
        bars_by_symbol = {symbol: child_eval._bars(symbol, "4h", min_signal, max_signal + INTERVAL_MS) for symbol in symbols}
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
        features, _ = child_eval._features(bars, feature_spec)
        states[symbol] = state_for_bars(bars, features)
        source_summary[symbol] = {
            "closed_4h_bars": len(bars),
            "first_open_ts": ts[0],
            "last_open_ts": ts[-1],
            "state_true_bars": sum(1 for x in states[symbol] if x),
            "bars_sha256": stable(bars),
        }

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for row in parent:
        symbol = str(row["symbol"])
        bars = bars_by_symbol[symbol]
        idx = transplant.available_bar_index(bars, int(row["signal_ts"]))
        ok = bool(idx is not None and idx >= 50 and states[symbol][idx])
        refs.append({
            "trade_key": list(transplant.trade_key(row)),
            "feature_bar_open_ts": None if idx is None else int(bars[idx]["ts"]),
            "ownership_armed": ok,
        })
        (accepted if ok else rejected).append(dict(row))

    parent_keys = {transplant.trade_key(x) for x in parent}
    accepted_keys = [transplant.trade_key(x) for x in accepted]
    if len(accepted_keys) != len(set(accepted_keys)) or not set(accepted_keys).issubset(parent_keys):
        raise RuntimeError("ACCEPTED_PARENT_IDENTITY_INVALID")
    if any(transplant.compact_trade(x) != transplant.compact_trade(next(y for y in parent if transplant.trade_key(y) == transplant.trade_key(x))) for x in accepted):
        raise RuntimeError("PARENT_PAYLOAD_MUTATION_DETECTED")

    base_m = transplant.metric_plus(parent)
    m = transplant.metric_plus(accepted)
    retention = len(accepted) / len(parent) * 100.0
    rejected_wins = sum(1 for x in rejected if float(x["net_bps"]) > 0)
    rejected_losses = sum(1 for x in rejected if float(x["net_bps"]) < 0)
    wr_harm = 0.0 if m.get("win_rate") is None else max(0.0, (float(base_m["win_rate"]) - float(m["win_rate"])) * 100.0)
    cell: dict[str, Any] = {
        "challenger_id": arch.get("challenger_id"),
        "parent_lane_id": "break_and_continue_main",
        "parent_strategy_id": "break_and_continue",
        "parent_metrics": base_m,
        "metrics": m,
        "retention_pct": retention,
        "rejected_T": len(rejected),
        "rejected_wins": rejected_wins,
        "rejected_losses": rejected_losses,
        "rejection_loss_precision": (rejected_losses / len(rejected)) if rejected else None,
        "win_rate_harm_pp": wr_harm,
        "delta_vs_parent": {k: transplant.delta(m, base_m, k) for k in ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff", "win_rate", "drawdown_bps")},
        "accepted_trade_keys": [list(x) for x in accepted_keys],
        "rejected_trade_keys": [list(transplant.trade_key(x)) for x in rejected],
        "feature_state_refs_sha256": stable(refs),
        "native_parent_payload_preserved": True,
        "new_trade_admission": False,
        "parent_exit_mutated": False,
        "cost_rededucted": False,
    }
    eligible, checks, failed = economic_gate(cell, contract["development_gate"])
    cell["development_gate_pass"] = eligible
    cell["development_checks"] = checks
    cell["failed_development_checks"] = failed

    state = "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER" if eligible else "FALSIFIED_RECLAIM_OWNERSHIP_REDESIGN_V1"
    deterministic = {
        "contract_sha256": file_sha(CONTRACT),
        "parent_sha256": file_sha(BREAK9),
        "immutable_source_receipt_sha256": immutable.get("receipt_sha256"),
        "source_summary": source_summary,
        "cell": cell,
    }
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_master_sha": git_head(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": file_sha(Path(__file__).resolve()),
        "parent_path": str(BREAK9.relative_to(ROOT)),
        "parent_sha256": file_sha(BREAK9),
        "selection_aware_seed_credit_to_g4": 0,
        "development_T_credit_to_g4": 0,
        "new_g4_activation_created": False,
        "new_g4_cohort_created": False,
        "fresh_g4_T": 0,
        "source_summary": source_summary,
        "cell": cell,
        "next": "FREEZE_NEW_G4_CHALLENGER_WITH_FRESH_BOUNDARY" if eligible else "STOP_RECLAIM_OWNERSHIP_V1_AND_REQUIRE_NEW_ARCHITECTURE_SEED",
        "deterministic_result_sha256": stable(deterministic),
        **AUTH,
    }
    receipt_payload = dict(result)
    receipt_payload.pop("observed_at_utc", None)
    receipt_payload.pop("source_master_sha", None)
    result["receipt_sha256"] = stable(receipt_payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    closes = [9.0, 9.5, 10.2, 10.4, 10.3, 9.9, 10.4]
    ema20 = [10.0, 10.0, 10.0, 10.1, 10.2, 10.1, 10.1]
    ema50 = [9.0] * len(closes)
    state = ownership_state_from_values(closes, ema20, ema50)
    assert state == [False, False, True, True, True, False, True], state
    ema50_break = [9.0, 9.0, 9.0, 9.0, 10.5, 9.0, 9.0]
    state2 = ownership_state_from_values(closes, ema20, ema50_break)
    assert state2[2] is True and state2[4] is False and state2[5] is False and state2[6] is True
    print("PASS_A1_BREAK_KELTNER_RECLAIM_OWNERSHIP_STATE_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--immutable-break-source", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_keltner_reclaim_ownership_challenger_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.immutable_break_source is None:
        raise SystemExit("--immutable-break-source required")
    result = run(args.immutable_break_source, args.out)
    print(json.dumps({
        "state": result["state"],
        "T": result["cell"]["metrics"]["trades"],
        "wins": result["cell"]["metrics"]["wins"],
        "losses": result["cell"]["metrics"]["losses"],
        "retention_pct": result["cell"]["retention_pct"],
        "net_pnl_bps": result["cell"]["metrics"]["net_pnl_bps"],
        "net_expectancy_bps": result["cell"]["metrics"]["net_expectancy_bps"],
        "profit_factor": result["cell"]["metrics"]["profit_factor"],
        "failed_checks": result["cell"]["failed_development_checks"],
        "deterministic_result_sha256": result["deterministic_result_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
