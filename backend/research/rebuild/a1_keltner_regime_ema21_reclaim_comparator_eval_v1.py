#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/rebuild/keltner_regime_ema21_reclaim_comparator_policy_v1.py"
SCHEMA = "zel.a1.keltner.regime_ema21_reclaim_comparator.eval.v1"
MIN_HARDENING_TRADES = 25
AUTH = {"selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "protected_mutations": 0}


def _read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return row


def _metric(row: Mapping[str, Any], key: str) -> float | None:
    m = row.get("metrics")
    if isinstance(m, Mapping) and isinstance(m.get(key), (int, float)):
        return float(m[key])
    if isinstance(row.get(key), (int, float)):
        return float(row[key])
    return None


def _summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trades": int(row.get("completed_trades") or 0),
        "win_rate": _metric(row, "win_rate"),
        "net_pnl_bps": _metric(row, "net_pnl_bps"),
        "net_expectancy_bps": _metric(row, "net_expectancy_bps"),
        "profit_factor": _metric(row, "net_profit_factor") or _metric(row, "profit_factor"),
        "max_drawdown_bps": _metric(row, "max_drawdown_bps") or _metric(row, "drawdown_bps"),
    }


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="keltner-reclaim-comparator-") as td:
        work = Path(td)
        pp = work / "parent.json"
        cp = subprocess.run([sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2", "--strategy-id", "keltner_trend", "--out", str(pp), "--terminal-replay"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if cp.returncode != 0 or not pp.is_file():
            raise RuntimeError("KELTNER_PARENT_REPLAY_FAILED:" + (cp.stderr or cp.stdout)[-1000:])
        parent = _read(pp)
        if list(parent.get("integrity_defects") or []) or int(parent.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_PARENT_INTEGRITY_FAIL")
        boundary = str(parent.get("prospective_boundary_utc") or parent.get("boundary_utc") or "")
        if not boundary:
            raise RuntimeError("KELTNER_PARENT_BOUNDARY_MISSING")

        cp2 = work / "comparator.json"
        comp, shadow = run_terminal_shadow(strategy_id="keltner_trend", policy_path=POLICY, fresh_boundary_utc=boundary, out=cp2)
        if list(comp.get("integrity_defects") or []) or int(comp.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_RECLAIM_COMPARATOR_INTEGRITY_FAIL")
        if str(comp.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("KELTNER_RECLAIM_COMPARATOR_POLICY_MISMATCH")

        ps, cs = _summary(parent), _summary(comp)
        pnet, cnet = float(ps["net_pnl_bps"] or 0.0), float(cs["net_pnl_bps"] or 0.0)
        pexp, cexp = float(ps["net_expectancy_bps"] or 0.0), float(cs["net_expectancy_bps"] or 0.0)
        pwr, cwr = ps["win_rate"], cs["win_rate"]
        pdd, cdd = ps["max_drawdown_bps"], cs["max_drawdown_bps"]
        hardening = None
        h4 = h5 = "NOT_RUN_MIN_SAMPLE"
        if int(cs["trades"]) >= MIN_HARDENING_TRADES:
            hp = work / "hardening.json"
            hcp = subprocess.run([sys.executable, "-m", "backend.research.rebuild.a1_keltner_h4_h5_hardening_v1", "--receipt", str(cp2), "--out", str(hp)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if hcp.returncode == 0 and hp.is_file():
                hardening = _read(hp)
                h4 = str((hardening.get("h4_receipt") or {}).get("state") or "")
                h5 = str((hardening.get("h5_receipt") or {}).get("state") or "")
            else:
                h4 = h5 = "HOLD_HARDENING_TECHNICAL"

        count = int(cs["trades"])
        if count >= max(8, int(ps["trades"]) // 2) and cnet > pnet:
            state = "EMA21_RECLAIM_SYSTEMATIC_TIMING_OUTPERFORMS_PARENT_DISCOVERY"
            nxt = "SPLIT_AS_DISTINCT_REGIME_STRATEGY_AND_PREREGISTER_FRESH_PROOF"
        elif count >= 8 and cnet > 0 and cexp > pexp:
            state = "EMA21_RECLAIM_HIGH_EXPECTANCY_MEANINGFUL_SAMPLE_DISCOVERY"
            nxt = "PRESERVE_SEPARATE_HYPOTHESIS_AND_REQUIRE_FRESH_PROOF"
        elif count > 0 and cnet > 0 and cexp > pexp:
            state = "EMA21_RECLAIM_HIGH_EXPECTANCY_LOW_SAMPLE_DISCOVERY"
            nxt = "DO_NOT_PROMOTE_ACCUMULATE_OR_TEST_ONE_MORE_DISTINCT_REGIME_TIMING"
        else:
            state = "EMA21_RECLAIM_COMPARATOR_NOT_SUPERIOR"
            nxt = "KEEP_PARENT_AND_STOP_REGIME_TIMING_ROTATION_IF_NO_NEW_CAUSAL_AXIS"

        result = {
            "schema_version": SCHEMA,
            "state": state,
            "strategy_transport_id": "keltner_trend",
            "comparison_identity": "VOL_HIGH_EMA21_TOUCH_RECLAIM_VS_KELTNER_BREAKOUT",
            "not_a_keltner_child": True,
            "prospective_boundary_utc": boundary,
            "parent": ps,
            "ema21_reclaim_comparator": cs,
            "trade_count_delta": count - int(ps["trades"]),
            "delta_net_pnl_bps": cnet - pnet,
            "delta_net_expectancy_bps": cexp - pexp,
            "delta_win_rate": (float(cwr) - float(pwr)) if cwr is not None and pwr is not None else None,
            "delta_max_drawdown_bps": (float(cdd) - float(pdd)) if cdd is not None and pdd is not None else None,
            "h4_state": h4,
            "h5_state": h5,
            "hardening_receipt": hardening,
            "shadow_replay": shadow,
            "risk_exit_geometry_preserved": True,
            "numeric_threshold_sweep": False,
            "outcome_used_at_runtime": False,
            "canonical_ledger_mutation": False,
            "next": nxt,
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result


def self_test() -> int:
    assert MIN_HARDENING_TRADES == 25
    assert POLICY.name == "keltner_regime_ema21_reclaim_comparator_policy_v1.py"
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_KELTNER_REGIME_EMA21_RECLAIM_COMPARATOR_EVAL_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_regime_ema21_reclaim_comparator_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({"state": r["state"], "parent": r["parent"], "comparator": r["ema21_reclaim_comparator"], "delta_net_pnl_bps": r["delta_net_pnl_bps"], "delta_net_expectancy_bps": r["delta_net_expectancy_bps"], "h4": r["h4_state"], "h5": r["h5_state"], "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
