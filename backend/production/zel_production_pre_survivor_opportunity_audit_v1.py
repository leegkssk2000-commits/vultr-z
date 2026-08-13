from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_ai_admission_executor_v2 as executor_v2
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_pre_survivor_opportunity_audit.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_opportunity_audit_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_opportunity_audit_v1.json")


def safety() -> dict[str, Any]:
    return {"selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "action": "hold"}


def guard(row: Mapping[str, Any], label: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}_AUTHORITY_DRIFT")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED" or row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_EXECUTION_DRIFT")


def validate_policy(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("schema_version") != POLICY_SCHEMA or str(row.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_OPPORTUNITY_AUDIT_POLICY_INVALID")
    for key in ("history_path", "challenger_evidence_path", "output_path"):
        if not str(row.get(key) or ""):
            raise RuntimeError(f"PRE_SURVIVOR_OPPORTUNITY_AUDIT_PATH_MISSING:{key}")
    guard(row, "PRE_SURVIVOR_OPPORTUNITY_AUDIT_POLICY")
    if row.get("source_code_mutation_allowed") is not False or row.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_OPPORTUNITY_AUDIT_MUTATION_FORBIDDEN")
    return dict(row)


def pair_ready(rows: Sequence[Mapping[str, Any]]) -> int:
    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol") or ""), []).append(row)
    total = 0
    for xs in by_symbol.values():
        xs = sorted(xs, key=lambda x: (int(x.get("observed_at_ms") or 0), int(x.get("outcome_candle_ts_ms") or 0)))
        for cur, _ in zip(xs, xs[1:]):
            side = int(cur.get("signal_side") or cur.get("primary_imbalance_sign") or 0)
            total += int(cur.get("context_pass") is True and side != 0)
    return total


def diagnose(observations: int, snapshots: int, signals: int, ready: int, trades: int) -> str:
    if observations == 0: return "NO_OBSERVATIONS"
    if snapshots < 2: return "PRIMING_ONLY"
    if signals == 0: return "NO_CONTEXT_TRIGGER"
    if ready == 0: return "SIGNALS_WAITING_OUTCOME"
    if trades < ready: return "ECONOMIC_CAPTURE_LAG"
    return "HEALTHY_ACCUMULATING"


def audit_tick(policy: Mapping[str, Any], *, history: Sequence[Mapping[str, Any]], evidence: Mapping[str, Any] | None, now_ms: int | None = None) -> dict[str, Any]:
    validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(evidence, Mapping):
        out = {"schema_version": SCHEMA, "state": "HOLD_PRE_SURVIVOR_OPPORTUNITY_EVIDENCE_MISSING", "contracts": [], "updated_at_ms": now, **safety()}; out["receipt_sha256"] = stable_sha(out); return out
    guard(evidence, "PRE_SURVIVOR_OPPORTUNITY_EVIDENCE")
    audits = []
    for ev in evidence.get("challengers") or []:
        if not isinstance(ev, Mapping): continue
        cid = str(ev.get("contract_id") or "")
        rows = [dict(x) for x in history if isinstance(x, Mapping) and str(x.get("contract_id") or "") == cid]
        times = {int(x.get("observed_at_ms") or 0) for x in rows if int(x.get("observed_at_ms") or 0) > 0}
        signals = sum(int(x.get("signal_side") or x.get("primary_imbalance_sign") or 0) != 0 for x in rows)
        ready = pair_ready(rows)
        trades = int(ev.get("trade_count") or 0)
        latest = max(times) if times else 0
        row = {"family_id": str(ev.get("family_id") or ""), "contract_id": cid, "template_id": str(ev.get("template_id") or ""), "observation_count": len(rows), "unique_snapshot_count": len(times), "context_pass_count": sum(x.get("context_pass") is True for x in rows), "signal_count": signals, "pair_ready_count": ready, "economic_trade_count": trades, "economic_capture_gap": max(0, ready - trades), "observation_age_ms": max(0, now - latest) if latest else None, "diagnosis": diagnose(len(rows), len(times), signals, ready, trades), **safety()}
        row["receipt_sha256"] = stable_sha(row); audits.append(row)
    counts: dict[str, int] = {}
    for row in audits: counts[row["diagnosis"]] = counts.get(row["diagnosis"], 0) + 1
    gap = any(row["diagnosis"] in {"NO_OBSERVATIONS", "ECONOMIC_CAPTURE_LAG"} for row in audits)
    out = {"schema_version": SCHEMA, "state": "HOLD_PRE_SURVIVOR_OPPORTUNITY_PIPELINE_GAP" if gap else "PASS_PRE_SURVIVOR_OPPORTUNITY_AUDIT", "contract_count": len(audits), "diagnosis_counts": counts, "pipeline_gap_detected": gap, "contracts": audits, "updated_at_ms": now, **safety()}
    out["receipt_sha256"] = stable_sha(out); return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY); ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text()))
    row = audit_tick(cfg, history=executor_v2.read_history(Path(str(cfg["history_path"]))), evidence=read_json(Path(str(cfg["challenger_evidence_path"]))))
    atomic_json_write(Path(str(cfg["output_path"])), row)
    print(json.dumps({"state": row["state"], "diagnosis_counts": row["diagnosis_counts"], "pipeline_gap_detected": row["pipeline_gap_detected"], "receipt_sha256": row["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
