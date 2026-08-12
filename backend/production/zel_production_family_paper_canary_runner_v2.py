from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_family_paper_canary_runner_v1 as v1
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = v1.SCHEMA
RESULT_SCHEMA = v1.RESULT_SCHEMA
DEFAULT_POLICY = v1.DEFAULT_POLICY
WINDOWS = v1.WINDOWS
RUNTIME_SYMBOLS = {"BTC-USDT": "BTCUSDT", "ETH-USDT": "ETHUSDT"}


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    cfg = v1.validate_policy(policy)
    precedence = list(map(str, cfg.get("runtime_symbol_precedence") or []))
    if precedence != ["BTCUSDT", "ETHUSDT"]:
        raise RuntimeError("FAMILY_CANARY_RUNTIME_SYMBOL_PRECEDENCE_DRIFT")
    return cfg


def _compact_symbol(value: Any) -> str:
    compact = str(value or "").replace("-", "").upper()
    if compact not in set(RUNTIME_SYMBOLS.values()):
        raise RuntimeError(f"FAMILY_CANARY_RUNTIME_SYMBOL_UNSUPPORTED:{compact or 'MISSING'}")
    return compact


def _symbol_eval(
    trades: Sequence[Mapping[str, Any]],
    *,
    trades_per_window: int,
    frozen_contract: Mapping[str, Any],
) -> dict[str, Any]:
    required = trades_per_window * len(WINDOWS)
    if len(trades) < required:
        return {
            "state": "PENDING_SYMBOL_SAMPLE",
            "trade_count": len(trades),
            "required_trade_count": required,
            "economic_gate_pass": False,
            "durability_gate_pass": False,
            "integrity_pass": False,
            "windows": None,
            "metrics": None,
        }

    frozen_trades = list(trades[:required])
    values = [float(x["equity_return_pct"]) for x in frozen_trades]
    windows: dict[str, dict[str, Any]] = {}
    raw_stats: dict[str, dict[str, float]] = {}
    for idx, name in enumerate(WINDOWS):
        start = idx * trades_per_window
        stop = start + trades_per_window
        raw_stats[name] = v1._stats(values[start:stop])
    w1_expectancy = raw_stats["W1"]["expectancy"]
    for name in WINDOWS:
        stats = raw_stats[name]
        retention = 1.0 if name == "W1" else (stats["expectancy"] / w1_expectancy if w1_expectancy > 0.0 else 0.0)
        windows[name] = {
            "trade_count": int(stats["trade_count"]),
            "net_pnl": stats["net_pnl"],
            "profit_factor": stats["profit_factor"],
            "expectancy": stats["expectancy"],
            "payoff_ratio": stats["payoff_ratio"],
            "retention": retention,
        }
    aggregate = v1._stats(values)
    economic_gate = all(
        windows[name]["net_pnl"] > float(frozen_contract["min_net_pnl_exclusive"])
        and windows[name]["profit_factor"] >= float(frozen_contract["min_profit_factor"])
        and windows[name]["expectancy"] > float(frozen_contract["min_expectancy_exclusive"])
        and windows[name]["payoff_ratio"] >= float(frozen_contract["min_payoff_ratio"])
        for name in WINDOWS
    ) and aggregate["net_pnl"] > 0.0 and aggregate["expectancy"] > 0.0 and aggregate["profit_factor"] >= 1.0
    durability_gate = all(windows[name]["retention"] >= float(frozen_contract["min_retention"]) for name in WINDOWS)
    integrity_gate = (
        all(windows[name]["trade_count"] == trades_per_window for name in WINDOWS)
        and int(aggregate["trade_count"]) == required
        and aggregate["max_dd_pct"] <= float(frozen_contract["max_dd_pct"])
    )
    passed = economic_gate and durability_gate and integrity_gate
    return {
        "state": "PASS_SYMBOL_PAPER_CANARY" if passed else "REJECT_SYMBOL_PAPER_CANARY",
        "trade_count": required,
        "required_trade_count": required,
        "economic_gate_pass": economic_gate,
        "durability_gate_pass": durability_gate,
        "integrity_pass": integrity_gate,
        "windows": windows,
        "metrics": {
            "trade_count": int(aggregate["trade_count"]),
            "net_expectancy": aggregate["expectancy"],
            "profit_factor": aggregate["profit_factor"],
            "net_pnl": aggregate["net_pnl"],
            "max_dd_pct": aggregate["max_dd_pct"],
        },
    }


