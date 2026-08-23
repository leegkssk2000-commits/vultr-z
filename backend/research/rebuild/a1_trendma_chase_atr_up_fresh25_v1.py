#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild import a1_finalist_good_regime_fresh25_v1 as common
from backend.research.rebuild import a1_finalist_good_regime_h4_h5_hardening_v1 as generic_hardening
from backend.tools import zel_economic_hardening_gate_v1 as hard

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = "trend_ma_macd_chase_atr_up_good_v1"
STRATEGY_ID = "trend_ma_macd"
POLICY = ROOT / "backend/research/rebuild/trend_ma_macd_chase_atr_up_good_child_policy_v1.py"
PREREG = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_good_prereg_v1.json"
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
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
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _validate_prereg() -> dict[str, Any]:
    p = _read(PREREG)
    if p.get("state") != "PASS_PREREG_FROZEN":
        raise RuntimeError("CHASE_PREREG_NOT_FROZEN")
    if p.get("candidate_identity") != IDENTITY or p.get("transport_strategy_id") != STRATEGY_ID:
        raise RuntimeError("CHASE_PREREG_IDENTITY_MISMATCH")
    if tuple(p.get("fixed_universe") or []) != LIQUID6:
        raise RuntimeError("CHASE_PREREG_LIQUID6_MISMATCH")
    if int(p.get("minimum_fresh_trades") or 0) != MIN_TRADES or int(p.get("exact_first_completed_trades") or 0) != MIN_TRADES:
        raise RuntimeError("CHASE_PREREG_SAMPLE_MISMATCH")
    if p.get("preboundary_outcomes_counted") is not False or p.get("numeric_threshold_sweep") is not False:
        raise RuntimeError("CHASE_PREREG_FRESH_CONTRACT_FAIL")
    if p.get("outcome_used_at_runtime") is not False or p.get("combined_with_primary") is not False:
        raise RuntimeError("CHASE_PREREG_RUNTIME_OR_COMBINATION_FAIL")
    actual_blob = common._git_blob_sha(POLICY)
    if actual_blob != str(p.get("policy_blob_sha") or ""):
        raise RuntimeError(f"CHASE_POLICY_BLOB_MISMATCH:{actual_blob}:{p.get('policy_blob_sha')}")
    return p


def _base(prereg: Mapping[str, Any]) -> dict[str, Any]:
    boundary = str(prereg["fresh_boundary_utc"])
    return {
        "schema_version": "zel.a1.trendma_chase_atr_up.fresh25.v1",
        "candidate_identity": IDENTITY,
        "transport_strategy_id": STRATEGY_ID,
        "strategy_id": STRATEGY_ID,
        "alternative_to": "trend_ma_macd_ema_fast_up_good_v1",
        "combined_with_primary": False,
        "policy_path": str(POLICY.relative_to(ROOT)),
        "policy_blob_sha_preregistered": str(prereg["policy_blob_sha"]),
        "policy_freeze_commit": str(prereg["policy_freeze_commit"]),
        "fresh_boundary_utc": boundary,
        "boundary_utc": boundary,
        "fresh_boundary_rule": str(prereg["fresh_boundary_rule"]),
        "fixed_universe": list(LIQUID6),
        "minimum_fresh_trades": MIN_TRADES,
        "exact_first_completed_trades": MIN_TRADES,
        "preboundary_outcomes_counted": False,
        "preboundary_data_feature_warmup_only": True,
        "post_25_outcomes_ignored": True,
        "parent_preserved": True,
        "primary_child_preserved": True,
        "parent_h4_h5_reuse_for_promotion": False,
        "identity_specific_hardening_required_after_25": True,
        "numeric_threshold_sweep": False,
        "outcome_used_at_runtime": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        "runtime_good_boost_enabled": False,
        **AUTH,
    }


