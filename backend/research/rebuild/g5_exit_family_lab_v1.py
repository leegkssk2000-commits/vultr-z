#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
FEATURE_LEDGER = ROOT / "backend/research/rebuild/g5_exit_feature_ledger_latest_v1.json"
CONTRACT = ROOT / "backend/research/contracts/g5_exit_research_contract_v1.json"
SCHEMA = "zel.g5.exit_family_lab.v1"
FAMILIES = (
    "TIME_DECAY_EXIT",
    "VOLATILITY_ADAPTIVE_STOP",
    "MFE_RUNNER",
    "PARTIAL_TRAIL",
    "REGIME_CONDITIONED_EXIT",
)


def read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def close_at_or_after(points: Sequence[Mapping[str, Any]], t_min: float) -> tuple[float, float] | None:
    rows = [x for x in points if float(x.get("t_min") or 0.0) >= t_min]
    if not rows:
        return None
    row = min(rows, key=lambda x: float(x.get("t_min") or 0.0))
    return float(row["close_directional_bps"]), float(row["t_min"])


def incremental_sigma(points: Sequence[Mapping[str, Any]], calibration_min: float = 60.0) -> float | None:
    rows = [x for x in points if float(x.get("t_min") or 0.0) <= calibration_min]
    closes = [float(x["close_directional_bps"]) for x in rows]
    if len(closes) < 4:
        return None
    increments = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    return statistics.pstdev(increments)


def native_gross(row: Mapping[str, Any]) -> float:
    return float(row.get("gross_bps") or 0.0)


def realized_cost(row: Mapping[str, Any]) -> float:
    return float(row.get("fee_bps") or 0.0) + float(row.get("slippage_bps") or 0.0) + float(row.get("funding_bps") or 0.0)


