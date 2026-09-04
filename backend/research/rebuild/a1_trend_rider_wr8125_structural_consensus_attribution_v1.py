#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_wr8125_dynamic_trendline_htf_attribution_v2 as frozen_authority
from backend.research.rebuild import trend_rider_wr8125_structural_consensus_child_policy_v1 as candidate_policy

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_frozen24_source_v1.json"
EXACT_PARENT = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
PREREG = ROOT / "backend/research/contracts/g5_trend_rider_structural_consensus_prereg_v1.json"
SCHEMA = "zel.a1.trend_rider.wr8125.structural_consensus_attribution.v1"
BASE_TRADES = 16
BASE_WINS = 13
BASE_WR = 0.8125
BASE_NET_BPS = 23297.769437281215
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _write(out: Path, result: dict[str, Any]) -> dict[str, Any]:
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _is_restored_identity(row: Mapping[str, Any], restored: Mapping[str, Any]) -> bool:
    return (
        str(row.get("symbol")) == str(restored.get("symbol"))
        and int(row.get("signal_ts") or 0) == int(restored.get("signal_ts") or -1)
        and str(row.get("side")) == str(restored.get("side"))
    )


def _fused_stats(selected: list[dict[str, Any]]) -> dict[str, Any]:
    winners = sum(1 for x in selected if float(x["net_bps"]) > 0.0)
    trades = BASE_TRADES + len(selected)
    wins = BASE_WINS + winners
    net = BASE_NET_BPS + sum(float(x["net_bps"]) for x in selected)
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": wins / trades if trades else None,
        "net_pnl_bps": net,
        "net_expectancy_bps": net / trades if trades else None,
        "incremental_us_selected": len(selected),
        "incremental_us_winners": winners,
        "incremental_us_losers": len(selected) - winners,
    }


def _enrich(rows: list[dict[str, Any]]) -> int:
    missing = 0
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        index = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for row in (x for x in rows if str(x["symbol"]) == symbol):
            i = index.get(int(row["signal_ts"]))
            if i is None or i < 65:
                row["structural_feature_missing"] = True
                row["structural_consensus_fresh"] = None
                missing += 1
                continue
            history = bars[: i + 1]
            state = candidate_policy.structural_consensus_state(
                history,
                symbol=symbol,
                now_ts_ms=int(row["signal_ts"]),
            )
            side = str(row["side"])
            key = "long_structural_consensus_fresh" if side == "long" else "short_structural_consensus_fresh"
            row["structural_feature_missing"] = False
            row["structural_consensus_fresh"] = bool(state[key])
            row["structural_state"] = state
    return missing


