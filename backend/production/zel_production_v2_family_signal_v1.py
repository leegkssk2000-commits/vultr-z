from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_ai_admission_executor_v1 import _authority_guard, _basis_rows, _l2_rows, read_history
from backend.production.zel_production_ai_admission_executor_v2 import (
    BASIS_OI_TEMPLATE,
    FUNDING_L2_TEMPLATE,
    L2_TEMPLATE,
    SUPPORTED_TEMPLATES,
    _carry_maps,
)
from backend.production.zel_production_improvement_controller_v1 import read_json, stable_sha

SCHEMA = "zel.production_v2_family_signal.v1"
SIGNAL_SCHEMA = "zel.production_alpha_signal.v1"
POLICY_SCHEMA = "zel.production_v2_family_signal_policy.v1"
CANARY_STATE_SCHEMA = "zel.production_family_paper_canary_runner.v1"
DEFAULT_POLICY = Path("config/zel_production_v2_family_signal_v1.json")
SUPPORTED_STRATEGIES = frozenset(SUPPORTED_TEMPLATES)
SUPPORTED_SYMBOLS = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}


def _f(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"V2_FAMILY_SIGNAL_NUMERIC_NONFINITE:{name}")
    return out


def _i(value: Any, name: str) -> int:
    out = _f(value, name)
    if not out.is_integer():
        raise RuntimeError(f"V2_FAMILY_SIGNAL_INTEGER_INVALID:{name}")
    return int(out)


def _sign(value: float) -> int:
    return 1 if value > 0.0 else -1 if value < 0.0 else 0


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_{label}_RECEIPT_MISMATCH")
    return claimed


