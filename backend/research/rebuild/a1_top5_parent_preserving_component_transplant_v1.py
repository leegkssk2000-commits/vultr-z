#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import statistics
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_parent_preserving_component_transplant_v1.json"
PARENTS = ROOT / "backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json"
OUT = ROOT / "backend/research/rebuild/a1_top5_parent_preserving_component_transplant_latest.json"
API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
TF = "4h"
TF_MS = 4 * 60 * 60 * 1000
LANES = ("keltner_trend_main", "supertrend_pullback_main")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def req(symbol: str, end_ms: int) -> list[dict[str, float]]:
    q = urllib.parse.urlencode({"symbol": symbol, "interval": TF, "limit": 1000, "endTime": end_ms})
    with urllib.request.urlopen(API + "?" + q, timeout=30) as r:
        value = json.loads(r.read().decode("utf-8"))
    if isinstance(value, dict) and value.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX:{value.get('code')}:{value.get('msg')}")
    rows = value.get("data", []) if isinstance(value, dict) else value
    out = []
    for x in rows or []:
        try:
            if isinstance(x, dict):
                ts = int(x.get("time") or x.get("openTime") or x.get("timestamp"))
                out.append({"ts":ts,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume") or x.get("vol") or 0.0)})
            else:
                out.append({"ts":int(x[0]),"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
        except Exception:
            continue
    return sorted({int(x["ts"]): x for x in out}.values(), key=lambda x: int(x["ts"]))


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    a = 2.0 / (period + 1.0)
    cur = values[0]
    for i, v in enumerate(values):
        cur = v if i == 0 else (a * v + (1.0 - a) * cur)
        if i >= period - 1:
            out[i] = cur
    return out


def feature_table(rows: list[dict[str, float]]) -> tuple[list[int], list[dict[str, Any]]]:
    c = [float(x["close"]) for x in rows]
    v = [float(x["volume"]) for x in rows]
    e20, e50 = ema(c, 20), ema(c, 50)
    ret: list[float | None] = [None] + [(c[i] / c[i-1] - 1.0) if c[i-1] else None for i in range(1, len(c))]
    feat: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        r20 = [float(x) for x in ret[max(1, i-19):i+1] if x is not None]
        sd = statistics.pstdev(r20) if len(r20) >= 20 else None
        vol20 = sum(v[max(0, i-19):i+1]) / 20.0 if i >= 19 else None
        highest_prev50 = max(float(x["high"]) for x in rows[i-50:i]) if i >= 50 else None
        mom = bool(ret[i] is not None and sd not in (None, 0) and e20[i] is not None and e50[i] is not None and float(ret[i]) > 0 and abs(float(ret[i])) >= 1.0 * float(sd) and float(e20[i]) > float(e50[i]))
        breakout = bool(highest_prev50 is not None and e20[i] is not None and e50[i] is not None and vol20 not in (None, 0) and c[i] > highest_prev50 and float(e20[i]) > float(e50[i]) and v[i] / float(vol20) >= 1.10)
        reclaim = bool(i >= 1 and e20[i] is not None and e50[i] is not None and e20[i-1] is not None and c[i-1] <= float(e20[i-1]) and c[i] > float(e20[i]) and float(e20[i]) > float(e50[i]))
        feat.append({"bar_ts":int(row["ts"]),"SUPERTREND_MOMENTUM_1P00":mom,"BREAKOUT50_VOLUME":breakout,"KELTNER_RECLAIM":reclaim})
    return [int(x["ts"]) for x in rows], feat


def metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in trades]
    gp = sum(x for x in vals if x > 0)
    gl = -sum(x for x in vals if x < 0)
    eq = peak = dd = 0.0
    for x in vals:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(vals),
        "wins": sum(x > 0 for x in vals),
        "win_rate": (sum(x > 0 for x in vals) / len(vals)) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": (sum(vals) / len(vals)) if vals else None,
        "profit_factor": (gp / gl) if gl > 0 else None,
        "profit_factor_unbounded": bool(gp > 0 and gl == 0),
        "drawdown_bps": dd,
    }


def pf_score(m: Mapping[str, Any]) -> float:
    if m.get("profit_factor_unbounded"):
        return 1e30
    return float(m.get("profit_factor") or 0.0)


def donor_flags(trades: list[Mapping[str, Any]]) -> tuple[dict[str, dict[str, bool]], dict[str, Any]]:
    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for t in trades:
        by_symbol.setdefault(str(t["symbol"]), []).append(t)
    flags: dict[str, dict[str, bool]] = {}
    src: dict[str, Any] = {}
    for symbol, rows_t in by_symbol.items():
        max_signal = max(int(x["signal_ts"]) for x in rows_t)
        bars = req(symbol, max_signal + TF_MS)
        ts, ft = feature_table(bars)
        src[symbol] = {"bars":len(bars),"first_ts":ts[0] if ts else None,"last_ts":ts[-1] if ts else None}
        for t in rows_t:
            signal = int(t["signal_ts"])
            # Use only a fully closed 4h donor bar; no future-bar access.
            cutoff = signal - TF_MS
            j = bisect.bisect_right(ts, cutoff) - 1
            if j < 0:
                row = {"SUPERTREND_MOMENTUM_1P00":False,"BREAKOUT50_VOLUME":False,"KELTNER_RECLAIM":False}
            else:
                row = ft[j]
            tid = str(t.get("closed_trade_id") or sha({k:t.get(k) for k in ("lane_id","symbol","signal_ts","entry_ts","exit_ts","side")}))
            flags[tid] = {k:bool(row[k]) for k in ("SUPERTREND_MOMENTUM_1P00","BREAKOUT50_VOLUME","KELTNER_RECLAIM")}
    return flags, src


def keep_for(cell: Mapping[str, Any], f: Mapping[str, bool]) -> bool:
    mode = str(cell["mode"])
    if mode == "ACCEPT_ONLY":
        return bool(f[str(cell["predicate"])])
    if mode == "ACCEPT_ONLY_OR":
        return any(bool(f[str(x)]) for x in cell["predicates"])
    if mode == "NEGATIVE_VETO":
        return not bool(f[str(cell["predicate"])])
    if mode == "NEGATIVE_VETO_OR":
        return not any(bool(f[str(x)]) for x in cell["predicates"])
    raise RuntimeError(f"MODE:{mode}")


def eligible(parent: Mapping[str, Any], child: Mapping[str, Any], kept_t: int, parent_t: int, rule: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    need = max(int(rule["minimum_kept_T"]), math.ceil(parent_t * float(rule["minimum_retention_ratio"])))
    exp_p, exp_c = float(parent.get("net_expectancy_bps") or 0.0), float(child.get("net_expectancy_bps") or -1e30)
    pf_p, pf_c = pf_score(parent), pf_score(child)
    dd_p, dd_c = float(parent.get("drawdown_bps") or 0.0), float(child.get("drawdown_bps") or 0.0)
    dims = {
        "net_expectancy_bps": exp_c > exp_p,
        "profit_factor": pf_c > pf_p,
        "drawdown_bps": dd_c < dd_p,
    }
    ok = kept_t >= need and float(child.get("net_pnl_bps") or 0.0) > 0 and dims["net_expectancy_bps"] and sum(bool(x) for x in dims.values()) >= int(rule["improvement_dimensions_required"])
    return ok, {"minimum_kept_T_effective":need,"retention_ratio":kept_t/parent_t if parent_t else 0.0,"improvement_dimensions":dims,"improvement_count":sum(bool(x) for x in dims.values()),"net_expectancy_bps_delta":exp_c-exp_p,"profit_factor_delta":pf_c-pf_p if pf_c < 1e29 and pf_p < 1e29 else None,"drawdown_reduction_bps":dd_p-dd_c}


def run(out: Path) -> dict[str, Any]:
    contract, source = read(CONTRACT), read(PARENTS)
    if contract.get("state") != "PREREGISTERED_BEFORE_PARENT_SPECIFIC_RESULTS":
        raise RuntimeError("CONTRACT_NOT_PREREGISTERED")
    result_lanes: dict[str, Any] = {}
    for lane_id in LANES:
        lane = (source.get("lanes") or {}).get(lane_id) or {}
        trades = [dict(x) for x in lane.get("closed_trades") or []]
        if not trades:
            raise RuntimeError(f"NO_PARENT_CLOSED_TRADES:{lane_id}")
        parent_m = metrics(trades)
        flags, src = donor_flags(trades)
        cells = []
        for cell in contract["candidate_cells"][lane_id]:
            kept = []
            vetoed = []
            for t in trades:
                tid = str(t.get("closed_trade_id") or sha({k:t.get(k) for k in ("lane_id","symbol","signal_ts","entry_ts","exit_ts","side")}))
                (kept if keep_for(cell, flags[tid]) else vetoed).append(t)
            cm = metrics(kept)
            ok, gate = eligible(parent_m, cm, len(kept), len(trades), contract["selection_rule"])
            cells.append({**cell,"eligible_historical_candidate":ok,"parent_T":len(trades),"kept_T":len(kept),"vetoed_T":len(vetoed),"metrics":cm,"gate":gate,"kept_trade_ids":[str(x.get("closed_trade_id")) for x in kept],"vetoed_trade_ids":[str(x.get("closed_trade_id")) for x in vetoed]})
        winners = [x for x in cells if x["eligible_historical_candidate"]]
        winners.sort(key=lambda x:(float(x["gate"]["net_expectancy_bps_delta"]), float(x["gate"].get("profit_factor_delta") or -1e30), float(x["gate"]["drawdown_reduction_bps"]), int(x["kept_T"])), reverse=True)
        selected = winners[0]["cell_id"] if winners else None
        result_lanes[lane_id] = {
            "original_parent_preserved": True,
            "original_parent_metrics_current_rolling": parent_m,
            "original_frozen_parent_T": int(contract["parents"][lane_id]["original_frozen_parent_T"]),
            "historical_strict_ceiling_T": int(contract["parents"][lane_id]["historical_strict_ceiling_T"]),
            "donor_development_population_T_not_consumed": int(contract["parents"][lane_id]["donor_development_population_T_is_not_parent_T"]),
            "evaluated_parent_closed_T": len(trades),
            "cells": cells,
            "selected_historical_candidate": selected,
            "formal_g4_credit_T": 0,
            "formal_g5_credit_T": 0,
            "source_summary": src,
        }
    result = {
        "schema_version":"zel.a1.top5.parent_preserving_component_transplant.receipt.v1",
        "state":"PASS_PARENT_PRESERVING_COMPONENT_TRANSPLANT_EVALUATED",
        "contract_path":str(CONTRACT.relative_to(ROOT)),
        "parent_source_path":str(PARENTS.relative_to(ROOT)),
        "lanes":result_lanes,
        "whole_replacement_population_consumed":False,
        "post_result_retune":False,
        "threshold_sweep":False,
        "cost_rededuction_count":0,
        "parent_exit_mutation_count":0,
        "selection_authority":False,
        "promotion_authority":False,
        "execution_authority":"NONE",
        "order_authority":"BLOCKED",
        "live_trade_authority":"BLOCKED"
    }
    result["receipt_sha256"] = sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k:{"parent_T":v["evaluated_parent_closed_T"],"parent":v["original_parent_metrics_current_rolling"],"selected":v["selected_historical_candidate"],"cells":[{"id":c["cell_id"],"T":c["kept_T"],"net":c["metrics"]["net_pnl_bps"],"exp":c["metrics"]["net_expectancy_bps"],"pf":c["metrics"]["profit_factor"],"dd":c["metrics"]["drawdown_bps"],"eligible":c["eligible_historical_candidate"]} for c in v["cells"]]} for k,v in result_lanes.items()}, sort_keys=True))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args()
    run(a.out)


if __name__ == "__main__":
    main()