def run(now: datetime | None = None) -> dict[str, Any]:
    prereg = _validate_prereg()
    result = _base(prereg)
    boundary = str(prereg["fresh_boundary_utc"])
    boundary_dt = datetime.fromisoformat(boundary.replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)

    if current < boundary_dt:
        result.update({
            "state": "WAIT_FRESH_BOUNDARY",
            "completed_trades": 0,
            "raw_completed_trades_since_boundary": 0,
            "sample_gap_to_25": MIN_TRADES,
            "metrics": common._metrics([]),
            "win_rate": None,
            "net_pnl_bps": None,
            "net_expectancy_bps": None,
            "profit_factor": None,
            "max_drawdown_bps": None,
            "source_quality_state": "NOT_RUN_BEFORE_FRESH_BOUNDARY",
            "integrity_defects": [],
            "leakage_lookahead": 0,
            "trades": [],
            "shadow_replay": None,
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
            "next": "WAIT_FOR_PREREGISTERED_FRESH_BOUNDARY_THEN_COLLECT_EXACT25",
        })
        result["receipt_sha256"] = hard.stable_sha(result)
        return result

    with tempfile.TemporaryDirectory(prefix="trendma_chase_atr_up_fresh25_") as td:
        td_path = Path(td)
        raw_path = td_path / "raw.json"
        raw, shadow = run_terminal_shadow(
            strategy_id=STRATEGY_ID,
            policy_path=POLICY,
            fresh_boundary_utc=boundary,
            out=raw_path,
            symbols=LIQUID6,
        )
        if str(raw.get("policy_path") or "") != str(POLICY.relative_to(ROOT)):
            raise RuntimeError(f"CHASE_POLICY_PATH_MISMATCH:{raw.get('policy_path')}")
        defects = list(raw.get("integrity_defects") or [])
        lookahead = int(raw.get("leakage_lookahead") or 0)
        source_quality = raw.get("source_quality_gate") if isinstance(raw.get("source_quality_gate"), Mapping) else {}
        source_state = str(source_quality.get("state") or "")
        if defects or lookahead != 0:
            raise RuntimeError(f"CHASE_FRESH_INTEGRITY_FAIL:{defects}:{lookahead}")
        source_symbols = tuple(sorted(str(x) for x in ((raw.get("source") or {}).get("symbols") or [])))
        if source_symbols and source_symbols != tuple(sorted(LIQUID6)):
            raise RuntimeError(f"CHASE_SOURCE_UNIVERSE_MISMATCH:{source_symbols}")

        raw_trades = [dict(x) for x in (raw.get("trades") or [])]
        trades = common._ordered_first25(raw_trades)
        metrics = common._metrics(trades)
        completed = len(trades)
        result.update({
            "completed_trades": completed,
            "raw_completed_trades_since_boundary": len(raw_trades),
            "sample_gap_to_25": max(0, MIN_TRADES - completed),
            "metrics": metrics,
            "win_rate": metrics["win_rate"],
            "net_pnl_bps": metrics["net_pnl_bps"],
            "net_expectancy_bps": metrics["net_expectancy_bps"],
            "profit_factor": metrics["net_profit_factor"],
            "max_drawdown_bps": metrics["realized_exit_bucket_max_drawdown_bps"],
            "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
            "source_quality_state": source_state,
            "source_quality_gate": dict(source_quality),
            "integrity_defects": defects,
            "leakage_lookahead": lookahead,
            "trades": trades,
            "source": raw.get("source"),
            "config_sha": raw.get("config_sha"),
            "cost_authority_sha256": raw.get("cost_authority_sha256"),
            "policy_sha": raw.get("policy_sha"),
            "shadow_replay": shadow,
            "h4_state": "NOT_RUN_MIN_SAMPLE",
            "h5_state": "NOT_RUN_MIN_SAMPLE",
            "hardening_receipt": None,
        })

        if source_state == "FAIL":
            state = "HOLD_FRESH_SOURCE_QUALITY"
            nxt = "REPAIR_SOURCE_ONLY_NO_STRATEGY_CHANGE"
        elif completed < MIN_TRADES:
            state = "WAIT_FRESH_25"
            nxt = "CONTINUE_HOURLY_EXACT_FIRST25_COLLECTION"
        elif metrics["net_pnl_bps"] <= 0 or metrics["net_expectancy_bps"] is None or metrics["net_expectancy_bps"] <= 0 or (metrics["net_profit_factor"] is not None and metrics["net_profit_factor"] < 1.0):
            state = "HOLD_FRESH_25_ECONOMICS_NONPOSITIVE"
            nxt = "PRESERVE_PARENT_PRIMARY_AND_ALTERNATIVE_EVIDENCE_DO_NOT_HARDEN_OR_PROMOTE"
        else:
            result["state"] = "READY_IDENTITY_HARDENING"
            result["next"] = "RUN_IDENTITY_SPECIFIC_H4_H5"
            result["receipt_sha256"] = hard.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
            candidate_path = td_path / "candidate.json"
            candidate_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            hard_path = td_path / "hardening.json"

            # Reuse the already-CI-validated generic H4/H5 engine without
            # changing the sealed two-child target registry on master.
            generic_hardening.TARGETS[IDENTITY] = {
                "transport_strategy_id": STRATEGY_ID,
                "indicator_removal_semantics": "REMOVE_CHASE_ATR_UP_GOOD_ADMISSION_RESTORE_UNCHANGED_TRENDMA_PARENT",
            }
            hardened = generic_hardening.run(candidate_path, hard_path)
            result["hardening_receipt"] = hardened
            result["h4_state"] = str((hardened.get("h4_receipt") or {}).get("state") or "")
            result["h5_state"] = str((hardened.get("h5_receipt") or {}).get("state") or "")
            if hardened.get("state") == "PASS_GOOD_REGIME_IDENTITY_HARDENING":
                state = "PASS_TRENDMA_CHASE_ATR_UP_FRESH_SURVIVOR_GATE"
                nxt = "COMPARE_FRESH_WITH_EMA_FAST_PRIMARY_WITHOUT_COMBINING_OR_PROMOTION_AUTHORITY"
            else:
                state = "HOLD_TRENDMA_CHASE_ATR_UP_FRESH_HARDENING"
                nxt = "PRESERVE_PARENT_PRIMARY_AND_ALTERNATIVE_EVIDENCE_NO_PROMOTION"

        result["state"] = state
        result["next"] = nxt
        result["receipt_sha256"] = hard.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
        return result


def self_test() -> int:
    p = _validate_prereg()
    assert p["fresh_boundary_utc"] == "2026-08-23T18:00:00Z"
    assert p["discovery_relation"] == "PARETO_DOMINATES_PARENT"
    assert p["combined_with_primary"] is False
    fake_before = datetime(2026, 8, 23, 17, 30, tzinfo=timezone.utc)
    r = run(now=fake_before)
    assert r["state"] == "WAIT_FRESH_BOUNDARY" and r["completed_trades"] == 0
    assert r["preboundary_outcomes_counted"] is False and r["combined_with_primary"] is False
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED"
    print("PASS_A1_TRENDMA_CHASE_ATR_UP_FRESH25_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendma_chase_atr_up_fresh25_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "completed_trades": result["completed_trades"],
        "sample_gap_to_25": result["sample_gap_to_25"],
        "win_rate": result.get("win_rate"),
        "net_pnl_bps": result.get("net_pnl_bps"),
        "h4_state": result["h4_state"],
        "h5_state": result["h5_state"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
