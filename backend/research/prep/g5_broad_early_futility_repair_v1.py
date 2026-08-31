#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as broad
from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as transplant
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as market

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/g5_broad_early_futility_repair_v1.json"
SEAL = ROOT / "backend/research/rebuild/a1_g4_trendrider_broad30_economic_survivor_v1.json"
PRODUCT = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
FORENSIC = ROOT / "backend/research/prep/g5_trendrider_w2_forensic_latest.json"
FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
PRELIM = ROOT / "backend/research/rebuild/a1_g4_top5_preliminary_survivor_g5_v1_latest.json"
LATEST = ROOT / "backend/research/prep/g5_broad_early_futility_repair_latest.json"
SCHEMA = "zel.g5.trendrider_broad.early_futility_repair.receipt.v1"
INTERVAL_MS = 14_400_000

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "PAPER_SIM_ONLY",
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


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x.get("net_bps") or 0.0) for x in rows]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = dd = 0.0
    for x in vals:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    pf = gp / gl if gl > 0 else (None if gp <= 0 else "INF")
    return {
        "trades": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": pf,
        "drawdown_bps": dd,
    }


def pf_gt_one(value: Any) -> bool:
    if value == "INF":
        return True
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 1.0


def pf_lte_one(value: Any) -> bool:
    if value is None:
        return True
    if value == "INF":
        return False
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) <= 1.0


def loss_reduction_pct(parent_net: float, child_net: float) -> float:
    if parent_net >= 0:
        return 0.0
    return (child_net - parent_net) / abs(parent_net) * 100.0


def early_futility(product: Mapping[str, Any], first6: list[Mapping[str, Any]], c: Mapping[str, Any]) -> dict[str, Any]:
    gate = c["early_futility_gate"]
    m = metrics(first6)
    stress = product.get("stress") or {}
    cost2 = stress.get("COST_2X") or {}
    fund = stress.get("P95_FUNDING") or {}
    plus = stress.get("PLUS_ONE_BAR") or {}
    checks = {
        "minimum_T": int(m["trades"]) >= int(gate["minimum_T"]),
        "wins_equal_zero": int(m["wins"]) == 0,
        "net_pnl_nonpositive": float(m["net_pnl_bps"] or 0.0) <= 0.0,
        "expectancy_nonpositive": m["net_expectancy_bps"] is None or float(m["net_expectancy_bps"]) <= 0.0,
        "profit_factor_lte_one": pf_lte_one(m["profit_factor"]),
        "cost_2x_net_nonpositive": float(cost2.get("net_pnl_bps") or 0.0) <= 0.0,
        "p95_funding_net_nonpositive": float(fund.get("net_pnl_bps") or 0.0) <= 0.0,
        "plus_one_bar_net_nonpositive": float(plus.get("net_pnl_bps") or 0.0) <= 0.0,
    }
    triggered = all(checks.values())
    return {
        "triggered": triggered,
        "checks": checks,
        "first6_metrics": m,
        "effect": gate["effect"] if triggered else "NO_EARLY_FUTILITY_TRIGGER",
        "formal_W2_control_continues": True,
        "formal_W2_target_T": 12,
        "development_priority": "CONTROL_ONLY_LOW" if triggered else "NORMAL",
    }


def frozen_architectures(freeze: Mapping[str, Any]) -> list[dict[str, Any]]:
    if freeze.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v2":
        raise RuntimeError("V2_FREEZE_REQUIRED")
    rows = []
    for child in freeze.get("children") or []:
        if not isinstance(child, Mapping) or not isinstance(child.get("executable_spec"), Mapping):
            continue
        spec = dict(child["executable_spec"])
        if str(spec.get("bar_interval")) != "4h":
            raise RuntimeError("DONOR_4H_SPEC_REQUIRED")
        rows.append({
            "architecture_id": str(child.get("child_id") or ""),
            "source_lane": str(child.get("lane_id") or ""),
            "family": str(child.get("architecture_family") or ""),
            "spec": spec,
        })
    if len(rows) != 3:
        raise RuntimeError(f"EXACT_THREE_FROZEN_DONORS_REQUIRED:{len(rows)}")
    return rows


