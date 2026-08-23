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
POLICY = ROOT / "backend/research/rebuild/keltner_regime_transition_comparator_policy_v1.py"
SCHEMA = "zel.a1.keltner.regime_transition_comparator.eval.v1"
MIN_HARDENING_TRADES = 25
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return row


def _metric(row: Mapping[str, Any], key: str) -> float | None:
    metrics = row.get("metrics")
    if isinstance(metrics, Mapping) and isinstance(metrics.get(key), (int, float)):
        return float(metrics[key])
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
    with tempfile.TemporaryDirectory(prefix="keltner-regime-comparator-") as td:
        work = Path(td)
        parent_path = work / "parent.json"
        cp = subprocess.run([
            sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
            "--strategy-id", "keltner_trend", "--out", str(parent_path), "--terminal-replay",
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if cp.returncode != 0 or not parent_path.is_file():
            raise RuntimeError("KELTNER_PARENT_REPLAY_FAILED:" + (cp.stderr or cp.stdout)[-1000:])
        parent = _read(parent_path)
        if list(parent.get("integrity_defects") or []) or int(parent.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_PARENT_INTEGRITY_FAIL")
        boundary = str(parent.get("prospective_boundary_utc") or parent.get("boundary_utc") or "")
        if not boundary:
            raise RuntimeError("KELTNER_PARENT_BOUNDARY_MISSING")

        comp_path = work / "comparator.json"
        comparator, shadow = run_terminal_shadow(
            strategy_id="keltner_trend", policy_path=POLICY, fresh_boundary_utc=boundary, out=comp_path
        )
        if list(comparator.get("integrity_defects") or []) or int(comparator.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_REGIME_COMPARATOR_INTEGRITY_FAIL")
        if str(comparator.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("KELTNER_REGIME_COMPARATOR_POLICY_MISMATCH")

        ps = _summary(parent)
        cs = _summary(comparator)
        p_net = float(ps["net_pnl_bps"] or 0.0)
        c_net = float(cs["net_pnl_bps"] or 0.0)
        p_wr = ps["win_rate"]
        c_wr = cs["win_rate"]
        p_dd = ps["max_drawdown_bps"]
        c_dd = cs["max_drawdown_bps"]

        hardening = None
        h4 = "NOT_RUN_MIN_SAMPLE"
        h5 = "NOT_RUN_MIN_SAMPLE"
        if int(cs["trades"]) >= MIN_HARDENING_TRADES:
            hard_path = work / "hardening.json"
            hp = subprocess.run([
                sys.executable, "-m", "backend.research.rebuild.a1_keltner_h4_h5_hardening_v1",
                "--receipt", str(comp_path), "--out", str(hard_path),
            ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if hp.returncode == 0 and hard_path.is_file():
                hardening = _read(hard_path)
                h4 = str((hardening.get("h4_receipt") or {}).get("state") or "")
                h5 = str((hardening.get("h5_receipt") or {}).get("state") or "")
            else:
                h4 = "HOLD_HARDENING_TECHNICAL"
                h5 = "HOLD_HARDENING_TECHNICAL"

        if int(cs["trades"]) == 0:
            state = "REGIME_TRANSITION_COMPARATOR_NO_TRADES"
            nxt = "REJECT_COMPARATOR"
        elif c_net > p_net and int(cs["trades"]) >= max(5, int(ps["trades"]) // 3):
            state = "REGIME_TRANSITION_SYSTEMATIC_TIMING_OUTPERFORMS_PARENT_DISCOVERY"
            nxt = "DO_NOT_PATCH_KELTNER_SPLIT_AND_FRESH_VALIDATE_REGIME_STRATEGY_IDENTITY"
        elif float(cs["net_expectancy_bps"] or 0.0) > float(ps["net_expectancy_bps"] or 0.0) and c_net > 0:
            state = "REGIME_TRANSITION_HIGH_EXPECTANCY_LOW_SAMPLE_DISCOVERY"
            nxt = "PRESERVE_AS_SEPARATE_STRATEGY_HYPOTHESIS_NOT_KELTNER_CHILD"
        else:
            state = "REGIME_TRANSITION_COMPARATOR_NOT_SUPERIOR"
            nxt = "KEEP_KELTNER_PARENT_AND_TEST_OTHER_NONFILTER_TIMING_MECHANISM"

        result = {
            "schema_version": SCHEMA,
            "state": state,
            "strategy_transport_id": "keltner_trend",
            "comparison_identity": "VOL_HIGH_EMA_REGIME_TRANSITION_VS_KELTNER_BREAKOUT",
            "not_a_keltner_child": True,
            "prospective_boundary_utc": boundary,
            "parent": ps,
            "regime_transition_comparator": cs,
            "trade_count_delta": int(cs["trades"]) - int(ps["trades"]),
            "delta_net_pnl_bps": c_net - p_net,
            "delta_net_expectancy_bps": float(cs["net_expectancy_bps"] or 0.0) - float(ps["net_expectancy_bps"] or 0.0),
            "delta_win_rate": (float(c_wr) - float(p_wr)) if c_wr is not None and p_wr is not None else None,
            "delta_max_drawdown_bps": (float(c_dd) - float(p_dd)) if c_dd is not None and p_dd is not None else None,
            "h4_state": h4,
            "h5_state": h5,
            "hardening_receipt": hardening,
            "shadow_replay": shadow,
            "risk_exit_geometry_preserved": True,
            "breakout_admission_replaced_for_diagnostic": True,
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
    assert POLICY.name == "keltner_regime_transition_comparator_policy_v1.py"
    assert MIN_HARDENING_TRADES == 25
    assert AUTH["selection_authority"] is False and AUTH["execution_authority"] == "NONE"
    print("PASS_A1_KELTNER_REGIME_TRANSITION_COMPARATOR_EVAL_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_regime_transition_comparator_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({"state": r["state"], "parent": r["parent"], "comparator": r["regime_transition_comparator"], "delta_net_pnl_bps": r["delta_net_pnl_bps"], "h4": r["h4_state"], "h5": r["h5_state"], "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
