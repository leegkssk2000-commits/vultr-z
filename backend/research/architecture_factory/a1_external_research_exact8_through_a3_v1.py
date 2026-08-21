from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import random
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory import a1_external_research_exact8_source_audit_v1 as source_audit
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.prep import a3_exact25_forward_durability_v3 as a3

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_spec_v1.json"
BOUNDARY_PATH = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_boundary_v1.json"
COST_AUTHORITY_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
A3_CONTEXT_PATH = ROOT / "backend/research/prep/a3_forward_context_ledger_v2.json"
DEFAULT_STATE_PATH = ROOT / "backend/research/prep/a1_external_research_exact8_forward_state_v1.json"

SYMBOLS = ("BTC-USDT", "ETH-USDT")
SOURCE_READY = (
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "fvg_revert",
    "range_fade",
    "session_bias",
)
CHILD_MODULES = {
    "anchor_vwap_trend": "backend.research.architecture_factory.a1_exact8_anchor_vwap_trend_adapter_v1",
    "bb_revert": "backend.research.architecture_factory.a1_exact8_bb_revert_adapter_v1",
    "break_and_continue": "backend.research.architecture_factory.a1_exact8_break_and_continue_adapter_v1",
    "fvg_revert": "backend.research.architecture_factory.a1_exact8_fvg_revert_adapter_v1",
    "range_fade": "backend.research.architecture_factory.a1_exact8_range_fade_adapter_v1",
    "session_bias": "backend.research.architecture_factory.a1_exact8_session_bias_adapter_v1",
}
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


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def metrics(values: Sequence[float]) -> dict[str, Any]:
    vals = [float(x) for x in values]
    gp = sum(x for x in vals if x > 0)
    gl = -sum(x for x in vals if x < 0)
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    equity = peak = dd = 0.0
    for x in vals:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "trades": len(vals),
        "net_bps": sum(vals),
        "expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff_ratio": (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else None,
        "win_rate": len(wins) / len(vals) if vals else None,
        "drawdown_bps": dd,
    }


def paired_stats(candidate: Sequence[float], control: Sequence[float], seed: int, bootstrap_n: int = 10000) -> dict[str, Any]:
    if len(candidate) != len(control) or not candidate:
        raise RuntimeError("PAIRED_CONTROL_BUDGET_INVALID")
    diffs = [float(a) - float(b) for a, b in zip(candidate, control)]
    n = len(diffs)
    rng = random.Random(seed)
    observed = sum(diffs) / n
    ge = 1
    for _ in range(bootstrap_n):
        perm = sum(x if rng.random() < 0.5 else -x for x in diffs) / n
        if perm >= observed:
            ge += 1
    p_value = ge / (bootstrap_n + 1)
    boots = [sum(diffs[rng.randrange(n)] for __ in range(n)) for _ in range(bootstrap_n)]
    boots.sort()
    ci_low = boots[max(0, int(0.05 * bootstrap_n) - 1)]
    return {
        "p_value": p_value,
        "candidate_minus_control_ci_low_bps": ci_low,
        "candidate_minus_control_net_bps": sum(diffs),
        "state": "PASS" if p_value <= 0.05 and ci_low > 0.0 else "FAIL",
    }


def _state_template(boundary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "zel.a1_external_research_exact8_forward_state.v1",
        "state": "COLLECTING",
        "boundary_utc": boundary["boundary_utc"],
        "boundary_ms": int(boundary["boundary_ms"]),
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "streams": {},
        "cost_snapshot_by_symbol": {},
        "source_audit_receipt_sha256": None,
        "integrity_defects": [],
        **AUTH,
    }


def _stream_key(symbol: str, timeframe_ms: int) -> str:
    return f"{symbol}|{int(timeframe_ms)}"