def donor_screen(
    ref30: list[dict[str, Any]],
    w2rows: list[dict[str, Any]],
    donors: list[dict[str, Any]],
    c: Mapping[str, Any],
) -> dict[str, Any]:
    cfg = c["repair_screen"]
    all_rows = ref30 + w2rows
    symbols = sorted({str(x["symbol"]) for x in all_rows})
    if not symbols:
        raise RuntimeError("NO_ROWS_FOR_DONOR_SCREEN")
    start_ms = min(int(x["signal_ts"]) for x in all_rows) - 60 * INTERVAL_MS
    end_ms = max(int(x["exit_ts"]) for x in all_rows) + 2 * INTERVAL_MS

    bars: dict[str, list[dict[str, float]]] = {}
    engines: dict[tuple[str, str], Any] = {}
    for symbol in symbols:
        b = market._bars(symbol, "4h", start_ms, end_ms)
        if not b:
            raise RuntimeError(f"NO_4H_BARS:{symbol}")
        bars[symbol] = b
        for donor in donors:
            _, engine = market._features(b, donor["spec"])
            engine.validate(str(donor["spec"]["entry_rule"]))
            engines[(donor["architecture_id"], symbol)] = engine

    parent_w2 = metrics(w2rows)
    cells: list[dict[str, Any]] = []
    for donor in donors:
        did = donor["architecture_id"]
        hits_ref: dict[int, bool] = {}
        hits_w2: dict[int, bool] = {}
        for row in ref30:
            symbol = str(row["symbol"])
            hit, _ = transplant.architecture_accepts(row, bars[symbol], engines[(did, symbol)], donor["spec"])
            hits_ref[id(row)] = bool(hit)
        for row in w2rows:
            symbol = str(row["symbol"])
            hit, _ = transplant.architecture_accepts(row, bars[symbol], engines[(did, symbol)], donor["spec"])
            hits_w2[id(row)] = bool(hit)

        for mode in cfg["modes"]:
            if mode == "INCLUSION":
                kept_ref = [x for x in ref30 if hits_ref[id(x)]]
                kept_w2 = [x for x in w2rows if hits_w2[id(x)]]
            elif mode == "NEGATIVE_VETO":
                kept_ref = [x for x in ref30 if not hits_ref[id(x)]]
                kept_w2 = [x for x in w2rows if not hits_w2[id(x)]]
            else:
                raise RuntimeError(f"UNKNOWN_MODE:{mode}")
            mr = metrics(kept_ref)
            mw = metrics(kept_w2)
            retention = len(kept_ref) / len(ref30) * 100.0 if ref30 else 0.0
            reduction = loss_reduction_pct(float(parent_w2["net_pnl_bps"] or 0.0), float(mw["net_pnl_bps"] or 0.0))
            checks = {
                "reference_T": int(mr["trades"]) >= int(cfg["minimum_reference_T"]),
                "reference_retention": retention >= float(cfg["minimum_reference_retention_pct"]),
                "reference_net_positive": float(mr["net_pnl_bps"] or 0.0) > 0.0,
                "reference_expectancy_positive": mr["net_expectancy_bps"] is not None and float(mr["net_expectancy_bps"]) > 0.0,
                "reference_pf_gt_one": pf_gt_one(mr["profit_factor"]),
                "w2_loss_reduction": reduction >= float(cfg["minimum_w2_loss_reduction_pct"]),
                "w2_min_kept_T": int(mw["trades"]) >= int(cfg["minimum_w2_kept_T"]),
                "w2_max_kept_T": int(mw["trades"]) <= int(cfg["maximum_w2_kept_T"]),
            }
            passed = all(checks.values())
            cells.append({
                "cell_id": f"{did}::{mode}",
                "architecture_id": did,
                "source_lane": donor["source_lane"],
                "family": donor["family"],
                "mode": mode,
                "reference_metrics": mr,
                "reference_retention_pct": retention,
                "w2_metrics": mw,
                "w2_loss_reduction_pct": reduction,
                "checks": checks,
                "pass": passed,
            })

    if len(cells) != int(cfg["expected_cells"]):
        raise RuntimeError(f"CELL_COUNT_DRIFT:{len(cells)}")
    winners = [x for x in cells if x["pass"]]
    winners.sort(
        key=lambda x: (
            float(x["w2_loss_reduction_pct"]),
            float(x["reference_metrics"].get("net_expectancy_bps") or -1e30),
            float(x["reference_retention_pct"]),
        ),
        reverse=True,
    )
    selected = winners[0] if winners else None
    return {
        "state": "REPAIR_CANDIDATE_FOUND_FRESH_PROSPECTIVE_REQUIRED" if selected else "NO_FIXED_DONOR_REPAIR_WINNER",
        "parent_w2_metrics": parent_w2,
        "cell_count": len(cells),
        "winner_count": len(winners),
        "selected_cell_id": selected["cell_id"] if selected else None,
        "selected": selected,
        "cells": cells,
        "formal_g4_credit": 0,
        "formal_g5_credit": 0,
        "fresh_prospective_required": True,
        "next": "FREEZE_SELECTED_REPAIR_CHILD_AT_NEW_BOUNDARY" if selected else "KEEP_BROAD_CONTROL_ONLY_AND_PRIORITIZE_OTHER_G5_LANES",
    }


