from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_a1_jump_liquidity_economic_v1 import (
    ROW_SCHEMA,
    SEAL_SCHEMA,
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

POLICY_SCHEMA = "zel.production_a1_l2_flow_persistence_policy.v1"
OUT_SCHEMA = "zel.production_a1_l2_flow_persistence_receipt.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_l2_flow_persistence_v1.json")


def validate_policy(p: Mapping[str, Any]) -> dict[str, Any]:
    if p.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("A1_L2P_POLICY_SCHEMA_INVALID")
    if p.get("family") != "l2_flow_persistence_regime_filter":
        raise RuntimeError("A1_L2P_FAMILY_INVALID")
    if p.get("role") != "A1_COST_AWARE_MULTI_MINUTE_PROSPECTIVE_FALSIFICATION":
        raise RuntimeError("A1_L2P_ROLE_INVALID")
    if p.get("symbols") != ["BTC-USDT", "ETH-USDT"] or int(p.get("bucket_ms") or 0) != 5000:
        raise RuntimeError("A1_L2P_SOURCE_SCOPE_INVALID")
    if p.get("falsification_horizons_sec") != [300, 900, 1800]:
        raise RuntimeError("A1_L2P_HORIZONS_DRIFT")
    if p.get("negative_controls") != ["DIRECTION_FLIP", "PLUS_ONE_BUCKET_DELAY", "TIMESTAMP_SHIFT_PLACEBO", "BROKEN_PERSISTENCE"]:
        raise RuntimeError("A1_L2P_CONTROLS_DRIFT")
    if int(p.get("event_contract", {}).get("persistence_buckets") or 0) != 3:
        raise RuntimeError("A1_L2P_PERSISTENCE_DRIFT")
    if p.get("fee_model") != "ALL_TAKER_CONSERVATIVE" or float(p.get("taker_fee_bps_per_side") or -1) != 5.0:
        raise RuntimeError("A1_L2P_FEE_MODEL_INVALID")
    cb = p.get("cost_budget") or {}
    if float(cb.get("verified_fee_only_round_trip_bps") or -1) != 10.0:
        raise RuntimeError("A1_L2P_COST_AUTHORITY_INVALID")
    if float(cb.get("design_cost_budget_ratio") or 0) < 2.0 or cb.get("design_only_not_pass_evidence") is not True:
        raise RuntimeError("A1_L2P_COST_BUDGET_INVALID")
    for k in ("parameter_search", "best_horizon_selection", "threshold_tuning", "selection_authority", "promotion_authority", "exchange_order_submitted"):
        if p.get(k) is not False:
            raise RuntimeError(f"A1_L2P_FORBIDDEN:{k}")
    if p.get("execution_authority") != "NONE" or p.get("order_authority") != "BLOCKED" or p.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("A1_L2P_AUTHORITY_INVALID")
    return dict(p)


def _row_state(r: Mapping[str, Any], prev: Mapping[str, Any], th: Mapping[str, Any]) -> tuple[bool, int]:
    if not (_source_complete(r) and _source_complete(prev)):
        return False, 0
    pm = _finite(prev.get("mid_last")); m = _finite(r.get("mid_last"))
    ti = _finite(r.get("trade_imbalance")); bi = _finite(r.get("imbalance_top20_mean"))
    qn = _finite(r.get("trade_quote_notional")); sp = _finite(r.get("spread_bps_mean"))
    bq = _finite(r.get("bid_qty_top20_last")); aq = _finite(r.get("ask_qty_top20_last"))
    if None in (pm, m, ti, bi, qn, sp, bq, aq) or pm == 0:
        return False, 0
    jump_bps = ((m / pm) - 1.0) * 10000.0
    direction = _sign(ti)
    aligned = direction != 0 and direction == _sign(bi)
    no_jump = abs(jump_bps) < float(th["jump_abs_return_bps_q975"])
    strong_book = abs(float(bi)) >= float(th["abs_book_imbalance_q80"])
    active_flow = float(qn) >= float(th["trade_quote_notional_q80"])
    depth = float(bq) + float(aq)
    stressed = depth <= float(th["total_depth_top20_q20"]) or float(sp) >= float(th["spread_bps_q80"])
    return bool(aligned and no_jump and strong_book and active_flow and stressed), direction


