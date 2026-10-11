"""Frozen INTERNAL_BASELINE adapter for Issue 1388.

This module is research-only.  It implements the exact causal lifecycle in
PREFLIGHT_CONTRACT.json and cannot place an order or promote a strategy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


CANDIDATE_ID = "IB_THREE_RED_REVERSAL_1H_24H_V1"
CONTRACT_RELATIVE = Path(
    "research/campaigns/scalp7_20261011/"
    "issue1388_internal_three_red_reversal_v1/PREFLIGHT_CONTRACT.json"
)
RECEIPT_RELATIVE = CONTRACT_RELATIVE.with_name("PREFLIGHT_RECEIPT.json")
CONTRACT_SHA256 = "62f3605f5eef01fe80ea680ec76ff8d04515178bd557738da9abefdc08134925"
RECEIPT_SHA256 = "d89293a41aa77e84f0dc8a4cf45486446fd4f46c91eaa10843b62283edf90e3d"
EXTRA_FUNDING_RESERVE_BPS = 2.0
TOTAL_FUNDING_RESERVE_BPS = 3.0
HOLD_BARS = 24


class ContractError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(root: Path) -> dict[str, Any]:
    contract_path = root / CONTRACT_RELATIVE
    receipt_path = root / RECEIPT_RELATIVE
    if _sha256(contract_path) != CONTRACT_SHA256:
        raise ContractError("THREE_RED_FROZEN_CONTRACT_DRIFT")
    if _sha256(receipt_path) != RECEIPT_SHA256:
        raise ContractError("THREE_RED_PREFLIGHT_RECEIPT_DRIFT")
    contract = json.loads(contract_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    required = {
        "schema": "issue1388.internal_baseline.contract.v1",
        "owner": "CLOUD_WORK_COORDINATOR_ISSUE1358_V1",
        "strategy_id": CANDIDATE_ID,
        "classification": "INTERNAL_BASELINE_DEV_ONLY",
        "donor_attribution": None,
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise ContractError("THREE_RED_CONTRACT_BINDING")
    if (
        receipt.get("strategy_id") != CANDIDATE_ID
        or receipt.get("contract_blob_sha") != "9bee79f506ed6bb6934fb10c4add6e1d60a4d47e"
        or receipt.get("preflight", {}).get("density_gate") != "PASS_137_CLOSED_GT_20"
        or receipt.get("preflight", {}).get("economic_result_computed") is not False
        or receipt.get("totals", {}).get("closed_density") != 137
        or receipt.get("pnl_metrics") is not None
    ):
        raise ContractError("THREE_RED_PREFLIGHT_BINDING")
    return contract


def _bar_is_bearish(bar: Mapping[str, Any]) -> bool:
    return float(bar["close"]) < float(bar["open"])


def replay_symbol(
    symbol: str,
    frame: pd.DataFrame,
    reference_cost_bps: float,
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    """Replay the frozen next-open/stop-first/24h lifecycle for one symbol."""
    rows = frame.to_dict("records")
    trades: list[dict[str, Any]] = []
    raw_signals = 0
    admitted = 0
    missed_occupied = 0
    missed_gap_invalid = 0
    missing_fill_evidence = 0
    gap_quarantined = 0
    censored = 0
    active_until = -1

    for i in range(2, len(rows) - 1):
        a, b, c = rows[i - 2], rows[i - 1], rows[i]
        if int(c["close_ts_ms"]) >= end_ms:
            break
        if not (
            a["segment_id"] == b["segment_id"] == c["segment_id"]
            and _bar_is_bearish(a)
            and _bar_is_bearish(b)
            and _bar_is_bearish(c)
            and float(a["close"]) > float(b["close"]) > float(c["close"])
        ):
            continue
        entry_i = i + 1
        entry = rows[entry_i]
        if int(entry["open_ts_ms"]) < start_ms:
            continue
        raw_signals += 1
        if i <= active_until:
            missed_occupied += 1
            continue
        if entry["segment_id"] != c["segment_id"]:
            gap_quarantined += 1
            active_until = entry_i
            continue
        signal_available_ms = max(int(c["close_ts_ms"]), int(c["available_ts_ms"]))
        if signal_available_ms > int(entry["open_ts_ms"]):
            missing_fill_evidence += 1
            continue
        stop = min(float(a["low"]), float(b["low"]), float(c["low"]))
        entry_price = float(entry["open"])
        if entry_price <= stop:
            missed_gap_invalid += 1
            continue

        admitted += 1
        timeout_i = entry_i + HOLD_BARS
        if timeout_i >= len(rows) or int(rows[timeout_i]["open_ts_ms"]) >= end_ms:
            censored += 1
            active_until = len(rows)
            continue

        exit_i: int | None = None
        exit_price: float | None = None
        exit_reason: str | None = None
        quarantined = False
        for j in range(entry_i, timeout_i):
            bar = rows[j]
            if bar["segment_id"] != c["segment_id"]:
                gap_quarantined += 1
                active_until = j
                quarantined = True
                break
            if float(bar["open"]) <= stop:
                exit_i, exit_price, exit_reason = j, float(bar["open"]), "ADVERSE_GAP_STOP"
                break
            if float(bar["low"]) <= stop:
                exit_i, exit_price, exit_reason = j, stop, "STOP_FIRST"
                break
        if quarantined:
            continue
        if exit_i is None:
            timeout = rows[timeout_i]
            if timeout["segment_id"] != c["segment_id"]:
                gap_quarantined += 1
                active_until = timeout_i
                continue
            timeout_open = float(timeout["open"])
            if timeout_open <= stop:
                exit_i, exit_price, exit_reason = timeout_i, timeout_open, "ADVERSE_GAP_STOP"
            else:
                exit_i, exit_price, exit_reason = timeout_i, timeout_open, "FIXED_24H_TIMEOUT"

        assert exit_price is not None and exit_reason is not None
        gross_bps = (exit_price / entry_price - 1.0) * 10_000.0
        cost_bps = float(reference_cost_bps) + EXTRA_FUNDING_RESERVE_BPS
        trades.append(
            {
                "identity": CANDIDATE_ID,
                "symbol": symbol,
                "side": "LONG",
                "signal_open_ts_ms": int(c["open_ts_ms"]),
                "signal_available_ts_ms": signal_available_ms,
                "entry_ts_ms": int(entry["open_ts_ms"]),
                "entry_price": entry_price,
                "stop_price": stop,
                "exit_ts_ms": int(rows[exit_i]["open_ts_ms"]),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "holding_hours": (int(rows[exit_i]["open_ts_ms"]) - int(entry["open_ts_ms"])) / 3_600_000,
                "reference_cost_bps_one_settlement": float(reference_cost_bps),
                "funding_reserve_bps_embedded": TOTAL_FUNDING_RESERVE_BPS,
                "cost_bps": cost_bps,
                "gross_bps": gross_bps,
                "net_bps": gross_bps - cost_bps,
            }
        )
        active_until = exit_i

    return {
        "trades": trades,
        "raw_signals": raw_signals,
        "admitted_entries": admitted,
        "missed_occupied": missed_occupied,
        "missed_gap_invalid": missed_gap_invalid,
        "missing_fill_evidence": missing_fill_evidence,
        "gap_quarantined": gap_quarantined,
        "censored": censored,
        "completed": len(trades),
    }