def _symbol(value: Any) -> tuple[str, str]:
    compact = str(value or "").replace("-", "").upper()
    native = SUPPORTED_SYMBOLS.get(compact)
    if native is None:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_SYMBOL_UNSUPPORTED:{compact or 'MISSING'}")
    return compact, native


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("V2_FAMILY_SIGNAL_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("V2_FAMILY_SIGNAL_NON_PAPER_FORBIDDEN")
    for key in ("canary_state_path", "l2_snapshot_path", "carry_snapshot_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"V2_FAMILY_SIGNAL_PATH_MISSING:{key}")
    if set(map(str, policy.get("supported_strategy_ids") or [])) != set(SUPPORTED_STRATEGIES):
        raise RuntimeError("V2_FAMILY_SIGNAL_STRATEGY_SET_DRIFT")
    if policy.get("numeric_signal_thresholds") != [] or policy.get("parameter_search") is not False:
        raise RuntimeError("V2_FAMILY_SIGNAL_SEARCH_FORBIDDEN")
    if policy.get("execution_authority") != "PAPER_SIGNAL_ONLY":
        raise RuntimeError("V2_FAMILY_SIGNAL_EXECUTION_AUTHORITY_INVALID")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("V2_FAMILY_SIGNAL_LIVE_AUTHORITY_FORBIDDEN")
    return dict(policy)


def _stale_ms(policy: Mapping[str, Any]) -> float:
    raw = policy.get("data_stale_ms")
    if raw is None:
        env_map = policy.get("required_env_when_null")
        env_name = env_map.get("data_stale_ms") if isinstance(env_map, Mapping) else None
        if not env_name:
            raise RuntimeError("V2_FAMILY_SIGNAL_STALE_UNBOUND")
        raw = os.environ.get(str(env_name))
        if raw is None or not str(raw).strip():
            raise RuntimeError(f"V2_FAMILY_SIGNAL_STALE_ENV_UNBOUND:{env_name}")
    value = _f(raw, "data_stale_ms")
    if value <= 0.0:
        raise RuntimeError("V2_FAMILY_SIGNAL_STALE_NONPOSITIVE")
    return value


def _snapshot_age(snapshot: Mapping[str, Any], label: str, *, now_ms: int, max_stale_ms: float) -> tuple[int, str]:
    _authority_guard(snapshot, f"V2_FAMILY_SIGNAL_{label}")
    receipt = _verified_receipt(snapshot, label)
    observed = _i(snapshot.get("observed_at_ms"), f"{label}.observed_at_ms")
    age = now_ms - observed
    if age < 0:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_{label}_FUTURE")
    if age > max_stale_ms:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_{label}_STALE:{age}")
    return observed, receipt


def _authority_lineage(authority: Mapping[str, Any]) -> dict[str, str]:
    strategy_id = str(authority.get("strategy_id") or "")
    if strategy_id not in SUPPORTED_STRATEGIES:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_STRATEGY_UNSUPPORTED:{strategy_id or 'MISSING'}")
    alpha_id = str(authority.get("alpha_id") or "")
    family_id = str(authority.get("family_id") or "")
    contract_id = str(authority.get("contract_id") or "")
    canary_key = str(authority.get("canary_key") or "")
    contract_receipt = str(authority.get("contract_receipt_sha256") or "")
    if not alpha_id or not family_id or not contract_id or not canary_key or len(contract_receipt) != 64:
        raise RuntimeError("V2_FAMILY_SIGNAL_AUTHORITY_LINEAGE_INCOMPLETE")
    return {
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "family_id": family_id,
        "contract_id": contract_id,
        "canary_key": canary_key,
        "contract_receipt_sha256": contract_receipt,
    }


def _passed_canary(authority: Mapping[str, Any], canary_state: Mapping[str, Any]) -> dict[str, Any]:
    lineage = _authority_lineage(authority)
    if canary_state.get("schema_version") != CANARY_STATE_SCHEMA:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_STATE_SCHEMA_INVALID")
    _authority_guard(canary_state, "V2_FAMILY_SIGNAL_CANARY_STATE")
    _verified_receipt(canary_state, "CANARY_STATE")
    rows = canary_state.get("canaries")
    raw = rows.get(lineage["canary_key"]) if isinstance(rows, Mapping) else None
    if not isinstance(raw, Mapping):
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_NOT_FOUND")
    if str(raw.get("status") or "") != "PASS":
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_NOT_PASS")
    if str(raw.get("family_id") or "") != lineage["family_id"]:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_FAMILY_MISMATCH")
    if str(raw.get("strategy_id") or "") != lineage["strategy_id"]:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_STRATEGY_MISMATCH")
    if str(raw.get("contract_id") or "") != lineage["contract_id"]:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_CONTRACT_MISMATCH")
    if str(raw.get("contract_receipt_sha256") or "") != lineage["contract_receipt_sha256"]:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_CONTRACT_RECEIPT_MISMATCH")
    result = raw.get("result")
    if not isinstance(result, Mapping) or result.get("state") != "PASS_FAMILY_PAPER_CANARY":
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_RESULT_NOT_PASS")
    _verified_receipt(result, "CANARY_RESULT")
    expected = {
        "family_id": lineage["family_id"],
        "strategy_id": lineage["strategy_id"],
        "alpha_id": lineage["alpha_id"],
        "canary_key": lineage["canary_key"],
        "contract_id": lineage["contract_id"],
        "contract_receipt_sha256": lineage["contract_receipt_sha256"],
    }
    for key, value in expected.items():
        if str(result.get(key) or "") != value:
            raise RuntimeError(f"V2_FAMILY_SIGNAL_CANARY_RESULT_LINEAGE_MISMATCH:{key}")
    if result.get("prospective_only") is not True or result.get("admission_history_reuse_allowed") is not False:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_INDEPENDENCE_INVALID")
    return dict(raw)


def _latest_history(history: Sequence[Mapping[str, Any]], contract_id: str, native_symbol: str) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for raw in history:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("contract_id") or "") != contract_id or str(raw.get("symbol") or "") != native_symbol:
            continue
        _authority_guard(raw, "V2_FAMILY_SIGNAL_HISTORY")
        _verified_receipt(raw, "HISTORY")
        rows.append(dict(raw))
    if not rows:
        return None
    rows.sort(key=lambda x: (_i(x.get("observed_at_ms"), "history.observed_at_ms"), _i(x.get("outcome_candle_ts_ms"), "history.outcome_candle_ts_ms")))
    return rows[-1]


def _verified_prior_signal(prior: Mapping[str, Any] | None, lineage: Mapping[str, str], compact_symbol: str) -> dict[str, Any] | None:
    if not isinstance(prior, Mapping):
        return None
    if prior.get("schema_version") != SIGNAL_SCHEMA or prior.get("state") != "PASS_ACTIVE_ALPHA_SIGNAL":
        return None
    if str(prior.get("strategy_id") or "") != lineage["strategy_id"] or str(prior.get("alpha_id") or "") != lineage["alpha_id"]:
        return None
    if str(prior.get("symbol") or "").replace("-", "").upper() != compact_symbol:
        return None
    for key in ("family_id", "contract_id", "canary_key", "contract_receipt_sha256"):
        if str(prior.get(key) or "") != lineage[key]:
            return None
    _verified_receipt(prior, "PRIOR_SIGNAL")
    return dict(prior)


def _reuse_if_same_source(prior: Mapping[str, Any] | None, relevant_receipts: Sequence[str]) -> dict[str, Any] | None:
    if not isinstance(prior, Mapping):
        return None
    source = prior.get("source")
    prior_receipts = source.get("snapshot_receipts") if isinstance(source, Mapping) else None
    if isinstance(prior_receipts, list) and list(map(str, prior_receipts)) == list(map(str, relevant_receipts)):
        return dict(prior)
    return None


def _signal_name(side: int) -> str:
    return "LONG" if side > 0 else "SHORT" if side < 0 else "EXIT"


def _base_signal(
    *,
    lineage: Mapping[str, str],
    compact_symbol: str,
    native_symbol: str,
    side: int,
    signal_ts: int,
    features: Mapping[str, Any],
    source_hashes: Sequence[str],
    snapshot_receipts: Sequence[str],
    canary_result_receipt: str,
) -> dict[str, Any]:
    hashes = sorted({str(x) for x in source_hashes if len(str(x)) == 64})
    if not hashes:
        raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_HASHES_EMPTY")
    row: dict[str, Any] = {
        "schema_version": SIGNAL_SCHEMA,
        "producer_schema_version": SCHEMA,
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": lineage["strategy_id"],
        "alpha_id": lineage["alpha_id"],
        "family": lineage["family_id"],
        "family_id": lineage["family_id"],
        "contract_id": lineage["contract_id"],
        "canary_key": lineage["canary_key"],
        "contract_receipt_sha256": lineage["contract_receipt_sha256"],
        "symbol": compact_symbol,
        "signal": _signal_name(side),
        "signal_ts": signal_ts,
        "timeframe": "1h",
        "features": dict(features),
        "source": {
            "provider": "verified_native_bingx_snapshots",
            "native_symbol": native_symbol,
            "snapshot_receipts": list(snapshot_receipts),
            "canary_result_receipt_sha256": canary_result_receipt,
            "dummy_fallback_used": False,
        },
        "source_hashes": hashes,
        "promotion_authority": False,
        "execution_authority": "PAPER_SIGNAL_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def build_signal(
    authority: Mapping[str, Any],
    *,
    canary_state: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    l2_snapshot: Mapping[str, Any] | None,
    carry_snapshot: Mapping[str, Any] | None,
    prior_signal: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
    max_stale_ms: float,
) -> dict[str, Any]:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    lineage = _authority_lineage(authority)
    compact_symbol, native_symbol = _symbol(authority.get("symbol"))
    canary = _passed_canary(authority, canary_state)
    result = canary["result"]
    result_receipt = str(result["receipt_sha256"])
    prior = _verified_prior_signal(prior_signal, lineage, compact_symbol)

    strategy_id = lineage["strategy_id"]
    relevant_receipts: list[str] = []
    source_hashes = [lineage["contract_receipt_sha256"], result_receipt]
    observed: list[int] = []
    features: dict[str, Any] = {"context_pass": False, "signal_side": 0}
    side = 0

    if strategy_id == L2_TEMPLATE:
        if not isinstance(l2_snapshot, Mapping) or not isinstance(carry_snapshot, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SNAPSHOT_MISSING")
        l2_observed, l2_receipt = _snapshot_age(l2_snapshot, "L2", now_ms=now, max_stale_ms=max_stale_ms)
        carry_observed, carry_receipt = _snapshot_age(carry_snapshot, "CARRY", now_ms=now, max_stale_ms=max_stale_ms)
        relevant_receipts = [l2_receipt, carry_receipt]
        reused = _reuse_if_same_source(prior, relevant_receipts)
        if reused is not None:
            return reused
        l2 = _l2_rows(l2_snapshot)
        basis = _basis_rows(carry_snapshot)
        if native_symbol not in l2 or native_symbol not in basis:
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SYMBOL_MISSING")
        lr, br = l2[native_symbol], basis[native_symbol]
        derived = br.get("derived_observation")
        if not isinstance(derived, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_BASIS_DERIVED_MISSING")
        imbalance = _f(lr.get("imbalance_returned_book"), "imbalance_returned_book")
        primary_sign = int(lr.get("primary_imbalance_sign") or 0)
        basis_bps = _f(derived.get("basis_bps"), "basis_bps")
        basis_sign = _sign(basis_bps)
        context_pass = primary_sign != 0 and basis_sign == primary_sign
        side = primary_sign if context_pass else 0
        features.update({"context_pass": context_pass, "signal_side": side, "primary_imbalance_sign": primary_sign, "imbalance_returned_book": imbalance, "basis_bps": basis_bps, "basis_sign": basis_sign})
        source_hashes.extend([str(lr.get("source_payload_sha256") or ""), str(br.get("source_payload_sha256") or ""), l2_receipt, carry_receipt])
        observed.extend([l2_observed, carry_observed])

    elif strategy_id == FUNDING_L2_TEMPLATE:
        if not isinstance(l2_snapshot, Mapping) or not isinstance(carry_snapshot, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SNAPSHOT_MISSING")
        l2_observed, l2_receipt = _snapshot_age(l2_snapshot, "L2", now_ms=now, max_stale_ms=max_stale_ms)
        carry_observed, carry_receipt = _snapshot_age(carry_snapshot, "CARRY", now_ms=now, max_stale_ms=max_stale_ms)
        relevant_receipts = [l2_receipt, carry_receipt]
        reused = _reuse_if_same_source(prior, relevant_receipts)
        if reused is not None:
            return reused
        l2 = _l2_rows(l2_snapshot)
        premium, _ = _carry_maps(carry_snapshot)
        if native_symbol not in l2 or native_symbol not in premium:
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SYMBOL_MISSING")
        lr, pr = l2[native_symbol], premium[native_symbol]
        raw = pr.get("raw")
        if not isinstance(raw, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_FUNDING_RAW_MISSING")
        funding_rate = _f(raw.get("lastFundingRate"), "lastFundingRate")
        funding_sign = _sign(funding_rate)
        imbalance_sign = int(lr.get("primary_imbalance_sign") or 0)
        imbalance = _f(lr.get("imbalance_returned_book"), "imbalance_returned_book")
        context_pass = funding_sign != 0 and imbalance_sign == funding_sign
        side = -funding_sign if context_pass else 0
        features.update({"context_pass": context_pass, "signal_side": side, "funding_rate": funding_rate, "funding_sign": funding_sign, "primary_imbalance_sign": imbalance_sign, "imbalance_returned_book": imbalance})
        source_hashes.extend([str(pr.get("source_payload_sha256") or ""), str(lr.get("source_payload_sha256") or ""), carry_receipt, l2_receipt])
        observed.extend([l2_observed, carry_observed])

    elif strategy_id == BASIS_OI_TEMPLATE:
        if not isinstance(carry_snapshot, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SNAPSHOT_MISSING")
        carry_observed, carry_receipt = _snapshot_age(carry_snapshot, "CARRY", now_ms=now, max_stale_ms=max_stale_ms)
        relevant_receipts = [carry_receipt]
        reused = _reuse_if_same_source(prior, relevant_receipts)
        if reused is not None:
            return reused
        premium, oi = _carry_maps(carry_snapshot)
        if native_symbol not in premium or native_symbol not in oi:
            raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SYMBOL_MISSING")
        pr, orow = premium[native_symbol], oi[native_symbol]
        derived = pr.get("derived_observation")
        raw_oi = orow.get("raw")
        if not isinstance(derived, Mapping) or not isinstance(raw_oi, Mapping):
            raise RuntimeError("V2_FAMILY_SIGNAL_BASIS_OI_FIELDS_MISSING")
        basis_bps = _f(derived.get("basis_bps"), "basis_bps")
        open_interest = _f(raw_oi.get("openInterest"), "openInterest")
        prev_basis: float | None = None
        prev_oi: float | None = None
        if isinstance(prior, Mapping):
            pfeatures = prior.get("features")
            if isinstance(pfeatures, Mapping) and "basis_bps" in pfeatures and "open_interest" in pfeatures:
                prev_basis = _f(pfeatures.get("basis_bps"), "prior.basis_bps")
                prev_oi = _f(pfeatures.get("open_interest"), "prior.open_interest")
        if prev_basis is None or prev_oi is None:
            prev = _latest_history(history, lineage["contract_id"], native_symbol)
            if prev is not None and "basis_bps" in prev and "open_interest" in prev:
                prev_basis = _f(prev.get("basis_bps"), "history.basis_bps")
                prev_oi = _f(prev.get("open_interest"), "history.open_interest")
        if prev_basis is None or prev_oi is None:
            context_pass = False
            basis_delta = 0.0
            oi_delta = 0.0
            side = 0
        else:
            basis_delta = basis_bps - prev_basis
            oi_delta = open_interest - prev_oi
            basis_change_sign = _sign(basis_delta)
            context_pass = oi_delta > 0.0 and basis_change_sign != 0
            side = -basis_change_sign if context_pass else 0
        features.update({"context_pass": context_pass, "signal_side": side, "basis_bps": basis_bps, "open_interest": open_interest, "basis_delta_bps": basis_delta, "open_interest_delta": oi_delta})
        source_hashes.extend([str(pr.get("source_payload_sha256") or ""), str(orow.get("source_payload_sha256") or ""), carry_receipt])
        observed.append(carry_observed)

    else:
        raise RuntimeError(f"V2_FAMILY_SIGNAL_STRATEGY_UNSUPPORTED:{strategy_id}")

    if any(len(str(x)) != 64 for x in source_hashes):
        raise RuntimeError("V2_FAMILY_SIGNAL_SOURCE_SHA_INVALID")
    signal_ts = min(observed) if observed else now
    return _base_signal(
        lineage=lineage,
        compact_symbol=compact_symbol,
        native_symbol=native_symbol,
        side=side,
        signal_ts=signal_ts,
        features=features,
        source_hashes=source_hashes,
        snapshot_receipts=relevant_receipts,
        canary_result_receipt=result_receipt,
    )


def generate_runtime_signal(
    authority: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    prior_signal: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(dict(policy) if policy is not None else json.loads(DEFAULT_POLICY.read_text(encoding="utf-8")))
    canary_state = read_json(Path(str(cfg["canary_state_path"])), required=True)
    if canary_state is None:
        raise RuntimeError("V2_FAMILY_SIGNAL_CANARY_STATE_MISSING")
    canary = _passed_canary(authority, canary_state)
    history_path = str(canary.get("history_path") or "")
    if not history_path:
        raise RuntimeError("V2_FAMILY_SIGNAL_HISTORY_PATH_MISSING")
    history = read_history(Path(history_path))
    if prior_signal is None:
        signal_path = str(cfg.get("active_signal_path") or "")
        if signal_path:
            prior_signal = read_json(Path(signal_path))
    return build_signal(
        authority,
        canary_state=canary_state,
        history=history,
        l2_snapshot=read_json(Path(str(cfg["l2_snapshot_path"]))),
        carry_snapshot=read_json(Path(str(cfg["carry_snapshot_path"]))),
        prior_signal=prior_signal,
        now_ms=now_ms,
        max_stale_ms=_stale_ms(cfg),
    )
