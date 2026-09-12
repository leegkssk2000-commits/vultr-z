#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, trade_key

SCHEMA = "zel.trendrider.true_component_synthesis.v1"
SCOPE = "TRENDRIDER_TRUE_COMPONENT_SYNTHESIS_AFTER_PR1285_V1"
PRIMARY_EXPECTED = {
    "trades": 16,
    "wins": 13,
    "win_rate": 0.8125,
    "net_pnl_bps": 23297.769437281215,
    "net_expectancy_bps": 1456.110589830076,
    "profit_factor": 64.50116053521394,
    "payoff": 14.884883200433986,
    "drawdown_bps": 219.06777382538348,
}
BROAD_EXPECTED = {
    "trades": 30,
    "wins": 21,
    "win_rate": 0.70,
    "net_pnl_bps": 34960.57723836853,
    "net_expectancy_bps": 1165.3525746122843,
    "profit_factor": 60.814848013018874,
    "payoff": 26.063506291293802,
    "drawdown_bps": 413.7929696059291,
}
WR80_EXPECTED = {
    "selected_T": 25,
    "win_rate": 0.80,
    "net_pnl_bps": 32984.20768445511,
    "net_expectancy_bps": 1319.3683073782045,
    "profit_factor": 90.0146879104085,
    "payoff": 22.503671977602124,
    "drawdown_bps": 310.0387511193403,
}
EPS = 1e-8


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def assert_close(name: str, actual: float | None, expected: float, tol: float = 0.11) -> None:
    if actual is None or abs(float(actual) - expected) > tol:
        raise RuntimeError(f"{name}_MISMATCH:{actual}:{expected}")


def enrich_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    m = metrics(rows)
    vals = [float(x["net_bps"]) for x in rows]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    streak = cur = 0
    for v in vals:
        if v < 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    positives = sorted(wins, reverse=True)
    top1 = positives[0] / sum(positives) if positives and sum(positives) > 0 else None
    loss_tail_n = max(1, math.ceil(len(losses) * 0.10)) if losses else 0
    loss_tail = sum(sorted(losses)[:loss_tail_n]) / loss_tail_n if loss_tail_n else None
    return {
        **m,
        "wins": len(wins),
        "losses": len(losses),
        "payoff": payoff(rows),
        "max_loss_streak": streak,
        "loss_tail_10pct_mean_bps": loss_tail,
        "top1_positive_contribution_fraction": top1,
    }