def run(out: Path) -> dict[str, Any]:
    source = _read(SOURCE)
    exact = _read(EXACT_PARENT)
    prereg = _read(PREREG)

    authority_ok, defects = frozen_authority._authority(source, exact)
    if str(((exact.get("historical_source") or {}).get("policy_path") or "")) != "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py":
        defects.append("FROZEN_SOURCE_POLICY_NOT_TRANSITION_FRESHNESS")
        authority_ok = False
    if prereg.get("state") != "PREREGISTERED_BEFORE_CANDIDATE_EVALUATION":
        defects.append("PREREG_STATE")
        authority_ok = False
    candidate = prereg.get("candidate") or {}
    if candidate.get("architecture_id") != candidate_policy.ARCHITECTURE_ID:
        defects.append("ARCHITECTURE_ID_DRIFT")
        authority_ok = False
    if candidate.get("numeric_threshold_sweep") is not False or candidate.get("candidate_family_sweep") is not False:
        defects.append("SWEEP_FORBIDDEN")
        authority_ok = False
    if int((prereg.get("discovery_gate") or {}).get("candidate_count") or 0) != 1:
        defects.append("CANDIDATE_COUNT_NOT_ONE")
        authority_ok = False

    if not authority_ok:
        return _write(out, {
            "schema_version": SCHEMA,
            "state": "HARD_HOLD_PREREG_OR_FROZEN_AUTHORITY_MISMATCH",
            "strategy_id": "trend_rider",
            "authority_match": False,
            "authority_defects": defects,
            "formal_credit": 0,
            "next": "REPAIR_AUTHORITY_ONLY",
            **AUTH,
        })

    base_metrics = exact.get("metrics") or {}
    expected = {
        "completed_trades": BASE_TRADES,
        "wins": BASE_WINS,
        "win_rate": BASE_WR,
        "net_pnl_bps": BASE_NET_BPS,
    }
    for key, value in expected.items():
        actual = base_metrics.get(key)
        tol = 0.05 if key == "net_pnl_bps" else 1e-12
        if actual is None or abs(float(actual) - float(value)) > tol:
            return _write(out, {
                "schema_version": SCHEMA,
                "state": "HARD_HOLD_BASELINE_METRIC_DRIFT",
                "strategy_id": "trend_rider",
                "authority_match": True,
                "metric": key,
                "expected": value,
                "actual": actual,
                "formal_credit": 0,
                "next": "RESTORE_FROZEN_PARENT_ONLY",
                **AUTH,
            })

    rows = [dict(x) for x in (source.get("us_trade_attribution") or [])]
    restored = (source.get("identity_authority") or {}).get("reintroduced_us_trade") or {}
    remaining = [x for x in rows if not _is_restored_identity(x, restored)]
    if len(remaining) != 8:
        return _write(out, {
            "schema_version": SCHEMA,
            "state": "HARD_HOLD_REMAINING_MEMBERSHIP_DRIFT",
            "strategy_id": "trend_rider",
            "authority_match": True,
            "remaining_count": len(remaining),
            "formal_credit": 0,
            "next": "RESTORE_FROZEN_MEMBERSHIP_ONLY",
            **AUTH,
        })

    missing = _enrich(remaining)
    if missing:
        return _write(out, {
            "schema_version": SCHEMA,
            "state": "HOLD_STRUCTURAL_FEATURE_UNAVAILABLE",
            "strategy_id": "trend_rider",
            "authority_match": True,
            "missing_trade_count": missing,
            "classified_rows": remaining,
            "formal_credit": 0,
            "next": "WAIT_OR_RESTORE_HISTORICAL_1H_SOURCE_VISIBILITY",
            **AUTH,
        })

    selected = [x for x in remaining if x.get("structural_consensus_fresh") is True]
    stats = _fused_stats(selected)
    strict = bool(
        stats["incremental_us_winners"] >= 1
        and stats["incremental_us_losers"] <= 0
        and float(stats["win_rate"]) >= BASE_WR
        and float(stats["net_pnl_bps"]) > BASE_NET_BPS
    )
    state = "STRUCTURAL_CONSENSUS_FUSION_DISCOVERY_PASS" if strict else "NO_STRICT_STRUCTURAL_CONSENSUS_FUSION"
    return _write(out, {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "authority_match": True,
        "architecture_id": candidate_policy.ARCHITECTURE_ID,
        "changed_axis": candidate_policy.AXIS,
        "candidate_count": 1,
        "baseline": {
            "trades": BASE_TRADES,
            "wins": BASE_WINS,
            "win_rate": BASE_WR,
            "net_pnl_bps": BASE_NET_BPS,
        },
        "remaining_us_trade_count": len(remaining),
        "selected_incremental_identities": [
            {
                "symbol": x["symbol"],
                "signal_ts": x["signal_ts"],
                "side": x["side"],
                "net_bps": x["net_bps"],
            }
            for x in selected
        ],
        "candidate": stats,
        "classified_rows": remaining,
        "strict_discovery_pass": strict,
        "historical_result_role": "DESIGN_EVIDENCE_ONLY",
        "historical_union_allowed": False,
        "formal_credit": 0,
        "numeric_threshold_sweep": False,
        "candidate_family_sweep": False,
        "outcome_used_for_runtime": False,
        "rr_exit_mutated": False,
        "parent_incumbent_mutated": False,
        "candidate_freeze_required": bool(strict),
        "fresh_boundary_required": bool(strict),
        "fresh_oos_required": True,
        "next": (
            "FREEZE_CANDIDATE_THEN_START_NEW_FRESH_BOUNDARY"
            if strict
            else "PRESERVE_WR8125_AND_MOVE_TO_DIFFERENT_CAUSAL_ARCHITECTURE_CLASS"
        ),
        **AUTH,
    })


def self_test() -> int:
    selected = [{"net_bps": 20.0}]
    stats = _fused_stats(selected)
    assert stats["trades"] == 17
    assert stats["wins"] == 14
    assert abs(float(stats["win_rate"]) - (14 / 17)) < 1e-12
    assert stats["incremental_us_winners"] == 1 and stats["incremental_us_losers"] == 0
    inv = candidate_policy.invariant_receipt()
    assert inv["baseline_admission_monotonic_superset"] is True
    assert inv["numeric_threshold_sweep"] is False and inv["candidate_family_sweep"] is False
    assert inv["rr_exit_mutated"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_STRUCTURAL_CONSENSUS_ATTRIBUTION_V1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("out/a1_trend_rider_wr8125_structural_consensus_latest.json"),
    )
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "authority_match": result.get("authority_match"),
        "candidate": result.get("candidate"),
        "selected_incremental_identities": result.get("selected_incremental_identities"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
