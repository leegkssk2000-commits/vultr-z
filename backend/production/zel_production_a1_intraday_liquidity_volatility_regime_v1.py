from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
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

POLICY_SCHEMA = "zel.production_a1_intraday_liquidity_volatility_regime_policy.v1"
OUT_SCHEMA = "zel.production_a1_intraday_liquidity_volatility_regime_receipt.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_intraday_liquidity_volatility_regime_v1.json")


def validate_policy(p: Mapping[str, Any]) -> dict[str, Any]:
    if p.get("schema_version") != POLICY_SCHEMA or p.get("family") != "intraday_liquidity_volatility_regime":
        raise RuntimeError("A1_ILVR_POLICY_INVALID")
    if p.get("falsification_horizons_sec") != [3600, 7200, 14400]:
        raise RuntimeError("A1_ILVR_HORIZONS_DRIFT")
    ev = p.get("event_contract") or {}
    if int(ev.get("decision_grid_ms") or 0) != 900000:
        raise RuntimeError("A1_ILVR_GRID_DRIFT")
    if int(ev.get("lookback_move_ms") or 0) != 1800000 or int(ev.get("baseline_ms") or 0) != 14400000:
        raise RuntimeError("A1_ILVR_LOOKBACK_DRIFT")
    if float(ev.get("move_expansion_multiple") or 0) != 2.0 or float(ev.get("spread_expansion_multiple") or 0) != 1.0:
        raise RuntimeError("A1_ILVR_EVENT_CONTRACT_DRIFT")
    if p.get("fee_model") != "ALL_TAKER_CONSERVATIVE" or float(p.get("taker_fee_bps_per_side") or -1) != 5.0:
        raise RuntimeError("A1_ILVR_FEE_MODEL_INVALID")
    cb = p.get("cost_budget") or {}
    if float(cb.get("verified_fee_only_round_trip_bps") or -1) != 10.0 or float(cb.get("design_cost_budget_ratio") or 0) < 2.0:
        raise RuntimeError("A1_ILVR_COST_BUDGET_INVALID")
    for k in ("parameter_search", "best_horizon_selection", "threshold_tuning", "selection_authority", "promotion_authority", "exchange_order_submitted"):
        if p.get(k) is not False:
            raise RuntimeError(f"A1_ILVR_FORBIDDEN:{k}")
    if p.get("execution_authority") != "NONE" or p.get("order_authority") != "BLOCKED" or p.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("A1_ILVR_AUTHORITY_INVALID")
    return dict(p)


def _event_at(xs: list[dict[str, Any]], index: dict[int, int], t: int, cfg: Mapping[str, Any]) -> int:
    bucket_ms = int(cfg["bucket_ms"])
    ev = cfg["event_contract"]
    lookback_ms = int(ev["lookback_move_ms"])
    baseline_ms = int(ev["baseline_ms"])
    signal_i = index.get(t - bucket_ms)
    past_i = index.get(t - lookback_ms - bucket_ms)
    if signal_i is None or past_i is None:
        return 0
    signal = xs[signal_i]; past = xs[past_i]
    if not (_source_complete(signal) and _source_complete(past)):
        return 0
    sm = _finite(signal.get("mid_last")); pm = _finite(past.get("mid_last"))
    if sm in (None, 0.0) or pm in (None, 0.0):
        return 0
    move_bps = ((sm / pm) - 1.0) * 10000.0
    direction = _sign(move_bps)
    if direction == 0:
        return 0

    baseline_start = t - lookback_ms - baseline_ms
    baseline_end = t - lookback_ms
    baseline_abs_moves: list[float] = []
    for bt in range(baseline_start + int(ev["decision_grid_ms"]), baseline_end + 1, int(ev["decision_grid_ms"])):
        e_i = index.get(bt - bucket_ms); p_i = index.get(bt - lookback_ms - bucket_ms)
        if e_i is None or p_i is None or not (_source_complete(xs[e_i]) and _source_complete(xs[p_i])):
            continue
        em = _finite(xs[e_i].get("mid_last")); bm = _finite(xs[p_i].get("mid_last"))
        if em in (None, 0.0) or bm in (None, 0.0):
            continue
        baseline_abs_moves.append(abs(((em / bm) - 1.0) * 10000.0))
    if len(baseline_abs_moves) < 8:
        return 0

    baseline_spreads: list[float] = []
    latest_spreads: list[float] = []
    for r in xs:
        rt = int(r.get("bucket_start_ms") or 0)
        sp = _finite(r.get("spread_bps_mean"))
        if sp is None or not _source_complete(r):
            continue
        if baseline_start <= rt < baseline_end:
            baseline_spreads.append(sp)
        elif t - lookback_ms <= rt < t:
            latest_spreads.append(sp)
    if not baseline_spreads or not latest_spreads:
        return 0
    move_gate = abs(move_bps) >= float(ev["move_expansion_multiple"]) * median(baseline_abs_moves)
    spread_gate = (sum(latest_spreads) / len(latest_spreads)) >= float(ev["spread_expansion_multiple"]) * median(baseline_spreads)
    return direction if move_gate and spread_gate else 0