def verify_primary(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    if doc.get("state") != "FROZEN_EXACT_16T_8125_TRADE_RECEIPT":
        raise RuntimeError("PRIMARY_EXACT16_STATE")
    rows = [dict(x) for x in doc.get("trades") or []]
    m = enrich_stats(rows)
    if len(rows) != 16 or m["wins"] != 13:
        raise RuntimeError("PRIMARY_EXACT16_MEMBERSHIP")
    for key in ("win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        assert_close("PRIMARY_" + key, m[key], PRIMARY_EXPECTED[key])
    assert_close("PRIMARY_payoff", m["payoff"], PRIMARY_EXPECTED["payoff"])
    return rows


def verify_broad(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in doc.get("trades") or []]
    m = enrich_stats(rows)
    if len(rows) != 30 or m["wins"] != 21:
        raise RuntimeError("BROAD_EXACT30_MEMBERSHIP")
    for key in ("win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        assert_close("BROAD_" + key, m[key], BROAD_EXPECTED[key])
    assert_close("BROAD_payoff", m["payoff"], BROAD_EXPECTED["payoff"])
    return rows


def verify_wr80(doc: Mapping[str, Any], broad: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profile = dict(doc.get("historical_profile") or {})
    selected_compact = [dict(x) for x in profile.get("rows") or []]
    if len(selected_compact) != WR80_EXPECTED["selected_T"]:
        raise RuntimeError("WR80_SELECTED_T")
    bmap = {trade_key(x): dict(x) for x in broad}
    selected = []
    for compact in selected_compact:
        key = trade_key(compact)
        if key not in bmap:
            raise RuntimeError(f"WR80_ROW_NOT_BROAD:{key}")
        row = dict(bmap[key])
        for field in ("session", "prior_chase_atr", "chase_atr", "chase_state", "wr80_state_allowed"):
            row[field] = compact.get(field)
        if row.get("wr80_state_allowed") is not True:
            raise RuntimeError("WR80_SELECTED_ROW_NOT_ALLOWED")
        selected.append(row)
    m = enrich_stats(selected)
    for key in ("win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        assert_close("WR80_" + key, m[key], WR80_EXPECTED[key])
    assert_close("WR80_payoff", m["payoff"], WR80_EXPECTED["payoff"])
    return selected, m


def historical_synthesis(primary: list[dict[str, Any]], broad: list[dict[str, Any]],
                         wr80: list[dict[str, Any]]) -> dict[str, Any]:
    pkeys = {trade_key(x) for x in primary}
    bkeys = {trade_key(x) for x in broad}
    wkeys = {trade_key(x) for x in wr80}
    overlap = pkeys & bkeys
    broad_only = bkeys - pkeys
    wr80_broad_only = wkeys & broad_only
    added = [dict(x) for x in broad if trade_key(x) in wr80_broad_only]
    union = [dict(x) for x in primary] + added
    union.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")))
    um = enrich_stats(union)
    am = enrich_stats(added)
    pmap = {trade_key(x): x for x in primary}
    union_map = {trade_key(x): x for x in union}
    retained = all(k in union_map and union_map[k] == pmap[k] for k in pkeys)
    gates = {
        "primary_core_retention_100pct": retained and len(pkeys & set(union_map)) == 16,
        "added_broad_only_at_least_1": len(added) >= 1,
        "WR_ge_primary_8125": float(um["win_rate"] or 0) + EPS >= PRIMARY_EXPECTED["win_rate"],
        "net_gt_primary": float(um["net_pnl_bps"]) > PRIMARY_EXPECTED["net_pnl_bps"] + EPS,
        "expectancy_ge_primary": float(um["net_expectancy_bps"] or 0) + EPS >= PRIMARY_EXPECTED["net_expectancy_bps"],
        "PF_ge_primary": bool(um.get("profit_factor_unbounded")) or (um.get("profit_factor") is not None and float(um["profit_factor"]) + EPS >= PRIMARY_EXPECTED["profit_factor"]),
        "payoff_ge_primary": um["payoff"] is not None and float(um["payoff"]) + EPS >= PRIMARY_EXPECTED["payoff"],
        "DD_le_broad": float(um["drawdown_bps"] or 0) <= BROAD_EXPECTED["drawdown_bps"] + EPS,
        "identity_integrity": len(union_map) == len(union) and not (set(trade_key(x) for x in added) & pkeys),
    }
    return {
        "architecture": "PRIMARY_EXACT16_CORE OR (BROAD_ONLY AND EXACT_BROAD_WR80_STATE)",
        "primary_T": len(primary),
        "broad_T": len(broad),
        "primary_broad_overlap_T": len(overlap),
        "primary_only_T": len(pkeys - bkeys),
        "broad_only_T": len(broad_only),
        "wr80_selected_T": len(wr80),
        "wr80_broad_only_added_T": len(added),
        "added_metrics": am,
        "union_metrics": um,
        "gates": gates,
        "historical_gate_pass": all(gates.values()),
        "primary_core_retention_fraction": len(pkeys & set(union_map)) / len(pkeys),
        "added_rows": [{k: x.get(k) for k in ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "net_bps", "reason") } for x in added],
        "union_keys_sha256": digest(sorted([list(trade_key(x)) for x in union])),
        "primary_keys_sha256": digest(sorted([list(k) for k in pkeys])),
        "broad_keys_sha256": digest(sorted([list(k) for k in bkeys])),
        "wr80_keys_sha256": digest(sorted([list(k) for k in wkeys])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", type=Path, required=True)
    ap.add_argument("--broad", type=Path, required=True)
    ap.add_argument("--wr80", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    args = ap.parse_args()
    primary_doc, broad_doc, wr80_doc = read(args.primary), read(args.broad), read(args.wr80)
    primary = verify_primary(primary_doc)
    broad = verify_broad(broad_doc)
    wr80, wr80_metrics = verify_wr80(wr80_doc, broad)

    ledger = {
        "schema": "trendrider.true_component_ledger.v1",
        "scope_key": SCOPE,
        "proxy_common_replay_role": "FAILED_METHOD_COMPARATOR_ONLY_NOT_PARENT_OR_COMPONENT",
        "parents": {
            "PRIMARY_CORE_WR8125": {"classification": "IMMUTABLE_PARENT_CORE", "receipt_sha256": sha(args.primary), "metrics": enrich_stats(primary)},
            "BROAD_PARENT_WR7000": {"classification": "IMMUTABLE_PARENT_REFERENCE", "receipt_sha256": sha(args.broad), "metrics": enrich_stats(broad)},
        },
        "components": {
            "BROAD_WR80_STATE": {
                "classification": "GOOD_QUALITY_COMPONENT",
                "receipt_sha256": sha(args.wr80),
                "rule": "session!=US OR current_chase_atr<=prior_closed_bar_chase_atr",
                "metrics": wr80_metrics,
                "strengths": ["WR", "expectancy", "PF", "DD"],
                "weaknesses": ["payoff_vs_Broad"],
                "result_driven_threshold": False,
            },
            "PRIMARY_HIGHAMP_PERSISTENCE": {
                "classification": "UNAVAILABLE",
                "reason": "ORIGINAL_PR1044_TERMINAL_HOLD_FROZEN_PRIMARY_TRADE_PAYLOAD_UNAVAILABLE; no proxy substitution authorized",
            },
            "BROAD_HTF_UP": {"classification": "NEGATIVE_REFERENCE", "reason": "WR/PF/DD deteriorated vs Broad30"},
            "BROAD_TRANSITION_ADDONLY": {"classification": "NEGATIVE_REFERENCE", "reason": "profitable but dilutive/incomplete source"},
            "PRIMARY_DONOR_STATE_GATES": {"classification": "NEGATIVE_REFERENCE", "reason": "strict preservation failed"},
            "PRIMARY_FRESH2_POSITIVE2": {"classification": "NEGATIVE_REFERENCE", "reason": "entry amplitude / expectancy / payoff ceiling"},
        },
        "allowed_candidate_ids": ["U1"],
        "U1_definition": "PRIMARY_EXACT16_CORE OR (BROAD_ONLY AND EXACT_BROAD_WR80_STATE)",
        "proxy_substitution_allowed": False,
        "numeric_sweep_allowed": False,
        "formal_credit": 0,
    }
    synth = historical_synthesis(primary, broad, wr80)
    final_state = "HISTORICAL_TRUE_COMPONENT_PASS_PENDING_ROBUSTNESS" if synth["historical_gate_pass"] else "TRUE_COMPONENT_SYNTHESIS_NOT_EARNED"
    final = {
        "schema": SCHEMA,
        "scope_key": SCOPE,
        "strategy_name": "TrendRider Unified v1" if synth["historical_gate_pass"] else None,
        "candidate": "U1",
        "state": final_state,
        "historical_synthesis": synth,
        "robustness_required": bool(synth["historical_gate_pass"]),
        "robustness_state": "NOT_RUN_HISTORICAL_GATE_FAILED" if not synth["historical_gate_pass"] else "PENDING_EXACT_SEMANTICS_REPLAY",
        "prospective_G5A_handoff": False,
        "formal_credit": 0,
        "live_order_deploy": 0,
    }
    final["receipt_sha256"] = digest(final)
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "TRUE_COMPONENT_LEDGER.json").write_bytes(canonical(ledger))
    (args.out_root / "HISTORICAL_SYNTHESIS_RESULT.json").write_bytes(canonical(synth))
    (args.out_root / "FINAL_STATUS.json").write_bytes(canonical(final))
    print(json.dumps({"state": final_state, "historical_gate_pass": synth["historical_gate_pass"],
                      "union_metrics": synth["union_metrics"], "added_T": synth["wr80_broad_only_added_T"],
                      "gates": synth["gates"]}, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