def evaluate_canary(
    meta: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    trades_per_window: int = 60,
    runtime_symbol_precedence: Sequence[str] = ("BTCUSDT", "ETHUSDT"),
) -> dict[str, Any] | None:
    risk = meta.get("risk_request")
    contract = meta.get("survivor_contract")
    if not isinstance(risk, Mapping) or not isinstance(contract, Mapping):
        raise RuntimeError("FAMILY_CANARY_EVALUATION_POLICY_MISSING")
    frozen_contract = v1._survivor_contract(contract)
    trades = v1._trade_rows(history, v1._f(meta.get("execution_cost_bps"), "execution_cost_bps"), risk)
    by_symbol: dict[str, list[dict[str, Any]]] = {"BTCUSDT": [], "ETHUSDT": []}
    for raw in trades:
        by_symbol[_compact_symbol(raw.get("symbol"))].append(dict(raw))

    precedence = list(map(str, runtime_symbol_precedence))
    if precedence != ["BTCUSDT", "ETHUSDT"]:
        raise RuntimeError("FAMILY_CANARY_RUNTIME_SYMBOL_PRECEDENCE_DRIFT")
    evaluations = {
        symbol: _symbol_eval(by_symbol[symbol], trades_per_window=trades_per_window, frozen_contract=frozen_contract)
        for symbol in precedence
    }
    selected = next((symbol for symbol in precedence if evaluations[symbol]["state"] == "PASS_SYMBOL_PAPER_CANARY"), None)
    if selected is None and any(evaluations[symbol]["state"] == "PENDING_SYMBOL_SAMPLE" for symbol in precedence):
        return None

    diagnostic_symbol = selected or precedence[0]
    selected_eval = evaluations[diagnostic_symbol]
    if selected is None and selected_eval["state"] == "PENDING_SYMBOL_SAMPLE":
        selected_eval = next(v for v in evaluations.values() if v["state"] != "PENDING_SYMBOL_SAMPLE")
    passed = selected is not None
    selected_native = selected.replace("USDT", "-USDT") if selected is not None else None
    source_history = [x for x in history if selected_native is None or str(x.get("symbol") or "") == selected_native]
    source_hashes = v1._source_hashes(source_history, meta)
    integrity_gate = bool(source_hashes) and bool(selected_eval.get("integrity_pass"))
    if passed and not integrity_gate:
        passed = False
        selected = None

    result = {
        "schema_version": RESULT_SCHEMA,
        "state": "PASS_FAMILY_PAPER_CANARY" if passed else "REJECT_FAMILY_PAPER_CANARY",
        "symbol_qualified": passed,
        "runtime_symbol": selected,
        "runtime_symbol_precedence": precedence,
        "symbol_evaluations": evaluations,
        "economic_gate_pass": bool(passed and selected_eval.get("economic_gate_pass")),
        "durability_gate_pass": bool(passed and selected_eval.get("durability_gate_pass")),
        "integrity_pass": bool(passed and integrity_gate),
        "family_id": str(meta.get("family_id") or ""),
        "strategy_id": str(meta.get("strategy_id") or ""),
        "alpha_id": str(meta.get("alpha_id") or ""),
        "canary_key": str(meta.get("canary_key") or ""),
        "contract_id": str(meta.get("contract_id") or ""),
        "source_hashes": source_hashes,
        "risk_request": {"leverage_x": v1._i(risk.get("leverage_x"), "leverage_x"), "position_pct": v1._f(risk.get("position_pct"), "position_pct")},
        "windows": selected_eval.get("windows"),
        "metrics": selected_eval.get("metrics"),
        "retention_semantics": "WINDOW_EXPECTANCY_DIV_W1_EXPECTANCY",
        "execution_cost_bps": v1._f(meta.get("execution_cost_bps"), "execution_cost_bps"),
        "prospective_only": True,
        "admission_history_reuse_allowed": False,
        "first_not_before_ms": v1._i(meta.get("first_not_before_ms"), "first_not_before_ms"),
        "first_request_receipt_sha256": str(meta.get("first_request_receipt_sha256") or ""),
        "contract_receipt_sha256": str(meta.get("contract_receipt_sha256") or ""),
        "survivor_contract_sha256": str(meta.get("survivor_contract_sha256") or ""),
        "parameter_search_performed": False,
        "numeric_signal_threshold_count": 0,
        "symbol_selection_method": "FROZEN_PRECEDENCE_FIRST_QUALIFIED_NO_METRIC_SEARCH",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def _invalidate_legacy_terminal_rows(state: dict[str, Any], now_ms: int) -> int:
    count = 0
    for meta in state.get("canaries", {}).values():
        if not isinstance(meta, dict) or str(meta.get("status") or "") not in {"PASS", "REJECT"}:
            continue
        result = meta.get("result")
        if isinstance(result, Mapping) and "runtime_symbol_precedence" in result:
            continue
        meta["status"] = "ACCUMULATING"
        meta["result"] = None
        meta["published"] = False
        meta["consumed"] = False
        meta["symbol_qualification_reset_at_ms"] = now_ms
        count += 1
    return count


def tick(
    policy: Mapping[str, Any],
    *,
    request_batch: Mapping[str, Any] | None,
    handoff_state: Mapping[str, Any] | None,
    contract_state: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any],
    family_evidence_policy: Mapping[str, Any],
    risk_policy: Mapping[str, Any],
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    existing_state: Mapping[str, Any] | None,
    histories: Mapping[str, Sequence[Mapping[str, Any]]],
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    current_result: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any] | None, dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    state = v1._load_state(existing_state, now)
    reset_count = _invalidate_legacy_terminal_rows(state, now)
    survivor_contract = v1._family_survivor_contract(family_evidence_policy)
    risk_request, risk_sha = v1._risk_request(risk_policy)
    requests = v1._request_rows(handoff_state, request_batch)
    initialized = v1._initialize_requests(
        state,
        requests,
        contract_state,
        template_registry,
        survivor_contract,
        risk_request,
        risk_sha,
        Path(str(cfg["history_dir"])),
        now,
    )

    if isinstance(current_result, Mapping) and v1._result_consumed(current_result, evidence):
        current_receipt = str(current_result.get("receipt_sha256") or "")
        for meta in state["canaries"].values():
            result = meta.get("result")
            if isinstance(result, Mapping) and str(result.get("receipt_sha256") or "") == current_receipt:
                meta["consumed"] = True

    appends: dict[str, list[dict[str, Any]]] = {}
    newly_terminal: list[dict[str, Any]] = []
    for key in sorted(state["canaries"]):
        meta = state["canaries"][key]
        if str(meta.get("status") or "") != "ACCUMULATING":
            continue
        history = v1._verify_history(list(histories.get(key) or []), meta)
        new_rows = v1._new_observations(meta, history, l2_snapshot, carry_snapshot, candles_by_symbol, cfg["symbols"])
        merged = v1._verify_history(history + new_rows, meta)
        if new_rows:
            appends[key] = new_rows
        result = evaluate_canary(meta, merged, int(cfg["trades_per_window"]), cfg["runtime_symbol_precedence"])
        trades = v1._trade_rows(merged, v1._f(meta.get("execution_cost_bps"), "execution_cost_bps"), meta["risk_request"])
        counts = {symbol: 0 for symbol in cfg["runtime_symbol_precedence"]}
        for trade in trades:
            counts[_compact_symbol(trade.get("symbol"))] += 1
        meta["trade_count"] = len(trades)
        meta["symbol_trade_counts"] = counts
        meta["observation_count"] = len(merged)
        meta["updated_at_ms"] = now
        if result is not None:
            meta["result"] = result
            meta["status"] = "PASS" if result["state"] == "PASS_FAMILY_PAPER_CANARY" else "REJECT"
            meta["runtime_symbol"] = result.get("runtime_symbol")
            meta["terminal_at_ms"] = now
            newly_terminal.append(result)

    publish: dict[str, Any] | None = None
    terminal_reject: dict[str, Any] | None = None
    current_unconsumed = isinstance(current_result, Mapping) and not v1._result_consumed(current_result, evidence)
    if current_unconsumed and current_result.get("runtime_symbol_precedence") is None:
        current_unconsumed = False
    if not current_unconsumed:
        for key in sorted(state["canaries"]):
            meta = state["canaries"][key]
            result = meta.get("result")
            if meta.get("status") == "PASS" and isinstance(result, Mapping) and meta.get("consumed") is not True:
                publish = dict(result)
                meta["published"] = True
                meta["published_at_ms"] = now
                break
    for result in newly_terminal:
        if result.get("state") == "REJECT_FAMILY_PAPER_CANARY":
            terminal_reject = dict(result)
            break

    statuses = [str(v.get("status") or "") for v in state["canaries"].values()]
    if publish is not None:
        top_state = "PASS_FAMILY_PAPER_CANARY_RESULT_READY"
    elif terminal_reject is not None:
        top_state = "REJECT_FAMILY_PAPER_CANARY"
    elif any(x == "ACCUMULATING" for x in statuses):
        top_state = "HOLD_FAMILY_PAPER_CANARY_ACCUMULATING"
    elif statuses:
        top_state = "HOLD_FAMILY_PAPER_CANARY_TERMINAL_ONLY"
    else:
        top_state = "HOLD_FAMILY_CANARY_NO_ACTIVE_REQUEST"
    state.update({
        "state": top_state,
        "action": "hold",
        "runner_version": "V2_SYMBOL_QUALIFIED",
        "runtime_symbol_precedence": list(cfg["runtime_symbol_precedence"]),
        "legacy_terminal_reset_count": reset_count,
        "initialized_count": initialized,
        "active_count": sum(1 for x in statuses if x == "ACCUMULATING"),
        "pass_count": sum(1 for x in statuses if x == "PASS"),
        "reject_count": sum(1 for x in statuses if x == "REJECT"),
        "published_result": publish is not None,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    })
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    return state, appends, publish, terminal_reject


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Symbol-qualified independent prospective family PAPER canary runner")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    existing_state = read_json(Path(str(cfg["state_path"])))
    histories: dict[str, list[dict[str, Any]]] = {}
    if isinstance(existing_state, Mapping) and isinstance(existing_state.get("canaries"), Mapping):
        for key, meta in existing_state["canaries"].items():
            if isinstance(meta, Mapping):
                histories[str(key)] = v1.read_history(Path(str(meta.get("history_path") or Path(str(cfg["history_dir"])) / f"{key}.ndjson")))
    candles = asyncio.run(v1._fetch_candles(cfg["symbols"]))
    family_policy = read_json(Path(str(cfg["family_evidence_policy_path"])), required=True)
    risk_policy = read_json(Path(str(cfg["risk_policy_path"])), required=True)
    template_registry = read_json(Path(str(cfg["template_registry_path"])), required=True)
    assert family_policy is not None and risk_policy is not None and template_registry is not None
    state, appends, result, terminal = tick(
        cfg,
        request_batch=read_json(Path(str(cfg["request_path"]))),
        handoff_state=read_json(Path(str(cfg["handoff_state_path"]))),
        contract_state=read_json(Path(str(cfg["contract_state_path"]))),
        template_registry=template_registry,
        family_evidence_policy=family_policy,
        risk_policy=risk_policy,
        l2_snapshot=read_json(Path(str(cfg["l2_snapshot_path"]))),
        carry_snapshot=read_json(Path(str(cfg["carry_snapshot_path"]))),
        existing_state=existing_state,
        histories=histories,
        candles_by_symbol=candles,
        current_result=read_json(Path(str(cfg["result_path"]))),
        evidence=read_json(Path(str(family_policy.get("evidence_path") or ""))),
    )
    for key, rows in appends.items():
        meta = state["canaries"][key]
        v1.append_observations(Path(str(meta["history_path"])), rows)
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if result is not None:
        atomic_json_write(Path(str(cfg["result_path"])), result)
    if terminal is not None:
        atomic_json_write(Path(str(cfg["terminal_result_path"])), terminal)
    print(json.dumps({
        "state": state["state"],
        "runner_version": state["runner_version"],
        "active_count": state["active_count"],
        "pass_count": state["pass_count"],
        "reject_count": state["reject_count"],
        "published_result": state["published_result"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
