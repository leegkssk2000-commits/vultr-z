#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_wr8125_dynamic_trendline_htf_attribution_v1 as legacy

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_frozen24_source_v1.json"
EXACT_PARENT = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
SCHEMA = "zel.a1.trend_rider.wr8125.dynamic_trendline_htf_attribution.v2"
EXPECTED_SOURCE_RECEIPT = "3e0f087a1b5536f0eb95532d5289dbee0171c1806805261c129838608534bec5"
EXPECTED_BASE_TRADES = 16
EXPECTED_BASE_WINS = 13
EXPECTED_BASE_WR = 0.8125
EXPECTED_BASE_NET_BPS = 23297.769437281215
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


def _metric(metrics: Mapping[str, Any], key: str) -> Any:
    # The immutable exact parent predates the rescue contract and names its
    # trade-count field completed_trades. The recovered artifact uses trades.
    # Normalize names only; never alter values or replace frozen economics.
    if key == "trades":
        return metrics.get("trades", metrics.get("completed_trades"))
    return metrics.get(key)


def _authority(source: dict[str, Any], exact: dict[str, Any]) -> tuple[bool, list[str]]:
    defects: list[str] = []
    if source.get("schema_version") != "zel.a1.trend_rider.wr8125.frozen24_source.v1":
        defects.append("SOURCE_SCHEMA")
    if source.get("state") != "IMMUTABLE_FROZEN24_SOURCE_RECOVERED":
        defects.append("SOURCE_STATE")
    if source.get("source_receipt_sha256") != EXPECTED_SOURCE_RECEIPT:
        defects.append("SOURCE_RECEIPT_SHA")
    if source.get("historical_union_allowed") is not False:
        defects.append("HISTORICAL_UNION_MUST_BE_FALSE")
    if exact.get("state") != "EXACT_HISTORICAL_PARENT_FROZEN":
        defects.append("EXACT_PARENT_STATE")

    sm = source.get("wr8125_discovery_child") or {}
    em = exact.get("metrics") or {}
    checks = {
        "trades": EXPECTED_BASE_TRADES,
        "wins": EXPECTED_BASE_WINS,
        "win_rate": EXPECTED_BASE_WR,
        "net_pnl_bps": EXPECTED_BASE_NET_BPS,
    }
    for key, expected in checks.items():
        for prefix, metrics in (("source", sm), ("exact", em)):
            value = _metric(metrics, key)
            tolerance = 0.05 if key == "net_pnl_bps" else 1e-12
            if value is None or abs(float(value) - float(expected)) > tolerance:
                defects.append(f"{prefix.upper()}_{key.upper()}_MISMATCH")

    exact_ident = (((exact.get("membership_authority") or {}).get("immutable_identity_authority") or {}).get("reintroduced_us_trade") or {})
    source_ident = ((source.get("identity_authority") or {}).get("reintroduced_us_trade") or {})
    for key in ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "intent_sha"):
        if source_ident.get(key) != exact_ident.get(key):
            defects.append(f"REINTRODUCED_IDENTITY_{key.upper()}")

    rows = source.get("us_trade_attribution") or []
    if len(rows) != 9:
        defects.append("US_TRADE_COUNT_NOT_9")
    if sum(1 for x in rows if float(x.get("net_bps") or 0.0) > 0) != 2:
        defects.append("US_WINNER_COUNT_NOT_2")
    return not defects, defects


def _enrich(rows: list[dict[str, Any]]) -> None:
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        index = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for row in (x for x in rows if str(x["symbol"]) == symbol):
            i = index.get(int(row["signal_ts"]))
            states = None if i is None else legacy._structure_states(bars, i, str(row["side"]))
            if states is None:
                row["dynamic_htf_feature_missing"] = True
                continue
            row.update(states)
            row["dynamic_htf_feature_missing"] = False