def evaluate(policy: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    freeze_ms = int(cfg.get("family_freeze_not_before_ms") or 0)
    grid_ms = int(cfg["event_contract"]["decision_grid_ms"])
    if freeze_ms <= 0 or freeze_ms % grid_ms != 0:
        raise RuntimeError("A1_ILVR_FREEZE_NOT_GRID_BOUNDARY")

    by_symbol = {s: [] for s in cfg["symbols"]}
    for r in rows:
        s = str(r.get("symbol") or "")
        if s in by_symbol and r.get("schema_version") == ROW_SCHEMA:
            by_symbol[s].append(r)
    for xs in by_symbol.values():
        xs.sort(key=lambda r: int(r.get("bucket_start_ms") or 0))

    events: list[tuple[str, list[dict[str, Any]], dict[int, int], int, int]] = []
    for symbol, xs in by_symbol.items():
        index = {int(r.get("bucket_start_ms") or 0): i for i, r in enumerate(xs)}
        for t in sorted(index):
            if t < freeze_ms or t % grid_ms != 0:
                continue
            direction = _event_at(xs, index, t, cfg)
            entry_i = index.get(t)
            if direction and entry_i is not None and _source_complete(xs[entry_i]):
                events.append((symbol, xs, index, entry_i, direction))

    per_h: dict[str, dict[str, Any]] = {}
    funding_skipped = 0
    for horizon in [int(x) for x in cfg["falsification_horizons_sec"]]:
        gross: list[float] = []; net: list[float] = []; flip: list[float] = []; placebo: list[float] = []
        horizon_ms = horizon * 1000
        for _, xs, index, entry_i, direction in events:
            entry = xs[entry_i]
            exit_i = index.get(int(entry["bucket_start_ms"]) + horizon_ms)
            if exit_i is None or not _source_complete(xs[exit_i]):
                continue
            exit_row = xs[exit_i]
            if _crosses_funding(int(entry["bucket_start_ms"]), int(exit_row["bucket_end_ms"]), list(cfg["funding_settlement_hours_utc"])):
                funding_skipped += 1
                continue
            tr = _trade_return(entry, exit_row, direction, float(cfg["taker_fee_bps_per_side"]))
            fr = _trade_return(entry, exit_row, -direction, float(cfg["taker_fee_bps_per_side"]))
            if tr and fr:
                gross.append(tr["gross_bps"]); net.append(tr["net_bps"]); flip.append(fr["net_bps"])
            p_t = int(entry["bucket_start_ms"]) + int(cfg["placebo_shift_ms"])
            p_i = index.get(p_t); px_i = index.get(p_t + horizon_ms)
            if p_i is not None and px_i is not None and _source_complete(xs[p_i]) and _source_complete(xs[px_i]):
                if not _crosses_funding(int(xs[p_i]["bucket_start_ms"]), int(xs[px_i]["bucket_end_ms"]), list(cfg["funding_settlement_hours_utc"])):
                    pr = _trade_return(xs[p_i], xs[px_i], direction, float(cfg["taker_fee_bps_per_side"]))
                    if pr:
                        placebo.append(pr["net_bps"])
        gm = _metrics(gross); nm = _metrics(net)
        controls = {"DIRECTION_FLIP": _metrics(flip)["expectancy_bps"], "ONE_HOUR_TIMESTAMP_SHIFT_PLACEBO": _metrics(placebo)["expectancy_bps"]}
        per_h[str(horizon)] = {
            "gross": gm,
            "net": nm,
            "controls_expectancy_bps": controls,
            "control_delta_bps": {k: (nm["expectancy_bps"] - v if nm["expectancy_bps"] is not None and v is not None else None) for k, v in controls.items()},
        }

    latest = max((int(r.get("bucket_end_ms") or 0) for r in rows), default=0)
    if not events:
        state = "HOLD_A1_ILVR_NO_PROSPECTIVE_EVENT_YET"; blockers = ["ZERO_POST_FREEZE_REGIME_EVENTS"]
    elif not any((per_h[str(h)]["net"]["trades"] or 0) > 0 for h in cfg["falsification_horizons_sec"]):
        state = "HOLD_A1_ILVR_EVENTS_WAITING_FROZEN_HORIZON"; blockers = ["NO_COMPLETED_FROZEN_HORIZON_YET"]
    else:
        state = "PASS_A1_ILVR_FIRST_PROSPECTIVE_ECONOMIC_EVIDENCE"; blockers = []

    out = {
        "schema_version": OUT_SCHEMA,
        "state": state,
        "family": cfg["family"],
        "mechanism": cfg["mechanism"],
        "family_freeze_not_before_ms": freeze_ms,
        "prospective_boundary_enforced": True,
        "latest_bucket_end_ms": latest,
        "post_freeze_elapsed_ms": max(0, latest - freeze_ms),
        "event_count": len(events),
        "horizons": per_h,
        "cost_budget": cfg["cost_budget"],
        "fee_authority": {"model": cfg["fee_model"], "taker_fee_bps_per_side": cfg["taker_fee_bps_per_side"], "round_trip_fee_bps": 10.0, "spread_slippage_model": cfg["fill_model"]},
        "funding_crossed_trades_skipped": funding_skipped,
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
