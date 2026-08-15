from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_a1_jump_liquidity_economic_v1 import (
    ROW_SCHEMA,
    _atomic_json,
    _crosses_funding,
    _finite,
    _load,
    _load_jsonl,
    _metrics,
    _sha_obj,
    _sign,
    _source_complete,
    _trade_return,
)

POLICY_SCHEMA = "zel.production_a1_clock_phase_liquidity_impulse_policy.v1"
OUT_SCHEMA = "zel.production_a1_clock_phase_liquidity_impulse_receipt.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_clock_phase_liquidity_impulse_v1.json")


def validate_policy(p: Mapping[str, Any]) -> dict[str, Any]:
    if p.get("schema_version") != POLICY_SCHEMA or p.get("family") != "clock_phase_liquidity_impulse":
        raise RuntimeError("A1_CLK_POLICY_INVALID")
    if p.get("falsification_horizons_sec") != [14400, 28800, 43200]:
        raise RuntimeError("A1_CLK_HORIZONS_DRIFT")
    ev = p.get("event_contract") or {}
    if int(ev.get("clock_period_ms") or 0) != 900000 or int(ev.get("opening_window_ms") or 0) != 60000:
        raise RuntimeError("A1_CLK_EVENT_CONTRACT_DRIFT")
    if p.get("fee_model") != "ALL_TAKER_CONSERVATIVE" or float(p.get("taker_fee_bps_per_side") or -1) != 5.0:
        raise RuntimeError("A1_CLK_FEE_MODEL_INVALID")
    cb = p.get("cost_budget") or {}
    if float(cb.get("verified_fee_only_round_trip_bps") or -1) != 10.0 or float(cb.get("design_cost_budget_ratio") or 0) < 2.0:
        raise RuntimeError("A1_CLK_COST_BUDGET_INVALID")
    for k in ("parameter_search", "best_horizon_selection", "threshold_tuning", "selection_authority", "promotion_authority", "exchange_order_submitted"):
        if p.get(k) is not False:
            raise RuntimeError(f"A1_CLK_FORBIDDEN:{k}")
    if p.get("execution_authority") != "NONE" or p.get("order_authority") != "BLOCKED" or p.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("A1_CLK_AUTHORITY_INVALID")
    return dict(p)


def _opening_direction(xs: list[dict[str, Any]], start_i: int, bucket_ms: int) -> int:
    start = int(xs[start_i].get("bucket_start_ms") or 0)
    signed = 0.0
    for j in range(start_i, start_i + 12):
        if j >= len(xs):
            return 0
        r = xs[j]
        if int(r.get("bucket_start_ms") or 0) != start + (j - start_i) * bucket_ms or not _source_complete(r):
            return 0
        ti = _finite(r.get("trade_imbalance")); qn = _finite(r.get("trade_quote_notional"))
        if ti is None or qn is None:
            return 0
        signed += float(ti) * float(qn)
    return _sign(signed)


