#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
SCHEMA = "zel.a1_finalist_fresh_growth.v1"
TARGETS = (
    "supertrend_pullback",
    "trend_ma_macd",
    "keltner_trend",
    "break_and_continue",
)
MIN_HARDENING_TRADES = 25
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


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _number(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    metrics = row.get("metrics")
    if isinstance(metrics, Mapping) and isinstance(metrics.get(key), (int, float)):
        return float(metrics[key])
    return None


def _authority_defects(row: Mapping[str, Any]) -> list[str]:
    expected = {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    defects: list[str] = []
    for key, value in expected.items():
        if key in row and row.get(key) != value:
            defects.append(f"{key}:{row.get(key)}!={value}")
    return defects


def _classify(*, trades: int, integrity_ok: bool, technical_ok: bool) -> str:
    if not technical_ok:
        return "HOLD_FINALIST_REPLAY_TECHNICAL"
    if not integrity_ok:
        return "HOLD_FINALIST_REPLAY_INTEGRITY"
    if trades >= MIN_HARDENING_TRADES:
        return "READY_FINALIST_H4_H5_SAMPLE"
    return "WAIT_FINALIST_FRESH_GROWTH_25"


def run(output: Path) -> dict[str, Any]:
    ledger = _read(LEDGER)
    strategies = ledger.get("strategies") or {}
    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="a1-finalist-fresh-growth-") as td:
        work = Path(td)
        for sid in TARGETS:
            base = strategies.get(sid)
            if not isinstance(base, Mapping):
                rows.append({
                    "strategy_id": sid,
                    "state": "HOLD_FINALIST_LEDGER_TARGET_MISSING",
                    "technical_ok": False,
                })
                continue

            baseline_status = str(base.get("status") or "")
            baseline_trades = int(base.get("completed_trades") or 0)
            baseline_boundary = str(base.get("prospective_boundary_utc") or "")
            receipt_path = work / f"{sid}.json"
            cmd = [
                sys.executable,
                "-m",
                "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
                "--strategy-id",
                sid,
                "--out",
                str(receipt_path),
                "--terminal-replay",
            ]
            cp = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            technical_ok = cp.returncode == 0 and receipt_path.is_file()
            if not technical_ok:
                rows.append({
                    "strategy_id": sid,
                    "state": "HOLD_FINALIST_REPLAY_TECHNICAL",
                    "baseline_status": baseline_status,
                    "baseline_completed_trades": baseline_trades,
                    "prospective_boundary_utc": baseline_boundary,
                    "technical_ok": False,
                    "error": (cp.stderr or cp.stdout)[-1200:],
                })
                continue

            receipt = _read(receipt_path)
            completed = int(receipt.get("completed_trades") or 0)
            receipt_boundary = str(receipt.get("prospective_boundary_utc") or baseline_boundary)
            boundary_preserved = bool(baseline_boundary and receipt_boundary == baseline_boundary)
            strategy_match = str(receipt.get("strategy_id") or sid) == sid
            integrity_defects = list(receipt.get("integrity_defects") or [])
            lookahead = int(receipt.get("leakage_lookahead") or 0)
            auth_defects = _authority_defects(receipt)
            integrity_ok = bool(strategy_match and boundary_preserved and not integrity_defects and lookahead == 0 and not auth_defects)

            net_pnl = _number(receipt, "net_pnl_bps")
            net_exp = _number(receipt, "net_expectancy_bps")
            pf = _number(receipt, "profit_factor")
            economic_nonfail = bool(
                net_pnl is not None and net_pnl > 0
                and net_exp is not None and net_exp > 0
                and (pf is None or pf >= 1.0)
            )
            source_gate = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
            rows.append({
                "strategy_id": sid,
                "state": _classify(trades=completed, integrity_ok=integrity_ok, technical_ok=True),
                "baseline_status": baseline_status,
                "baseline_completed_trades": baseline_trades,
                "completed_trades": completed,
                "trade_growth_vs_terminal_receipt": completed - baseline_trades,
                "minimum_hardening_trades": MIN_HARDENING_TRADES,
                "sample_gap": max(0, MIN_HARDENING_TRADES - completed),
                "prospective_boundary_utc": receipt_boundary,
                "boundary_preserved": boundary_preserved,
                "strategy_identity_match": strategy_match,
                "technical_ok": True,
                "integrity_ok": integrity_ok,
                "integrity_defects": integrity_defects,
                "leakage_lookahead": lookahead,
                "authority_defects": auth_defects,
                "win_rate": _number(receipt, "win_rate"),
                "net_expectancy_bps": net_exp,
                "net_pnl_bps": net_pnl,
                "profit_factor": pf,
                "payoff": _number(receipt, "payoff"),
                "drawdown_bps": _number(receipt, "drawdown_bps"),
                "economic_nonfail": economic_nonfail,
                "source_quality_state": source_gate.get("state"),
                "replay_receipt_sha256": receipt.get("receipt_sha256") or receipt.get("receipt_sha"),
            })

    technical_holds = sum(1 for x in rows if not x.get("technical_ok"))
    integrity_holds = sum(1 for x in rows if x.get("technical_ok") and not x.get("integrity_ok"))
    ready = sum(1 for x in rows if int(x.get("completed_trades") or 0) >= MIN_HARDENING_TRADES and x.get("integrity_ok"))
    growth = sum(1 for x in rows if int(x.get("trade_growth_vs_terminal_receipt") or 0) > 0)
    if technical_holds:
        state = "HOLD_FINALIST_FRESH_GROWTH_TECHNICAL"
    elif integrity_holds:
        state = "HOLD_FINALIST_FRESH_GROWTH_INTEGRITY"
    elif ready:
        state = "PASS_FINALIST_H4_H5_SAMPLE_READY"
    else:
        state = "WAIT_FINALIST_FRESH_GROWTH_25"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "purpose": "Continue prospective evidence growth for parked positive-economics finalists without reopening terminal screening or mutating the canonical ledger.",
        "targets": rows,
        "target_count": len(TARGETS),
        "growth_target_count": growth,
        "ready_25_count": ready,
        "minimum_hardening_trades": MIN_HARDENING_TRADES,
        "sequential_heavy_evaluator": True,
        "terminal_replay_only": True,
        "canonical_ledger_mutation": False,
        "thresholds_changed": False,
        "strategy_parameters_changed": False,
        "next": "ROUTE_ONLY_SAMPLE_READY_TARGETS_TO_EXISTING_H4_H5_WITHOUT_PROMOTION" if ready else "CONTINUE_HOURLY_TERMINAL_REPLAY",
        **AUTH,
    }
    result["receipt_sha256"] = _sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert TARGETS == ("supertrend_pullback", "trend_ma_macd", "keltner_trend", "break_and_continue")
    assert MIN_HARDENING_TRADES == 25
    assert _classify(trades=24, integrity_ok=True, technical_ok=True) == "WAIT_FINALIST_FRESH_GROWTH_25"
    assert _classify(trades=25, integrity_ok=True, technical_ok=True) == "READY_FINALIST_H4_H5_SAMPLE"
    assert _classify(trades=25, integrity_ok=False, technical_ok=True) == "HOLD_FINALIST_REPLAY_INTEGRITY"
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_FINALIST_FRESH_GROWTH_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("out/a1_finalist_fresh_growth_latest.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "growth": result["growth_target_count"],
        "ready25": result["ready_25_count"],
        "targets": [
            {"id": x.get("strategy_id"), "trades": x.get("completed_trades"), "growth": x.get("trade_growth_vs_terminal_receipt"), "state": x.get("state")}
            for x in result["targets"]
        ],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