def acquisition_telemetry(prelim: Mapping[str, Any]) -> dict[str, Any]:
    lanes = prelim.get("lanes") or {}
    out: dict[str, Any] = {}
    for lane_id, lane in lanes.items():
        if not isinstance(lane, Mapping):
            continue
        out[str(lane_id)] = {
            "g4_fresh_closed_T": int(lane.get("g4_fresh_closed_T") or 0),
            "formal_g5_T": int(lane.get("formal_g5_T") or 0),
            "pre_g5_shadow_T": int(lane.get("pre_g5_shadow_T") or 0),
            "pre_g5_paper_T": int(lane.get("pre_g5_paper_T") or 0),
            "g5_state": lane.get("g5_state"),
            "next": lane.get("next"),
        }
    return {
        "lane_count": len(out),
        "lanes": out,
        "fanout_policy": read(CONTRACT)["telemetry"],
    }


def run(out: Path) -> dict[str, Any]:
    c = read(CONTRACT)
    seal = read(SEAL)
    product = read(PRODUCT)
    manifest = read(MANIFEST)
    forensic = read(FORENSIC)
    freeze = read(FREEZE)
    prelim = read(PRELIM)

    if c.get("state") != "PREREGISTERED_EARLY_FUTILITY_AND_FIXED_DONOR_REPAIR_SCREEN":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    if product.get("lane_id") != c["lane_id"] or product.get("stage") != "G5":
        raise RuntimeError("BROAD_PRODUCT_DRIFT")
    if int(product.get("postlock_closed_T") or 0) < int(c["early_futility_gate"]["minimum_T"]):
        raise RuntimeError("EARLY_FUTILITY_MIN_T_NOT_REACHED")
    if seal.get("state") != "PASS_G4_ECONOMIC_SURVIVOR":
        raise RuntimeError("G4_SEAL_REQUIRED")

    with tempfile.TemporaryDirectory(prefix="g5-broad-futility-") as td:
        receipt = broad.current_policy_replay(
            out_path=Path(td) / "broad_replay.json",
            boundary_utc=str(c["sources"]["g4_reference_replay_boundary_utc"]),
        )
    rows = sorted(
        [dict(x) for x in receipt.get("trades") or [] if isinstance(x, Mapping)],
        key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )
    boundary_ms = int(manifest["prospective_boundary_ms"])
    ref_candidates = [x for x in rows if int(x["signal_ts"]) <= boundary_ms]
    w2_all = [x for x in rows if int(x["signal_ts"]) > boundary_ms and int(x["exit_ts"]) > boundary_ms]
    if len(ref_candidates) < 30:
        raise RuntimeError(f"G4_REFERENCE_30_NOT_REPRODUCED:{len(ref_candidates)}")
    ref30 = ref_candidates[:30]
    if len(w2_all) < 6:
        raise RuntimeError(f"W2_FIRST6_NOT_REPRODUCED:{len(w2_all)}")
    first6 = w2_all[:6]

    refm = metrics(ref30)
    sealed = seal["sealed_metrics"]
    if abs(float(refm["net_pnl_bps"]) - float(sealed["net_pnl_bps"])) > 1e-6:
        raise RuntimeError(f"G4_REFERENCE_NET_DRIFT:{refm['net_pnl_bps']}:{sealed['net_pnl_bps']}")

    futility = early_futility(product, first6, c)
    if not futility["triggered"]:
        raise RuntimeError(f"EXPECTED_6T_FUTILITY_NOT_TRIGGERED:{futility['checks']}")

    screen = donor_screen(ref30, first6, frozen_architectures(freeze), c)
    atr_probe = {
        "source_forensic_state": forensic.get("state"),
        "selected_causal_axis": forensic.get("selected_causal_axis"),
        "first4_all_atr_cool": bool(
            len((forensic.get("w2") or {}).get("rows") or []) >= 4
            and all(bool(x.get("atr_pct_self_normalized_cool")) for x in (forensic.get("w2") or {}).get("rows")[:4])
        ),
        "interpretation": "RETIRE_ATR_COOL_AS_SOLE_REPAIR_AXIS_IF_IT_ACCEPTED_ALL_OBSERVED_LOSSES",
    }

    result = {
        "schema_version": SCHEMA,
        "state": "G5_BROAD_EARLY_FUTILITY_RED_REPAIR_PARALLEL_ACTIVE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lane_id": c["lane_id"],
        "formal_parent": {
            "state": product.get("state"),
            "postlock_closed_T": int(product.get("postlock_closed_T") or 0),
            "W2_target_T": int(((manifest.get("windows") or {}).get("W2") or {}).get("target_closed_trades") or 12),
            "mutated": False,
            "role": "FORMAL_CONTROL_ONLY_CONTINUE_TO_12T",
        },
        "early_futility": futility,
        "causal_axis_review": atr_probe,
        "repair_screen": screen,
        "acquisition_telemetry": acquisition_telemetry(prelim),
        "roadmap_policy": {
            "broad_parent_blocks_G5": False,
            "broad_parent_development_priority": "LOW_CONTROL_ONLY",
            "other_top5_preliminary_lanes_continue": True,
            "selected_repair_if_any_requires_new_boundary": True,
            "screen_credit_g4_T": 0,
            "screen_credit_g5_T": 0,
        },
        "integrity": {
            "g4_reference_T": len(ref30),
            "w2_first6_T": len(first6),
            "threshold_sweep": False,
            "symbol_sweep": False,
            "exit_retune": False,
            "cost_retune": False,
            "formal_parent_mutation": False,
            "formal_W2_control_stopped": False,
        },
        "next": screen["next"],
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "futility": result["early_futility"],
        "repair_state": screen["state"],
        "winner_count": screen["winner_count"],
        "selected": screen["selected_cell_id"],
        "cells": [{
            "id": x["cell_id"],
            "refT": x["reference_metrics"]["trades"],
            "refNet": x["reference_metrics"]["net_pnl_bps"],
            "w2T": x["w2_metrics"]["trades"],
            "w2Net": x["w2_metrics"]["net_pnl_bps"],
            "lossReduction": x["w2_loss_reduction_pct"],
            "pass": x["pass"],
        } for x in screen["cells"]],
        "out": str(out),
    }, sort_keys=True))
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["early_futility_gate"]["minimum_T"] == 6
    assert c["repair_screen"]["expected_cells"] == 6
    assert c["repair_screen"]["fresh_prospective_required_after_selection"] is True
    assert c["repair_screen"]["formal_g5_credit_from_screen"] == 0
    assert c["prohibitions"]["mutate_formal_broad_parent"] is True
    print("PASS_G5_BROAD_EARLY_FUTILITY_REPAIR_SELF_TEST")
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