def evaluate(policy: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    freeze_ms = int(cfg.get("family_freeze_not_before_ms") or 0)
    bucket_ms = int(cfg["bucket_ms"])
    period_ms = int(cfg["event_contract"]["clock_period_ms"])
    opening_ms = int(cfg["event_contract"]["opening_window_ms"])
    if freeze_ms <= 0 or freeze_ms % period_ms != 0:
        raise RuntimeError("A1_CLK_FREEZE_NOT_QUARTER_BOUNDARY")

    by_symbol = {s: [] for s in cfg["symbols"]}
    for r in rows:
        s = str(r.get("symbol") or "")
        if s in by_symbol and r.get("schema_version") == ROW_SCHEMA:
            by_symbol[s].append(r)
    for xs in by_symbol.values():
        xs.sort(key=lambda r: int(r.get("bucket_start_ms") or 0))

    horizons = [int(x) for x in cfg["falsification_horizons_sec"]]
    per_h: dict[str, dict[str, Any]] = {}
    event_count = 0
    funding_crossed = False

    events: list[tuple[str, list[dict[str, Any]], dict[int, int], int, int]] = []
    for symbol, xs in by_symbol.items():
        index = {int(r.get("bucket_start_ms") or 0): i for i, r in enumerate(xs)}
        for i, r in enumerate(xs):
            t = int(r.get("bucket_start_ms") or 0)
            if t < freeze_ms or t % period_ms != 0:
                continue
            direction = _opening_direction(xs, i, bucket_ms)
            if direction == 0:
                continue
            entry_t = t + opening_ms
            entry_i = index.get(entry_t)
            if entry_i is None or not _source_complete(xs[entry_i]):
                continue
            events.append((symbol, xs, index, entry_i, direction))
    event_count = len(events)

    for horizon in horizons:
        gross: list[float] = []
        net: list[float] = []
        flip: list[float] = []
        placebo: list[float] = []
        horizon_ms = horizon * 1000
        for symbol, xs, index, entry_i, direction in events:
            entry = xs[entry_i]
            exit_i = index.get(int(entry["bucket_start_ms"]) + horizon_ms)
            if exit_i is None or not _source_complete(xs[exit_i]):
                continue
            exit_row = xs[exit_i]
            if _crosses_funding(int(entry["bucket_start_ms"]), int(exit_row["bucket_end_ms"]), list(cfg["funding_settlement_hours_utc"])):
                funding_crossed = True
                continue
            tr = _trade_return(entry, exit_row, direction, float(cfg["taker_fee_bps_per_side"]))
            fr = _trade_return(entry, exit_row, -direction, float(cfg["taker_fee_bps_per_side"]))
            if tr and fr:
                gross.append(tr["gross_bps"]); net.append(tr["net_bps"]); flip.append(fr["net_bps"])

            p_t = int(entry["bucket_start_ms"]) + int(cfg["placebo_shift_ms"])
            p_i = index.get(p_t)
            if p_i is not None:
                px_i = index.get(p_t + horizon_ms)
                if px_i is not None and _source_complete(xs[p_i]) and _source_complete(xs[px_i]):
                    pr = _trade_return(xs[p_i], xs[px_i], direction, float(cfg["taker_fee_bps_per_side"]))
                    if pr:
                        placebo.append(pr["net_bps"])

        gm = _metrics(gross); nm = _metrics(net)
        controls = {
            "DIRECTION_FLIP": _metrics(flip)["expectancy_bps"],
            "HALF_PHASE_SHIFT_PLACEBO": _metrics(placebo)["expectancy_bps"],
        }
        per_h[str(horizon)] = {
            "gross": gm,
            "net": nm,
            "controls_expectancy_bps": controls,
            "control_delta_bps": {k: (nm["expectancy_bps"] - v if nm["expectancy_bps"] is not None and v is not None else None) for k, v in controls.items()},
        }

    latest = max((int(r.get("bucket_end_ms") or 0) for r in rows), default=0)
    blockers: list[str] = []
    if funding_crossed and cfg.get("funding_fail_closed_if_crossed") and not cfg.get("funding_rate_source"):
        state = "HOLD_A1_CLK_FUNDING_RATE_REQUIRED"; blockers.append("FUNDING_SETTLEMENT_CROSSED_WITHOUT_RATE_SOURCE")
    elif event_count == 0:
        state = "HOLD_A1_CLK_NO_PROSPECTIVE_QUARTER_EVENT_YET"; blockers.append("ZERO_POST_FREEZE_QUARTER_EVENTS")
    elif not any((per_h[str(h)]["net"]["trades"] or 0) > 0 for h in horizons):
        state = "HOLD_A1_CLK_EVENTS_WAITING_FROZEN_HORIZON"; blockers.append("NO_COMPLETED_FROZEN_HORIZON_YET")
    else:
        state = "PASS_A1_CLK_FIRST_PROSPECTIVE_ECONOMIC_EVIDENCE"

    out = {
        "schema_version": OUT_SCHEMA,
        "state": state,
        "family": cfg["family"],
        "mechanism": cfg["mechanism"],
        "family_freeze_not_before_ms": freeze_ms,
        "prospective_boundary_enforced": True,
        "latest_bucket_end_ms": latest,
        "post_freeze_elapsed_ms": max(0, latest - freeze_ms),
        "event_count": event_count,
        "horizons": per_h,
        "cost_budget": cfg["cost_budget"],
        "fee_authority": {"model": cfg["fee_model"], "taker_fee_bps_per_side": cfg["taker_fee_bps_per_side"], "round_trip_fee_bps": 10.0, "spread_slippage_model": cfg["fill_model"]},
        "funding_settlement_crossed": funding_crossed,
        "blockers": blockers,
        "integrity_defects": [],
        "leakage": False,
        "parameter_search": False,
        "best_horizon_selection": False,
        "threshold_tuning": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    out["receipt_sha256"] = _sha_obj(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(_load(ns.policy))
    rows = _load_jsonl(Path(str(cfg["history_path"])))
    out = evaluate(cfg, rows)
    _atomic_json(Path(str(cfg["output_path"])), out)
    print(json.dumps(out, sort_keys=True, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
