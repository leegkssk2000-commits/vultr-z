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
POLICY = ROOT / "backend/research/rebuild/keltner_trend_persistence_confirmation_child_policy_v1.py"
SCHEMA = "zel.a1.keltner.persistence_confirmation.eval.v1"
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
    with tempfile.TemporaryDirectory(prefix="keltner-persistence-eval-") as td:
        work = Path(td)
        parent_path = work / "parent.json"
        cp = subprocess.run([
            sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
            "--strategy-id", "keltner_trend", "--out", str(parent_path), "--terminal-replay",
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if cp.returncode != 0 or not parent_path.is_file():
            raise RuntimeError("KELTNER_PARENT_REPLAY_FAILED:" + (cp.stderr or cp.stdout)[-1200:])
        parent = _read(parent_path)
        boundary = str(parent.get("prospective_boundary_utc") or parent.get("boundary_utc") or "")
        if not boundary:
            raise RuntimeError("KELTNER_PARENT_BOUNDARY_MISSING")
        if list(parent.get("integrity_defects") or []) or int(parent.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_PARENT_INTEGRITY_FAIL")

        child_path = work / "child.json"
        child, shadow = run_terminal_shadow(
            strategy_id="keltner_trend",
            policy_path=POLICY,
            fresh_boundary_utc=boundary,
            out=child_path,
        )
        if list(child.get("integrity_defects") or []) or int(child.get("leakage_lookahead") or 0) != 0:
            raise RuntimeError("KELTNER_PERSISTENCE_CHILD_INTEGRITY_FAIL")
        if str(child.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("KELTNER_PERSISTENCE_POLICY_MISMATCH")

        ps = _summary(parent)
        cs = _summary(child)
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
                "--receipt", str(child_path), "--out", str(hard_path),
            ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if hp.returncode != 0 or not hard_path.is_file():
                raise RuntimeError("KELTNER_PERSISTENCE_HARDENING_FAILED:" + (hp.stderr or hp.stdout)[-1200:])
            hardening = _read(hard_path)
            h4 = str((hardening.get("h4_receipt") or {}).get("state") or "")
            h5 = str((hardening.get("h5_receipt") or {}).get("state") or "")

        parent_trades = int(ps["trades"])
        child_trades = int(cs["trades"])
        retention = child_trades / parent_trades if parent_trades else 0.0
        pnl_improved = c_net > p_net
        wr_improved = c_wr is not None and p_wr is not None and float(c_wr) > float(p_wr)
        dd_improved = c_dd is not None and p_dd is not None and float(c_dd) < float(p_dd)
        hardening_pass = bool(hardening and hardening.get("state") == "PASS_HARDENING_EVIDENCE")

        if hardening_pass:
            state = "PERSISTENCE_CHILD_HARDENING_PASS_DISCOVERY"
            nxt = "PREREGISTER_NEW_FRESH_BOUNDARY_BEFORE_ANY_AUTHORITY"
        elif pnl_improved and wr_improved and retention >= 0.5:
            state = "PERSISTENCE_CHILD_ECONOMIC_IMPROVEMENT_DISCOVERY"
            nxt = "PRESERVE_CHILD_AS_DISCOVERY_ONLY_AND_REQUIRE_FRESH_PROOF"
        elif child_trades < MIN_HARDENING_TRADES and (pnl_improved or wr_improved) and retention >= 0.35:
            state = "PERSISTENCE_CHILD_PROMISING_BUT_UNDER_HARDENING_SAMPLE"
            nxt = "DO_NOT_PROMOTE_COLLECT_FRESH_OR_TEST_NEXT_CAUSAL_TIMING_AXIS"
        else:
            state = "PERSISTENCE_CHILD_NOT_SUPERIOR"
            nxt = "PRESERVE_PARENT_REGIME_CORE_AND_TEST_NEXT_DISTINCT_TIMING_MECHANISM"

        result = {
            "schema_version": SCHEMA,
            "state": state,
            "strategy_id": "keltner_trend",
            "changed_axis": "ONE_BAR_KELTNER_ADMISSION_PERSISTENCE_ONLY",
            "prospective_boundary_utc": boundary,
            "parent": ps,
            "child": cs,
            "trade_retention_ratio": retention,
            "delta_net_pnl_bps": c_net - p_net,
            "delta_win_rate": (float(c_wr) - float(p_wr)) if c_wr is not None and p_wr is not None else None,
            "delta_max_drawdown_bps": (float(c_dd) - float(p_dd)) if c_dd is not None and p_dd is not None else None,
            "pnl_improved": pnl_improved,
            "win_rate_improved": wr_improved,
            "drawdown_improved": dd_improved,
            "h4_state": h4,
            "h5_state": h5,
            "hardening_receipt": hardening,
            "shadow_replay": shadow,
            "parent_policy_mutated": False,
            "canonical_ledger_mutation": False,
            "numeric_threshold_sweep": False,
            "outcome_used_at_runtime": False,
            "fresh_proof_required_for_any_selection": True,
            "next": nxt,
            **AUTH,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result


def self_test() -> int:
    assert MIN_HARDENING_TRADES == 25
    assert POLICY.name == "keltner_trend_persistence_confirmation_child_policy_v1.py"
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_KELTNER_PERSISTENCE_CONFIRMATION_EVAL_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_persistence_confirmation_eval_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"], "parent": r["parent"], "child": r["child"],
        "retention": r["trade_retention_ratio"], "delta_net_pnl_bps": r["delta_net_pnl_bps"],
        "delta_win_rate": r["delta_win_rate"], "h4": r["h4_state"], "h5": r["h5_state"], "next": r["next"]
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