def family_trade(row: Mapping[str, Any], family: str) -> dict[str, Any]:
    f = row.get("features") if isinstance(row.get("features"), Mapping) else {}
    points = [x for x in (f.get("directional_path_5m") or []) if isinstance(x, Mapping)]
    points = sorted(points, key=lambda x: float(x.get("t_min") or 0.0))
    if not points:
        return {"evaluable": False, "reason": "DIRECTIONAL_PATH_MISSING"}
    native = native_gross(row)
    cost = realized_cost(row)
    exit_gross = native
    exit_min = float(f.get("hold_min") or points[-1].get("t_min") or 0.0)
    extra_cost = 0.0
    mechanism: dict[str, Any] = {}

    if family == "TIME_DECAY_EXIT":
        hit = close_at_or_after(points, 1440.0)
        if hit is not None and exit_min > 1440.0:
            exit_gross, exit_min = hit
        mechanism = {"fixed_horizon_min": 1440, "sweep": False}

    elif family == "VOLATILITY_ADAPTIVE_STOP":
        sigma = incremental_sigma(points)
        if sigma is None:
            return {"evaluable": False, "reason": "FIRST_HOUR_PATH_INSUFFICIENT"}
        stop_bps = max(25.0, 2.5 * sigma)
        for p in points:
            if float(p["t_min"]) <= 60.0:
                continue
            if float(p["close_directional_bps"]) <= -stop_bps:
                exit_gross, exit_min = float(p["close_directional_bps"]), float(p["t_min"])
                break
        mechanism = {"calibration_min": 60, "stop_sigma_multiple": 2.5, "floor_bps": 25.0, "sweep": False}

    elif family in {"MFE_RUNNER", "PARTIAL_TRAIL"}:
        sigma = incremental_sigma(points)
        if sigma is None:
            return {"evaluable": False, "reason": "FIRST_HOUR_PATH_INSUFFICIENT"}
        activation = max(50.0, 3.0 * sigma)
        retrace = max(25.0, 1.5 * sigma)
        peak = 0.0
        activated = False
        partial_gross: float | None = None
        runner_gross = native
        runner_min = exit_min
        for p in points:
            t = float(p["t_min"]); fav = float(p["favorable_bps"]); close = float(p["close_directional_bps"])
            peak = max(peak, fav)
            if t <= 60.0:
                continue
            if not activated and peak >= activation:
                activated = True
                partial_gross = close
            if activated and peak - close >= retrace:
                runner_gross, runner_min = close, t
                break
        if family == "MFE_RUNNER":
            exit_gross, exit_min = runner_gross, runner_min
        else:
            if activated and partial_gross is not None:
                exit_gross = 0.30 * partial_gross + 0.70 * runner_gross
                exit_min = runner_min
                extra_cost = 0.15 * (float(row.get("fee_bps") or 0.0) + float(row.get("slippage_bps") or 0.0))
            else:
                exit_gross = native
        mechanism = {"calibration_min": 60, "activation_sigma_multiple": 3.0, "retrace_sigma_multiple": 1.5, "partial_fraction": (0.30 if family == "PARTIAL_TRAIL" else 0.0), "sweep": False}

    elif family == "REGIME_CONDITIONED_EXIT":
        samples = [x for x in (row.get("microstructure_samples") or []) if isinstance(x, Mapping)]
        samples = sorted(samples, key=lambda x: int(x.get("observed_at_ms") or 0))
        if len(samples) < 2:
            return {"evaluable": False, "reason": "MIDPATH_MICROSTRUCTURE_SAMPLES_LT2"}
        side = str(row.get("side") or "")
        consecutive = 0
        trigger_min: float | None = None
        entry_ts = int(row.get("entry_ts") or 0)
        for s in samples:
            imb = s.get("book_imbalance")
            if imb is None:
                consecutive = 0
                continue
            adverse = float(imb) < 0 if side == "long" else float(imb) > 0
            consecutive = consecutive + 1 if adverse else 0
            if consecutive >= 2:
                trigger_min = max(0.0, (int(s["observed_at_ms"]) - entry_ts) / 60_000.0)
                break
        if trigger_min is not None:
            hit = close_at_or_after(points, trigger_min)
            if hit is not None:
                exit_gross, exit_min = hit
        mechanism = {"adverse_book_sign_consecutive_samples": 2, "magnitude_threshold": None, "sweep": False}
    else:
        raise RuntimeError(f"FAMILY_UNKNOWN:{family}")

    return {
        "evaluable": True,
        "candidate_gross_bps": exit_gross,
        "candidate_net_bps": exit_gross - cost - extra_cost,
        "native_gross_bps": native,
        "native_net_bps": float(row.get("net_bps") or (native - cost)),
        "candidate_exit_min": exit_min,
        "extra_execution_cost_bps": extra_cost,
        "mechanism": mechanism,
        "cost_semantics": "REALIZED_NATIVE_COST_REFERENCE_PLUS_EXPLICIT_EXTRA_PARTIAL_COST__G5_NO_CREDIT",
    }


def metrics(values: Sequence[float]) -> dict[str, Any]:
    xs = [float(x) for x in values]
    wins = [x for x in xs if x > 0]
    losses = [-x for x in xs if x < 0]
    gross_profit = sum(wins); gross_loss = sum(losses)
    pf = None if gross_loss == 0 else gross_profit / gross_loss
    equity = peak = dd = 0.0
    for x in xs:
        equity += x; peak = max(peak, equity); dd = max(dd, peak - equity)
    return {
        "T": len(xs),
        "net_bps": sum(xs),
        "expectancy_bps": (sum(xs) / len(xs) if xs else None),
        "win_rate": (len(wins) / len(xs) if xs else None),
        "profit_factor": pf,
        "drawdown_bps": dd,
    }


def positive_windows(values: Sequence[float], n: int = 3) -> int:
    xs = list(values)
    if not xs:
        return 0
    count = 0
    for i in range(n):
        lo = round(i * len(xs) / n); hi = round((i + 1) * len(xs) / n)
        if hi > lo and sum(xs[lo:hi]) > 0:
            count += 1
    return count


