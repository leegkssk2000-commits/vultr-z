from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
SSOT_PATH = ROOT / "backend/research/prep/a2_cost_turnover_ssot_v1.json"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_ssot() -> dict[str, Any]:
    value = json.loads(SSOT_PATH.read_text(encoding="utf-8"))
    if value.get("state") != "A2_PREP_READY":
        raise RuntimeError("A2_SSOT_NOT_READY")
    return value


def p95(values: Iterable[float]) -> float:
    xs = sorted(float(x) for x in values)
    if not xs:
        raise ValueError("P95_EMPTY")
    return xs[min(len(xs) - 1, max(0, math.ceil(0.95 * len(xs)) - 1))]


def depth_vwap(levels: list[list[float | str]], target_quote: float) -> float:
    remaining = float(target_quote)
    quote = 0.0
    base = 0.0
    for row in levels:
        price, qty = float(row[0]), float(row[1])
        if price <= 0 or qty <= 0:
            continue
        take = min(qty, remaining / price)
        quote += take * price
        base += take
        remaining -= take * price
        if remaining <= 1e-9:
            break
    if remaining > max(0.01, target_quote * 1e-6) or base <= 0:
        raise ValueError("DEPTH_REFERENCE_NOTIONAL_UNFILLED")
    return quote / base


@dataclass(frozen=True)
class CostInput:
    best_bid: float
    best_ask: float
    bids: list[list[float | str]]
    asks: list[list[float | str]]
    funding_abs_bps_history: list[float]
    reference_notional_usdt: float = 10000.0
    extra_verified_penalty_bps: float = 0.0


def compute_cost(inp: CostInput, ssot: dict[str, Any] | None = None) -> dict[str, Any]:
    s = ssot or load_ssot()
    if inp.best_bid <= 0 or inp.best_ask <= inp.best_bid:
        raise ValueError("TOP_OF_BOOK_INVALID")
    if inp.reference_notional_usdt <= 0:
        raise ValueError("REFERENCE_NOTIONAL_INVALID")
    if inp.extra_verified_penalty_bps < 0:
        raise ValueError("NEGATIVE_PENALTY_FORBIDDEN")

    mid = (inp.best_bid + inp.best_ask) / 2.0
    spread_observed = (inp.best_ask - inp.best_bid) / mid * 10_000.0
    buy_vwap = depth_vwap(inp.asks, inp.reference_notional_usdt)
    sell_vwap = depth_vwap(inp.bids, inp.reference_notional_usdt)
    impact_observed = max(0.0, (buy_vwap / inp.best_ask - 1.0) * 10_000.0) + max(0.0, (inp.best_bid / sell_vwap - 1.0) * 10_000.0)
    spread = max(float(s["spread"]["floor_bps"]), spread_observed)
    impact = max(float(s["depth_vwap_impact"]["floor_bps"]), impact_observed)
    funding = p95(inp.funding_abs_bps_history)
    fee = float(s["fee"]["taker_round_trip_bps"])
    one_x = fee + spread + impact + funding + inp.extra_verified_penalty_bps
    two_x = 2.0 * one_x
    result = {
        "fee_bps": fee,
        "spread_observed_bps": spread_observed,
        "spread_charged_bps": spread,
        "depth_impact_observed_bps": impact_observed,
        "depth_impact_charged_bps": impact,
        "funding_p95_abs_bps": funding,
        "verified_penalty_bps": inp.extra_verified_penalty_bps,
        "one_x_cost_bps": one_x,
        "two_x_cost_bps": two_x,
        "reference_notional_usdt": inp.reference_notional_usdt,
        "maker_cost_used": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def expected_move_cost_ratio(expected_gross_move_bps: float, one_x_cost_bps: float) -> float:
    if expected_gross_move_bps < 0 or one_x_cost_bps <= 0:
        raise ValueError("MOVE_COST_INPUT_INVALID")
    return expected_gross_move_bps / one_x_cost_bps


def turnover_summary(realized_cost_bps: list[float], gross_notional_usdt: list[float], elapsed_days: float) -> dict[str, float]:
    if len(realized_cost_bps) != len(gross_notional_usdt):
        raise ValueError("TURNOVER_LENGTH_MISMATCH")
    if elapsed_days <= 0:
        raise ValueError("TURNOVER_ELAPSED_INVALID")
    n = len(realized_cost_bps)
    return {
        "round_trips": float(n),
        "round_trips_per_day": n / elapsed_days,
        "gross_turnover_notional_usdt": sum(float(x) for x in gross_notional_usdt),
        "cost_bps_total": sum(float(x) for x in realized_cost_bps),
        "cost_bps_per_trade": sum(float(x) for x in realized_cost_bps) / n if n else 0.0,
    }
