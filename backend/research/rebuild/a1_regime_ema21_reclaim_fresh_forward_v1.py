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
PREREG = ROOT / "backend/research/rebuild/a1_regime_ema21_reclaim_prereg_v1.json"
SCHEMA = "zel.a1.regime_ema21_reclaim.fresh_forward.v2"
MIN_TRADES = 25
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
    m = row.get("metrics")
    if isinstance(m, Mapping) and isinstance(m.get(key), (int, float)):
        return float(m[key])
    if isinstance(row.get(key), (int, float)):
        return float(row[key])
    return None


def run(out: Path) -> dict[str, Any]:
    prereg = _read(PREREG)
    boundary = str(prereg["fresh_boundary_utc"])
    with tempfile.TemporaryDirectory(prefix="ema21_reclaim_fresh_") as td:
        td_path = Path(td)
        raw_path = td_path / "raw.json"
        base, shadow = run_terminal_shadow(
            strategy_id=str(prereg["transport_strategy_id"]),
            policy_path=POLICY,
            fresh_boundary_utc=boundary,
            out=raw_path,
        )
        if str(base.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError("REGIME_EMA21_RECLAIM_POLICY_MISMATCH")
        defects = list(base.get("integrity_defects") or [])
        lookahead = int(base.get("leakage_lookahead") or 0)
        if defects or lookahead != 0:
            raise RuntimeError(f"REGIME_EMA21_RECLAIM_INTEGRITY_FAIL:{defects}:{lookahead}")
        if str(base.get("boundary_utc") or "") != boundary:
            raise RuntimeError("REGIME_EMA21_RECLAIM_BOUNDARY_MISMATCH")

        trades = [dict(x) for x in (base.get("trades") or [])]
        completed = len(trades)
        source_quality = base.get("source_quality_gate") if isinstance(base.get("source_quality_gate"), Mapping) else {}
        source_state = str(source_quality.get("state") or "")
        net_pnl = _metric(base, "net_pnl_bps")
        net_exp = _metric(base, "net_expectancy_bps")
        pf = _metric(base, "net_profit_factor") or _metric(base, "profit_factor")
        wr = _metric(base, "win_rate")
        dd = _metric(base, "max_drawdown_bps") or _metric(base, "drawdown_bps")

        result: dict[str, Any] = {
            "schema_version": SCHEMA,
            "candidate_identity": str(prereg["candidate_identity"]),
            "transport_strategy_id": str(prereg["transport_strategy_id"]),
            "strategy_id": str(prereg["transport_strategy_id"]),
            "identity_class": str(prereg["identity_class"]),
            "fresh_boundary_utc": boundary,
            "boundary_utc": boundary,
            "completed_trades": completed,
            "sample_gap_to_25": max(0, MIN_TRADES - completed),
            "minimum_fresh_trades": MIN_TRADES,
            "win_rate": wr,
            "net_pnl_bps": net_pnl,
            "net_expectancy_bps": net_exp,
            "profit_factor": pf,
            "max_drawdown_bps": dd,
            "source_quality_state": source_state,
            "source_quality_gate": dict(source_quality),
            "integrity_defects": defects,
            "leakage_lookahead": lookahead,
            "trades": trades,
            "source": base.get("source"),
            "config_sha": base.get("config_sha"),
            "cost_authority_sha256": base.get("cost_authority_sha256"),
            "policy_sha": base.get("policy_sha"),
            "policy_path": str(POLICY.relative_to(ROOT)),
            "policy_blob_sha_preregistered": str(prereg["policy_blob_sha"]),
            "policy_freeze_commit": str(prereg["policy_freeze_commit"]),
            "prereg_receipt_sha256": ev.stable_sha(prereg),
            "preboundary_outcomes_counted": False,
            "preboundary_data_feature_warmup_only": True,
            "numeric_threshold_sweep": False,
            "outcome_used_at_runtime": False,
            "existing_keltner_h4_h5_reuse_for_promotion": False,
            "identity_specific_hardening_required_after_25": True,
            "canonical_ledger_mutation": False,
            "shadow_replay": shadow,
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
            **AUTH,
        }

        if source_state == "FAIL":
            state = "HOLD_FRESH_SOURCE_QUALITY"
            nxt = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif completed < MIN_TRADES:
            state = "WAIT_FRESH_25"
            nxt = "CONTINUE_HOURLY_FRESH_COLLECTION"
        elif net_pnl is None or net_exp is None or net_pnl <= 0 or net_exp <= 0 or (pf is not None and pf < 1.0):
            state = "HOLD_FRESH_25_ECONOMICS_NONPOSITIVE"
            nxt = "PRESERVE_EVIDENCE_DO_NOT_HARDEN_OR_PROMOTE"
        else:
            result["receipt_sha256"] = ev.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
            candidate_path = td_path / "candidate.json"
            candidate_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            hard_path = td_path / "hardening.json"
            subprocess.run([
                sys.executable, "-m", "backend.research.rebuild.a1_regime_ema21_reclaim_h4_h5_hardening_v1",
                "--receipt", str(candidate_path), "--out", str(hard_path),
            ], check=True)
            hardening = _read(hard_path)
            result["hardening_receipt"] = hardening
            result["h4_state"] = str((hardening.get("h4_receipt") or {}).get("state") or "")
            result["h5_state"] = str((hardening.get("h5_receipt") or {}).get("state") or "")
            if hardening.get("state") == "PASS_EMA21_RECLAIM_IDENTITY_HARDENING":
                state = "PASS_EMA21_RECLAIM_FRESH_SURVIVOR_GATE"
                nxt = "ROUTE_A2_A3_WITHOUT_PROMOTION_AUTHORITY"
            else:
                state = "HOLD_EMA21_RECLAIM_FRESH_HARDENING"
                nxt = "PRESERVE_EVIDENCE_AND_ROUTE_NEXT_DISTINCT_AXIS"

        result["state"] = state
        result["next"] = nxt
        result["receipt_sha256"] = ev.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return result


def self_test() -> int:
    p = _read(PREREG)
    assert p["candidate_identity"] == "regime_ema21_reclaim_v1"
    assert p["fresh_boundary_utc"] == "2026-08-23T14:00:00Z"
    assert p["existing_keltner_h4_h5_reuse_for_promotion"] is False
    assert p["identity_specific_hardening_required_after_25"] is True
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_REGIME_EMA21_RECLAIM_FRESH_FORWARD_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_regime_ema21_reclaim_fresh_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "completed_trades": r["completed_trades"],
        "sample_gap_to_25": r["sample_gap_to_25"],
        "win_rate": r["win_rate"],
        "net_pnl_bps": r["net_pnl_bps"],
        "net_expectancy_bps": r["net_expectancy_bps"],
        "h4_state": r["h4_state"],
        "h5_state": r["h5_state"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
