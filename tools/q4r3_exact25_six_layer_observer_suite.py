from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.q4r3_exact25_six_layer_observer_core import (
    SEV, atomic_json, atomic_jsonl, cost_layer, funnel_layer, load_json,
    now_iso, outcome_layer, owners, problem, read_jsonl, validate,
)
from tools.q4r3_exact25_six_layer_analytics import market_layer, portfolio_layer, replay_layer


def violations(path: Path, issues: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stable = sorted((str(item.get("code")), str(item.get("severity")), str(item.get("metric")), str(item.get("detail"))) for item in issues); fingerprint = hashlib.sha256(json.dumps(stable, separators=(",", ":")).encode()).hexdigest() if stable else None; prior = load_json(path, True); severity = max((str(item.get("severity") or "m") for item in issues), key=lambda value: SEV.get(value, 0), default=None); notify = bool(issues) and (prior.get("fingerprint") != fingerprint or SEV.get(severity, 0) > SEV.get(prior.get("severity"), 0))
    return {"schema": "q4r3_exact25_six_layer_observer_violations_v1", "generated_at": now_iso(), "state": "VIOLATION" if issues else "CLEAR", "severity": severity, "notify": notify, "fingerprint": fingerprint, "count": len(issues), "violations": list(issues), "action": "hold"}


def run(args: argparse.Namespace) -> int:
    ssot, manifest = load_json(args.ssot), load_json(args.manifest); producer_status = load_json(args.producer_status); producer_state = load_json(args.producer_state, True); open_positions = load_json(args.open_positions, True); context_status = load_json(args.context_status, True)
    rows, ledger_hash, issues = read_jsonl(args.ledger); contexts, context_hash, context_issues = read_jsonl(args.context_ledger, True); issues.extend(context_issues)
    if context_status and (context_status.get("state") != "RUNNING" or int(context_status.get("error_count") or 0) > 0): issues.append(problem("MARKET_CONTEXT_COLLECTOR_DEGRADED", "M", f"state={context_status.get('state')}:errors={context_status.get('error_count')}", "market_context"))
    for item in contexts:
        if item.get("epoch_id") != ssot.get("expected_epoch") or item.get("measurement_namespace") != ssot.get("expected_namespace"): issues.append(problem("CONTEXT_IDENTITY_MISMATCH", "M", str(item.get("snapshot_id") or "unknown"), "market_context"))
        if item.get("observer_only") is not True or any(item.get(key) is not False for key in ("paper_enabled", "live_enabled", "order_enabled")): issues.append(problem("UNSAFE_CONTEXT_SNAPSHOT", "C", str(item.get("snapshot_id") or "unknown"), "market_context"))
    owner_map = owners(manifest, int(ssot.get("expected_strategy_count") or 25)); issues.extend(validate(rows, owner_map, ssot)); cfg = ssot.get("outcome_contract") if isinstance(ssot.get("outcome_contract"), Mapping) else {}
    projections, outcome, outcome_issues = outcome_layer(rows, cfg); issues.extend(outcome_issues); projection_hash = atomic_jsonl(args.projection, projections); outcome.update({"projection_path": str(args.projection.resolve()), "projection_sha256": projection_hash})
    funnel, funnel_issues = funnel_layer(rows, owner_map, producer_status, producer_state, open_positions); issues.extend(funnel_issues); cost = cost_layer(rows, cfg); market = market_layer(rows, contexts, ssot, context_status); portfolio = portfolio_layer(rows, ssot)
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); ssot_hash = hashlib.sha256(json.dumps(ssot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); replay = replay_layer(rows, ssot, {"formal_ledger_sha256": ledger_hash, "outcome_projection_sha256": projection_hash, "market_context_ledger_sha256": context_hash, "manifest_sha256": manifest_hash, "ssot_sha256": ssot_hash})
    outputs = [(args.outcome_report, outcome), (args.funnel_report, funnel), (args.cost_exit_report, cost), (args.market_report, market), (args.portfolio_report, portfolio), (args.replay_report, replay)]
    for path, payload in outputs:
        payload.update({"epoch_id": ssot.get("expected_epoch"), "measurement_namespace": ssot.get("expected_namespace"), "paper_enabled": False, "live_enabled": False, "order_enabled": False, "historical_backfill_allowed": False}); atomic_json(path, payload)
    violation = violations(args.violations, issues); atomic_json(args.violations, violation)
    status = {"schema": "q4r3_exact25_six_layer_observer_suite_status_v1", "generated_at": now_iso(), "state": "VIOLATION" if issues else "HEALTHY", "action": "hold", "epoch_id": ssot.get("expected_epoch"), "measurement_namespace": ssot.get("expected_namespace"), "formal_ledger_row_count": len(rows), "context_snapshot_count": len(contexts), "installed_layers": ["OUTCOME_CONTRACT_V1", "STRATEGY_FUNNEL_DEAD_ROUTE_OBSERVER", "COST_EXIT_EFFICIENCY_CUBE", "MARKET_CONTEXT_REGIME_OBSERVER", "PORTFOLIO_INTERACTION_OBSERVER", "REPLAY_ABLATION_STRATEGY_LAB"], "layer_count": 6, "outcome_core_complete_count": outcome.get("core_complete_count"), "outcome_full_complete_count": outcome.get("full_complete_count"), "funnel_verdict": funnel.get("verdict"), "context_joined_count": market.get("entry_context_joined_count"), "portfolio_pair_count": portfolio.get("pair_count"), "replay_minimum_sample_met": replay.get("minimum_replay_sample_met"), "violation_count": len(issues), "violation_severity": violation.get("severity"), "violation_notify": violation.get("notify"), "violation_fingerprint": violation.get("fingerprint"), "formal_ledger_mutated": False, "strategy_modified": False, "producer_modified": False, "writer_modified": False, "filter_enabled": False, "comparison_decision_enabled": False, "promotion_enabled": False, "paper_enabled": False, "live_enabled": False, "order_enabled": False, "historical_backfill_allowed": False, "order_authority": "blocked", "execution_authority": "none", "outputs": {path.name: str(path.resolve()) for path, _ in outputs}}
    atomic_json(args.status, status); print(json.dumps(status, ensure_ascii=False, sort_keys=True)); return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in ("ledger", "manifest", "producer-status", "producer-state", "open-positions", "context-ledger", "context-status", "ssot", "projection", "outcome-report", "funnel-report", "cost-exit-report", "market-report", "portfolio-report", "replay-report", "status", "violations"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