def evaluate(policy: Mapping[str, Any], seal: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    freeze_ms = int(cfg.get("family_freeze_not_before_ms") or 0)
    if freeze_ms <= 0 or freeze_ms % int(cfg["bucket_ms"]) != 0:
        raise RuntimeError("A1_L2P_FAMILY_FREEZE_BOUNDARY_INVALID")
    if seal.get("schema_version") != SEAL_SCHEMA or seal.get("state") != "PASS_A1_JUMP_SOURCE_ONLY_CALIBRATION_SEALED":
        return {
            "schema_version": OUT_SCHEMA,
            "state": "HOLD_A1_L2P_SOURCE_THRESHOLD_SEAL_REQUIRED",
            "family": cfg["family"],
            "family_freeze_not_before_ms": freeze_ms,
            "prospective_boundary_enforced": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
        }

    start_ms = max(int(seal["economic_evaluation_start_bucket_ms"]), freeze_ms)
    horizons = [int(x) for x in cfg["falsification_horizons_sec"]]
    persistence = int(cfg["event_contract"]["persistence_buckets"])
    by_symbol: dict[str, list[dict[str, Any]]] = {s: [] for s in cfg["symbols"]}
    for r in rows:
        s = str(r.get("symbol") or "")
        if s in by_symbol and r.get("schema_version") == ROW_SCHEMA:
            by_symbol[s].append(r)
    for xs in by_symbol.values():
        xs.sort(key=lambda r: int(r.get("bucket_start_ms") or 0))

    event_count = 0
    funding_crossed = False
    per_h: dict[str, dict[str, Any]] = {}

    for horizon in horizons:
        gross: list[float] = []
        net: list[float] = []
        flip: list[float] = []
        delay: list[float] = []
        placebo: list[float] = []
        broken: list[float] = []
        horizon_ms = horizon * 1000

        for symbol, xs in by_symbol.items():
            th = seal["thresholds_by_symbol"][symbol]
            index = {int(r.get("bucket_start_ms") or 0): i for i, r in enumerate(xs)}
            for i in range(persistence, len(xs)):
                r = xs[i]
                t = int(r.get("bucket_start_ms") or 0)
                if t < start_ms:
                    continue
                dirs: list[int] = []
                ok = True
                for j in range(i - persistence + 1, i + 1):
                    state_ok, direction = _row_state(xs[j], xs[j - 1], th)
                    if not state_ok:
                        ok = False
                        break
                    dirs.append(direction)
                if not ok or len(set(dirs)) != 1:
                    continue
                direction = dirs[0]
                if horizon == horizons[0]:
                    event_count += 1

                entry_i = i + 1
                if entry_i >= len(xs):
                    continue
                entry = xs[entry_i]
                exit_i = index.get(int(entry.get("bucket_start_ms") or 0) + horizon_ms)
                if exit_i is None:
                    continue
                exit_row = xs[exit_i]
                if not (_source_complete(entry) and _source_complete(exit_row)):
                    continue
                if _crosses_funding(int(entry["bucket_start_ms"]), int(exit_row["bucket_end_ms"]), list(cfg["funding_settlement_hours_utc"])):
                    funding_crossed = True
                    continue

                tr = _trade_return(entry, exit_row, direction, float(cfg["taker_fee_bps_per_side"]))
                fr = _trade_return(entry, exit_row, -direction, float(cfg["taker_fee_bps_per_side"]))
                if tr and fr:
                    gross.append(tr["gross_bps"]); net.append(tr["net_bps"]); flip.append(fr["net_bps"])

                dentry_i = i + 2
                if dentry_i < len(xs):
                    dentry = xs[dentry_i]
                    dexit_i = index.get(int(dentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if dexit_i is not None and _source_complete(dentry) and _source_complete(xs[dexit_i]):
                        dr = _trade_return(dentry, xs[dexit_i], direction, float(cfg["taker_fee_bps_per_side"]))
                        if dr:
                            delay.append(dr["net_bps"])

                shift_i = i + int(cfg["timestamp_shift_buckets"])
                if shift_i + 1 < len(xs):
                    pentry = xs[shift_i + 1]
                    pexit_i = index.get(int(pentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if pexit_i is not None and _source_complete(pentry) and _source_complete(xs[pexit_i]):
                        pr = _trade_return(pentry, xs[pexit_i], direction, float(cfg["taker_fee_bps_per_side"]))
                        if pr:
                            placebo.append(pr["net_bps"])

                broken_i = i - 1
                if broken_i >= 1:
                    bentry_i = broken_i + 1
                    bentry = xs[bentry_i]
                    bexit_i = index.get(int(bentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if bexit_i is not None and _source_complete(bentry) and _source_complete(xs[bexit_i]):
                        br = _trade_return(bentry, xs[bexit_i], direction, float(cfg["taker_fee_bps_per_side"]))
                        if br:
                            broken.append(br["net_bps"])

        net_m = _metrics(net)
        gross_m = _metrics(gross)
        controls = {
            "DIRECTION_FLIP": _metrics(flip)["expectancy_bps"],
            "PLUS_ONE_BUCKET_DELAY": _metrics(delay)["expectancy_bps"],
            "TIMESTAMP_SHIFT_PLACEBO": _metrics(placebo)["expectancy_bps"],
            "BROKEN_PERSISTENCE": _metrics(broken)["expectancy_bps"],
        }
        per_h[str(horizon)] = {
            "gross": gross_m,
            "net": net_m,
            "controls_expectancy_bps": controls,
            "control_delta_bps": {k: (net_m["expectancy_bps"] - v if net_m["expectancy_bps"] is not None and v is not None else None) for k, v in controls.items()},
        }

    latest = max((int(r.get("bucket_end_ms") or 0) for r in rows), default=0)
    blockers: list[str] = []
    if funding_crossed and cfg.get("funding_fail_closed_if_crossed") and not cfg.get("funding_rate_source"):
        state = "HOLD_A1_L2P_FUNDING_RATE_REQUIRED"; blockers.append("FUNDING_SETTLEMENT_CROSSED_WITHOUT_RATE_SOURCE")
    elif event_count == 0:
        state = "HOLD_A1_L2P_NO_QUALIFYING_EVENTS_YET"; blockers.append("ZERO_PRE_REGISTERED_PERSISTENCE_EVENTS")
    else:
        state = "PASS_A1_L2P_FIRST_PROSPECTIVE_ECONOMIC_EVIDENCE"

    out = {
        "schema_version": OUT_SCHEMA,
        "state": state,
        "family": cfg["family"],
        "mechanism": cfg["mechanism"],
        "economic_evaluation_start_bucket_ms": start_ms,
        "family_freeze_not_before_ms": freeze_ms,
        "prospective_boundary_enforced": True,
        "latest_bucket_end_ms": latest,
        "post_freeze_elapsed_ms": max(0, latest - start_ms),
        "event_count": event_count,
        "horizons": per_h,
        "cost_budget": cfg["cost_budget"],
        "fee_authority": {
            "model": cfg["fee_model"],
            "taker_fee_bps_per_side": cfg["taker_fee_bps_per_side"],
            "round_trip_fee_bps": 2.0 * float(cfg["taker_fee_bps_per_side"]),
            "spread_slippage_model": cfg["fill_model"],
        },
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
        "source_threshold_seal_sha256": _sha_obj(seal),
    }
    out["receipt_sha256"] = _sha_obj(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(_load(ns.policy))
    seal_path = Path(str(cfg["source_threshold_seal_path"]))
    seal = _load(seal_path) if seal_path.is_file() else {}
    rows = _load_jsonl(Path(str(cfg["history_path"])))
    out = evaluate(cfg, seal, rows)
    _atomic_json(Path(str(cfg["output_path"])), out)
    print(json.dumps(out, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
