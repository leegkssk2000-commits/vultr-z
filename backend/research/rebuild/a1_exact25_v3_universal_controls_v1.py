from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
OWNERSHIP = ROOT / "backend/research/rebuild/a1_exact25_mechanism_ownership_v1.json"
POLICY = ROOT / "backend/research/zel_survivor_tiering_policy_v3.json"
AUTH = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "protected_mutations": 0, "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def paired_stats(candidate: list[float], control: list[float], seed: int, *, bootstrap_n: int = 10000) -> tuple[float, float]:
    if len(candidate) != len(control) or not candidate:
        raise RuntimeError("PAIRED_CONTROL_BUDGET_INVALID")
    diffs = [a - b for a, b in zip(candidate, control)]
    n = len(diffs)
    rng = random.Random(seed)
    obs = sum(diffs) / n
    ge = 1
    for _ in range(bootstrap_n):
        perm = sum(x if rng.random() < 0.5 else -x for x in diffs) / n
        if perm >= obs:
            ge += 1
    p = ge / (bootstrap_n + 1)
    boots = []
    for _ in range(bootstrap_n):
        boots.append(sum(diffs[rng.randrange(n)] for __ in range(n)))
    boots.sort()
    ci = boots[max(0, int(0.05 * bootstrap_n) - 1)]
    return ci, p


