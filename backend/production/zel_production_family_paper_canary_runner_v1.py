from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_ai_admission_executor_v1 import (
    EXPECTED_CONTROLS,
    _authority_guard,
    _fetch_candles,
    append_observations,
    read_history,
)
from backend.production.zel_production_ai_admission_executor_v2 import (
    SUPPORTED_TEMPLATES,
    build_observations,
    validate_contract,
)
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_family_paper_canary_runner.v1"
POLICY_SCHEMA = "zel.production_family_paper_canary_runner_policy.v1"
REQUEST_SCHEMA = "zel.production_family_paper_canary_request.v1"
REQUEST_BATCH_SCHEMA = REQUEST_SCHEMA + ".batch"
HANDOFF_SCHEMA = "zel.production_ai_family_canary_handoff.v1"
CONTRACT_STATE_SCHEMA = "zel.production_ai_admission_materializer.v1"
RESULT_SCHEMA = "zel.production_family_paper_canary_result.v1"
EVIDENCE_SCHEMA = "zel.production_family_paper_evidence.v1"
RISK_POLICY_SCHEMA = "zel.production_risk_sizing_policy.v1"
FAMILY_EVIDENCE_POLICY_SCHEMA = "zel.production_family_paper_evidence_producer_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_family_paper_canary_runner_v1.json")
WINDOWS = ("W1", "W2", "W3")


