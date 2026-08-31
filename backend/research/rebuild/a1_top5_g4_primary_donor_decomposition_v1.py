#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as transplant
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as market

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_primary_donor_decomposition_v1.json"
PARENT = ROOT / "backend/research/rebuild/a1_top5_g4_primary_month_sharded_fasttrack_v2_latest.json"
FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_g4_primary_donor_decomposition_v1_latest.json"
SCHEMA = "zel.a1.top5.g4.primary_donor_decomposition.receipt.v1"
INTERVAL_MS = 14_400_000

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in rows]
    gp = sum(x for x in vals if x > 0)
    gl = -sum(x for x in vals if x < 0)
    eq = peak = dd = 0.0
    for x in vals:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    wins = sum(1 for x in vals if x > 0)
    losses = sum(1 for x in vals if x < 0)
    return {
        "closed_T": len(vals),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "profit_factor_unbounded": bool(gp > 0 and gl == 0),
        "drawdown_bps": dd,
    }


def pf_ge(m: Mapping[str, Any], threshold: float) -> bool:
    if bool(m.get("profit_factor_unbounded")):
        return True
    value = m.get("profit_factor")
    return value is not None and math.isfinite(float(value)) and float(value) >= threshold


def recent(rows: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    return [x for x in rows if start_ms <= int(x["signal_ts"]) < end_ms]


def recent_loss_reduction(parent: Mapping[str, Any], child: Mapping[str, Any]) -> float:
    p = float(parent.get("net_pnl_bps") or 0.0)
    c = float(child.get("net_pnl_bps") or 0.0)
    if p >= 0:
        return 0.0
    return (c - p) / abs(p) * 100.0


def gate_cell(
    mode: str,
    child6: Mapping[str, Any],
    child3: Mapping[str, Any],
    parent6: Mapping[str, Any],
    parent3: Mapping[str, Any],
    retention_pct: float,
    gate: Mapping[str, Any],
) -> tuple[bool, dict[str, bool], float | None]:
    checks = {
        "T6_min": int(child6.get("closed_T") or 0) >= int(gate["minimum_full6m_closed_T"]),
        "T3_min": int(child3.get("closed_T") or 0) >= int(gate["minimum_recent3m_closed_T"]),
        "net6_pos": float(child6.get("net_pnl_bps") or 0.0) > 0.0,
        "net3_pos": float(child3.get("net_pnl_bps") or 0.0) > 0.0,
        "pf6_min": pf_ge(child6, float(gate["full6m_profit_factor_minimum"])),
        "pf3_min": pf_ge(child3, float(gate["recent3m_profit_factor_minimum"])),
        "exp6_up": child6.get("net_expectancy_bps") is not None
        and parent6.get("net_expectancy_bps") is not None
        and float(child6["net_expectancy_bps"]) > float(parent6["net_expectancy_bps"]),
        "dd6_up": float(child6.get("drawdown_bps") or 0.0) < float(parent6.get("drawdown_bps") or 0.0),
    }
    loss_red = None
    if mode == "INCLUSION":
        checks["retention_min"] = retention_pct >= float(gate["inclusion_minimum_retention_pct"])
    elif mode == "NEGATIVE_VETO":
        checks["retention_min"] = retention_pct >= float(gate["veto_minimum_retention_pct"])
        loss_red = recent_loss_reduction(parent3, child3)
        checks["recent3_loss_reduction_min"] = loss_red >= float(gate["veto_recent3m_loss_reduction_minimum_pct"])
    else:
        raise RuntimeError(f"UNKNOWN_MODE:{mode}")
    return all(checks.values()), checks, loss_red


def run(out: Path) -> dict[str, Any]:
    c = read(CONTRACT)
    p = read(PARENT)
    freeze = read(FREEZE)
    if c.get("state") != "PREREGISTERED_PRIMARY_DONOR_DECOMPOSITION_NO_RETUNE":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    if p.get("state") != "HIST_3M_6M_ECONOMIC_FAIL_ARCHITECTURE_REPLACEMENT_PRIORITY":
        raise RuntimeError(f"PARENT_STATE_DRIFT:{p.get('state')}")
    if int(p.get("trade_count") or 0) != len(p.get("trades") or []):
        raise RuntimeError("PARENT_T_MISMATCH")
    if p.get("formal_credit") != {"fresh_g4_T": 0, "g5_T": 0}:
        raise RuntimeError("PARENT_FORMAL_CREDIT_DRIFT")

    rows = [dict(x) for x in p.get("trades") or []]
    ids = [str(x.get("trade_id") or "") for x in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("PARENT_TRADE_ID_INTEGRITY")
    if set(str(x.get("symbol")) for x in rows) - {"BTC-USDT", "ETH-USDT"}:
        raise RuntimeError("PARENT_SYMBOL_DRIFT")

    full_start = utc_ms(str(p["recent_6m"]["start_utc"]))
    full_end = utc_ms(str(p["recent_6m"]["end_utc"]))
    recent_start = utc_ms(str(p["recent_3m"]["start_utc"]))
    recent_end = utc_ms(str(p["recent_3m"]["end_utc"]))
    if full_start >= recent_start or recent_end != full_end:
        raise RuntimeError("PARENT_WINDOW_DRIFT")
    if any(not (full_start <= int(x["signal_ts"]) < full_end) for x in rows):
        raise RuntimeError("PARENT_WINDOW_LEAKAGE")

    parent6 = metrics(rows)
    parent3_rows = recent(rows, recent_start, recent_end)
    parent3 = metrics(parent3_rows)

    specs = {
        str(x["child_id"]): dict(x["executable_spec"])
        for x in freeze.get("children") or []
        if isinstance(x, Mapping) and isinstance(x.get("executable_spec"), Mapping)
    }
    donor_cfg = c["fixed_donors"]
    for donor_id in donor_cfg:
        if donor_id not in specs:
            raise RuntimeError(f"DONOR_SPEC_MISSING:{donor_id}")

    symbols = sorted({str(x["symbol"]) for x in rows})
    bars: dict[str, list[dict[str, float]]] = {}
    engines: dict[tuple[str, str], Any] = {}
    for symbol in symbols:
        b = market._bars(symbol, "4h", full_start, full_end + INTERVAL_MS)
        if not b:
            raise RuntimeError(f"NO_DONOR_BARS:{symbol}")
        bars[symbol] = b
        for donor_id in donor_cfg:
            _, engine = market._features(b, specs[donor_id])
            engine.validate(str(specs[donor_id]["entry_rule"]))
            engines[(donor_id, symbol)] = engine

    cells: list[dict[str, Any]] = []
    for cell in c["cells"]:
        cid = str(cell["id"])
        donor_id = str(cell["donor_id"])
        mode = str(cell["mode"])
        allow = set(str(x) for x in donor_cfg[donor_id].get("symbol_allow") or [])
        kept: list[dict[str, Any]] = []
        filtered: list[dict[str, Any]] = []
        hit_ids: list[str] = []
        for row in rows:
            symbol = str(row["symbol"])
            eligible_symbol = not allow or symbol in allow
            hit = False
            if eligible_symbol:
                hit, _ = transplant.architecture_accepts(row, bars[symbol], engines[(donor_id, symbol)], specs[donor_id])
            if hit:
                hit_ids.append(str(row["trade_id"]))
            if mode == "INCLUSION":
                (kept if hit else filtered).append(row)
            elif mode == "NEGATIVE_VETO":
                (filtered if hit else kept).append(row)
            else:
                raise RuntimeError(f"UNKNOWN_MODE:{mode}")

        m6 = metrics(kept)
        kept3 = recent(kept, recent_start, recent_end)
        m3 = metrics(kept3)
        retention = len(kept) / len(rows) * 100.0 if rows else 0.0
        passed, checks, loss_red = gate_cell(mode, m6, m3, parent6, parent3, retention, c["gate"])
        cells.append({
            "cell_id": cid,
            "donor_id": donor_id,
            "donor_source_lane": donor_cfg[donor_id]["source_lane"],
            "symbol_allow": sorted(allow),
            "mode": mode,
            "parent_T": len(rows),
            "kept_T": len(kept),
            "filtered_T": len(filtered),
            "retention_pct": retention,
            "donor_hit_T": len(hit_ids),
            "donor_hit_trade_ids": sorted(hit_ids),
            "metrics_6m": m6,
            "metrics_recent3m": m3,
            "recent3m_loss_reduction_pct": loss_red,
            "checks": checks,
            "pass": passed,
            "decision": "HISTORICAL_SALVAGE_CANDIDATE_FRESH_6T_REQUIRED_NOT_G4_PASS" if passed else "DROP_CELL_KEEP_PARENT_FALSIFIED",
        })

    winners = [x for x in cells if x["pass"]]
    winners.sort(
        key=lambda x: (
            float(x["metrics_recent3m"].get("net_pnl_bps") or -1e30),
            float(x["metrics_recent3m"].get("profit_factor") or -1e30),
            float(x["metrics_6m"].get("net_pnl_bps") or -1e30),
            -float(x["metrics_6m"].get("drawdown_bps") or 1e30),
        ),
        reverse=True,
    )
    selected = winners[0]["cell_id"] if winners else None
    state = "HISTORICAL_PRIMARY_SALVAGE_CANDIDATE_FRESH_REQUIRED" if winners else "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"
    next_action = "FREEZE_SELECTED_CELL_AND_COLLECT_GENUINE_FRESH_6T" if winners else "REPLACE_PRIMARY_ARCHITECTURE_DO_NOT_WAIT_FOR_MORE_PARENT_T"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "parent_receipt": str(PARENT.relative_to(ROOT)),
        "parent_receipt_sha256": sha(p),
        "parent_lane_id": c["parent_lane_id"],
        "parent_metrics_6m": parent6,
        "parent_metrics_recent3m": parent3,
        "cell_count": len(cells),
        "winner_count": len(winners),
        "selected_cell_id": selected,
        "winners": winners,
        "cells": cells,
        "integrity": {
            "parent_trade_count": len(rows),
            "unique_parent_trade_ids": len(ids) == len(set(ids)),
            "fixed_cell_count": len(cells) == 4,
            "threshold_sweep": False,
            "symbol_sweep": False,
            "post_result_retune": False,
            "parent_mutation": False,
            "exit_mutation": False,
            "cost_rededuction": False,
            "historical_credit_to_fresh_g4_T": 0,
            "historical_credit_to_g5_T": 0,
        },
        "formal_credit": {"fresh_g4_T": 0, "g5_T": 0},
        "minimum_fresh_T_if_selected": int(c["interpretation"]["minimum_fresh_T_before_formal_gate"]),
        "fresh_6T_is_not_automatic_pass": True,
        "next": next_action,
        **AUTH,
    }
    result["receipt_sha256"] = sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "winner_count": len(winners),
        "selected_cell_id": selected,
        "parent6": parent6,
        "parent3": parent3,
        "cells": [{
            "id": x["cell_id"],
            "mode": x["mode"],
            "T6": x["metrics_6m"]["closed_T"],
            "net6": x["metrics_6m"]["net_pnl_bps"],
            "pf6": x["metrics_6m"]["profit_factor"],
            "T3": x["metrics_recent3m"]["closed_T"],
            "net3": x["metrics_recent3m"]["net_pnl_bps"],
            "pf3": x["metrics_recent3m"]["profit_factor"],
            "pass": x["pass"],
        } for x in cells],
        "out": str(out),
    }, sort_keys=True))
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["state"] == "PREREGISTERED_PRIMARY_DONOR_DECOMPOSITION_NO_RETUNE"
    assert len(c["cells"]) == 4
    assert set(x["mode"] for x in c["cells"]) == {"INCLUSION", "NEGATIVE_VETO"}
    assert c["interpretation"]["minimum_fresh_T_before_formal_gate"] == 6
    assert c["interpretation"]["fresh_6T_is_not_automatic_pass"] is True
    assert c["formal_credit"] == {"fresh_g4_T": 0, "g5_T": 0}
    print("PASS_PRIMARY_DONOR_DECOMPOSITION_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=LATEST)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
