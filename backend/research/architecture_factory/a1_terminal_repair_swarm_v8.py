#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
V7_RECEIPT = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v7_latest.json"
BOUNDARY_MS = econ._cutoff_ms()
COST_BPS = econ.COST_BPS
MIN_OOS_EVENTS = 12
WARMUP_BARS = 180
INTERVAL_MS = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _read_v7() -> dict[str, Any]:
    value = json.loads(V7_RECEIPT.read_text(encoding="utf-8"))
    if value.get("schema_version") != "zel.a1_terminal_repair_swarm.v7":
        raise RuntimeError("V7_RECEIPT_SCHEMA_INVALID")
    if int(value.get("development_economic_pass_count") or 0) <= 0:
        raise RuntimeError("V7_HAS_NO_ECONOMIC_PASS")
    if (value.get("compiler") or {}).get("spec_reject_closed") is not True:
        raise RuntimeError("V7_COMPILER_NOT_CLOSED")
    return value


def _recent_bars(symbol: str, interval: str, now_ms: int) -> list[dict[str, float]]:
    if interval not in econ.INTERVAL_MAP or interval not in INTERVAL_MS:
        raise ValueError(f"INTERVAL_UNSUPPORTED:{interval}")
    step = INTERVAL_MS[interval]
    warmup_start = BOUNDARY_MS - WARMUP_BARS * step
    all_rows: dict[int, dict[str, float]] = {}
    end = now_ms
    for _ in range(4):
        payload = econ._req({"symbol": symbol, "interval": econ.INTERVAL_MAP[interval], "limit": 1000, "endTime": end})
        page = sorted(econ._decode_rows(payload), key=lambda x: int(x["ts"]))
        if not page:
            break
        for row in page:
            ts = int(row["ts"])
            if warmup_start <= ts and ts + step <= now_ms:
                all_rows[ts] = row
        oldest = int(page[0]["ts"])
        if oldest <= warmup_start or oldest >= end:
            break
        end = oldest - 1
    return [all_rows[k] for k in sorted(all_rows)]


def _features(rows: list[dict[str, float]], spec: Mapping[str, Any]) -> tuple[dict[str, list[float | None]], econ.Expr]:
    features: dict[str, list[float | None]] = {}
    engine = econ.Expr(rows, features)
    for raw in spec.get("features") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("FEATURE_OBJECT_REQUIRED")
        name = str(raw.get("name") or "").strip()
        formula = econ._feature_formula(str(raw.get("formula") or ""))
        if not name or not formula:
            raise ValueError("FEATURE_EMPTY")
        if name in features:
            raise ValueError(f"FEATURE_DUPLICATE:{name}")
        features[name] = []
        engine = econ.Expr(rows, features)
        engine.validate(formula)
        arr = features[name]
        for i in range(len(rows)):
            try:
                value = engine.eval(formula, i)
                arr.append(float(value) if isinstance(value, (int, float, bool)) and math.isfinite(float(value)) else None)
            except (TypeError, ZeroDivisionError, ValueError):
                arr.append(None)
    return features, econ.Expr(rows, features)


