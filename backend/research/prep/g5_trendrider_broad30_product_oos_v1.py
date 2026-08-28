#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as ev2

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
SEAL = ROOT / "backend/research/rebuild/a1_g4_trendrider_broad30_economic_survivor_v1.json"
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
SCHEMA = "zel.g5.trendrider_broad30.product_oos.v1"
EPS = 1e-12


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def validate_seal(seal: Mapping[str, Any]) -> None:
    supplied = str(seal.get("receipt_sha256") or "")
    core = dict(seal)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("G4_ECONOMIC_SURVIVOR_SEAL_SHA_MISMATCH")
    if seal.get("state") != "PASS_G4_ECONOMIC_SURVIVOR":
        raise RuntimeError("G4_ECONOMIC_SURVIVOR_NOT_PASS")
    if seal.get("strategy_id") != "trend_rider" or seal.get("lane_id") != "trend_rider_broad_wr7000":
        raise RuntimeError("G4_ECONOMIC_SURVIVOR_IDENTITY_MISMATCH")
    if (seal.get("economic_gate") or {}).get("pass") is not True:
        raise RuntimeError("G4_ECONOMIC_GATE_NOT_PASS")
    if (seal.get("strict_reference") or {}).get("canonical_strict_survivor_mutated") is not False:
        raise RuntimeError("STRICT_REFERENCE_MUTATION_FORBIDDEN")


def trade_key(row: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(row["symbol"]), int(row["signal_ts"]), int(row["entry_ts"]), str(row["side"])


def metrics(rows: list[Mapping[str, Any]], values: list[float] | None = None) -> dict[str, Any]:
    vals = [float(x.get("net_bps") or 0.0) for x in rows] if values is None else [float(x) for x in values]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    avgw = gp / len(wins) if wins else 0.0
    avgl = gl / len(losses) if losses else 0.0
    return {
        "trades": len(vals),
        "wins": len(wins),
        "win_rate": len(wins) / len(vals) if vals else 0.0,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else 0.0,
        "profit_factor": gp / gl if gl > 0 else (None if gp <= 0 else "INF"),
        "payoff": avgw / avgl if avgl > 0 else (None if avgw <= 0 else "INF"),
        "drawdown_bps": dd,
    }


def numeric_ge_one(value: Any) -> bool:
    if value == "INF":
        return True
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) + EPS >= 1.0


def economics_nonfail(m: Mapping[str, Any]) -> bool:
    return bool(
        int(m.get("trades") or 0) > 0
        and float(m.get("net_pnl_bps") or 0.0) > 0
        and float(m.get("net_expectancy_bps") or 0.0) > 0
        and numeric_ge_one(m.get("profit_factor"))
        and numeric_ge_one(m.get("payoff"))
    )


