#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_trendrider_8125_fresh2_highamp_rescue_v1 import metrics, payoff, strict, trade_key
from backend.research.rebuild.a1_trendrider_causal_rescue_broad_hardening_v3 import broad_checks

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2 = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.3bar_persistence_causal.v4"
RULE = "PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE_TRUE"
EPS = 1e-12


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def compact(x: Mapping[str, Any]) -> dict[str, Any]:
    return {k: x.get(k) for k in (
        "symbol", "signal_ts", "entry_ts", "side", "net_bps", "reason",
        "preentry_3bar_directional_persistence", "preentry_directional_steps",
    )}


def enrich_persistence(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    symbols = sorted({str(x["symbol"]) for x in rows})
    bars_by: dict[str, list[dict[str, Any]]] = {}
    idx_by: dict[str, dict[int, int]] = {}
    for symbol in symbols:
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        bars_by[symbol] = bars
        idx_by[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        i = idx_by[symbol].get(signal_ts)
        if i is None or i < 3:
            row["persistence_missing"] = True
            continue
        bars = bars_by[symbol]
        closes = [float(bars[j]["close"]) for j in range(i - 3, i + 1)]
        steps = [closes[j] - closes[j - 1] for j in range(1, 4)]
        side = str(row["side"])
        if side == "long":
            passed = all(x > 0 for x in steps)
            signed = [1 if x > 0 else (-1 if x < 0 else 0) for x in steps]
        elif side == "short":
            passed = all(x < 0 for x in steps)
            signed = [1 if x < 0 else (-1 if x > 0 else 0) for x in steps]
        else:
            raise RuntimeError(f"SIDE_INVALID:{side}")
        row["preentry_3bar_directional_persistence"] = bool(passed)
        row["preentry_directional_steps"] = signed
        row["persistence_missing"] = False


def validate(pd: Mapping[str, Any], fd: Mapping[str, Any], bd: Mapping[str, Any]) -> None:
    if len(pd.get("trades") or []) != 16 or abs(float(pd["metrics"]["win_rate"]) - 0.8125) > EPS:
        raise RuntimeError("PRIMARY_16T_8125_AUTHORITY_MISMATCH")
    if len(fd.get("trades") or []) != 2 or any(float(x["net_bps"]) <= 0 for x in fd.get("trades") or []):
        raise RuntimeError("FRESH2_AUTHORITY_MISMATCH")
    if len(bd.get("trades") or []) != 30 or abs(float(bd["metrics"]["win_rate"]) - 0.70) > EPS:
        raise RuntimeError("BROAD30_70_AUTHORITY_MISMATCH")


def run(broad_path: Path) -> dict[str, Any]:
    pd, fd, bd = read(PARENT), read(FRESH2), read(broad_path)
    validate(pd, fd, bd)
    parent = [dict(x) for x in pd["trades"]]
    fresh2 = [dict(x) for x in fd["trades"]]
    broad = [dict(x) for x in bd["trades"]]
    current = [dict(x) for x in (rebuild_current().get("trades") or [])]
    if not current:
        raise RuntimeError("CURRENT_REBUILD_EMPTY")

    # One preregistered, threshold-free, entry-observable predicate only.
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for x in broad + current:
        by_key[trade_key(x)] = dict(x)
    enriched = list(by_key.values())
    enrich_persistence(bd, enriched)
    missing = [x for x in enriched if bool(x.get("persistence_missing"))]
    if missing:
        raise RuntimeError(f"PERSISTENCE_FEATURE_MISSING:{len(missing)}")
    emap = {trade_key(x): x for x in enriched}
    broad = [dict(emap[trade_key(x)]) for x in broad]
    current = [dict(emap[trade_key(x)]) for x in current]

    pkeys = {trade_key(x) for x in parent}
    fkeys = {trade_key(x) for x in fresh2}
    bkeys = {trade_key(x) for x in broad}
    donor = [dict(x) for x in broad if trade_key(x) not in pkeys and trade_key(x) not in fkeys]
    overlap = [x for x in broad if trade_key(x) in pkeys]
    if len(overlap) != 15 or len(donor) != 15:
        raise RuntimeError(f"BROAD_MEMBERSHIP_MISMATCH:{len(overlap)}:{len(donor)}")

    boundary_ts = max(int(x["signal_ts"]) for x in broad)
    holdout = [
        dict(x) for x in current
        if int(x["signal_ts"]) > boundary_ts and trade_key(x) not in bkeys and trade_key(x) not in fkeys
    ]

    hist_donor = [x for x in donor if bool(x["preentry_3bar_directional_persistence"])]
    holdout_selected = [x for x in holdout if bool(x["preentry_3bar_directional_persistence"])]
    broad_hist = [x for x in broad if bool(x["preentry_3bar_directional_persistence"])]

    p_hist_ok, p_hist_checks, p_hist_added, p_hist_combined, p_hist_payoff = strict(parent, fresh2 + hist_donor)
    p_full_ok, p_full_checks, p_full_added, p_full_combined, p_full_payoff = strict(
        parent, fresh2 + hist_donor + holdout_selected
    )
    p_preregisterable = bool(p_hist_ok and holdout_selected and p_full_ok)

    b_hist_checks = broad_checks(broad, broad_hist) if broad_hist else {"selected_T_at_least_min": False}
    b_hist_pass = bool(broad_hist and all(b_hist_checks.values()))
    if holdout_selected:
        b_full_ok, b_full_checks, b_full_added, b_full_combined, b_full_payoff = strict(broad, holdout_selected)
    else:
        b_full_ok = False
        b_full_checks = {"holdout_match_present": False}
        b_full_added = metrics([])
        b_full_combined = metrics(broad)
        b_full_payoff = payoff(broad)
    b_preregisterable = bool(b_hist_pass and holdout_selected and b_full_ok)

    state = (
        "PASS_3BAR_PRIMARY_AND_BROAD_PREREGISTERABLE" if p_preregisterable and b_preregisterable
        else "PASS_3BAR_PRIMARY_PREREGISTERABLE" if p_preregisterable
        else "PASS_3BAR_BROAD_PREREGISTERABLE" if b_preregisterable
        else "HOLD_3BAR_PERSISTENCE_NOT_CAUSAL_ENOUGH"
    )
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "predicate": {
            "id": RULE,
            "field": "preentry_3bar_directional_persistence",
            "op": "eq",
            "value": True,
            "definition": "last three close-to-close steps ending at signal bar are all in trade direction",
            "entry_observable": True,
            "numeric_threshold_sweep": False,
            "alternative_rule_sweep": False,
        },
        "primary": {
            "parent_T": 16,
            "parent_metrics": metrics(parent),
            "parent_payoff": payoff(parent),
            "fresh2_fixed_T": 2,
            "historical_donor_T": len(donor),
            "historical_selected_T": len(hist_donor),
            "historical_selected_rows": [compact(x) for x in hist_donor],
            "historical_strict_pass": bool(p_hist_ok),
            "historical_checks": p_hist_checks,
            "historical_added_metrics": p_hist_added,
            "historical_combined_metrics": p_hist_combined,
            "historical_combined_payoff": p_hist_payoff,
            "holdout_source_T": len(holdout),
            "holdout_selected_T": len(holdout_selected),
            "holdout_selected_rows": [compact(x) for x in holdout_selected],
            "holdout_extended_strict_pass": bool(p_full_ok),
            "holdout_extended_checks": p_full_checks,
            "holdout_extended_added_metrics": p_full_added,
            "holdout_extended_combined_metrics": p_full_combined,
            "holdout_extended_combined_payoff": p_full_payoff,
            "causal_gate_preregisterable": p_preregisterable,
        },
        "broad30": {
            "parent_T": 30,
            "parent_metrics": metrics(broad),
            "parent_payoff": payoff(broad),
            "historical_selected_T": len(broad_hist),
            "historical_selected_rows": [compact(x) for x in broad_hist],
            "historical_selected_metrics": metrics(broad_hist),
            "historical_selected_payoff": payoff(broad_hist),
            "historical_profile_checks": b_hist_checks,
            "historical_profile_pass": b_hist_pass,
            "holdout_source_T": len(holdout),
            "holdout_selected_T": len(holdout_selected),
            "holdout_selected_rows": [compact(x) for x in holdout_selected],
            "holdout_add_only_strict_pass": bool(b_full_ok),
            "holdout_add_only_checks": b_full_checks,
            "holdout_added_metrics": b_full_added,
            "holdout_combined_metrics": b_full_combined,
            "holdout_combined_payoff": b_full_payoff,
            "causal_gate_preregisterable": b_preregisterable,
        },
        "holdout_boundary": {
            "broad_max_signal_ts": boundary_ts,
            "holdout_T": len(holdout),
            "max_holdout_signal_ts": max([int(x["signal_ts"]) for x in holdout], default=boundary_ts),
        },
        "policy": {
            "parent16_immutable": True,
            "broad30_immutable": True,
            "fresh2_immutable": True,
            "historical_outcome_used_to_choose_predicate": False,
            "runtime_outcome_used": False,
            "holdout_not_promotion_evidence": True,
            "prospective_confirmation_required_after_freeze": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": (
            "FREEZE_3BAR_GATE_AT_HOLDOUT_BOUNDARY_AND_COLLECT_ONLY_NEW_MATCHES"
            if p_preregisterable or b_preregisterable
            else "REJECT_3BAR_GATE_AND_ROTATE_TO_HTF_ALIGNMENT"
        ),
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-source", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_3bar_persistence_causal_v4.json"))
    args = ap.parse_args()
    r = run(args.broad_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "primary_hist_T": r["primary"]["historical_selected_T"],
        "primary_hist_pass": r["primary"]["historical_strict_pass"],
        "primary_holdout_T": r["primary"]["holdout_selected_T"],
        "primary_holdout_pass": r["primary"]["holdout_extended_strict_pass"],
        "primary_preregisterable": r["primary"]["causal_gate_preregisterable"],
        "broad_hist_T": r["broad30"]["historical_selected_T"],
        "broad_hist_metrics": r["broad30"]["historical_selected_metrics"],
        "broad_hist_payoff": r["broad30"]["historical_selected_payoff"],
        "broad_hist_pass": r["broad30"]["historical_profile_pass"],
        "broad_holdout_T": r["broad30"]["holdout_selected_T"],
        "broad_holdout_pass": r["broad30"]["holdout_add_only_strict_pass"],
        "broad_preregisterable": r["broad30"]["causal_gate_preregisterable"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