def _evaluate(candidate: Mapping[str, Any], now_ms: int) -> dict[str, Any]:
    cid = str(candidate.get("candidate_id") or "")
    spec = candidate.get("executable_spec")
    if not isinstance(spec, Mapping):
        return {"candidate_id": cid, "state": "REJECT_SPEC_MISSING", "economic_pass": False}
    interval = str(spec.get("bar_interval") or "")
    step = INTERVAL_MS.get(interval)
    if not step:
        return {"candidate_id": cid, "state": "REJECT_INTERVAL", "economic_pass": False}
    try:
        hold = int(spec.get("max_hold_bars") or 0)
    except Exception:
        hold = 0
    if not 1 <= hold <= 720:
        return {"candidate_id": cid, "state": "REJECT_HOLD", "economic_pass": False}

    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    exit_rule = str(spec.get("exit_rule") or "time_stop")
    time_only = exit_rule.strip().lower() in {"time_stop", "time stop", "max_hold", "max_hold_bars"}
    trades: list[dict[str, Any]] = []
    source: dict[str, Any] = {}

    try:
        for symbol in econ.SYMBOLS:
            rows = _recent_bars(symbol, interval, now_ms)
            post = [r for r in rows if int(r["ts"]) >= BOUNDARY_MS]
            source[symbol] = {
                "all_closed_bars_with_warmup": len(rows),
                "post_boundary_closed_bars": len(post),
                "first_post_boundary_bar_ts": int(post[0]["ts"]) if post else None,
                "last_post_boundary_bar_ts": int(post[-1]["ts"]) if post else None,
            }
            features, engine = _features(rows, spec)
            engine.validate(entry_rule)
            econ._validate_side(side_rule, engine)
            if not time_only:
                engine.validate(exit_rule)

            i = max(30, 1)
            while i < len(rows) - 1:
                signal_ts = int(rows[i]["ts"])
                if signal_ts < BOUNDARY_MS:
                    i += 1
                    continue
                try:
                    fire = bool(engine.eval(entry_rule, i))
                except (TypeError, ZeroDivisionError, ValueError):
                    fire = False
                if not fire:
                    i += 1
                    continue
                side = econ._side(side_rule, engine, i)
                if side not in {"long", "short"}:
                    raise ValueError("SIDE_RULE_UNSUPPORTED")
                entry_i = i + 1
                if entry_i >= len(rows):
                    break
                desired_exit_i = entry_i + hold - 1
                if desired_exit_i >= len(rows):
                    # Genuine signal exists, but the frozen holding horizon has not closed yet.
                    break
                exit_i = desired_exit_i
                if not time_only:
                    for j in range(entry_i, desired_exit_i + 1):
                        if bool(engine.eval(exit_rule, j)):
                            exit_i = j
                            break
                entry_px = float(rows[entry_i]["open"])
                exit_px = float(rows[exit_i]["close"])
                gross = (exit_px / entry_px - 1.0) * 10000.0 * (1 if side == "long" else -1)
                net = gross - COST_BPS
                trades.append({
                    "candidate_id": cid,
                    "symbol": symbol,
                    "side": side,
                    "signal_ts": signal_ts,
                    "entry_ts": int(rows[entry_i]["ts"]),
                    "exit_ts": int(rows[exit_i]["ts"]),
                    "gross_bps": gross,
                    "net_bps": net,
                })
                i = max(i + 1, exit_i + 1)
    except Exception as exc:
        return {
            "candidate_id": cid,
            "state": "REJECT_OOS_EXECUTION",
            "error": f"{type(exc).__name__}:{str(exc)[:260]}",
            "economic_pass": False,
            "source_summary": source,
        }

    net = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    elapsed_days = max(1e-9, (now_ms - BOUNDARY_MS) / 86_400_000.0)
    metrics = {
        "trades": len(net),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_pnl_bps": sum(net),
        "profit_factor": econ._pf(net),
        "payoff": econ._payoff(net),
        "win_rate": sum(1 for x in net if x > 0) / len(net) if net else None,
        "drawdown_bps": econ._dd(net),
        "cost_bps_per_trade": COST_BPS,
        "events_per_day": len(net) / elapsed_days,
        "net_bps_per_calendar_day": sum(net) / elapsed_days,
        "prospective_elapsed_days": elapsed_days,
    }
    enough = len(net) >= MIN_OOS_EVENTS
    positive = bool(enough and (metrics["net_expectancy_bps"] or 0) > 0 and (metrics["profit_factor"] or 0) > 1.0 and metrics["net_pnl_bps"] > 0)
    state = "OOS_PASS_EARLY" if positive else ("OOS_FAIL_ECONOMICS" if enough else "WAIT_NEW_T")
    return {
        "candidate_id": cid,
        "state": state,
        "economic_pass": positive,
        "enough_events": enough,
        "minimum_oos_events": MIN_OOS_EVENTS,
        "metrics": metrics,
        "source_summary": source,
        "trades": trades,
        "data_scope": "GENUINE_POST_GEN1_BOUNDARY_CLOSED_BARS_ONLY_WITH_PREBOUNDARY_WARMUP",
        "boundary": econ.BOUNDARY,
        "evaluated_at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "development_only": False,
        "prospective": True,
        "promotion_authority": False,
    }


