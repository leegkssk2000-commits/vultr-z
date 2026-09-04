#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend/research/rebuild"

TOP5 = REBUILD / "a1_top5_latest_only_ssot_v1.json"
PROSPECTIVE = REBUILD / "a1_top5_replacement_child_prospective_v2_latest.json"
CLEAN_RUN = REBUILD / "g5_clean_runner_run_latest_v1.json"
FORWARD = REBUILD / "g5_forward_real_bridge_latest_v1.json"
BBO_STATE = REBUILD / "g5_trend_rider_bbo_oos_state_v1.json"
BBO_EVENTS = REBUILD / "g5_trend_rider_bbo_oos_events_v1.jsonl"

SCHEMA = "zel.g5.pipeline_watchdog.v1"
AUTHORITY = {
    "formal_credit": 0,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
}


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    v = json.loads(path.read_text(encoding="utf-8"))
    return v if isinstance(v, dict) else {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            v = json.loads(line)
            if isinstance(v, dict):
                out.append(v)
    return out


def iv(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def fv(v: Any) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def lane_funnel(lane: Mapping[str, Any]) -> dict[str, Any]:
    raw = iv(lane.get("raw_signal_T") or lane.get("raw_signal_count") or lane.get("signal_T"))
    eligible = iv(lane.get("eligible_T") or lane.get("eligible_count"))
    opened = iv(lane.get("open_T") or lane.get("opened_T") or lane.get("opened"))
    closed = iv(lane.get("closed_T") or lane.get("closed"))
    rejected = iv(lane.get("rejected_T") or lane.get("rejected"))
    metrics = lane.get("metrics") if isinstance(lane.get("metrics"), dict) else {}
    net = fv(metrics.get("net_pnl_bps") if metrics else lane.get("net_pnl_bps"))
    pf = fv(metrics.get("profit_factor") if metrics else lane.get("profit_factor"))
    if closed > 0:
        if net is not None and net <= 0:
            cls = "ECONOMIC_EVIDENCE_NEGATIVE"
        else:
            cls = "ECONOMIC_EVIDENCE_ACCUMULATING"
    elif opened > 0:
        cls = "OPEN_NOT_CLOSED"
    elif raw > 0 or eligible > 0 or rejected > 0:
        cls = "ENTRY_FILTER_OR_ADMISSION_BLOCK"
    else:
        cls = "SIGNAL_STARVATION"
    return {
        "raw_signal_T": raw,
        "eligible_T": eligible,
        "open_T": opened,
        "closed_T": closed,
        "rejected_T": rejected,
        "net_pnl_bps": net,
        "profit_factor": pf,
        "classification": cls,
    }


def build(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    top5 = load(TOP5)
    prospective = load(PROSPECTIVE)
    clean = load(CLEAN_RUN)
    forward = load(FORWARD)
    bbo_state = load(BBO_STATE)
    bbo_events = load_jsonl(BBO_EVENTS)

    lanes_src = prospective.get("lanes") if isinstance(prospective.get("lanes"), dict) else {}
    funnels = {k: lane_funnel(v) for k, v in lanes_src.items() if isinstance(v, dict)}

    evals = clean.get("evaluation_counts") if isinstance(clean.get("evaluation_counts"), dict) else {}
    life = clean.get("lifecycle_counts") if isinstance(clean.get("lifecycle_counts"), dict) else {}
    clean_signal = iv(evals.get("signal"))
    clean_new = iv(evals.get("new"))
    clean_no_signal = iv(evals.get("no_signal"))
    clean_cls = "SIGNAL_STARVATION" if clean_new > 0 and clean_signal == 0 and clean_no_signal == clean_new else "ACTIVE_SIGNAL_FLOW"

    prod_t = iv(forward.get("production_grade_T_total"))
    bridge_open = iv(forward.get("bridge_open_T"))
    if prod_t > 0:
        forward_cls = "PRODUCTION_GRADE_EVIDENCE_ACCUMULATING"
    elif bridge_open > 0:
        forward_cls = "OPEN_NOT_CLOSED"
    elif clean_signal == 0:
        forward_cls = "UPSTREAM_SIGNAL_STARVATION"
    else:
        forward_cls = "PROVENANCE_OR_WRITER_PATH_REVIEW_REQUIRED"

    bbo_confirmed = sum(1 for x in bbo_events if x.get("bbo_confirm") is True)
    bbo_rejected = sum(1 for x in bbo_events if x.get("bbo_confirm") is False)
    bbo_cls = "BBO_EVIDENCE_ACCUMULATING" if bbo_events else "BBO_CANDIDATE_SIGNAL_STARVATION"

    broad = {}
    lanes_top5 = top5.get("lanes") if isinstance(top5.get("lanes"), dict) else {}
    for key, value in lanes_top5.items():
        if "broad" in str(key).lower() and isinstance(value, dict):
            broad = value
            break

    blockers: list[str] = []
    if clean_cls == "SIGNAL_STARVATION":
        blockers.append("CLEAN_RUNNER_SIGNAL_STARVATION")
    for lane_id, f in funnels.items():
        if f["classification"] in {"SIGNAL_STARVATION", "ENTRY_FILTER_OR_ADMISSION_BLOCK", "ECONOMIC_EVIDENCE_NEGATIVE"}:
            blockers.append(f"{lane_id}:{f['classification']}")
    if bbo_cls == "BBO_CANDIDATE_SIGNAL_STARVATION":
        blockers.append("TRENDRIDER_BBO_CANDIDATE_SIGNAL_STARVATION")
    if forward_cls != "PRODUCTION_GRADE_EVIDENCE_ACCUMULATING":
        blockers.append(f"FORWARD_REAL:{forward_cls}")

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "state": "G5_BOTTLENECKS_PRESENT" if blockers else "G5_PIPELINE_FLOWING",
        "bottlenecks": blockers,
        "clean_runner": {
            "generated_at_utc": clean.get("generated_at_utc"),
            "new_evaluations": clean_new,
            "signal_T": clean_signal,
            "no_signal_T": clean_no_signal,
            "open_T": iv(life.get("opened")),
            "closed_T": iv(life.get("closed")),
            "ledger_written_T": iv(life.get("ledger_written")),
            "classification": clean_cls,
        },
        "replacement_lanes": funnels,
        "trendrider_bbo": {
            "activation_ms": iv(bbo_state.get("activation_ms")),
            "candidate_T": len(bbo_events),
            "confirmed_T": bbo_confirmed,
            "rejected_T": bbo_rejected,
            "classification": bbo_cls,
        },
        "forward_real": {
            "state": forward.get("state"),
            "bridge_open_T": bridge_open,
            "production_grade_T": prod_t,
            "classification": forward_cls,
        },
        "broad_control": {
            "terminal_fail_expected": True,
            "current_state": broad.get("state") or broad.get("g5_state") or broad.get("current_state"),
            "role": "FAILED_CONTROL_ONLY__DO_NOT_WAIT_OR_RETUNE",
        },
        "guards": {
            "historical_backfill": False,
            "strategy_retune": False,
            "rr_exit_mutation": False,
            "g6_advance": False,
        },
        **AUTHORITY,
    }
    receipt["receipt_sha256"] = stable(receipt)
    return receipt


def self_test() -> int:
    x = lane_funnel({"raw_signal_T": 0, "open_T": 0, "closed_T": 0})
    assert x["classification"] == "SIGNAL_STARVATION"
    x = lane_funnel({"raw_signal_T": 2, "open_T": 0, "closed_T": 0, "rejected_T": 2})
    assert x["classification"] == "ENTRY_FILTER_OR_ADMISSION_BLOCK"
    x = lane_funnel({"open_T": 1, "closed_T": 0})
    assert x["classification"] == "OPEN_NOT_CLOSED"
    x = lane_funnel({"closed_T": 2, "metrics": {"net_pnl_bps": -1.0, "profit_factor": 0.5}})
    assert x["classification"] == "ECONOMIC_EVIDENCE_NEGATIVE"
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="out/g5_pipeline_watchdog_latest_v1.json")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        return self_test()
    out = build()
    path = Path(a.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": out["state"], "bottlenecks": out["bottlenecks"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
