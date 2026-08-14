from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

POLICY_SCHEMA = "zel.production_a1_jump_liquidity_economic_policy.v1"
SEAL_SCHEMA = "zel.production_a1_jump_liquidity_calibration_seal.v1"
ROW_SCHEMA = "zel.production_bingx_ws_microstructure_row.v1"
OUT_SCHEMA = "zel.production_a1_jump_liquidity_economic_receipt.v1"
DEFAULT_POLICY = Path("config/zel_production_a1_jump_liquidity_economic_v1.json")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return dict(value)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            raw = json.loads(line)
        except Exception:
            continue
        if isinstance(raw, Mapping):
            rows.append(dict(raw))
    return rows


def _finite(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _sign(x: float | None) -> int:
    if x is None or x == 0:
        return 0
    return 1 if x > 0 else -1


def _sha_obj(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(dict(value), h, ensure_ascii=False, sort_keys=True, indent=2)
            h.write("\n")
            h.flush(); os.fsync(h.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def validate_policy(p: Mapping[str, Any]) -> dict[str, Any]:
    if p.get("schema_version") != POLICY_SCHEMA: raise RuntimeError("A1_ECON_POLICY_SCHEMA_INVALID")
    if p.get("family") != "jump_liquidity_state_switch": raise RuntimeError("A1_ECON_FAMILY_INVALID")
    if p.get("role") != "A1_MINIMAL_PROSPECTIVE_ECONOMIC_FALSIFICATION": raise RuntimeError("A1_ECON_ROLE_INVALID")
    if p.get("symbols") != ["BTC-USDT", "ETH-USDT"]: raise RuntimeError("A1_ECON_SYMBOLS_INVALID")
    if int(p.get("bucket_ms") or 0) != 5000: raise RuntimeError("A1_ECON_BUCKET_INVALID")
    if p.get("falsification_horizons_sec") != [5, 15, 30, 60]: raise RuntimeError("A1_ECON_HORIZONS_DRIFT")
    if p.get("negative_controls") != ["DIRECTION_FLIP", "PLUS_ONE_BUCKET_DELAY", "TIMESTAMP_SHIFT_PLACEBO", "MATCHED_NON_EVENT"]: raise RuntimeError("A1_ECON_CONTROLS_DRIFT")
    if p.get("fee_model") != "ALL_TAKER_CONSERVATIVE" or float(p.get("taker_fee_bps_per_side") or -1) != 5.0: raise RuntimeError("A1_ECON_FEE_MODEL_INVALID")
    for k in ("parameter_search", "best_horizon_selection", "threshold_tuning", "selection_authority", "promotion_authority", "exchange_order_submitted"):
        if p.get(k) is not False: raise RuntimeError(f"A1_ECON_FORBIDDEN:{k}")
    if p.get("execution_authority") != "NONE" or p.get("order_authority") != "BLOCKED" or p.get("live_trade_authority") != "BLOCKED": raise RuntimeError("A1_ECON_AUTHORITY_INVALID")
    return dict(p)


def _source_complete(r: Mapping[str, Any]) -> bool:
    return (
        r.get("schema_version") == ROW_SCHEMA
        and _finite(r.get("mid_last")) not in (None, 0.0)
        and _finite(r.get("spread_bps_mean")) is not None
        and _finite(r.get("trade_quote_notional")) is not None
        and _finite(r.get("trade_imbalance")) is not None
        and _finite(r.get("imbalance_top20_mean")) is not None
        and _finite(r.get("bid_qty_top20_last")) is not None
        and _finite(r.get("ask_qty_top20_last")) is not None
        and int(r.get("depth_messages") or 0) > 0
    )


def _crosses_funding(start_ms: int, end_ms: int, hours: list[int]) -> bool:
    if end_ms <= start_ms: return False
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    day = start.date()
    while day <= end.date():
        for hour in hours:
            t = datetime(day.year, day.month, day.day, int(hour), tzinfo=timezone.utc)
            ms = int(t.timestamp() * 1000)
            if start_ms < ms <= end_ms: return True
        day = day.fromordinal(day.toordinal() + 1)
    return False


def _trade_return(entry: Mapping[str, Any], exit_row: Mapping[str, Any], direction: int, fee_bps_side: float) -> dict[str, float] | None:
    em = _finite(entry.get("mid_last")); xm = _finite(exit_row.get("mid_last"))
    es = _finite(entry.get("spread_bps_mean")); xs = _finite(exit_row.get("spread_bps_mean"))
    if None in (em, xm, es, xs) or em <= 0 or xm <= 0 or direction not in (-1, 1): return None
    gross = direction * ((xm / em) - 1.0) * 10000.0
    spread_cost = max(0.0, es) / 2.0 + max(0.0, xs) / 2.0
    fee_cost = 2.0 * fee_bps_side
    return {"gross_bps": gross, "fee_bps": fee_cost, "spread_slippage_bps": spread_cost, "net_bps": gross - fee_cost - spread_cost}


def _metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"trades": 0, "expectancy_bps": None, "net_pnl_bps": 0.0, "pf": None, "payoff": None, "max_dd_bps": None, "win_rate": None}
    wins = [x for x in values if x > 0]; losses = [x for x in values if x < 0]
    gp = sum(wins); gl = -sum(losses)
    avgw = gp / len(wins) if wins else 0.0; avgl = gl / len(losses) if losses else 0.0
    equity = peak = dd = 0.0
    for x in values:
        equity += x; peak = max(peak, equity); dd = max(dd, peak - equity)
    return {
        "trades": len(values),
        "expectancy_bps": sum(values) / len(values),
        "net_pnl_bps": sum(values),
        "pf": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else None),
        "payoff": (avgw / avgl) if avgl > 0 else (float("inf") if avgw > 0 else None),
        "max_dd_bps": dd,
        "win_rate": len(wins) / len(values),
    }


def evaluate(policy: Mapping[str, Any], seal: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    if seal.get("schema_version") != SEAL_SCHEMA or seal.get("state") != "PASS_A1_JUMP_SOURCE_ONLY_CALIBRATION_SEALED":
        return {"schema_version": OUT_SCHEMA, "state": "HOLD_A1_ECON_CALIBRATION_SEAL_REQUIRED", "family": cfg["family"], "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "protected_mutations": 0}
    start_ms = int(seal["economic_evaluation_start_bucket_ms"])
    by_symbol: dict[str, list[dict[str, Any]]] = {s: [] for s in cfg["symbols"]}
    for r in rows:
        s = str(r.get("symbol") or "")
        if s in by_symbol and r.get("schema_version") == ROW_SCHEMA:
            by_symbol[s].append(r)
    for xs in by_symbol.values(): xs.sort(key=lambda r: int(r.get("bucket_start_ms") or 0))
    horizons = [int(x) for x in seal["falsification_horizons_sec"]]
    per_h: dict[str, dict[str, Any]] = {}
    event_count = 0; continuation_count = 0; reversal_count = 0; integrity_defects: list[str] = []
    funding_crossed = False
    for horizon in horizons:
        event_net: list[float] = []; event_gross: list[float] = []; flip: list[float] = []; delay: list[float] = []; placebo: list[float] = []; non_event: list[float] = []
        horizon_ms = horizon * 1000
        for symbol, xs in by_symbol.items():
            th = seal["thresholds_by_symbol"][symbol]
            index = {int(r.get("bucket_start_ms") or 0): i for i, r in enumerate(xs)}
            for i, r in enumerate(xs):
                t = int(r.get("bucket_start_ms") or 0)
                if t < start_ms or i == 0 or not _source_complete(r): continue
                prev = xs[i-1]
                pm = _finite(prev.get("mid_last")); m = _finite(r.get("mid_last"))
                if pm in (None, 0.0) or m in (None, 0.0): continue
                jump_bps = ((m / pm) - 1.0) * 10000.0
                ti = _finite(r.get("trade_imbalance")); bi = _finite(r.get("imbalance_top20_mean")); qn = _finite(r.get("trade_quote_notional")); sp = _finite(r.get("spread_bps_mean")); bq = _finite(r.get("bid_qty_top20_last")); aq = _finite(r.get("ask_qty_top20_last"))
                if None in (ti, bi, qn, sp, bq, aq): continue
                depth = bq + aq
                is_jump = abs(jump_bps) >= float(th["jump_abs_return_bps_q975"])
                stress = qn >= float(th["trade_quote_notional_q80"]) and abs(bi) >= float(th["abs_book_imbalance_q80"]) and (depth <= float(th["total_depth_top20_q20"]) or sp >= float(th["spread_bps_q80"]))
                js = _sign(jump_bps); ts = _sign(ti); bs = _sign(bi)
                state = None; direction = 0
                if is_jump and stress and js != 0 and js == ts == bs:
                    state = "CONTINUATION"; direction = js
                elif is_jump and stress and js != 0 and js == -ts and js == -bs:
                    state = "REPLENISHMENT_REVERSAL"; direction = -js
                if state is None: continue
                if horizon == horizons[0]:
                    event_count += 1
                    if state == "CONTINUATION": continuation_count += 1
                    else: reversal_count += 1
                entry_i = i + 1
                if entry_i >= len(xs): continue
                entry = xs[entry_i]
                exit_target = int(entry.get("bucket_start_ms") or 0) + horizon_ms
                exit_i = index.get(exit_target)
                if exit_i is None: continue
                exit_row = xs[exit_i]
                if not (_source_complete(entry) and _source_complete(exit_row)): continue
                if _crosses_funding(int(entry["bucket_start_ms"]), int(exit_row["bucket_end_ms"]), list(cfg["funding_settlement_hours_utc"])):
                    funding_crossed = True
                    continue
                tr = _trade_return(entry, exit_row, direction, float(cfg["taker_fee_bps_per_side"]))
                fr = _trade_return(entry, exit_row, -direction, float(cfg["taker_fee_bps_per_side"]))
                if tr and fr:
                    event_net.append(tr["net_bps"]); event_gross.append(tr["gross_bps"]); flip.append(fr["net_bps"])
                dentry_i = i + 2
                if dentry_i < len(xs):
                    dentry = xs[dentry_i]; dexit_i = index.get(int(dentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if dexit_i is not None and _source_complete(dentry) and _source_complete(xs[dexit_i]):
                        dr = _trade_return(dentry, xs[dexit_i], direction, float(cfg["taker_fee_bps_per_side"]));
                        if dr: delay.append(dr["net_bps"])
                shift_i = i + int(cfg["timestamp_shift_buckets"])
                if shift_i + 1 < len(xs):
                    pentry = xs[shift_i + 1]; pexit_i = index.get(int(pentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if pexit_i is not None and _source_complete(pentry) and _source_complete(xs[pexit_i]):
                        pr = _trade_return(pentry, xs[pexit_i], direction, float(cfg["taker_fee_bps_per_side"]));
                        if pr: placebo.append(pr["net_bps"])
                for j in range(i + 1, min(len(xs), i + 61)):
                    nr = xs[j]
                    if int(nr.get("bucket_start_ms") or 0) < start_ms or not _source_complete(nr): continue
                    npm = _finite(xs[j-1].get("mid_last")); nm = _finite(nr.get("mid_last"))
                    if npm in (None, 0.0) or nm in (None, 0.0): continue
                    nj = ((nm / npm) - 1.0) * 10000.0
                    if abs(nj) >= float(th["jump_abs_return_bps_q975"]): continue
                    nentry_i = j + 1
                    if nentry_i >= len(xs): break
                    nentry = xs[nentry_i]; nexit_i = index.get(int(nentry.get("bucket_start_ms") or 0) + horizon_ms)
                    if nexit_i is not None and _source_complete(nentry) and _source_complete(xs[nexit_i]):
                        nrtn = _trade_return(nentry, xs[nexit_i], direction, float(cfg["taker_fee_bps_per_side"]));
                        if nrtn: non_event.append(nrtn["net_bps"])
                    break
        em = _metrics(event_net); gm = _metrics(event_gross)
        control_means = {
            "DIRECTION_FLIP": _metrics(flip)["expectancy_bps"],
            "PLUS_ONE_BUCKET_DELAY": _metrics(delay)["expectancy_bps"],
            "TIMESTAMP_SHIFT_PLACEBO": _metrics(placebo)["expectancy_bps"],
            "MATCHED_NON_EVENT": _metrics(non_event)["expectancy_bps"],
        }
        per_h[str(horizon)] = {
            "gross": gm,
            "net": em,
            "controls_expectancy_bps": control_means,
            "control_delta_bps": {k: (em["expectancy_bps"] - v if em["expectancy_bps"] is not None and v is not None else None) for k, v in control_means.items()},
        }
    latest = max((int(r.get("bucket_end_ms") or 0) for r in rows), default=0)
    state = "PASS_A1_FIRST_PROSPECTIVE_ECONOMIC_EVIDENCE"
    blockers: list[str] = []
    if latest <= start_ms:
        state = "HOLD_A1_ECON_POST_SEAL_HISTORY_REQUIRED"; blockers.append("NO_POST_SEAL_HISTORY")
    elif funding_crossed and cfg.get("funding_fail_closed_if_crossed") and not cfg.get("funding_rate_source"):
        state = "HOLD_A1_ECON_FUNDING_RATE_REQUIRED"; blockers.append("FUNDING_SETTLEMENT_CROSSED_WITHOUT_RATE_SOURCE")
    elif event_count == 0:
        state = "HOLD_A1_ECON_NO_QUALIFYING_EVENTS_YET"; blockers.append("ZERO_PRE_REGISTERED_EVENTS")
    out = {
        "schema_version": OUT_SCHEMA, "state": state, "family": cfg["family"],
        "economic_evaluation_start_bucket_ms": start_ms, "latest_bucket_end_ms": latest,
        "post_seal_elapsed_ms": max(0, latest - start_ms), "event_count": event_count,
        "continuation_event_count": continuation_count, "reversal_event_count": reversal_count,
        "horizons": per_h, "funding_settlement_crossed": funding_crossed,
        "fee_authority": {"model": cfg["fee_model"], "taker_fee_bps_per_side": cfg["taker_fee_bps_per_side"], "round_trip_fee_bps": 2.0 * float(cfg["taker_fee_bps_per_side"]), "spread_slippage_model": cfg["fill_model"]},
        "integrity_defects": integrity_defects, "leakage": False, "parameter_search": False,
        "best_horizon_selection": False, "threshold_tuning": False, "blockers": blockers,
        "calibration_seal_sha256": _sha_obj(seal), "selection_authority": False,
        "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "protected_mutations": 0,
    }
    out["receipt_sha256"] = _sha_obj(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(_load(ns.policy))
    seal_path = Path(str(cfg["calibration_seal_path"]))
    seal = _load(seal_path) if seal_path.is_file() else {}
    rows = _load_jsonl(Path(str(cfg["history_path"])))
    out = evaluate(cfg, seal, rows)
    _atomic_json(Path(str(cfg["output_path"])), out)
    print(json.dumps(out, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