def _bar_fingerprint(bar: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(bar.get(k) for k in ("ts_ms", "open", "high", "low", "close", "volume"))


def merge_completed_bars(state: dict[str, Any], key: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    existing = state.setdefault("streams", {}).setdefault(key, [])
    by_ts = {int(x["ts_ms"]): dict(x) for x in existing}
    defects: list[str] = []
    for row in rows:
        item = dict(row)
        ts = int(item["ts_ms"])
        prior = by_ts.get(ts)
        if prior is not None and _bar_fingerprint(prior) != _bar_fingerprint(item):
            defects.append(f"APPEND_ONLY_BAR_MUTATION:{key}:{ts}")
            continue
        by_ts[ts] = item
    state["streams"][key] = [by_ts[k] for k in sorted(by_ts)]
    return defects


def collect_live(state_path: Path) -> dict[str, Any]:
    spec = read(SPEC_PATH)
    boundary = read(BOUNDARY_PATH)
    authority = read(COST_AUTHORITY_PATH)
    state = read(state_path) if state_path.exists() else _state_template(boundary)
    if state.get("boundary_utc") != boundary.get("boundary_utc") or int(state.get("boundary_ms") or 0) != int(boundary.get("boundary_ms") or 0):
        raise RuntimeError("EXACT8_BOUNDARY_IDENTITY_DRIFT")
    if boundary.get("state") != "PASS_EXACT8_FRESH_BOUNDARY_SEALED":
        raise RuntimeError("EXACT8_BOUNDARY_NOT_SEALED")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")

    raw_streams = source_audit.fetch_live_streams(spec)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    audit = source_audit.build_receipt(spec, raw_streams, now_ms=now_ms)
    defects = list(state.get("integrity_defects") or [])
    if audit.get("state") != "PASS_EXACT8_SIX_SOURCE_REALITY_AUDIT_NO_BOUNDARY":
        defects.append(f"SOURCE_AUDIT_NOT_PASS:{audit.get('state')}")

    needed = sorted({int(spec["specs"][pid]["timeframe_ms"]) for pid in SOURCE_READY})
    for symbol in SYMBOLS:
        for timeframe_ms in needed:
            audited, closed = source_audit.audit_stream(raw_streams[(symbol, timeframe_ms)], symbol=symbol, timeframe_ms=timeframe_ms, now_ms=now_ms)
            if audited["state"] != "PASS_SOURCE_STREAM_INTEGRITY":
                defects.append(f"STREAM_INTEGRITY:{symbol}:{timeframe_ms}:{audited['state']}")
            post = [x for x in closed if int(x["ts_ms"]) >= int(boundary["boundary_ms"])]
            defects.extend(merge_completed_bars(state, _stream_key(symbol, timeframe_ms), post))

    frozen_costs = state.setdefault("cost_snapshot_by_symbol", {})
    for symbol in SYMBOLS:
        if symbol not in frozen_costs:
            snap = ev.fetch_execution_snapshot(symbol, authority)
            frozen_costs[symbol] = {
                "captured_at_utc": utc_now(),
                "fee_bps": float(snap["fee_bps"]),
                "spread_bps": float(snap["spread_bps"]),
                "impact_bps": float(snap["impact_bps"]),
                "funding_p95_abs_bps": float(snap["funding_p95_abs_bps"]),
                "pretrade_verified_cost_bps": float(snap["pretrade_verified_cost_bps"]),
                "snapshot_sha256": snap["snapshot_sha256"],
                "cost_mode": "FROZEN_FIRST_POST_BOUNDARY_PUBLIC_SNAPSHOT_WITH_P95_FUNDING_RESERVE",
            }

    state["source_audit_receipt_sha256"] = audit.get("receipt_sha256")
    state["updated_at_utc"] = utc_now()
    state["integrity_defects"] = sorted(set(defects))
    state["state"] = "HOLD_INTEGRITY" if state["integrity_defects"] else "COLLECTING"
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def _load_parent(path: Path, parent_id: str) -> Any:
    name = f"exact8_parent_{parent_id}_{stable_sha(str(path))[:8]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"PARENT_IMPORT_FAIL:{parent_id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _intent_sha(intent: Any) -> str:
    value = getattr(intent, "sha", None)
    if isinstance(value, str) and value:
        return value
    body = asdict(intent) if is_dataclass(intent) else dict(vars(intent))
    return stable_sha(body)


def _side_name(intent: Any) -> str:
    value = getattr(intent, "side", "")
    raw = str(getattr(value, "value", value)).lower()
    if raw.endswith(".long"):
        raw = "long"
    if raw.endswith(".short"):
        raw = "short"
    if raw not in {"long", "short"}:
        raise RuntimeError(f"UNSUPPORTED_SIDE:{raw}")
    return raw


def _gross(side: str, entry: float, exit_px: float) -> float:
    return (exit_px / entry - 1.0) * 10000.0 if side == "long" else (1.0 - exit_px / entry) * 10000.0


def _simulate(intent: Any, bars: Sequence[Mapping[str, Any]], signal_i: int, cost_bps: float) -> dict[str, Any] | None:
    if signal_i + 1 >= len(bars):
        return None
    side = _side_name(intent)
    entry_bar = bars[signal_i + 1]
    entry_px = float(entry_bar["open"])
    timeout = getattr(intent, "timeout", {}) or {}
    timeout_bars = int(timeout.get("bars", 1)) if isinstance(timeout, Mapping) else int(getattr(timeout, "bars", 1))
    sl = getattr(intent, "sl", None)
    tp = getattr(intent, "tp", None)
    if sl is None and tp is None:
        raise RuntimeError("EXIT_GEOMETRY_UNSUPPORTED_NO_SL_TP")
    last_j = min(len(bars) - 1, signal_i + 1 + max(1, timeout_bars))
    exit_px: float | None = None
    exit_ts: int | None = None
    exit_index: int | None = None
    reason: str | None = None
    for j in range(signal_i + 1, last_j + 1):
        bar = bars[j]
        low, high = float(bar["low"]), float(bar["high"])
        if sl is not None and ((side == "long" and low <= float(sl)) or (side == "short" and high >= float(sl))):
            exit_px, exit_ts, exit_index, reason = float(sl), int(bar["ts_ms"]), j, "SL"
            break
        if tp is not None and ((side == "long" and high >= float(tp)) or (side == "short" and low <= float(tp))):
            exit_px, exit_ts, exit_index, reason = float(tp), int(bar["ts_ms"]), j, "TP"
            break
    if exit_px is None:
        if last_j >= len(bars) - 1:
            return None
        exit_px, exit_ts, exit_index, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), last_j, "TIMEOUT"
    gross_bps = _gross(side, entry_px, float(exit_px))
    return {
        "side": side,
        "entry_ts": int(entry_bar["ts_ms"]),
        "entry_px": entry_px,
        "exit_ts": int(exit_ts),
        "exit_px": float(exit_px),
        "entry_index": signal_i + 1,
        "exit_index": int(exit_index),
        "duration_bars": int(exit_index) - (signal_i + 1),
        "exit_reason": reason,
        "gross_bps": gross_bps,
        "realized_cost_bps": float(cost_bps),
        "net_bps": gross_bps - float(cost_bps),
    }


def _candidate_bars(state: Mapping[str, Any], symbol: str, timeframe_ms: int) -> list[dict[str, Any]]:
    return [dict(x) for x in (state.get("streams") or {}).get(_stream_key(symbol, timeframe_ms), [])]


def replay_child(parent_id: str, state: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    row = spec["specs"][parent_id]
    child_id = str(row["child_id"])
    timeframe_ms = int(row["timeframe_ms"])
    child_module = importlib.import_module(CHILD_MODULES[parent_id])
    cfg = ev.config_instance(child_module)
    child_compute, child_build = ev.policy_functions(child_module, parent_id)
    parent_path = ROOT / str(row["parent_policy"])
    parent_module = _load_parent(parent_path, parent_id)
    parent_compute, parent_build = ev.policy_functions(parent_module, parent_id)
    policy_sha = ev.git_blob_sha(parent_path)
    costs = state.get("cost_snapshot_by_symbol") or {}
    boundary_ms = int(state["boundary_ms"])
    warmup = int(source_audit.CANDIDATE_WARMUPS[parent_id])
    defects: list[str] = []
    parent_opportunities: list[dict[str, Any]] = []
    child_trades: list[dict[str, Any]] = []
    seen_parent: set[str] = set()
    seen_child: set[str] = set()

    for symbol in SYMBOLS:
        bars = _candidate_bars(state, symbol, timeframe_ms)
        if symbol not in costs:
            defects.append(f"COST_SNAPSHOT_MISSING:{symbol}")
            continue
        cost_bps = float(costs[symbol]["pretrade_verified_cost_bps"])
        for i in range(max(1, warmup), len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            try:
                parent_feature = parent_compute(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
                parent_intent = parent_build(parent_feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=cost_bps, config=cfg)
                child_feature = child_compute(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
                child_intent = child_build(child_feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=cost_bps, config=cfg)
            except ValueError:
                continue
            except Exception as exc:
                defects.append(f"POLICY_EVAL:{symbol}:{int(bars[i]['ts_ms'])}:{type(exc).__name__}:{exc}")
                continue
            if bool(getattr(parent_intent, "no_trade", True)):
                continue
            try:
                outcome = _simulate(parent_intent, bars, i, cost_bps)
            except Exception as exc:
                defects.append(f"OUTCOME:{symbol}:{int(bars[i]['ts_ms'])}:{type(exc).__name__}:{exc}")
                continue
            if outcome is None:
                continue
            psha = _intent_sha(parent_intent)
            if psha in seen_parent:
                defects.append(f"DUPLICATE_PARENT_INTENT:{psha}")
                continue
            seen_parent.add(psha)
            child_accept = not bool(getattr(child_intent, "no_trade", True))
            opportunity = {
                "parent_id": parent_id,
                "child_id": child_id,
                "symbol": symbol,
                "signal_ts": int(bars[i]["ts_ms"]),
                "parent_intent_sha": psha,
                "child_accept": child_accept,
                **outcome,
            }
            opportunity["child_net_bps_on_same_opportunity"] = float(outcome["net_bps"]) if child_accept else 0.0
            parent_opportunities.append(opportunity)
            if child_accept:
                csha = _intent_sha(child_intent)
                if csha in seen_child:
                    defects.append(f"DUPLICATE_CHILD_INTENT:{csha}")
                    continue
                seen_child.add(csha)
                child_trades.append({
                    **opportunity,
                    "intent_sha": csha,
                    "strategy_id": child_id,
                    "policy_sha": policy_sha,
                    "config_sha": stable_sha(asdict(cfg) if is_dataclass(cfg) else vars(cfg)),
                })

    parent_opportunities.sort(key=lambda x: (int(x["entry_ts"]), str(x["symbol"]), str(x["parent_intent_sha"])))
    child_trades.sort(key=lambda x: (int(x["entry_ts"]), str(x["symbol"]), str(x["intent_sha"])))
    return {
        "parent_id": parent_id,
        "child_id": child_id,
        "timeframe_ms": timeframe_ms,
        "parent_opportunities": parent_opportunities,
        "child_trades": child_trades,
        "integrity_defects": defects,
    }


def _random_entry_control(cohort: Sequence[Mapping[str, Any]], state: Mapping[str, Any], timeframe_ms: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    boundary_ms = int(state["boundary_ms"])
    used: set[tuple[str, int]] = set()
    output: list[float] = []
    for trade in cohort:
        symbol = str(trade["symbol"])
        bars = _candidate_bars(state, symbol, timeframe_ms)
        by_ts = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
        duration = max(1, int(trade.get("duration_bars") or 1))
        pool = [j for j, bar in enumerate(bars) if int(bar["ts_ms"]) >= boundary_ms and j + duration < len(bars) and (symbol, int(bar["ts_ms"])) not in used]
        if not pool:
            raise RuntimeError(f"RANDOM_ENTRY_POOL_EXHAUSTED:{symbol}")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        entry = float(bars[j]["open"])
        exit_px = float(bars[j + duration]["close"])
        gross = _gross(str(trade["side"]), entry, exit_px)
        output.append(gross - float(trade["realized_cost_bps"]))
    return output


def evaluate_a1(replay: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    child_id = str(replay["child_id"])
    all_trades = [dict(x) for x in replay["child_trades"]]
    defects = list(state.get("integrity_defects") or []) + list(replay.get("integrity_defects") or [])
    cohort = all_trades[:25]
    symbols = sorted({str(x["symbol"]) for x in cohort})
    blockers: list[str] = []
    if len(cohort) < 25:
        blockers.append(f"FIRST25_CHILD_TRADES:{len(cohort)}<25")
    if len(symbols) < 2:
        blockers.append(f"FIRST25_SYMBOLS:{len(symbols)}<2")
    if defects:
        blockers.append("INTEGRITY_DEFECTS_PRESENT")
    result: dict[str, Any] = {
        "schema_version": "zel.a1_external_research_exact8_a1.v1",
        "stage": "A1",
        "candidate_id": child_id,
        "parent_id": replay["parent_id"],
        "completed_child_trades": len(all_trades),
        "frozen_control_trade_count": len(cohort),
        "frozen_control_cohort_rule": "FIRST_25_CHILD_TRADES_BY_ENTRY_TS_SYMBOL_INTENT_SHA",
        "symbols_in_frozen_cohort": symbols,
        "integrity_defects": defects,
        "blockers": blockers,
        "hard_controls": {},
        "paired_parent_child": {},
        **AUTH,
    }
    if blockers:
        result["state"] = "HOLD_EXACT8_A1_INTEGRITY" if defects else "WAIT_EXACT8_A1_FRESH_SAMPLE"
        result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
        return result

    candidate = [float(x["net_bps"]) for x in cohort]
    seed_base = stable_sha({"candidate_id": child_id, "boundary_ms": state["boundary_ms"], "cohort": [(x["symbol"], x["entry_ts"], x["intent_sha"]) for x in cohort]})
    random_seed = int(stable_sha({"base": seed_base, "control": "same_count_random_entry"})[:16], 16)
    random_vals = _random_entry_control(cohort, state, int(replay["timeframe_ms"]), random_seed)
    direction_vals = [-float(x["gross_bps"]) - float(x["realized_cost_bps"]) for x in cohort]
    random_stats = paired_stats(candidate, random_vals, int(stable_sha({"base": seed_base, "stats": "random"})[:16], 16))
    direction_stats = paired_stats(candidate, direction_vals, int(stable_sha({"base": seed_base, "stats": "direction"})[:16], 16))
    result["hard_controls"] = {
        "same_count_random_entry": {**random_stats, "equal_trade_budget": True, "trade_count": 25},
        "direction_inversion": {**direction_stats, "equal_trade_budget": True, "trade_count": 25},
    }

    cutoff = int(cohort[-1]["entry_ts"])
    opportunities = [x for x in replay["parent_opportunities"] if int(x["entry_ts"]) <= cutoff]
    parent_vals = [float(x["net_bps"]) for x in opportunities]
    child_on_same = [float(x["child_net_bps_on_same_opportunity"]) for x in opportunities]
    result["paired_parent_child"] = {
        "opportunity_count": len(opportunities),
        "parent_net_bps": sum(parent_vals),
        "child_net_bps": sum(child_on_same),
        "child_minus_parent_net_bps": sum(child_on_same) - sum(parent_vals),
        "same_signal_opportunity_budget": True,
        "blocked_child_opportunity_return_bps": 0.0,
    }
    econ = metrics(candidate)
    result["economics"] = econ
    econ_pass = (
        float(econ["net_bps"]) > 0.0
        and float(econ["expectancy_bps"]) > 0.0
        and econ["profit_factor"] is not None and float(econ["profit_factor"]) > 1.0
        and econ["payoff_ratio"] is not None and float(econ["payoff_ratio"]) >= 1.0
    )
    hard_pass = all(x.get("state") == "PASS" for x in result["hard_controls"].values())
    paired_pass = result["paired_parent_child"]["child_minus_parent_net_bps"] > 0.0
    result["state"] = "PASS_EXACT8_A1_CAUSAL_READY_FOR_A2" if econ_pass and hard_pass and paired_pass else "FAIL_EXACT8_A1_CAUSAL"
    result["economics_pass"] = econ_pass
    result["hard_controls_pass"] = hard_pass
    result["paired_parent_child_pass"] = paired_pass
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def _plus_one_bar_values(trades: Sequence[Mapping[str, Any]], state: Mapping[str, Any], timeframe_ms: int) -> tuple[list[float], list[str]]:
    values: list[float] = []
    blockers: list[str] = []
    for trade in trades:
        symbol = str(trade["symbol"])
        bars = _candidate_bars(state, symbol, timeframe_ms)
        by_ts = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
        entry_i = by_ts.get(int(trade["entry_ts"]))
        exit_i = by_ts.get(int(trade["exit_ts"]))
        if entry_i is None or exit_i is None or entry_i + 1 >= exit_i:
            blockers.append(f"PLUS_ONE_BAR_UNAVAILABLE:{symbol}:{trade['entry_ts']}")
            continue
        delayed_entry = float(bars[entry_i + 1]["open"])
        gross = _gross(str(trade["side"]), delayed_entry, float(trade["exit_px"]))
        values.append(gross - float(trade["realized_cost_bps"]))
    return values, blockers


def evaluate_a2(a1_result: Mapping[str, Any], replay: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    child_id = str(replay["child_id"])
    if a1_result.get("state") != "PASS_EXACT8_A1_CAUSAL_READY_FOR_A2":
        result = {
            "schema_version": "zel.a1_external_research_exact8_a2.v1",
            "stage": "A2", "candidate_id": child_id, "state": "BLOCKED_BEFORE_A2",
            "a1_state": a1_result.get("state"), "stress": {}, **AUTH,
        }
        result["receipt_sha256"] = stable_sha(result)
        return result
    trades = [dict(x) for x in replay["child_trades"]]
    one_x = [float(x["net_bps"]) for x in trades]
    two_x = [float(x["gross_bps"]) - 2.0 * float(x["realized_cost_bps"]) for x in trades]
    delayed, delayed_blockers = _plus_one_bar_values(trades, state, int(replay["timeframe_ms"]))
    start_ms = int(state["boundary_ms"])
    end_ms = max((int(x["exit_ts"]) for x in trades), default=start_ms)
    elapsed_days = max((end_ms - start_ms) / 86_400_000.0, 1.0 / 1440.0)
    turnover = len(trades) / elapsed_days
    one = metrics(one_x)
    two = metrics(two_x)
    delay = metrics(delayed)
    stress = {
        "1X_COST": {"pass": one["expectancy_bps"] is not None and float(one["expectancy_bps"]) > 0.0, **one},
        "2X_COST": {"pass": two["expectancy_bps"] is not None and float(two["expectancy_bps"]) > 0.0, **two},
        "P95_FUNDING": {"pass": one["expectancy_bps"] is not None and float(one["expectancy_bps"]) > 0.0, "mode": "INCLUDED_IN_FROZEN_PRETRADE_COST_SNAPSHOT"},
        "PLUS_ONE_BAR": {"pass": len(delayed) == len(trades) and delay["expectancy_bps"] is not None and float(delay["expectancy_bps"]) > 0.0, **delay, "blockers": delayed_blockers},
        "TURNOVER": {"pass": len(trades) > 0 and turnover > 0.0, "round_trips": len(trades), "elapsed_days": elapsed_days, "round_trips_per_day": turnover},
    }
    passed = all(x.get("pass") is True for x in stress.values())
    result = {
        "schema_version": "zel.a1_external_research_exact8_a2.v1",
        "stage": "A2", "candidate_id": child_id,
        "state": "PASS_A2_COST_TURNOVER" if passed else "HOLD_A2_COST_TURNOVER",
        "a1_receipt_sha256": a1_result.get("receipt_sha256"),
        "stress": stress,
        "frozen_cost_snapshot_by_symbol": state.get("cost_snapshot_by_symbol"),
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def normalize_a3_context(context: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(context)
    rows: list[dict[str, Any]] = []
    for raw in context.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if row.get("capture_completed_at_ms") is None and row.get("snapshot_capture_completed_at_ms") is not None:
            row["capture_completed_at_ms"] = int(row["snapshot_capture_completed_at_ms"])
        rows.append(row)
    out["rows"] = rows
    out["exact8_context_alias_normalized"] = True
    return out


def evaluate_a3(a2_result: Mapping[str, Any], replay: Mapping[str, Any]) -> dict[str, Any]:
    child_id = str(replay["child_id"])
    if a2_result.get("state") != "PASS_A2_COST_TURNOVER":
        result = {
            "schema_version": "zel.a1_external_research_exact8_a3_route.v1",
            "stage": "A3", "candidate_id": child_id, "state": "BLOCKED_BEFORE_A3",
            "a2_state": a2_result.get("state"), **AUTH,
        }
        result["receipt_sha256"] = stable_sha(result)
        return result
    trades = [dict(x) for x in replay["child_trades"]]
    receipt = {
        "strategy_id": child_id,
        "boundary_utc": read(BOUNDARY_PATH)["boundary_utc"],
        "source_quality_gate": {"state": "PASS"},
        "integrity_defects": list(replay.get("integrity_defects") or []),
        "leakage_lookahead": 0,
        "trades": trades,
    }
    if receipt["integrity_defects"]:
        return {"schema_version": "zel.a1_external_research_exact8_a3_route.v1", "stage": "A3", "candidate_id": child_id, "state": "HOLD_A3_INTEGRITY", "integrity_defects": receipt["integrity_defects"], **AUTH}
    context = normalize_a3_context(read(A3_CONTEXT_PATH))
    result = a3.evaluate(receipt, a2_result, context)
    result["exact8_boundary_utc"] = read(BOUNDARY_PATH)["boundary_utc"]
    result["exact8_context_alias_normalized"] = True
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def evaluate_all(state: Mapping[str, Any]) -> dict[str, Any]:
    spec = read(SPEC_PATH)
    rows: list[dict[str, Any]] = []
    for parent_id in SOURCE_READY:
        replay = replay_child(parent_id, state, spec)
        a1_result = evaluate_a1(replay, state)
        a2_result = evaluate_a2(a1_result, replay, state)
        a3_result = evaluate_a3(a2_result, replay)
        rows.append({
            "parent_id": parent_id,
            "child_id": replay["child_id"],
            "completed_child_trades": len(replay["child_trades"]),
            "parent_opportunities": len(replay["parent_opportunities"]),
            "a1_state": a1_result.get("state"),
            "a2_state": a2_result.get("state"),
            "a3_state": a3_result.get("state"),
            "a1": a1_result,
            "a2": a2_result,
            "a3": a3_result,
        })
    a3_pass = sum(x["a3_state"] == "PASS_A3_GLOBAL_DURABILITY" for x in rows)
    a2_pass = sum(x["a2_state"] == "PASS_A2_COST_TURNOVER" for x in rows)
    a1_pass = sum(x["a1_state"] == "PASS_EXACT8_A1_CAUSAL_READY_FOR_A2" for x in rows)
    result = {
        "schema_version": "zel.a1_external_research_exact8_through_a3.v1",
        "state": "PASS_EXACT8_A3_EVIDENCE_PRESENT" if a3_pass else "WAIT_EXACT8_FRESH_EVIDENCE_THROUGH_A3",
        "boundary_utc": state["boundary_utc"],
        "evaluated_at_utc": utc_now(),
        "candidate_count": len(rows),
        "a1_pass_count": a1_pass,
        "a2_pass_count": a2_pass,
        "a3_pass_count": a3_pass,
        "effect_verified_count": a1_pass,
        "rows": rows,
        "held_exact8": {
            "rsi_swing_fail": "8640_PRIOR_COMPLETED_5M_RETURNS_REQUIRED",
            "scalp_snap": "TIMESTAMPED_PREENTRY_TRADES_AND_ORDERBOOK_DEPTH_REQUIRED",
        },
        "threshold_search": False,
        "holdout_outcomes_accessed": False,
        "synthetic_market_evidence_used": False,
        "parent_pass_inherited": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    spec = read(SPEC_PATH)
    boundary = read(BOUNDARY_PATH)
    if boundary.get("state") != "PASS_EXACT8_FRESH_BOUNDARY_SEALED":
        raise RuntimeError("BOUNDARY_NOT_SEALED")
    if set(boundary.get("source_ready_parent_ids") or []) != set(SOURCE_READY):
        raise RuntimeError("BOUNDARY_SOURCE_READY_SET_DRIFT")
    if spec.get("threshold_search") is not False or spec.get("holdout_outcomes_accessed") is not False:
        raise RuntimeError("OUTCOME_BLIND_SPEC_REQUIRED")
    for parent_id in SOURCE_READY:
        module = importlib.import_module(CHILD_MODULES[parent_id])
        cfg = ev.config_instance(module)
        if int(getattr(cfg, "timeframe_ms")) != int(spec["specs"][parent_id]["timeframe_ms"]):
            raise RuntimeError(f"TIMEFRAME_DRIFT:{parent_id}")
        if str(getattr(module, "CHILD_ID")) != str(spec["specs"][parent_id]["child_id"]):
            raise RuntimeError(f"CHILD_ID_DRIFT:{parent_id}")
    test_context = {"rows": [{"symbol": "BTC-USDT", "valid_for_a3": True, "snapshot_capture_completed_at_ms": 123, "bar_feature_cutoff_ts_ms": 100}]}
    normalized = normalize_a3_context(test_context)
    assert normalized["rows"][0]["capture_completed_at_ms"] == 123
    m = metrics([10.0, -5.0, 20.0])
    assert m["trades"] == 3 and m["net_bps"] == 25.0
    a3_contract = read(a3.CONTRACT)
    if int(boundary["boundary_ms"]) < a3.dt_ms(str(a3_contract["activation_boundary_utc"])):
        raise RuntimeError("EXACT8_BOUNDARY_PRECEDES_A3_ACTIVATION")
    print("PASS_EXACT8_THROUGH_A3_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--output", type=Path, default=Path("out/a1_external_research_exact8_through_a3_v1.json"))
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--collect-live", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.collect_live:
        raise SystemExit("--collect-live required unless --self-test")
    state = collect_live(args.state)
    result = evaluate_all(state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "a1_pass_count": result["a1_pass_count"],
        "a2_pass_count": result["a2_pass_count"],
        "a3_pass_count": result["a3_pass_count"],
        "rows": [{k: x[k] for k in ("parent_id", "child_id", "completed_child_trades", "a1_state", "a2_state", "a3_state")} for x in result["rows"]],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
