from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_family_paper_evidence_producer.v1"
INPUT_SCHEMA = "zel.production_family_paper_canary_result.v1"
OUTPUT_SCHEMA = "zel.production_family_paper_evidence.v1"
POLICY_SCHEMA = "zel.production_family_paper_evidence_producer_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_family_paper_evidence_producer_v1.json")
RUNTIME_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _f(v: Any, name: str) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_NUMERIC_NONFINITE:{name}")
    return out


def _i(v: Any, name: str) -> int:
    out = _f(v, name)
    if not out.is_integer():
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_INTEGER_INVALID:{name}")
    return int(out)


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_{label}_RECEIPT_MISMATCH")
    return claimed


def _hold(state: str, reason: str) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "reason": reason,
        "write_evidence": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": int(time.time() * 1000),
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _contract(policy: Mapping[str, Any]) -> dict[str, float | str]:
    raw = policy.get("survivor_contract")
    if not isinstance(raw, Mapping):
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_SURVIVOR_CONTRACT_MISSING")
    out: dict[str, float | str] = {
        "min_trades_per_window": float(_i(raw.get("min_trades_per_window"), "min_trades_per_window")),
        "min_profit_factor": _f(raw.get("min_profit_factor"), "min_profit_factor"),
        "min_expectancy_exclusive": _f(raw.get("min_expectancy_exclusive"), "min_expectancy_exclusive"),
        "min_net_pnl_exclusive": _f(raw.get("min_net_pnl_exclusive"), "min_net_pnl_exclusive"),
        "min_payoff_ratio": _f(raw.get("min_payoff_ratio"), "min_payoff_ratio"),
        "min_retention": _f(raw.get("min_retention"), "min_retention"),
        "max_dd_pct": _f(raw.get("max_dd_pct"), "max_dd_pct"),
        "source": str(raw.get("source") or "").strip(),
    }
    if out["min_trades_per_window"] != 60.0:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_MIN_TRADES_CONTRACT_INVALID")
    if out["min_profit_factor"] != 1.0 or out["min_payoff_ratio"] != 1.0:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_RATIO_CONTRACT_INVALID")
    if out["min_expectancy_exclusive"] != 0.0 or out["min_net_pnl_exclusive"] != 0.0:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_POSITIVE_EDGE_CONTRACT_INVALID")
    if out["min_retention"] != 0.60:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_RETENTION_CONTRACT_INVALID")
    if out["max_dd_pct"] != 10.0:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_DD_CONTRACT_INVALID")
    if not out["source"]:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_CONTRACT_SOURCE_MISSING")
    return out


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_NON_PAPER_FORBIDDEN")
    for key in ("canary_result_path", "evidence_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"FAMILY_PAPER_EVIDENCE_PATH_MISSING:{key}")
    _contract(policy)
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_PAPER_EVIDENCE_LIVE_FORBIDDEN")
    return dict(policy)


def _normalize_canary(row: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("schema_version") != INPUT_SCHEMA or row.get("state") != "PASS_FAMILY_PAPER_CANARY":
        raise RuntimeError("FAMILY_PAPER_CANARY_NOT_PASS")
    canary_receipt = _verified_receipt(row, "CANARY")
    if row.get("symbol_qualified") is not True:
        raise RuntimeError("FAMILY_PAPER_CANARY_SYMBOL_NOT_QUALIFIED")
    runtime_symbol = str(row.get("runtime_symbol") or "").replace("-", "").upper()
    if runtime_symbol not in RUNTIME_SYMBOLS:
        raise RuntimeError("FAMILY_PAPER_CANARY_RUNTIME_SYMBOL_INVALID")
    precedence = list(map(str, row.get("runtime_symbol_precedence") or []))
    if precedence != list(RUNTIME_SYMBOLS):
        raise RuntimeError("FAMILY_PAPER_CANARY_RUNTIME_SYMBOL_PRECEDENCE_INVALID")
    if row.get("symbol_selection_method") != "FROZEN_PRECEDENCE_FIRST_QUALIFIED_NO_METRIC_SEARCH":
        raise RuntimeError("FAMILY_PAPER_CANARY_SYMBOL_SELECTION_METHOD_INVALID")
    symbol_evaluations = row.get("symbol_evaluations")
    selected_eval = symbol_evaluations.get(runtime_symbol) if isinstance(symbol_evaluations, Mapping) else None
    if not isinstance(selected_eval, Mapping) or selected_eval.get("state") != "PASS_SYMBOL_PAPER_CANARY":
        raise RuntimeError("FAMILY_PAPER_CANARY_SELECTED_SYMBOL_NOT_PASS")
    if row.get("economic_gate_pass") is not True or row.get("durability_gate_pass") is not True or row.get("integrity_pass") is not True:
        raise RuntimeError("FAMILY_PAPER_CANARY_GATE_FAIL")
    family_id = str(row.get("family_id") or "").strip()
    strategy_id = str(row.get("strategy_id") or "").strip()
    alpha_id = str(row.get("alpha_id") or "").strip()
    canary_key = str(row.get("canary_key") or "").strip()
    contract_id = str(row.get("contract_id") or "").strip()
    contract_receipt = str(row.get("contract_receipt_sha256") or "").strip()
    if not family_id or not strategy_id or not alpha_id or not canary_key or not contract_id or len(contract_receipt) != 64:
        raise RuntimeError("FAMILY_PAPER_CANARY_IDENTITY_MISSING")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(len(str(x)) != 64 for x in hashes):
        raise RuntimeError("FAMILY_PAPER_CANARY_SOURCE_HASHES_INVALID")
    risk = row.get("risk_request")
    if not isinstance(risk, Mapping):
        raise RuntimeError("FAMILY_PAPER_CANARY_RISK_REQUEST_MISSING")
    lev = int(_f(risk.get("leverage_x"), "risk_request.leverage_x"))
    pos = _f(risk.get("position_pct"), "risk_request.position_pct")
    if lev not in (10, 15, 20) or pos not in (5.0, 10.0, 15.0, 20.0):
        raise RuntimeError("FAMILY_PAPER_CANARY_RISK_REQUEST_NOT_ALLOWED")
    windows = row.get("windows")
    if not isinstance(windows, Mapping) or set(windows) != {"W1", "W2", "W3"}:
        raise RuntimeError("FAMILY_PAPER_CANARY_WINDOWS_INVALID")
    if dict(selected_eval.get("windows") or {}) != dict(windows):
        raise RuntimeError("FAMILY_PAPER_CANARY_SELECTED_WINDOWS_MISMATCH")
    out_windows: dict[str, dict[str, float]] = {}
    for name in ("W1", "W2", "W3"):
        w = windows[name]
        if not isinstance(w, Mapping):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_INVALID:{name}")
        trades = _i(w.get("trade_count"), f"{name}.trade_count")
        net = _f(w.get("net_pnl"), f"{name}.net_pnl")
        pf = _f(w.get("profit_factor"), f"{name}.profit_factor")
        exp = _f(w.get("expectancy"), f"{name}.expectancy")
        payoff = _f(w.get("payoff_ratio"), f"{name}.payoff_ratio")
        retention = _f(w.get("retention"), f"{name}.retention")
        if trades < int(contract["min_trades_per_window"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_TRADES_FAIL:{name}")
        if net <= float(contract["min_net_pnl_exclusive"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_NET_FAIL:{name}")
        if pf < float(contract["min_profit_factor"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_PF_FAIL:{name}")
        if exp <= float(contract["min_expectancy_exclusive"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_EXPECTANCY_FAIL:{name}")
        if payoff < float(contract["min_payoff_ratio"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_PAYOFF_FAIL:{name}")
        if retention < float(contract["min_retention"]):
            raise RuntimeError(f"FAMILY_PAPER_CANARY_WINDOW_RETENTION_FAIL:{name}")
        out_windows[name] = {
            "trade_count": float(trades),
            "net_pnl": net,
            "profit_factor": pf,
            "expectancy": exp,
            "payoff_ratio": payoff,
            "retention": retention,
        }
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("FAMILY_PAPER_CANARY_METRICS_MISSING")
    if dict(selected_eval.get("metrics") or {}) != dict(metrics):
        raise RuntimeError("FAMILY_PAPER_CANARY_SELECTED_METRICS_MISMATCH")
    out_metrics = {k: _f(metrics.get(k), k) for k in ("trade_count", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct")}
    expected_trades = sum(v["trade_count"] for v in out_windows.values())
    if abs(out_metrics["trade_count"] - expected_trades) > 1e-9:
        raise RuntimeError("FAMILY_PAPER_CANARY_AGGREGATE_TRADE_COUNT_MISMATCH")
    if out_metrics["net_expectancy"] <= 0 or out_metrics["profit_factor"] < 1.0 or out_metrics["net_pnl"] <= 0:
        raise RuntimeError("FAMILY_PAPER_CANARY_AGGREGATE_ECONOMIC_FAIL")
    if out_metrics["max_dd_pct"] < 0 or out_metrics["max_dd_pct"] > float(contract["max_dd_pct"]):
        raise RuntimeError("FAMILY_PAPER_CANARY_AGGREGATE_DD_FAIL")
    contract_material = dict(contract)
    out = {
        "schema_version": OUTPUT_SCHEMA,
        "state": "PASS_FAMILY_PAPER_EVIDENCE",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "symbol_qualified": True,
        "runtime_symbol": runtime_symbol,
        "runtime_symbol_precedence": precedence,
        "symbol_selection_method": row["symbol_selection_method"],
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "canary_key": canary_key,
        "contract_id": contract_id,
        "contract_receipt_sha256": contract_receipt,
        "source_hashes": sorted(set(map(str, hashes))),
        "risk_request": {"leverage_x": lev, "position_pct": pos},
        "windows": out_windows,
        "metrics": out_metrics,
        "survivor_contract": contract_material,
        "survivor_contract_sha256": stable_sha(contract_material),
        "canary_receipt_sha256": canary_receipt,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "produced_at_ms": int(time.time() * 1000),
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def tick(policy: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    canary = read_json(Path(str(cfg["canary_result_path"])))
    if canary is None:
        return _hold("HOLD_FAMILY_PAPER_CANARY_MISSING", "NORMALIZED_FAMILY_PAPER_CANARY_NOT_AVAILABLE"), None
    if canary.get("runtime_symbol_precedence") is None:
        return _hold("HOLD_FAMILY_PAPER_CANARY_SYMBOL_QUALIFICATION_REQUIRED", "LEGACY_OR_UNQUALIFIED_CANARY_RESULT"), None
    evidence = _normalize_canary(canary, _contract(cfg))
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_FAMILY_PAPER_EVIDENCE_READY",
        "action": "hold",
        "write_evidence": True,
        "family_id": evidence["family_id"],
        "strategy_id": evidence["strategy_id"],
        "runtime_symbol": evidence["runtime_symbol"],
        "evidence_receipt_sha256": evidence["receipt_sha256"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": int(time.time() * 1000),
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, evidence


def main() -> int:
    policy = read_json(DEFAULT_POLICY, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, evidence = tick(cfg)
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if evidence is not None:
        atomic_json_write(Path(str(cfg["evidence_path"])), evidence)
    print(json.dumps({"state": state["state"], "write_evidence": state["write_evidence"], "receipt_sha256": state["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