def _f(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"FAMILY_CANARY_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"FAMILY_CANARY_NUMERIC_NONFINITE:{name}")
    return out


def _i(value: Any, name: str) -> int:
    out = _f(value, name)
    if not out.is_integer():
        raise RuntimeError(f"FAMILY_CANARY_INTEGER_INVALID:{name}")
    return int(out)


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"FAMILY_CANARY_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"FAMILY_CANARY_{label}_RECEIPT_MISMATCH")
    return claimed


def _survivor_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "min_trades_per_window": 60,
        "min_profit_factor": 1.0,
        "min_expectancy_exclusive": 0.0,
        "min_net_pnl_exclusive": 0.0,
        "min_payoff_ratio": 1.0,
        "min_retention": 0.60,
        "max_dd_pct": 10.0,
    }
    out = dict(raw)
    for key, value in expected.items():
        if _f(out.get(key), key) != float(value):
            raise RuntimeError(f"FAMILY_CANARY_SURVIVOR_CONTRACT_DRIFT:{key}")
    if not str(out.get("source") or "").strip():
        raise RuntimeError("FAMILY_CANARY_SURVIVOR_CONTRACT_SOURCE_MISSING")
    return out


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("FAMILY_CANARY_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_CANARY_NON_PAPER_FORBIDDEN")
    for key in (
        "request_path",
        "handoff_state_path",
        "contract_state_path",
        "template_registry_path",
        "l2_snapshot_path",
        "carry_snapshot_path",
        "history_dir",
        "state_path",
        "result_path",
        "terminal_result_path",
        "family_evidence_policy_path",
        "risk_policy_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"FAMILY_CANARY_POLICY_PATH_MISSING:{key}")
    if list(map(str, policy.get("symbols") or [])) != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("FAMILY_CANARY_SYMBOLS_DRIFT")
    if str(policy.get("outcome_timeframe") or "") != "1h":
        raise RuntimeError("FAMILY_CANARY_TIMEFRAME_DRIFT")
    if list(map(str, policy.get("windows") or [])) != list(WINDOWS):
        raise RuntimeError("FAMILY_CANARY_WINDOWS_DRIFT")
    if _i(policy.get("trades_per_window"), "trades_per_window") != 60:
        raise RuntimeError("FAMILY_CANARY_TRADES_PER_WINDOW_DRIFT")
    if policy.get("retention_semantics") != "WINDOW_EXPECTANCY_DIV_W1_EXPECTANCY":
        raise RuntimeError("FAMILY_CANARY_RETENTION_SEMANTICS_DRIFT")
    if policy.get("risk_basis") != "MINIMUM_FROZEN_PAPER_EXPOSURE":
        raise RuntimeError("FAMILY_CANARY_RISK_BASIS_DRIFT")
    if policy.get("numeric_signal_thresholds") != [] or policy.get("parameter_search") is not False:
        raise RuntimeError("FAMILY_CANARY_SEARCH_FORBIDDEN")
    _authority_guard(policy, "FAMILY_CANARY_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("FAMILY_CANARY_MUTATION_FORBIDDEN")
    return dict(policy)


def _risk_request(risk_policy: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if risk_policy.get("schema_version") != RISK_POLICY_SCHEMA:
        raise RuntimeError("FAMILY_CANARY_RISK_POLICY_SCHEMA_INVALID")
    if str(risk_policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_CANARY_RISK_POLICY_NON_PAPER")
    if risk_policy.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("FAMILY_CANARY_RISK_POLICY_EXECUTION_INVALID")
    if risk_policy.get("order_authority") != "BLOCKED" or risk_policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("FAMILY_CANARY_RISK_POLICY_LIVE_FORBIDDEN")
    lev = tuple(_i(x, "allowed_leverage_x") for x in (risk_policy.get("allowed_leverage_x") or []))
    pos = tuple(_f(x, "allowed_position_pct") for x in (risk_policy.get("allowed_position_pct") or []))
    if lev != (10, 15, 20) or pos != (5.0, 10.0, 15.0, 20.0):
        raise RuntimeError("FAMILY_CANARY_RISK_ALLOWLIST_DRIFT")
    return {"leverage_x": min(lev), "position_pct": min(pos)}, stable_sha(dict(risk_policy))


def _family_survivor_contract(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != FAMILY_EVIDENCE_POLICY_SCHEMA:
        raise RuntimeError("FAMILY_CANARY_EVIDENCE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("FAMILY_CANARY_EVIDENCE_POLICY_NON_PAPER")
    _authority_guard(policy, "FAMILY_CANARY_EVIDENCE_POLICY")
    raw = policy.get("survivor_contract")
    if not isinstance(raw, Mapping):
        raise RuntimeError("FAMILY_CANARY_EVIDENCE_SURVIVOR_CONTRACT_MISSING")
    return _survivor_contract(raw)


def _request_rows(
    handoff: Mapping[str, Any] | None,
    batch: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(handoff, Mapping) or handoff.get("schema_version") != HANDOFF_SCHEMA:
        return []
    _authority_guard(handoff, "FAMILY_CANARY_HANDOFF")
    if handoff.get("state") != "PASS_AI_FAMILY_CANARY_HANDOFF_READY":
        return []
    if not isinstance(batch, Mapping):
        raise RuntimeError("FAMILY_CANARY_REQUEST_BATCH_MISSING")
    if batch.get("schema_version") != REQUEST_BATCH_SCHEMA or batch.get("state") != "PASS_INDEPENDENT_FAMILY_PAPER_CANARY_REQUEST_READY":
        raise RuntimeError("FAMILY_CANARY_REQUEST_BATCH_INVALID")
    _authority_guard(batch, "FAMILY_CANARY_REQUEST_BATCH")
    batch_receipt = _verified_receipt(batch, "REQUEST_BATCH")
    if str(handoff.get("request_receipt_sha256") or "") != batch_receipt:
        raise RuntimeError("FAMILY_CANARY_HANDOFF_REQUEST_RECEIPT_MISMATCH")
    rows = batch.get("requests")
    if not isinstance(rows, list) or len(rows) not in (1, 2):
        raise RuntimeError("FAMILY_CANARY_REQUEST_COUNT_INVALID")
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("FAMILY_CANARY_REQUEST_ROW_INVALID")
        if raw.get("schema_version") != REQUEST_SCHEMA or raw.get("state") != "READY_INDEPENDENT_FAMILY_PAPER_CANARY":
            raise RuntimeError("FAMILY_CANARY_REQUEST_STATE_INVALID")
        _authority_guard(raw, "FAMILY_CANARY_REQUEST")
        if raw.get("exchange_order_submitted") is not False:
            raise RuntimeError("FAMILY_CANARY_REQUEST_ORDER_INVALID")
        _verified_receipt(raw, "REQUEST")
        if list(raw.get("negative_controls") or []) != EXPECTED_CONTROLS:
            raise RuntimeError("FAMILY_CANARY_REQUEST_CONTROLS_DRIFT")
        independence = raw.get("independence_contract")
        if not isinstance(independence, Mapping):
            raise RuntimeError("FAMILY_CANARY_INDEPENDENCE_CONTRACT_MISSING")
        if independence.get("prospective_only") is not True or independence.get("admission_history_reuse_allowed") is not False:
            raise RuntimeError("FAMILY_CANARY_INDEPENDENCE_CONTRACT_INVALID")
        if list(map(str, independence.get("windows") or [])) != list(WINDOWS):
            raise RuntimeError("FAMILY_CANARY_REQUEST_WINDOWS_DRIFT")
        if _i(independence.get("not_before_ms"), "not_before_ms") <= 0:
            raise RuntimeError("FAMILY_CANARY_NOT_BEFORE_INVALID")
        if str(raw.get("template_id") or "") not in SUPPORTED_TEMPLATES:
            raise RuntimeError("FAMILY_CANARY_TEMPLATE_UNSUPPORTED")
        lineage = raw.get("lineage")
        if not isinstance(lineage, Mapping):
            raise RuntimeError("FAMILY_CANARY_REQUEST_LINEAGE_MISSING")
        for key in (
            "proposal_receipt_sha256",
            "template_sha256",
            "source_registry_sha256",
            "contract_receipt_sha256",
            "economic_result_receipt_sha256",
            "economic_batch_receipt_sha256",
        ):
            if len(str(lineage.get(key) or "")) != 64:
                raise RuntimeError(f"FAMILY_CANARY_REQUEST_LINEAGE_SHA_INVALID:{key}")
        out.append(dict(raw))
    return out


def _contract_map(contract_state: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(contract_state, Mapping):
        return {}
    if contract_state.get("schema_version") != CONTRACT_STATE_SCHEMA:
        raise RuntimeError("FAMILY_CANARY_CONTRACT_STATE_SCHEMA_INVALID")
    _authority_guard(contract_state, "FAMILY_CANARY_CONTRACT_STATE")
    out: dict[str, dict[str, Any]] = {}
    for raw in contract_state.get("contracts") or []:
        if not isinstance(raw, Mapping):
            continue
        cid = str(raw.get("contract_id") or "")
        if not cid or cid in out:
            raise RuntimeError("FAMILY_CANARY_CONTRACT_ID_INVALID")
        _authority_guard(raw, "FAMILY_CANARY_CONTRACT")
        _verified_receipt(raw, "CONTRACT")
        out[cid] = dict(raw)
    return out


def _template_row(template_registry: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    templates = template_registry.get("templates") if isinstance(template_registry, Mapping) else None
    tid = str(contract.get("template_id") or "")
    if not isinstance(templates, Mapping) or not isinstance(templates.get(tid), Mapping):
        raise RuntimeError("FAMILY_CANARY_TEMPLATE_MISSING")
    template = dict(templates[tid])
    if stable_sha(template) != str(contract.get("template_sha256") or ""):
        raise RuntimeError("FAMILY_CANARY_TEMPLATE_SHA_MISMATCH")
    validate_contract(contract, {"templates": {tid: template}})
    return template


def _canary_key(contract: Mapping[str, Any]) -> str:
    receipt = _verified_receipt(contract, "FROZEN_CONTRACT")
    return stable_sha({"contract_receipt_sha256": receipt})[:32]


def _empty_state(now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": "HOLD_FAMILY_CANARY_NO_ACTIVE_REQUEST",
        "action": "hold",
        "canaries": {},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }


def _load_state(state: Mapping[str, Any] | None, now_ms: int) -> dict[str, Any]:
    if state is None:
        return _empty_state(now_ms)
    if state.get("schema_version") != SCHEMA:
        raise RuntimeError("FAMILY_CANARY_EXISTING_STATE_SCHEMA_INVALID")
    _authority_guard(state, "FAMILY_CANARY_EXISTING_STATE")
    rows = state.get("canaries")
    if not isinstance(rows, Mapping):
        raise RuntimeError("FAMILY_CANARY_EXISTING_STATE_ROWS_INVALID")
    out = dict(state)
    out["canaries"] = {str(k): dict(v) for k, v in rows.items() if isinstance(v, Mapping)}
    return out


def _initialize_requests(
    state: dict[str, Any],
    requests: Sequence[Mapping[str, Any]],
    contract_state: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any],
    survivor_contract: Mapping[str, Any],
    risk_request: Mapping[str, Any],
    risk_policy_sha256: str,
    history_dir: Path,
    now_ms: int,
) -> int:
    contracts = _contract_map(contract_state)
    initialized = 0
    canaries = state["canaries"]
    for request in requests:
        cid = str(request.get("contract_id") or "")
        contract = contracts.get(cid)
        if contract is None:
            raise RuntimeError(f"FAMILY_CANARY_CONTRACT_NOT_FOUND:{cid}")
        lineage = request["lineage"]
        if str(lineage.get("contract_receipt_sha256") or "") != str(contract.get("receipt_sha256") or ""):
            raise RuntimeError("FAMILY_CANARY_CONTRACT_LINEAGE_MISMATCH")
        if str(lineage.get("template_sha256") or "") != str(contract.get("template_sha256") or ""):
            raise RuntimeError("FAMILY_CANARY_TEMPLATE_LINEAGE_MISMATCH")
        if str(request.get("family_id") or "") != str(contract.get("family_id") or ""):
            raise RuntimeError("FAMILY_CANARY_FAMILY_LINEAGE_MISMATCH")
        if str(request.get("template_id") or "") != str(contract.get("template_id") or ""):
            raise RuntimeError("FAMILY_CANARY_TEMPLATE_ID_LINEAGE_MISMATCH")
        embedded = request.get("survivor_contract")
        if not isinstance(embedded, Mapping) or dict(_survivor_contract(embedded)) != dict(survivor_contract):
            raise RuntimeError("FAMILY_CANARY_SURVIVOR_CONTRACT_MISMATCH")
        if str(request.get("survivor_contract_sha256") or "") != stable_sha(dict(survivor_contract)):
            raise RuntimeError("FAMILY_CANARY_SURVIVOR_CONTRACT_SHA_MISMATCH")
        template = _template_row(template_registry, contract)
        key = _canary_key(contract)
        request_receipt = str(request.get("receipt_sha256") or "")
        not_before = _i(request["independence_contract"].get("not_before_ms"), "not_before_ms")
        current = canaries.get(key)
        if current is not None:
            if str(current.get("contract_receipt_sha256") or "") != str(contract.get("receipt_sha256") or ""):
                raise RuntimeError("FAMILY_CANARY_EXISTING_CONTRACT_DRIFT")
            current["latest_request_id"] = str(request.get("request_id") or "")
            current["latest_request_receipt_sha256"] = request_receipt
            current["latest_request_not_before_ms"] = not_before
            current["last_seen_at_ms"] = now_ms
            continue
        family_id = str(contract.get("family_id") or "")
        template_id = str(contract.get("template_id") or "")
        canaries[key] = {
            "canary_key": key,
            "status": "ACCUMULATING",
            "family_id": family_id,
            "strategy_id": template_id,
            "alpha_id": f"{family_id}__{key[:16]}",
            "contract_id": cid,
            "contract_receipt_sha256": str(contract.get("receipt_sha256") or ""),
            "contract": dict(contract),
            "template": template,
            "proposal_id": str(request.get("proposal_id") or ""),
            "first_request_id": str(request.get("request_id") or ""),
            "first_request_receipt_sha256": request_receipt,
            "latest_request_id": str(request.get("request_id") or ""),
            "latest_request_receipt_sha256": request_receipt,
            "first_not_before_ms": not_before,
            "latest_request_not_before_ms": not_before,
            "execution_cost_bps": _f(request.get("execution_cost_bps"), "execution_cost_bps"),
            "survivor_contract": dict(survivor_contract),
            "survivor_contract_sha256": stable_sha(dict(survivor_contract)),
            "risk_request": dict(risk_request),
            "risk_policy_sha256": risk_policy_sha256,
            "initial_lineage": dict(lineage),
            "history_path": str(history_dir / f"{key}.ndjson"),
            "trade_count": 0,
            "result": None,
            "published": False,
            "consumed": False,
            "created_at_ms": now_ms,
            "last_seen_at_ms": now_ms,
        }
        initialized += 1
    return initialized


def _verify_history(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    not_before = _i(meta.get("first_not_before_ms"), "first_not_before_ms")
    cid = str(meta.get("contract_id") or "")
    key = str(meta.get("canary_key") or "")
    seen: set[tuple[str, int]] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("FAMILY_CANARY_HISTORY_ROW_INVALID")
        _authority_guard(raw, "FAMILY_CANARY_HISTORY")
        _verified_receipt(raw, "HISTORY")
        if str(raw.get("contract_id") or "") != cid:
            raise RuntimeError("FAMILY_CANARY_HISTORY_CONTRACT_MISMATCH")
        if str(raw.get("canary_key") or "") != key:
            raise RuntimeError("FAMILY_CANARY_HISTORY_KEY_MISMATCH")
        observed = _i(raw.get("observed_at_ms"), "history.observed_at_ms")
        if observed < not_before:
            raise RuntimeError("FAMILY_CANARY_HISTORY_PRE_REQUEST_CONTAMINATION")
        identity = (str(raw.get("symbol") or ""), _i(raw.get("outcome_candle_ts_ms"), "history.outcome_candle_ts_ms"))
        if identity in seen:
            raise RuntimeError("FAMILY_CANARY_HISTORY_DUPLICATE")
        seen.add(identity)
        out.append(dict(raw))
    return out


def _new_observations(
    meta: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    symbols: Sequence[str],
) -> list[dict[str, Any]]:
    contract = meta.get("contract")
    template = meta.get("template")
    if not isinstance(contract, Mapping) or not isinstance(template, Mapping):
        raise RuntimeError("FAMILY_CANARY_FROZEN_CONTRACT_MISSING")
    validate_contract(contract, {"templates": {str(contract.get("template_id") or ""): dict(template)}})
    built = build_observations(contract, l2_snapshot, carry_snapshot, candles_by_symbol, symbols, history)
    not_before = _i(meta.get("first_not_before_ms"), "first_not_before_ms")
    existing = {(str(x.get("symbol") or ""), _i(x.get("outcome_candle_ts_ms"), "outcome_candle_ts_ms")) for x in history}
    out: list[dict[str, Any]] = []
    for raw in built:
        row = dict(raw)
        if _i(row.get("observed_at_ms"), "observed_at_ms") < not_before:
            continue
        identity = (str(row.get("symbol") or ""), _i(row.get("outcome_candle_ts_ms"), "outcome_candle_ts_ms"))
        if identity in existing:
            continue
        row["canary_key"] = str(meta.get("canary_key") or "")
        row["canary_first_request_id"] = str(meta.get("first_request_id") or "")
        row["canary_not_before_ms"] = not_before
        row["receipt_sha256"] = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
        out.append(row)
        existing.add(identity)
    return out


def _trade_rows(history: Sequence[Mapping[str, Any]], cost_bps: float, risk_request: Mapping[str, Any]) -> list[dict[str, Any]]:
    leverage = _i(risk_request.get("leverage_x"), "risk_request.leverage_x")
    position_pct = _f(risk_request.get("position_pct"), "risk_request.position_pct")
    exposure_fraction = leverage * position_pct / 100.0
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for raw in history:
        by_symbol.setdefault(str(raw.get("symbol") or ""), []).append(dict(raw))
    trades: list[dict[str, Any]] = []
    for symbol, rows in by_symbol.items():
        xs = sorted(rows, key=lambda x: (_i(x.get("outcome_candle_ts_ms"), "outcome_candle_ts_ms"), _i(x.get("observed_at_ms"), "observed_at_ms")))
        for cur, nxt in zip(xs, xs[1:]):
            if cur.get("context_pass") is not True:
                continue
            side = int(cur.get("signal_side") or cur.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            entry = _f(cur.get("outcome_close"), "entry_close")
            exit_ = _f(nxt.get("outcome_close"), "exit_close")
            if entry <= 0 or exit_ <= 0:
                raise RuntimeError("FAMILY_CANARY_PRICE_NONPOSITIVE")
            gross_bps = side * (exit_ / entry - 1.0) * 10_000.0
            net_bps = gross_bps - cost_bps
            equity_return_pct = net_bps / 100.0 * exposure_fraction
            trades.append({
                "symbol": symbol,
                "side": side,
                "entry_ts_ms": _i(cur.get("outcome_candle_ts_ms"), "entry_ts_ms"),
                "exit_ts_ms": _i(nxt.get("outcome_candle_ts_ms"), "exit_ts_ms"),
                "gross_bps": gross_bps,
                "net_bps": net_bps,
                "equity_return_pct": equity_return_pct,
                "entry_observation_receipt_sha256": str(cur.get("receipt_sha256") or ""),
                "exit_observation_receipt_sha256": str(nxt.get("receipt_sha256") or ""),
            })
    trades.sort(key=lambda x: (int(x["exit_ts_ms"]), str(x["symbol"]), int(x["entry_ts_ms"])))
    return trades


def _stats(values: Sequence[float]) -> dict[str, float]:
    vals = [float(x) for x in values]
    wins = [x for x in vals if x > 0.0]
    losses = [x for x in vals if x < 0.0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else (999.0 if gross_profit > 0.0 else 0.0)
    payoff_ratio = avg_win / avg_loss if avg_loss > 0.0 else (999.0 if avg_win > 0.0 else 0.0)
    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    for value in vals:
        equity *= 1.0 + value / 100.0
        if equity <= 0.0:
            equity = 0.0
            max_dd = 100.0
            break
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    return {
        "trade_count": float(len(vals)),
        "net_pnl": equity - 100.0,
        "expectancy": sum(vals) / len(vals) if vals else 0.0,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "max_dd_pct": max_dd,
    }


def _source_hashes(history: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> list[str]:
    hashes: set[str] = set()
    for row in history:
        for key, value in row.items():
            if key.endswith("_sha256") and len(str(value or "")) == 64:
                hashes.add(str(value))
    lineage = meta.get("initial_lineage")
    if isinstance(lineage, Mapping):
        for value in lineage.values():
            if len(str(value or "")) == 64:
                hashes.add(str(value))
    for key in ("contract_receipt_sha256", "risk_policy_sha256", "survivor_contract_sha256"):
        value = str(meta.get(key) or "")
        if len(value) == 64:
            hashes.add(value)
    return sorted(hashes)


def evaluate_canary(meta: Mapping[str, Any], history: Sequence[Mapping[str, Any]], trades_per_window: int = 60) -> dict[str, Any] | None:
    risk = meta.get("risk_request")
    contract = meta.get("survivor_contract")
    if not isinstance(risk, Mapping) or not isinstance(contract, Mapping):
        raise RuntimeError("FAMILY_CANARY_EVALUATION_POLICY_MISSING")
    frozen_contract = _survivor_contract(contract)
    trades = _trade_rows(history, _f(meta.get("execution_cost_bps"), "execution_cost_bps"), risk)
    required = trades_per_window * len(WINDOWS)
    if len(trades) < required:
        return None
    frozen_trades = trades[:required]
    values = [float(x["equity_return_pct"]) for x in frozen_trades]
    windows: dict[str, dict[str, Any]] = {}
    raw_stats: dict[str, dict[str, float]] = {}
    for idx, name in enumerate(WINDOWS):
        start = idx * trades_per_window
        stop = start + trades_per_window
        raw_stats[name] = _stats(values[start:stop])
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
    aggregate = _stats(values)
    economic_gate = all(
        windows[name]["net_pnl"] > float(frozen_contract["min_net_pnl_exclusive"])
        and windows[name]["profit_factor"] >= float(frozen_contract["min_profit_factor"])
        and windows[name]["expectancy"] > float(frozen_contract["min_expectancy_exclusive"])
        and windows[name]["payoff_ratio"] >= float(frozen_contract["min_payoff_ratio"])
        for name in WINDOWS
    ) and aggregate["net_pnl"] > 0.0 and aggregate["expectancy"] > 0.0 and aggregate["profit_factor"] >= 1.0
    durability_gate = all(windows[name]["retention"] >= float(frozen_contract["min_retention"]) for name in WINDOWS)
    source_hashes = _source_hashes(history, meta)
    integrity_gate = (
        all(windows[name]["trade_count"] == trades_per_window for name in WINDOWS)
        and int(aggregate["trade_count"]) == required
        and bool(source_hashes)
        and aggregate["max_dd_pct"] <= float(frozen_contract["max_dd_pct"])
    )
    passed = economic_gate and durability_gate and integrity_gate
    result = {
        "schema_version": RESULT_SCHEMA,
        "state": "PASS_FAMILY_PAPER_CANARY" if passed else "REJECT_FAMILY_PAPER_CANARY",
        "economic_gate_pass": economic_gate,
        "durability_gate_pass": durability_gate,
        "integrity_pass": integrity_gate,
        "family_id": str(meta.get("family_id") or ""),
        "strategy_id": str(meta.get("strategy_id") or ""),
        "alpha_id": str(meta.get("alpha_id") or ""),
        "canary_key": str(meta.get("canary_key") or ""),
        "contract_id": str(meta.get("contract_id") or ""),
        "source_hashes": source_hashes,
        "risk_request": {"leverage_x": _i(risk.get("leverage_x"), "leverage_x"), "position_pct": _f(risk.get("position_pct"), "position_pct")},
        "windows": windows,
        "metrics": {
            "trade_count": int(aggregate["trade_count"]),
            "net_expectancy": aggregate["expectancy"],
            "profit_factor": aggregate["profit_factor"],
            "net_pnl": aggregate["net_pnl"],
            "max_dd_pct": aggregate["max_dd_pct"],
        },
        "retention_semantics": "WINDOW_EXPECTANCY_DIV_W1_EXPECTANCY",
        "execution_cost_bps": _f(meta.get("execution_cost_bps"), "execution_cost_bps"),
        "prospective_only": True,
        "admission_history_reuse_allowed": False,
        "first_not_before_ms": _i(meta.get("first_not_before_ms"), "first_not_before_ms"),
        "first_request_receipt_sha256": str(meta.get("first_request_receipt_sha256") or ""),
        "contract_receipt_sha256": str(meta.get("contract_receipt_sha256") or ""),
        "survivor_contract_sha256": str(meta.get("survivor_contract_sha256") or ""),
        "parameter_search_performed": False,
        "numeric_signal_threshold_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def _result_consumed(current_result: Mapping[str, Any] | None, evidence: Mapping[str, Any] | None) -> bool:
    if not isinstance(current_result, Mapping):
        return True
    receipt = str(current_result.get("receipt_sha256") or "")
    if len(receipt) != 64:
        return False
    if not isinstance(evidence, Mapping) or evidence.get("schema_version") != EVIDENCE_SCHEMA:
        return False
    return str(evidence.get("canary_receipt_sha256") or "") == receipt


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
    state = _load_state(existing_state, now)
    survivor_contract = _family_survivor_contract(family_evidence_policy)
    risk_request, risk_sha = _risk_request(risk_policy)
    requests = _request_rows(handoff_state, request_batch)
    initialized = _initialize_requests(
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

    if isinstance(current_result, Mapping) and _result_consumed(current_result, evidence):
        current_receipt = str(current_result.get("receipt_sha256") or "")
        for meta in state["canaries"].values():
            result = meta.get("result")
            if isinstance(result, Mapping) and str(result.get("receipt_sha256") or "") == current_receipt:
                meta["consumed"] = True

    appends: dict[str, list[dict[str, Any]]] = {}
    active = 0
    newly_terminal: list[dict[str, Any]] = []
    for key in sorted(state["canaries"]):
        meta = state["canaries"][key]
        if str(meta.get("status") or "") != "ACCUMULATING":
            continue
        active += 1
        history = _verify_history(list(histories.get(key) or []), meta)
        new_rows = _new_observations(meta, history, l2_snapshot, carry_snapshot, candles_by_symbol, cfg["symbols"])
        merged = _verify_history(history + new_rows, meta)
        if new_rows:
            appends[key] = new_rows
        result = evaluate_canary(meta, merged, int(cfg["trades_per_window"]))
        meta["trade_count"] = len(_trade_rows(merged, _f(meta.get("execution_cost_bps"), "execution_cost_bps"), meta["risk_request"]))
        meta["observation_count"] = len(merged)
        meta["updated_at_ms"] = now
        if result is not None:
            meta["result"] = result
            meta["status"] = "PASS" if result["state"] == "PASS_FAMILY_PAPER_CANARY" else "REJECT"
            meta["terminal_at_ms"] = now
            newly_terminal.append(result)

    publish: dict[str, Any] | None = None
    terminal_reject: dict[str, Any] | None = None
    current_unconsumed = isinstance(current_result, Mapping) and not _result_consumed(current_result, evidence)
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
    ap = argparse.ArgumentParser(description="Independent prospective family PAPER canary runner")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg_raw = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = validate_policy(cfg_raw)
    existing_state = read_json(Path(str(cfg["state_path"])))
    histories: dict[str, list[dict[str, Any]]] = {}
    if isinstance(existing_state, Mapping) and isinstance(existing_state.get("canaries"), Mapping):
        for key, meta in existing_state["canaries"].items():
            if isinstance(meta, Mapping):
                histories[str(key)] = read_history(Path(str(meta.get("history_path") or Path(str(cfg["history_dir"])) / f"{key}.ndjson")))
    candles = asyncio.run(_fetch_candles(cfg["symbols"]))
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
        append_observations(Path(str(meta["history_path"])), rows)
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if result is not None:
        atomic_json_write(Path(str(cfg["result_path"])), result)
    if terminal is not None:
        atomic_json_write(Path(str(cfg["terminal_result_path"])), terminal)
    print(json.dumps({
        "state": state["state"],
        "active_count": state["active_count"],
        "pass_count": state["pass_count"],
        "reject_count": state["reject_count"],
        "published_result": state["published_result"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