def _candidate_stats(base: Mapping[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
    trades = int(_metric(base, "trades")) + len(selected)
    wins = int(base["wins"]) + sum(1 for x in selected if float(x.get("net_bps") or 0.0) > 0)
    net = float(base["net_pnl_bps"]) + sum(float(x.get("net_bps") or 0.0) for x in selected)
    return {
        "trades": trades,
        "wins": wins,
        "win_rate": wins / trades if trades else None,
        "net_pnl_bps": net,
        "net_expectancy_bps": net / trades if trades else None,
    }


def _write(out: Path, result: dict[str, Any]) -> dict[str, Any]:
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def run(out: Path) -> dict[str, Any]:
    source = _read(SOURCE)
    exact = _read(EXACT_PARENT)
    authority_ok, defects = _authority(source, exact)
    if not authority_ok:
        return _write(out, {
            "schema_version": SCHEMA,
            "state": "HARD_HOLD_FROZEN24_AUTHORITY_MISMATCH",
            "strategy_id": "trend_rider",
            "authority_match": False,
            "authority_defects": defects,
            "next": "REPAIR_FROZEN_SOURCE_BINDING_ONLY",
            **AUTH,
        })

    rows = [dict(x) for x in (source.get("us_trade_attribution") or [])]
    _enrich(rows)
    missing = sum(1 for x in rows if x.get("dynamic_htf_feature_missing"))
    if missing:
        return _write(out, {
            "schema_version": SCHEMA,
            "state": "HOLD_FROZEN24_DYNAMIC_FEATURE_UNAVAILABLE",
            "strategy_id": "trend_rider",
            "authority_match": True,
            "missing_trade_count": missing,
            "next": "WAIT_OR_RESTORE_HISTORICAL_1H_SOURCE_VISIBILITY",
            **AUTH,
        })

    base = dict(source["wr8125_discovery_child"])
    restored = (source.get("identity_authority") or {}).get("reintroduced_us_trade") or {}
    remaining = [
        x for x in rows
        if not (
            str(x.get("symbol")) == str(restored.get("symbol"))
            and int(x.get("signal_ts") or 0) == int(restored.get("signal_ts") or -1)
            and str(x.get("side")) == str(restored.get("side"))
        )
    ]

    axes = ("dynamic_trendline_state", "htf_alignment_state", "price_vs_htf_state", "dynamic_htf_combo")
    candidates: list[dict[str, Any]] = []
    for axis in axes:
        for value in sorted({str(x.get(axis)) for x in remaining}):
            selected = [x for x in remaining if str(x.get(axis)) == value]
            stats = _candidate_stats(base, selected)
            winners = sum(1 for x in selected if float(x.get("net_bps") or 0.0) > 0)
            losers = len(selected) - winners
            candidates.append({
                "axis": axis,
                "value": value,
                "candidate": stats,
                "remaining_us_selected": len(selected),
                "winner_reintroduced": winners,
                "loser_reintroduced": losers,
                "delta_wr": float(stats["win_rate"]) - EXPECTED_BASE_WR,
                "delta_net_pnl_bps": float(stats["net_pnl_bps"]) - EXPECTED_BASE_NET_BPS,
                "selected_trade_identities": [
                    {"symbol": x["symbol"], "signal_ts": x["signal_ts"], "side": x["side"], "net_bps": x["net_bps"]}
                    for x in selected
                ],
                "preentry_only": True,
                "ordinal_only": True,
                "numeric_threshold_sweep": False,
                "outcome_used_for_discovery_only": True,
                "outcome_used_at_runtime": False,
            })

    strict = [
        c for c in candidates
        if c["winner_reintroduced"] >= 1
        and c["loser_reintroduced"] == 0
        and float(c["candidate"]["win_rate"]) >= EXPECTED_BASE_WR
        and float(c["candidate"]["net_pnl_bps"]) > EXPECTED_BASE_NET_BPS
    ]
    strict.sort(key=lambda c: (-float(c["candidate"]["net_pnl_bps"]), -float(c["candidate"]["win_rate"]), str(c["axis"]), str(c["value"])))
    recommended = strict[0] if strict else None
    return _write(out, {
        "schema_version": SCHEMA,
        "state": "FROZEN24_DYNAMIC_HTF_STRICT_RESTORE_FOUND" if recommended else "NO_STRICT_FROZEN24_DYNAMIC_HTF_RESTORE",
        "strategy_id": "trend_rider",
        "canonical_head": "trend_rider_wr80_us_chase_cooling_v1",
        "fusion_role": "BROAD_FROZEN24_DISCOVERY_PLUS_WR8125_ADMISSION_PLUS_DYNAMIC_HTF_RESTORE",
        "authority_match": True,
        "source_receipt_sha256": source["source_receipt_sha256"],
        "base_wr8125": {
            "trades": int(_metric(base, "trades")),
            "wins": int(base["wins"]),
            "win_rate": float(base["win_rate"]),
            "net_pnl_bps": float(base["net_pnl_bps"]),
            "net_expectancy_bps": float(base["net_expectancy_bps"]),
        },
        "remaining_us_trade_count": len(remaining),
        "candidate_count": len(candidates),
        "strict_candidate_count": len(strict),
        "recommended_discovery_child": recommended,
        "candidates": candidates,
        "historical_union_allowed": False,
        "historical_metrics_are_design_evidence_only": True,
        "candidate_freeze_required": True,
        "fresh_boundary_required": True,
        "fresh_oos_required": True,
        "g5_formal_credit_before_fresh": 0,
        "rr_exit_mutated": False,
        "numeric_threshold_sweep": False,
        "creator_numeric_threshold_imported": False,
        "creator_performance_claim_imported": False,
        "outcome_used_for_discovery_only": True,
        "outcome_used_at_runtime": False,
        "parent_incumbent_mutated": False,
        "next": "PREREGISTER_FUSION_CHILD_THEN_NEW_FRESH_BOUNDARY" if recommended else "KEEP_WR8125_PARENT_AND_TEST_NEXT_STRUCTURAL_ENTRY_AXIS",
        **AUTH,
    })


def self_test() -> int:
    source = {
        "schema_version": "zel.a1.trend_rider.wr8125.frozen24_source.v1",
        "state": "IMMUTABLE_FROZEN24_SOURCE_RECOVERED",
        "source_receipt_sha256": EXPECTED_SOURCE_RECEIPT,
        "historical_union_allowed": False,
        "wr8125_discovery_child": {"trades": 16, "wins": 13, "win_rate": 0.8125, "net_pnl_bps": EXPECTED_BASE_NET_BPS},
        "us_trade_attribution": [{"net_bps": 1}] * 2 + [{"net_bps": -1}] * 7,
        "identity_authority": {"reintroduced_us_trade": {"symbol": "ETH-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "intent_sha": "x"}},
    }
    exact = {
        "state": "EXACT_HISTORICAL_PARENT_FROZEN",
        "metrics": {"completed_trades": 16, "wins": 13, "win_rate": 0.8125, "net_pnl_bps": EXPECTED_BASE_NET_BPS},
        "membership_authority": {"immutable_identity_authority": {"reintroduced_us_trade": {"symbol": "ETH-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "intent_sha": "x"}}},
    }
    ok, defects = _authority(source, exact)
    assert ok, defects
    c = _candidate_stats({"trades": 16, "wins": 13, "net_pnl_bps": 100.0}, [{"net_bps": 20.0}])
    assert c["trades"] == 17 and c["wins"] == 14 and c["net_pnl_bps"] == 120.0
    bars = []
    for i in range(240):
        px = 100.0 + 0.2 * i
        bars.append({"ts_ms": i * 3600000, "open": px - 0.05, "high": px + 0.2, "low": px - 0.2, "close": px, "volume": 1000.0 + i})
    state = legacy._structure_states(bars, 230, "long")
    assert state and state["dynamic_htf_combo"] == "ALIGNED"
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_WR8125_DYNAMIC_TRENDLINE_HTF_ATTRIBUTION_V2")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr8125_dynamic_trendline_htf_v2_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "authority_match": result.get("authority_match"),
        "strict_candidate_count": result.get("strict_candidate_count"),
        "recommended": result.get("recommended_discovery_child"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