def build(feature_ledger: Mapping[str, Any]) -> dict[str, Any]:
    rows = [x for x in feature_ledger.get("rows") or [] if isinstance(x, Mapping) and x.get("feature_complete") is True]
    native_values = [float(x.get("net_bps") or 0.0) for x in rows]
    native = metrics(native_values)
    results: dict[str, Any] = {}
    for family in FAMILIES:
        trades = [family_trade(row, family) for row in rows]
        evaluable = [x for x in trades if x.get("evaluable") is True]
        vals = [float(x["candidate_net_bps"]) for x in evaluable]
        matched_native = [float(x["native_net_bps"]) for x in evaluable]
        m = metrics(vals)
        base_m = metrics(matched_native)
        delta = (m["net_bps"] - base_m["net_bps"]) if vals else None
        results[family] = {
            "evaluable_T": len(evaluable),
            "unevaluable_T": len(trades) - len(evaluable),
            "metrics": m,
            "matched_native_metrics": base_m,
            "net_delta_bps": delta,
            "positive_windows": positive_windows(vals),
            "diagnostic_only": True,
            "formal_credit": 0,
            "trades": trades,
        }
    complete_T = int(feature_ledger.get("feature_complete_T") or len(rows))
    ranked = sorted(
        [
            (family, r) for family, r in results.items()
            if int(r["evaluable_T"]) >= 6 and r.get("net_delta_bps") is not None
        ],
        key=lambda kv: (float(kv[1]["net_delta_bps"]), -float(kv[1]["metrics"].get("drawdown_bps") or 0.0)),
        reverse=True,
    )
    research_leader = ranked[0][0] if ranked else None
    g6_candidate = None
    if complete_T >= 12 and ranked:
        family, r = ranked[0]
        m, b = r["metrics"], r["matched_native_metrics"]
        if float(r["net_delta_bps"]) > 0 and int(r["positive_windows"]) >= 2 and float(m["drawdown_bps"]) <= float(b["drawdown_bps"]) + 1e-9:
            g6_candidate = family
    state = "WAIT_PRODUCTION_EXIT_FEATURE_T" if complete_T < 6 else (
        "G5_EXIT_FAMILY_DIAGNOSTIC_ACTIVE" if complete_T < 12 else "G5_EXIT_FAMILY_STABILITY_VIEW_READY"
    )
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "production_feature_T": complete_T,
        "native_metrics": native,
        "family_results": results,
        "research_leader_non_authoritative": research_leader,
        "g6_preregister_candidate_non_authoritative": g6_candidate,
        "legacy_rr_geometry_rejected": True,
        "same_family_numeric_resweep": False,
        "g4_reference_used_for_selection": False,
        "formal_credit": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    out["receipt_sha256"] = ev.stable(out)
    return out


def self_test() -> int:
    points = []
    for i in range(1, 40):
        points.append({"t_min": i * 5.0, "favorable_bps": max(0.0, i * 4.0), "adverse_bps": max(0.0, 20.0 - i), "close_directional_bps": i * 3.0})
    row = {
        "trade_id": "t", "side": "long", "entry_ts": 1_000_000,
        "gross_bps": 100.0, "net_bps": 80.0, "fee_bps": 8.0, "slippage_bps": 10.0, "funding_bps": 2.0,
        "feature_complete": True,
        "features": {"hold_min": 195.0, "directional_path_5m": points},
        "microstructure_samples": [
            {"observed_at_ms": 1_300_000, "book_imbalance": -0.1},
            {"observed_at_ms": 1_600_000, "book_imbalance": -0.2},
        ],
    }
    for family in FAMILIES:
        x = family_trade(row, family)
        assert "evaluable" in x
    ledger = {"feature_complete_T": 6, "rows": [dict(row, trade_id=f"t{i}") for i in range(6)]}
    out = build(ledger)
    assert out["formal_credit"] == 0 and out["selection_authority"] is False
    assert out["legacy_rr_geometry_rejected"] is True
    assert set(out["family_results"]) == set(FAMILIES)
    print("PASS_G5_EXIT_FAMILY_LAB_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=FEATURE_LEDGER)
    ap.add_argument("--output", type=Path, default=Path("out/g5_exit_family_lab_latest_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    out = build(read(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": out["state"], "T": out["production_feature_T"], "leader": out["research_leader_non_authoritative"], "g6_candidate": out["g6_preregister_candidate_non_authoritative"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