def _compact(row: Mapping[str, Any], dev_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cid = str(row.get("candidate_id") or "")
    m = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    drow = dev_by_id.get(cid) or {}
    dm = drow.get("metrics") if isinstance(drow.get("metrics"), Mapping) else {}
    ne = m.get("net_expectancy_bps")
    dne = dm.get("net_expectancy_bps")
    pf = m.get("profit_factor")
    dpf = dm.get("profit_factor")
    return {
        "candidate_id": cid,
        "state": row.get("state"),
        "trades": m.get("trades"),
        "net_expectancy_bps": ne,
        "profit_factor": pf,
        "win_rate": m.get("win_rate"),
        "net_pnl_bps": m.get("net_pnl_bps"),
        "drawdown_bps": m.get("drawdown_bps"),
        "net_bps_per_calendar_day": m.get("net_bps_per_calendar_day"),
        "development_net_expectancy_bps": dne,
        "development_profit_factor": dpf,
        "net_expectancy_delta_bps": (float(ne) - float(dne)) if isinstance(ne, (int, float)) and isinstance(dne, (int, float)) else None,
        "profit_factor_delta": (float(pf) - float(dpf)) if isinstance(pf, (int, float)) and isinstance(dpf, (int, float)) else None,
    }


def run(output: Path, now_ms: int | None = None) -> dict[str, Any]:
    v7 = _read_v7()
    now_ms = int(now_ms or time.time() * 1000)
    dev = v7.get("development_economics") if isinstance(v7.get("development_economics"), Mapping) else {}
    passed_ids = {str(x.get("candidate_id")) for x in (dev.get("passes") or []) if isinstance(x, Mapping)}
    candidates = [x for x in (v7.get("ai_candidates") or []) if isinstance(x, Mapping) and str(x.get("candidate_id")) in passed_ids]
    if not candidates:
        raise RuntimeError("V7_PASS_CANDIDATES_EMPTY")
    rows = [_evaluate(c, now_ms) for c in candidates]
    dev_by_id = {str(x.get("candidate_id")): x for x in (dev.get("rows") or []) if isinstance(x, Mapping)}
    compact = [_compact(row, dev_by_id) for row in rows]
    pass_count = sum(1 for x in rows if x.get("state") == "OOS_PASS_EARLY")
    fail_count = sum(1 for x in rows if x.get("state") == "OOS_FAIL_ECONOMICS")
    wait_count = sum(1 for x in rows if x.get("state") == "WAIT_NEW_T")
    reject_count = sum(1 for x in rows if str(x.get("state") or "").startswith("REJECT_"))
    result = {
        "schema_version": "zel.a1_terminal_repair_swarm.v8",
        "objective": "GENUINE_POST_BOUNDARY_ECONOMIC_VALIDATION_WITHOUT_RETUNING",
        "source_v7_receipt_sha256": v7.get("receipt_sha256"),
        "source_v7_development_pass_count": int(v7.get("development_economic_pass_count") or 0),
        "boundary": econ.BOUNDARY,
        "evaluated_at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "cost_bps_per_trade": COST_BPS,
        "minimum_oos_events": MIN_OOS_EVENTS,
        "candidate_count": len(rows),
        "oos_pass_count": pass_count,
        "oos_fail_count": fail_count,
        "wait_new_t_count": wait_count,
        "reject_count": reject_count,
        "rows": rows,
        "economic_summary": compact,
        "frozen_validation_contract": {
            "candidate_set_frozen_from_v7": True,
            "formula_retuning": False,
            "threshold_retuning": False,
            "horizon_retuning": False,
            "candidate_reselection_from_oos": False,
            "fees_fixed_bps": COST_BPS,
            "entry_requires_post_boundary_signal_bar": True,
            "only_closed_bars_and_closed_horizons_count": True,
            "preboundary_data_used_only_for_indicator_warmup": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "next": "REVIEW_OOS_PASS_FOR_ALPHA_PROOF_GATE" if pass_count > 0 else ("FALSIFY_OR_REPLACE_FAILED_ARCHITECTURES" if fail_count > 0 else "WAIT_GENUINE_POST_BOUNDARY_CLOSED_T"),
    }
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert MIN_OOS_EVENTS == 12
    assert COST_BPS == 14.0
    assert BOUNDARY_MS == int(datetime.fromisoformat("2026-08-16T18:45:01+00:00").timestamp() * 1000)
    fake = {"candidate_id": "x", "state": "WAIT_NEW_T", "metrics": {"trades": 3, "net_expectancy_bps": 1.0, "profit_factor": 1.2}}
    compact = _compact(fake, {"x": {"metrics": {"net_expectancy_bps": 2.0, "profit_factor": 1.4}}})
    assert compact["net_expectancy_delta_bps"] == -1.0
    assert compact["profit_factor_delta"] < 0
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V8_PROSPECTIVE_OOS_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v8_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "candidate_count": result["candidate_count"],
        "oos_pass": result["oos_pass_count"],
        "oos_fail": result["oos_fail_count"],
        "wait": result["wait_new_t_count"],
        "reject": result["reject_count"],
        "summary": result["economic_summary"],
        "next": result["next"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
