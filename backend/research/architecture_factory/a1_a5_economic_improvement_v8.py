#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v7 as v7
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
NAMED = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v8"
RISK_SCHEMA = "zel.a1_named_channel_risk_sizing_evaluator.v1"
COMMON_SUBSTRATE = {"ohlcv", "volume"}
MAX_RISK_HYPOTHESES_PER_STRATEGY = 2
ATR_PERIOD = 14
MIN_PRIOR_RISK_DISTANCES = 5
PRIOR_RISK_WINDOW = 20


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _risk_axis(source_id: str, strategy_id: str, mechanism: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{strategy_id}|risk|{mechanism}".encode()).hexdigest()[:12].upper()
    return f"YTRISK_FIXED_FRACTIONAL_{digest}"


def _risk_hypotheses(
    doc: Mapping[str, Any], focus: list[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    wanted = set(focus)
    out: dict[str, list[dict[str, Any]]] = {sid: [] for sid in focus}
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for src in doc.get("accepted_sources") or []:
        if not isinstance(src, Mapping):
            continue
        source_id = str(src.get("id") or "")
        if not source_id.startswith("YTNAMED:"):
            continue
        if src.get("accepted_for_hypothesis_only") is not True:
            continue
        if src.get("direct_video_analysis") is not True:
            continue
        if src.get("channel_identity_verified_by_direct_analysis") is not True:
            continue
        channel = str(src.get("target_channel") or src.get("actual_channel") or "")
        for mech in src.get("reproducible_mechanisms") or []:
            if not isinstance(mech, Mapping):
                continue
            layer = str(mech.get("architecture_layer") or "").lower().strip()
            mechanism = str(mech.get("mechanism") or "").strip()
            if not mechanism:
                continue
            for mapping in mech.get("candidate_strategy_mappings") or []:
                if not isinstance(mapping, Mapping):
                    continue
                sid = str(mapping.get("strategy_id") or "")
                if sid not in wanted:
                    continue
                text = v7._text(mech, mapping)
                required = v7._required_sources(text)
                is_risk = layer == "risk" or "account_equity" in required
                if not is_risk:
                    continue
                unsupported = required - (COMMON_SUBSTRATE | {"account_equity"})
                if unsupported:
                    rejected.append({
                        "strategy_id": sid,
                        "source_id": source_id,
                        "channel": channel,
                        "reason": "RISK_EVALUATOR_UNSUPPORTED_SOURCE:" + ",".join(sorted(unsupported)),
                    })
                    continue
                key = (sid, re.sub(r"\s+", " ", mechanism.lower()).strip())
                if key in seen:
                    continue
                seen.add(key)
                out[sid].append({
                    "axis": _risk_axis(source_id, sid, mechanism),
                    "strategy_id": sid,
                    "mechanism": mechanism,
                    "source_id": source_id,
                    "channel": channel,
                    "video_id": str(src.get("video_id") or ""),
                    "application_mode": str(mapping.get("application_mode") or ""),
                    "local_test": str(mapping.get("local_test") or mech.get("local_test_needed") or ""),
                    "required_sources": sorted(required | {"account_equity"}),
                    "creator_numeric_threshold_imported": False,
                    "creator_performance_claim_imported": False,
                    "sizing_rule": "lagged realized equity x bounded inverse ATR14 risk-distance scale",
                    "risk_distance_mode": "ATR14_SIGNAL_TIME_PROXY_EVALUATOR_OWNED",
                    "parameter_provenance": "evaluator-owned structural constants only; creator numeric thresholds ignored; no outcome sweep",
                })

    for sid in focus:
        out[sid] = out[sid][:MAX_RISK_HYPOTHESES_PER_STRATEGY]
    return out, rejected


def _candidate_substrates(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket in ("initial_candidates", "second_step_candidates"):
        for raw in result.get(bucket) or []:
            if isinstance(raw, Mapping):
                rows.append(dict(raw))
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("strategy_id") or "")
        spec = row.get("executable_spec")
        req = set(row.get("required_sources") or [])
        if not sid or not isinstance(spec, Mapping):
            continue
        if not req or not req.issubset(COMMON_SUBSTRATE):
            continue
        selected.setdefault(sid, row)
    return selected


def _build_features(rs: list[dict[str, float]], spec: Mapping[str, Any]) -> econ.Expr:
    features: dict[str, list[float | None]] = {}
    eng = econ.Expr(rs, features)
    for raw in spec.get("features") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("FEATURE_INVALID")
        name = str(raw.get("name") or "").strip()
        formula = econ._feature_formula(str(raw.get("formula") or ""))
        if not name or not formula:
            raise ValueError("FEATURE_EMPTY")
        eng.validate(formula)
        arr: list[float | None] = []
        features[name] = arr
        for i in range(len(rs)):
            try:
                value = eng.eval(formula, i)
                arr.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None)
            except (TypeError, ZeroDivisionError, ValueError):
                arr.append(None)
    return econ.Expr(rs, features)


def _replay(candidate: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = candidate.get("executable_spec")
    if not isinstance(spec, Mapping):
        raise ValueError("SPEC_MISSING")
    interval = str(spec.get("bar_interval") or "")
    if interval not in econ.INTERVAL_MAP:
        raise ValueError("INTERVAL_UNSUPPORTED")
    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    exit_rule = str(spec.get("exit_rule") or "time_stop")
    hold = int(spec.get("max_hold_bars") or 0)
    if not 1 <= hold <= 720:
        raise ValueError("HOLD_UNSUPPORTED")

    alltr: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in econ.SYMBOLS:
        rs = econ.bars(symbol, interval)
        source[symbol] = {"bars": len(rs)}
        eng = _build_features(rs, spec)
        eng.validate(entry_rule)
        econ._validate_side(side_rule, eng)
        time_only = exit_rule.strip().lower() in {"time_stop", "time stop", "max_hold", "max_hold_bars"}
        if not time_only:
            eng.validate(exit_rule)
        i = max(30, ATR_PERIOD + 1)
        runtime_errors = 0
        while i < len(rs) - 1:
            try:
                fire = bool(eng.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                runtime_errors += 1
                fire = False
            if not fire:
                i += 1
                continue
            side = econ._side(side_rule, eng, i)
            if side not in {"long", "short"}:
                raise ValueError("SIDE_RULE_UNSUPPORTED")
            entry_i = i + 1
            entry_px = float(rs[entry_i]["open"])
            atr = eng.eval(f"atr({ATR_PERIOD})", i)
            if not isinstance(atr, (int, float)) or not math.isfinite(float(atr)) or float(atr) <= 0 or entry_px <= 0:
                i += 1
                continue
            risk_distance_bps = float(atr) / entry_px * 10000.0
            exit_i = min(entry_i + hold - 1, len(rs) - 1)
            if not time_only:
                for j in range(entry_i, min(entry_i + hold, len(rs))):
                    try:
                        if bool(eng.eval(exit_rule, j)):
                            exit_i = j
                            break
                    except (TypeError, ZeroDivisionError, ValueError):
                        raise ValueError("EXIT_RULE_UNSUPPORTED")
            exit_px = float(rs[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10000.0 * (1.0 if side == "long" else -1.0)
            net = gross - econ.COST_BPS
            alltr.append({
                "symbol": symbol,
                "side": side,
                "gross_bps": gross,
                "net_bps": net,
                "entry_ts": int(rs[entry_i]["ts"]),
                "exit_ts": int(rs[exit_i]["ts"]),
                "risk_distance_bps": risk_distance_bps,
            })
            i = max(i + 1, exit_i + 1)
        if runtime_errors > max(50, len(rs) // 2):
            raise ValueError(f"ENTRY_RUNTIME_ERRORS:{runtime_errors}")
    alltr.sort(key=lambda x: (int(x["entry_ts"]), int(x["exit_ts"]), str(x["symbol"])))
    return alltr, source


def _bounded_inverse_risk_scale(current: float, prior: list[float]) -> float:
    if len(prior) < MIN_PRIOR_RISK_DISTANCES:
        return 1.0
    reference = statistics.median(prior[-PRIOR_RISK_WINDOW:])
    if not math.isfinite(reference) or reference <= 0 or not math.isfinite(current) or current <= 0:
        return 1.0
    ratio = reference / current
    return 2.0 * ratio / (1.0 + ratio)


def _simulate(trades: list[dict[str, Any]], adaptive: bool) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "net_pnl_bps": 0.0,
            "net_expectancy_bps": None,
            "profit_factor": None,
            "win_rate": None,
            "drawdown_bps": 0.0,
            "ending_equity": 1.0,
            "avg_sizing_multiplier": None,
            "max_sizing_multiplier": None,
            "min_sizing_multiplier": None,
        }
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    open_positions: list[dict[str, Any]] = []
    realized_bps: list[float] = []
    scales: list[float] = []
    risk_history: list[float] = []

    def settle(until_ts: int | None) -> None:
        nonlocal equity, peak, max_dd, open_positions
        ready = [x for x in open_positions if until_ts is None or int(x["exit_ts"]) <= until_ts]
        pending = [x for x in open_positions if until_ts is not None and int(x["exit_ts"]) > until_ts]
        ready.sort(key=lambda x: (int(x["exit_ts"]), str(x["symbol"])))
        for pos in ready:
            pnl_amount = float(pos["pnl_amount"])
            equity += pnl_amount
            realized_bps.append(pnl_amount * 10000.0)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) * 10000.0)
        open_positions = pending

    idx = 0
    while idx < len(trades):
        ts = int(trades[idx]["entry_ts"])
        settle(ts)
        group: list[dict[str, Any]] = []
        while idx < len(trades) and int(trades[idx]["entry_ts"]) == ts:
            group.append(trades[idx])
            idx += 1
        entry_equity = max(0.0, equity)
        prior_snapshot = list(risk_history)
        group_risks: list[float] = []
        for tr in group:
            rd = float(tr["risk_distance_bps"])
            scale = _bounded_inverse_risk_scale(rd, prior_snapshot) if adaptive else 1.0
            scales.append(scale)
            pnl_amount = entry_equity * scale * float(tr["net_bps"]) / 10000.0
            open_positions.append({
                "exit_ts": int(tr["exit_ts"]),
                "symbol": tr["symbol"],
                "pnl_amount": pnl_amount,
            })
            group_risks.append(rd)
        risk_history.extend(group_risks)
    settle(None)

    return {
        "trades": len(realized_bps),
        "net_pnl_bps": (equity - 1.0) * 10000.0,
        "net_expectancy_bps": sum(realized_bps) / len(realized_bps) if realized_bps else None,
        "profit_factor": econ._pf(realized_bps),
        "win_rate": sum(1 for x in realized_bps if x > 0) / len(realized_bps) if realized_bps else None,
        "drawdown_bps": max_dd,
        "ending_equity": equity,
        "avg_sizing_multiplier": sum(scales) / len(scales) if scales else None,
        "max_sizing_multiplier": max(scales) if scales else None,
        "min_sizing_multiplier": min(scales) if scales else None,
    }


def _num(value: Any, fallback: float) -> float:
    try:
        x = float(value)
    except Exception:
        return fallback
    return x if math.isfinite(x) else fallback


def _evaluate_pair(substrate: Mapping[str, Any], hypothesis: Mapping[str, Any]) -> dict[str, Any]:
    sid = str(substrate.get("strategy_id") or "")
    cid = str(substrate.get("candidate_id") or "")
    try:
        trades, source = _replay(substrate)
    except Exception as exc:
        return {
            "strategy_id": sid,
            "substrate_candidate_id": cid,
            "risk_axis": hypothesis.get("axis"),
            "source_id": hypothesis.get("source_id"),
            "state": "REJECT_RISK_SIZING_REPLAY_UNEXECUTABLE",
            "error": f"{type(exc).__name__}:{str(exc)[:240]}",
            "economic_pass": False,
        }
    base = _simulate(trades, adaptive=False)
    risk = _simulate(trades, adaptive=True)
    trade_retention = 1.0 if base["trades"] == risk["trades"] else 0.0
    base_pf = _num(base.get("profit_factor"), 0.0)
    risk_pf = _num(risk.get("profit_factor"), 0.0)
    deltas = {
        "net_pnl_bps": _num(risk.get("net_pnl_bps"), 0.0) - _num(base.get("net_pnl_bps"), 0.0),
        "net_expectancy_bps": _num(risk.get("net_expectancy_bps"), 0.0) - _num(base.get("net_expectancy_bps"), 0.0),
        "profit_factor": risk_pf - base_pf,
        "drawdown_bps": _num(risk.get("drawdown_bps"), math.inf) - _num(base.get("drawdown_bps"), math.inf),
    }
    improvement = bool(
        base["trades"] >= 12
        and trade_retention == 1.0
        and deltas["net_pnl_bps"] > 0
        and deltas["net_expectancy_bps"] > 0
        and risk_pf >= base_pf
        and _num(risk.get("drawdown_bps"), math.inf) <= _num(base.get("drawdown_bps"), math.inf)
    )
    economic = bool(
        improvement
        and _num(risk.get("net_pnl_bps"), 0.0) > 0
        and _num(risk.get("net_expectancy_bps"), 0.0) > 0
        and risk_pf > 1.0
    )
    return {
        "strategy_id": sid,
        "substrate_candidate_id": cid,
        "substrate_changed_axis": substrate.get("changed_axis"),
        "risk_axis": hypothesis.get("axis"),
        "source_id": hypothesis.get("source_id"),
        "channel": hypothesis.get("channel"),
        "video_id": hypothesis.get("video_id"),
        "mechanism": hypothesis.get("mechanism"),
        "local_test": hypothesis.get("local_test"),
        "state": "PASS_RISK_SIZING_DEVELOPMENT_ECONOMICS" if economic else (
            "PASS_RISK_CONTROL_IMPROVEMENT_ONLY" if improvement else "FAIL_RISK_SIZING_DEVELOPMENT_ECONOMICS"
        ),
        "economic_pass": economic,
        "risk_control_improvement": improvement,
        "baseline_metrics": base,
        "risk_sized_metrics": risk,
        "deltas": deltas,
        "trade_retention_ratio": trade_retention,
        "source_summary": source,
        "risk_distance_mode": hypothesis.get("risk_distance_mode"),
        "sizing_rule": hypothesis.get("sizing_rule"),
        "creator_numeric_threshold_imported": False,
        "creator_performance_claim_imported": False,
        "uses_lagged_realized_equity_only": True,
        "same_signal_and_exit_events_preserved": True,
        "development_only": True,
        "prospective": False,
        "uses_data_strictly_before_gen1_boundary": True,
        "boundary": econ.BOUNDARY,
        "cost_bps_per_unit_exposure": econ.COST_BPS,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def _run_risk_evaluator(result: Mapping[str, Any], doc: Mapping[str, Any], focus: list[str]) -> dict[str, Any]:
    hypotheses, rejected = _risk_hypotheses(doc, focus)
    substrates = _candidate_substrates(result)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for sid in focus:
        hs = hypotheses.get(sid) or []
        if not hs:
            continue
        substrate = substrates.get(sid)
        if substrate is None:
            for h in hs:
                skipped.append({
                    "strategy_id": sid,
                    "risk_axis": h.get("axis"),
                    "source_id": h.get("source_id"),
                    "state": "SKIP_NO_COMMON_SOURCE_EXECUTABLE_SUBSTRATE",
                })
            continue
        for h in hs:
            rows.append(_evaluate_pair(substrate, h))
    econ_passes = [x for x in rows if x.get("economic_pass") is True]
    risk_improvements = [x for x in rows if x.get("risk_control_improvement") is True]
    executed = len(rows) > 0
    return {
        "schema_version": RISK_SCHEMA,
        "state": "PASS_RISK_SIZING_EVALUATOR_EXECUTED" if executed else "HOLD_NO_RISK_SIZING_SUBSTRATE",
        "hypothesis_count": sum(len(v) for v in hypotheses.values()),
        "hypothesis_count_by_strategy": {sid: len(hypotheses.get(sid) or []) for sid in focus},
        "substrate_strategy_ids": sorted(substrates),
        "evaluated_count": len(rows),
        "economic_pass_count": len(econ_passes),
        "risk_control_improvement_count": len(risk_improvements),
        "rows": rows,
        "passes": econ_passes,
        "skipped": skipped,
        "rejected_mapping_count": len(rejected),
        "rejected_mapping_sample": rejected[:20],
        "creator_numeric_threshold_imported": False,
        "creator_performance_claim_imported": False,
        "risk_fraction_absolute_value_imported": False,
        "stop_distance_proxy": f"ATR{ATR_PERIOD}_AT_SIGNAL_TIME",
        "stop_distance_proxy_reason": "substrate executable specs do not expose a canonical stop price; evaluator uses an outcome-blind structural proxy without changing entry/exit events",
        "sizing_scale": "2*r/(1+r), r=median(prior risk distances)/current risk distance; warmup uses 1.0",
        "prior_window_trades": PRIOR_RISK_WINDOW,
        "minimum_prior_trades": MIN_PRIOR_RISK_DISTANCES,
        "no_outcome_threshold_sweep": True,
        "same_signal_and_exit_events_required": True,
        "development_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }


def run(output: Path) -> dict[str, Any]:
    result = dict(v7.run(output))
    doc = _read(NAMED)
    focus = [str(x) for x in (result.get("performance_focus_order") or [])]
    risk = _run_risk_evaluator(result, doc, focus)
    result["named_channel_risk_sizing_evaluator"] = risk
    result.setdefault("policy", {})["named_channel_account_equity_risk_pipe_opened"] = True
    result["policy"]["creator_risk_fraction_import_forbidden"] = True
    result["policy"]["risk_sizing_outcome_threshold_sweep_forbidden"] = True
    result["schema_version"] = SCHEMA
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    doc = {
        "accepted_sources": [{
            "id": "YTNAMED:risk0000001",
            "accepted_for_hypothesis_only": True,
            "direct_video_analysis": True,
            "channel_identity_verified_by_direct_analysis": True,
            "target_channel": "Risk Test",
            "video_id": "risk0000001",
            "reproducible_mechanisms": [{
                "architecture_layer": "risk",
                "mechanism": "Fixed fractional position sizing from account equity and stop distance.",
                "data_requirements": ["OHLCV", "Account Equity", "Entry Price", "Stop Loss Price"],
                "creator_numeric_thresholds_unverified": ["1% risk per trade"],
                "candidate_strategy_mappings": [{
                    "strategy_id": "supertrend_pullback",
                    "application_mode": "ONE_AXIS_REPAIR_AFTER_LOCAL_ATTRIBUTION",
                    "local_test": "Compare fixed fractional risk sizing with static notional.",
                }],
            }],
        }]
    }
    hypotheses, rejected = _risk_hypotheses(doc, ["supertrend_pullback"])
    assert not rejected
    assert len(hypotheses["supertrend_pullback"]) == 1
    h = hypotheses["supertrend_pullback"][0]
    assert h["creator_numeric_threshold_imported"] is False
    assert "account_equity" in h["required_sources"]
    assert abs(_bounded_inverse_risk_scale(100.0, [100.0] * 5) - 1.0) < 1e-12
    assert v7.v3.AUTH["execution_authority"] == "NONE"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V8_SELF_TEST")
    print("PASS_NAMED_CHANNEL_ACCOUNT_EQUITY_RISK_SIZING_PIPE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v8.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    risk = result.get("named_channel_risk_sizing_evaluator") or {}
    print(json.dumps({
        "state": result.get("state"),
        "schema": result.get("schema_version"),
        "risk_state": risk.get("state"),
        "risk_hypotheses": risk.get("hypothesis_count"),
        "risk_evaluated": risk.get("evaluated_count"),
        "risk_economic_pass": risk.get("economic_pass_count"),
        "risk_control_improvement": risk.get("risk_control_improvement_count"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