def _bar_maps(symbols: list[str], interval: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, int]]]:
    bars_by: dict[str, list[dict[str, Any]]] = {}
    maps: dict[str, dict[int, int]] = {}
    for symbol in symbols:
        bars = ev.fetch_bars(symbol, interval, 1000)
        bars_by[symbol] = bars
        maps[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    return bars_by, maps


def _random_entry_control(receipt: Mapping[str, Any], trades: list[dict[str, Any]], seed: int) -> list[float]:
    interval = str((receipt.get("source") or {}).get("interval") or "")
    if not interval:
        raise RuntimeError("INTERVAL_MISSING")
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by, maps = _bar_maps(symbols, interval)
    boundary_ms = int(datetime.fromisoformat(str(receipt["boundary_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)
    latest_exit = max(int(x["exit_ts"]) for x in trades)
    rng = random.Random(seed)
    used: set[tuple[str, int]] = set()
    out: list[float] = []
    for trade in trades:
        symbol = str(trade["symbol"]); bars = bars_by[symbol]; mp = maps[symbol]
        if int(trade["entry_ts"]) not in mp or int(trade["exit_ts"]) not in mp:
            raise RuntimeError(f"RANDOM_CONTROL_TRADE_BAR_MISSING:{symbol}")
        duration = max(1, mp[int(trade["exit_ts"])] - mp[int(trade["entry_ts"])])
        pool = [
            j for j, bar in enumerate(bars)
            if boundary_ms <= int(bar["ts_ms"]) <= latest_exit
            and j + 1 + duration < len(bars)
            and (symbol, int(bar["ts_ms"])) not in used
        ]
        if not pool:
            raise RuntimeError(f"RANDOM_ENTRY_POOL_EXHAUSTED:{symbol}")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        entry = float(bars[j + 1]["open"]); exit_px = float(bars[j + 1 + duration]["close"])
        side = 1 if str(trade["side"]) == "long" else -1
        net_bps = side * (exit_px / entry - 1.0) * 10000.0 - float(trade["realized_cost_bps"])
        out.append(net_bps / 100.0)
    return out


def _timestamp_permutation_control(receipt: Mapping[str, Any], trades: list[dict[str, Any]], seed: int) -> list[float]:
    """Break clock/session ownership by permuting observed start times within symbol.

    Side, duration and realized cost stay attached to the candidate trade. The
    replacement timestamp comes only from another observed trade start, never
    from outcome labels or future selection.
    """
    interval = str((receipt.get("source") or {}).get("interval") or "")
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by, maps = _bar_maps(symbols, interval)
    rng = random.Random(seed)
    starts_by_symbol: dict[str, list[int]] = {}
    for symbol in symbols:
        starts_by_symbol[symbol] = [int(x["entry_ts"]) for x in trades if str(x["symbol"]) == symbol]
        rng.shuffle(starts_by_symbol[symbol])
    cursor = {symbol: 0 for symbol in symbols}
    out: list[float] = []
    for trade in trades:
        symbol = str(trade["symbol"]); bars = bars_by[symbol]; mp = maps[symbol]
        if int(trade["entry_ts"]) not in mp or int(trade["exit_ts"]) not in mp:
            raise RuntimeError(f"TIMESTAMP_CONTROL_TRADE_BAR_MISSING:{symbol}")
        duration = max(1, mp[int(trade["exit_ts"])] - mp[int(trade["entry_ts"])])
        starts = starts_by_symbol[symbol]
        if not starts:
            raise RuntimeError("TIMESTAMP_CONTROL_EMPTY_SYMBOL_POOL")
        replacement = starts[cursor[symbol] % len(starts)]; cursor[symbol] += 1
        if replacement not in mp:
            raise RuntimeError(f"TIMESTAMP_CONTROL_REPLACEMENT_MISSING:{symbol}")
        entry_i = mp[replacement]
        if entry_i + duration >= len(bars):
            raise RuntimeError(f"TIMESTAMP_CONTROL_FUTURE_BAR_MISSING:{symbol}")
        entry = float(bars[entry_i]["open"]); exit_px = float(bars[entry_i + duration]["close"])
        side = 1 if str(trade["side"]) == "long" else -1
        out.append((side * (exit_px / entry - 1.0) * 10000.0 - float(trade["realized_cost_bps"])) / 100.0)
    return out


def evaluate(receipt: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(receipt.get("strategy_id") or "")
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    source_quality = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    blockers: list[str] = []
    if not candidate_id:
        blockers.append("CANDIDATE_ID_MISSING")
    if source_quality.get("state") != "PASS":
        blockers.append(f"SOURCE_QUALITY_NOT_PASS:{source_quality.get('state')}")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0:
        blockers.append("CANDIDATE_INTEGRITY_NOT_PASS")
    if len(trades) < 25:
        blockers.append(f"HARD_CONTROL_SAMPLE_LT25:{len(trades)}")

    ownership = read(OWNERSHIP); policy = read(POLICY)
    own = (ownership.get("strategies") or {}).get(candidate_id) or {}
    features = {str(x) for x in own.get("mechanism_features") or []}
    conditional_cfg = (((policy.get("a1_causal_alpha_gate") or {}).get("conditional_hard_controls") or {}).get("timestamp_shuffle") or {})
    time_features = {str(x) for x in conditional_cfg.get("required_if_any_feature_owner") or []}
    timestamp_hard = bool(features & time_features)

    controls: dict[str, Any] = {
        "one_bar_delay": {"state": "NOT_RUN", "reason": "A2_EXECUTION_STRESS_OWNER"},
        "indicator_removal": {"state": "NOT_RUN", "reason": "MECHANISM_SPECIFIC_DIAGNOSTIC_NOT_UNIVERSAL"},
    }
    if not blockers:
        candidate = [float(x["net_bps"]) / 100.0 for x in trades]
        direction = [(-float(x["gross_bps"]) - float(x["realized_cost_bps"])) / 100.0 for x in trades]
        random_seed = int(stable_sha({"candidate": candidate_id, "receipt": receipt.get("receipt_sha256"), "control": "same_count_random_entry"})[:16], 16)
        random_vals = _random_entry_control(receipt, trades, random_seed)
        for name, vals in (("same_count_random_entry", random_vals), ("direction_inversion", direction)):
            seed = int(stable_sha({"candidate": candidate_id, "receipt": receipt.get("receipt_sha256"), "control": name, "stats": 1})[:16], 16)
            ci, p = paired_stats(candidate, vals, seed)
            controls[name] = {
                "state": "PASS" if p <= 0.05 and ci > 0.0 else "FAIL",
                "p_value": p, "candidate_minus_control_ci_low_R": ci,
                "candidate_net_R": sum(candidate), "control_net_R": sum(vals),
                "candidate_minus_control_net_R": sum(candidate) - sum(vals),
                "equal_trade_budget": True, "identical_window_lineage": True,
                "identical_cost_lineage": True, "trade_count": len(candidate),
            }
        if timestamp_hard:
            seed = int(stable_sha({"candidate": candidate_id, "receipt": receipt.get("receipt_sha256"), "control": "timestamp_shuffle"})[:16], 16)
            vals = _timestamp_permutation_control(receipt, trades, seed)
            ci, p = paired_stats(candidate, vals, seed ^ 0xA3A3)
            controls["timestamp_shuffle"] = {
                "state": "PASS" if p <= 0.05 and ci > 0.0 else "FAIL",
                "p_value": p, "candidate_minus_control_ci_low_R": ci,
                "candidate_net_R": sum(candidate), "control_net_R": sum(vals),
                "candidate_minus_control_net_R": sum(candidate) - sum(vals),
                "equal_trade_budget": True, "identical_window_lineage": True,
                "identical_cost_lineage": True, "trade_count": len(candidate),
            }
        else:
            controls["timestamp_shuffle"] = {"state": "NOT_APPLICABLE", "reason": "MECHANISM_DOES_NOT_OWN_TIME_FEATURE"}

    hard_names = ["same_count_random_entry", "direction_inversion"] + (["timestamp_shuffle"] if timestamp_hard else [])
    hard_states = {name: str((controls.get(name) or {}).get("state") or "NOT_RUN") for name in hard_names}
    hard_pass = not blockers and all(state == "PASS" for state in hard_states.values())
    result = {
        "schema_version": "zel.a1_exact25.v3_universal_controls.v1",
        "state": "PASS_V3_UNIVERSAL_HARD_CONTROLS" if hard_pass else ("WAIT_V3_CONTROL_SAMPLE" if blockers and all(x.startswith("HARD_CONTROL_SAMPLE_LT25") for x in blockers) else "HOLD_V3_UNIVERSAL_HARD_CONTROLS"),
        "candidate_id": candidate_id, "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "completed_trades": len(trades), "mechanism_features": sorted(features),
        "timestamp_shuffle_hard": timestamp_hard, "hard_control_names": hard_names,
        "hard_control_states": hard_states, "negative_controls": controls, "blockers": blockers,
        "diagnostics_do_not_grant_or_deny_a1_by_themselves": True,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k:v for k,v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    ownership = read(OWNERSHIP)
    assert len(ownership.get("strategies") or {}) == 25
    assert "session" in set(ownership["strategies"]["session_bias"]["mechanism_features"])
    print("PASS_A1_EXACT25_V3_UNIVERSAL_CONTROLS_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--receipt", type=Path); ap.add_argument("--output", type=Path, default=Path("out/a1_v3_universal_controls_v1.json")); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test: return self_test()
    if not args.receipt: raise SystemExit("--receipt required")
    result = evaluate(read(args.receipt)); args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"completed_trades":result["completed_trades"],"hard_control_states":result["hard_control_states"],"blockers":result["blockers"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