def current_policy_replay(*, out_path: Path, boundary_utc: str) -> dict[str, Any]:
    canonical = LEDGER.read_bytes()
    canonical_sha = hashlib.sha256(canonical).hexdigest()
    ledger = json.loads(canonical.decode("utf-8"))
    if not isinstance((ledger.get("strategies") or {}).get("trend_rider"), dict):
        raise RuntimeError("TREND_RIDER_LEDGER_ROW_MISSING")

    shadow = json.loads(json.dumps(ledger))
    shadow["active_strategy_id"] = "trend_rider"
    shadow["strategies"]["trend_rider"]["status"] = "ACTIVE"
    shadow["strategies"]["trend_rider"]["prospective_boundary_utc"] = boundary_utc

    with tempfile.TemporaryDirectory(prefix="g5-trendrider-broad30-") as td:
        shadow_path = Path(td) / "ledger.json"
        shadow_path.write_text(json.dumps(shadow, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        old_ledger, old_argv = ev.LEDGER_PATH, sys.argv[:]
        try:
            ev.LEDGER_PATH = shadow_path
            sys.argv = [
                old_argv[0], "--strategy-id", "trend_rider", "--symbols", "BTC-USDT,ETH-USDT", "--out", str(out_path)
            ]
            ev.main()
        finally:
            ev.LEDGER_PATH = old_ledger
            sys.argv = old_argv

    if hashlib.sha256(LEDGER.read_bytes()).hexdigest() != canonical_sha:
        raise RuntimeError("CANONICAL_LEDGER_MUTATED")
    receipt = read(out_path)
    receipt["source_quality_gate"] = ev2.source_quality_gate(receipt)
    return receipt


def funding_p95_by_symbol(receipt: Mapping[str, Any]) -> dict[str, float]:
    snaps = receipt.get("execution_snapshots") if isinstance(receipt.get("execution_snapshots"), Mapping) else {}
    out: dict[str, float] = {}
    for symbol, row in snaps.items():
        if isinstance(row, Mapping) and isinstance(row.get("funding_p95_abs_bps"), (int, float)):
            out[str(symbol)] = float(row["funding_p95_abs_bps"])
    return out


def stress_cost_2x(rows: list[Mapping[str, Any]]) -> list[float]:
    return [float(x.get("net_bps") or 0.0) - float(x.get("realized_cost_bps") or 0.0) for x in rows]


def stress_p95_funding(rows: list[Mapping[str, Any]], p95: Mapping[str, float]) -> list[float]:
    out: list[float] = []
    for row in rows:
        actual = float(row.get("funding_bps") or 0.0)
        count = int(row.get("funding_settlement_count") or 0)
        stressed = float(p95.get(str(row["symbol"]), 0.0)) * count
        out.append(float(row.get("net_bps") or 0.0) + actual - stressed)
    return out


def stress_plus_one_bar(rows: list[Mapping[str, Any]], bars_by: Mapping[str, list[Mapping[str, Any]]]) -> tuple[list[float], list[str]]:
    values: list[float] = []
    defects: list[str] = []
    idx_by = {symbol: {int(b["ts_ms"]): b for b in bars} for symbol, bars in bars_by.items()}
    for row in rows:
        symbol = str(row["symbol"])
        delayed_ts = int(row["entry_ts"]) + 3_600_000
        bar = idx_by.get(symbol, {}).get(delayed_ts)
        if bar is None or delayed_ts >= int(row["exit_ts"]):
            defects.append(f"PLUS_ONE_BAR_UNAVAILABLE:{symbol}:{row['entry_ts']}")
            continue
        delayed_entry = float(bar["open"])
        exit_price = float(row["exit"])
        if delayed_entry <= 0 or exit_price <= 0:
            defects.append(f"PLUS_ONE_BAR_PRICE_INVALID:{symbol}:{row['entry_ts']}")
            continue
        side = str(row["side"]).lower()
        if side == "long":
            gross = (exit_price / delayed_entry - 1.0) * 10_000.0
        elif side == "short":
            gross = (1.0 - exit_price / delayed_entry) * 10_000.0
        else:
            defects.append(f"PLUS_ONE_BAR_SIDE_INVALID:{side}")
            continue
        values.append(gross - float(row.get("realized_cost_bps") or 0.0))
    return values, defects


def evaluate(receipt: Mapping[str, Any], seal: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    validate_seal(seal)
    src = seal["source_authority"]
    if str(receipt.get("strategy_id")) != "trend_rider":
        raise RuntimeError("G5_STRATEGY_MISMATCH")
    if str(receipt.get("policy_sha")) != str(src["policy_sha"]):
        raise RuntimeError(f"G5_POLICY_DRIFT:{receipt.get('policy_sha')}:{src['policy_sha']}")
    if str(receipt.get("config_sha")) != str(src["config_sha"]):
        raise RuntimeError(f"G5_CONFIG_DRIFT:{receipt.get('config_sha')}:{src['config_sha']}")
    if (receipt.get("source_quality_gate") or {}).get("state") not in ("PASS", "PENDING"):
        raise RuntimeError("G5_SOURCE_QUALITY_FAIL")
    if list(receipt.get("integrity_defects") or []):
        raise RuntimeError("G5_INTEGRITY_DEFECT")
    if int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("G5_LOOKAHEAD_DEFECT")

    boundary_ms = int(manifest["prospective_boundary_ms"])
    rows = sorted(
        [
            dict(x) for x in (receipt.get("trades") or [])
            if int(x.get("signal_ts") or 0) > boundary_ms and int(x.get("exit_ts") or 0) > boundary_ms
        ],
        key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in rows:
        dedup[trade_key(row)] = row
    rows = list(dedup.values())
    w2_n = int(manifest["windows"]["W2"]["target_closed_trades"])
    w3_n = int(manifest["windows"]["W3"]["target_closed_trades"])
    w2, w3 = rows[:w2_n], rows[w2_n:w2_n + w3_n]
    combined = w2 + w3

    w2m, w3m, cm = metrics(w2), metrics(w3), metrics(combined)
    p95 = funding_p95_by_symbol(receipt)
    bars_by = {
        symbol: [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        for symbol in sorted({str(x["symbol"]) for x in combined})
    } if combined else {}
    plus_vals, plus_defects = stress_plus_one_bar(combined, bars_by) if combined else ([], [])
    stress = {
        "COST_2X": metrics(combined, stress_cost_2x(combined)) if combined else metrics([]),
        "P95_FUNDING": metrics(combined, stress_p95_funding(combined, p95)) if combined else metrics([]),
        "PLUS_ONE_BAR": metrics(combined[:len(plus_vals)], plus_vals) if plus_vals else metrics([]),
        "PLUS_ONE_BAR_defects": plus_defects,
    }

    w2_ready, w3_ready = len(w2) >= w2_n, len(w3) >= w3_n
    checks = {
        "w2_ready": w2_ready,
        "w3_ready": w3_ready,
        "w2_economics_nonfail": economics_nonfail(w2m) if w2_ready else False,
        "w3_economics_nonfail": economics_nonfail(w3m) if w3_ready else False,
        "combined_economics_nonfail": economics_nonfail(cm) if w3_ready else False,
        "cost_2x_nonfail": economics_nonfail(stress["COST_2X"]) if w3_ready else False,
        "p95_funding_nonfail": economics_nonfail(stress["P95_FUNDING"]) if w3_ready else False,
        "plus_one_bar_complete": w3_ready and not plus_defects and len(plus_vals) == len(combined),
        "plus_one_bar_nonfail": economics_nonfail(stress["PLUS_ONE_BAR"]) if w3_ready and not plus_defects else False,
    }
    if not w2_ready:
        state = "WAIT_G5_W2_12"
    elif not w3_ready:
        state = "WAIT_G5_W3_12"
    elif all(checks.values()):
        state = "PASS_G5_PRODUCT_OOS_WALK_FORWARD_STRESS"
    else:
        state = "HOLD_G5_PRODUCT_VALIDATION_FAIL"

    result = {
        "schema_version": SCHEMA,
        "stage": "G5",
        "state": state,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "g4_survivor_receipt_sha256": seal["receipt_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "source_quality_state": (receipt.get("source_quality_gate") or {}).get("state"),
        "postlock_closed_T": len(rows),
        "windows": {
            "W1": {"role": "LOCKED_REFERENCE_ONLY", "metrics": seal["sealed_metrics"], "retuned": False},
            "W2": {"role": "OOS_1", "metrics": w2m, "target_T": w2_n},
            "W3": {"role": "OOS_2", "metrics": w3m, "target_T": w3_n},
        },
        "combined_oos": cm,
        "stress": stress,
        "checks": checks,
        "strict_g5_reference_contract": "backend/research/prep/g5_validation_contract_v1.json",
        "strict_g5_reference_is_nonblocking_product_path": True,
        "policy_retune": False,
        "threshold_retune": False,
        "old_history_union": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    seal, manifest = read(SEAL), read(MANIFEST)
    validate_seal(seal)
    assert manifest["state"] == "FROZEN_G5_PRODUCT_MANIFEST"
    rows = [
        {"symbol": "BTC-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "net_bps": 100.0, "realized_cost_bps": 10.0},
        {"symbol": "ETH-USDT", "signal_ts": 4, "entry_ts": 5, "exit_ts": 6, "side": "long", "net_bps": -20.0, "realized_cost_bps": 10.0},
    ]
    m = metrics(rows)
    assert m["trades"] == 2 and abs(m["net_pnl_bps"] - 80.0) < EPS
    assert abs(metrics(rows, stress_cost_2x(rows))["net_pnl_bps"] - 60.0) < EPS
    assert economics_nonfail(m)
    assert manifest["windows"]["W2"]["target_closed_trades"] == 12
    assert manifest["windows"]["W3"]["target_closed_trades"] == 12
    print("PASS_G5_TRENDRIDER_BROAD30_PRODUCT_OOS_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/g5_trendrider_broad30_product_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    seal, manifest = read(SEAL), read(MANIFEST)
    validate_seal(seal)
    with tempfile.TemporaryDirectory(prefix="g5-trendrider-replay-") as td:
        receipt = current_policy_replay(
            out_path=Path(td) / "receipt.json",
            boundary_utc=str(manifest["prospective_boundary_utc"]),
        )
    result = evaluate(receipt, seal, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "postlock_closed_T": result["postlock_closed_T"],
        "W2_T": result["windows"]["W2"]["metrics"]["trades"],
        "W3_T": result["windows"]["W3"]["metrics"]["trades"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
