#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_a5_original_baseline_integrity_v1.json"
RETEST_QUEUE = ROOT / "backend/research/contracts/a1_a4_original_baseline_retest_queue_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
ECON = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
DEFAULT_OUT = ROOT / "backend/research/architecture_factory/a1_a5_original_baseline_audit_latest.json"

NON_TREND = ["break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd"]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def close(a: Any, b: Any, tol: float = 1e-8) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        scale = max(1.0, abs(float(a)), abs(float(b)))
        return abs(float(a) - float(b)) <= tol * scale
    return a == b


def verify_metrics(expected: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    aliases = {
        "completed_trades": "completed_trades",
        "win_rate": "win_rate",
        "net_pnl_bps": "net_pnl_bps",
        "net_expectancy_bps": "net_expectancy_bps",
        "profit_factor": "profit_factor",
        "payoff": "payoff",
        "drawdown_bps": "drawdown_bps",
    }
    for k, expected_value in expected.items():
        observed_key = aliases.get(k, k)
        if observed_key not in observed:
            defects.append(f"MISSING_METRIC:{observed_key}")
            continue
        if not close(expected_value, observed.get(observed_key), tol=2e-6):
            defects.append(
                f"METRIC_MISMATCH:{observed_key}:expected={expected_value}:observed={observed.get(observed_key)}"
            )
    return defects


def provider_transport_failed(econ: dict[str, Any]) -> bool:
    providers = econ.get("providers") or {}
    failed_with_error = [
        p for p in providers.values()
        if isinstance(p, dict) and p.get("request_count", 0) and not p.get("successful") and p.get("error")
    ]
    no_rows = not ((econ.get("initial_development_economics") or {}).get("rows") or [])
    no_candidates = not (econ.get("initial_candidates") or [])
    return bool(failed_with_error and no_rows and no_candidates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    contract = load(CONTRACT)
    queue = load(RETEST_QUEUE)
    ledger = load(LEDGER)
    econ = load(ECON)

    strategies = ledger.get("strategies") or {}
    canonical = contract.get("canonical_baselines") or {}
    transport_failed = provider_transport_failed(econ)
    by_econ = econ.get("by_strategy") or {}

    defects: list[str] = []
    rows: dict[str, Any] = {}

    for sid in NON_TREND:
        expected = (canonical.get(sid) or {}).get("metrics") or {}
        observed = strategies.get(sid) or {}
        metric_defects = verify_metrics(expected, observed)
        defects.extend(f"{sid}:{d}" for d in metric_defects)

        econ_row = by_econ.get(sid) or {}
        attempted = list(econ_row.get("economic_attempted_axes") or [])
        tested = list(econ_row.get("economically_tested_axes_this_run") or [])
        candidate_count = int(econ_row.get("candidate_count") or 0)
        pass_count = int(econ_row.get("development_economic_pass_count") or 0)

        old_zero_is_authoritative = bool(tested) and not transport_failed
        if pass_count > 0:
            conclusion = "EXACT_PARENT_PROOF_STILL_REQUIRED_BEFORE_IMPROVEMENT_CLAIM"
        elif candidate_count == 0 and attempted and not tested:
            conclusion = "RETEST_REQUIRED_OLD_ZERO_NOT_ECONOMIC_FAIL"
        else:
            conclusion = "RETEST_REQUIRED"

        rows[sid] = {
            "canonical_baseline_id": (canonical.get(sid) or {}).get("canonical_improvement_baseline_id"),
            "baseline_integrity": "PASS" if not metric_defects else "FAIL",
            "baseline_metric_defects": metric_defects,
            "latest_economic_attempted_axes": attempted,
            "latest_economically_tested_axes": tested,
            "latest_candidate_count": candidate_count,
            "latest_development_economic_pass_count": pass_count,
            "latest_zero_result_authoritative": old_zero_is_authoritative,
            "conclusion": conclusion,
        }

    tr = canonical.get("trend_rider") or {}
    tr_screen_expected = tr.get("historical_screening_reference") or {}
    tr_screen_observed = strategies.get("trend_rider") or {}
    tr_screen_defects = verify_metrics(tr_screen_expected, tr_screen_observed)
    defects.extend(f"trend_rider_screening:{d}" for d in tr_screen_defects)
    tr_expansion = econ.get("trend_rider_original_fresh_online_expansion") or {}
    rows["trend_rider"] = {
        "canonical_baseline_id": tr.get("canonical_improvement_baseline_id"),
        "canonical_fresh_win_rate": (tr.get("metrics") or {}).get("win_rate"),
        "historical_screening_reference_integrity": "PASS" if not tr_screen_defects else "FAIL",
        "historical_screening_reference_defects": tr_screen_defects,
        "derived_lineages_forbidden_as_baseline": tr.get("forbidden_substitute_baselines") or [],
        "direct_same_baseline_ab_receipt_present": bool(tr_expansion.get("direct_same_baseline_ab_receipt_present")),
        "conclusion": (
            "DIRECT_ORIGINAL_FRESH_AB_ACTIVE"
            if tr_expansion.get("direct_same_baseline_ab_receipt_present")
            else "WAIT_DIRECT_ORIGINAL_FRESH_AB_RECEIPT"
        ),
    }

    queue_ids = [x.get("strategy_id") for x in (queue.get("queue") or [])]
    if queue_ids != NON_TREND:
        defects.append(f"RETEST_QUEUE_ORDER_OR_MEMBERSHIP_MISMATCH:{queue_ids}")

    provider_errors = {
        name: row.get("error")
        for name, row in (econ.get("providers") or {}).items()
        if isinstance(row, dict) and row.get("error")
    }

    state = "PASS_A5_ORIGINAL_BASELINE_AUDIT_RETEST_REQUIRED" if not defects else "HOLD_A5_BASELINE_INTEGRITY_DEFECT"
    out: dict[str, Any] = {
        "schema_version": "zel.a1_a5_original_baseline_audit.v1",
        "state": state,
        "action": "hold",
        "official_pass_counts_unchanged": {"A1": 1, "A2": 1, "A3": 0},
        "transport_failure_detected_in_latest_generic_economic_run": transport_failed,
        "transport_errors": provider_errors,
        "audit_conclusion": "Do not treat generic zero-ready results as economic failures. Re-run remaining four finalists from their canonical original baselines with exact-parent direct A/B receipts.",
        "by_strategy": rows,
        "integrity_defects": defects,
        "authority": contract.get("authority"),
        "next": "RUN_EXACT_PARENT_ORIGINAL_BASELINE_RETEST_QUEUE" if not defects else "FIX_BASELINE_INTEGRITY_BEFORE_RETEST",
    }
    canonical_bytes = json.dumps(out, sort_keys=True, separators=(",", ":")).encode()
    out["receipt_sha256"] = hashlib.sha256(canonical_bytes).hexdigest()

    if args.self_test:
        assert contract["policy"]["transport_or_parser_failure_is_not_economic_failure"] is True
        assert contract["policy"]["derived_lineage_cannot_replace_original_baseline"] is True
        assert queue["policy"]["exact_original_parent_required"] is True
        assert queue["policy"]["generic_generated_executable_cannot_close_retest"] is True
        assert set(NON_TREND).issubset(strategies)
        assert "trend_rider" in strategies
        print(json.dumps({"state": state, "transport_failure": transport_failed, "defect_count": len(defects), "defects": defects}, sort_keys=True))
        return 0 if not defects else 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "out": str(out_path), "transport_failure": transport_failed}, sort_keys=True))
    return 0 if not defects else 2


if __name__ == "__main__":
    raise SystemExit(main())
