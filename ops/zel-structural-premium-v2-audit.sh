#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay
ENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py
LEGACY_CTRL=/tmp/zel_structural_premium_auto_improvement_v1.py
LEGACY_OVERLAY=/tmp/zel_structural_premium_overlay_patch_v1.py
CONTRACT=/tmp/zel_structural_premium_v2_contract.py
OUT=$ROOT/audit_v1

mkdir -p "$OUT"
for p in "$BASE/report.json" "$BASE/trades.jsonl.gz" "$ENG" "$LEGACY_CTRL" "$LEGACY_OVERLAY" "$CONTRACT"; do
  test -s "$p"
done

"$PY" "$CONTRACT" self-test
"$PY" "$CONTRACT" emit --output "$OUT/contract.json"

"$PY" - "$ENG" "$BASE/trades.jsonl.gz" "$LEGACY_CTRL" "$LEGACY_OVERLAY" "$OUT/audit.json" <<'PY'
import gzip
import importlib.util
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

eng_path, trades_path, ctrl_path, overlay_path, out_path = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("spv2_engine", eng_path)
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
assert spec.loader is not None
spec.loader.exec_module(engine)

rows = []
with gzip.open(trades_path, "rt", encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
if not rows:
    raise SystemExit("NO_TRADES")


def metrics(group):
    return engine.metrics(group)


def grouped(key, source):
    buckets = defaultdict(list)
    for row in source:
        buckets[str(row.get(key) or "UNKNOWN")].append(row)
    return {name: metrics(bucket) for name, bucket in sorted(buckets.items())}

strategy_rows = defaultdict(list)
for row in rows:
    strategy_rows[str(row.get("strategy_id") or "UNKNOWN")].append(row)

strategy_summary = {}
negative_abs_total = 0.0
for name, bucket in strategy_rows.items():
    m = metrics(bucket)
    net = float(m.get("net_R") or 0.0)
    if net < 0:
        negative_abs_total += abs(net)
    strategy_summary[name] = {
        "metrics": m,
        "trade_share": len(bucket) / len(rows),
        "by_window": grouped("window_id", bucket),
        "by_side": grouped("side", bucket),
        "by_regime": grouped("regime", bucket),
    }

for name, node in strategy_summary.items():
    net = float(node["metrics"].get("net_R") or 0.0)
    node["negative_loss_share"] = abs(net) / negative_abs_total if net < 0 and negative_abs_total > 0 else 0.0

worst_strategy = min(strategy_summary, key=lambda name: float(strategy_summary[name]["metrics"].get("net_R") or 0.0))
dominant_strategy = max(strategy_summary, key=lambda name: float(strategy_summary[name]["trade_share"]))

ctrl = ctrl_path.read_text()
overlay = overlay_path.read_text()
mandatory_vwap = bool(re.search(r'MAIN_OWNERS\s*=\s*\([^\n]*vwap_revert', ctrl)) and "if not all(name in owners for name in MAIN_OWNERS)" in ctrl
scalar_score_primary = "score = (" in ctrl and "0.010 * mean_win" in ctrl
legacy_axes = {
    "FREQUENCY": all(token in ctrl for token in ("min_confidence", "cooldown_min")),
    "COST_EXECUTION": all(token in ctrl for token in ("min_risk_distance_pct", "target_distance_mult")),
    "RISK_EXPOSURE": all(token in ctrl for token in ("stop_distance_mult", "max_hold_min")),
    "INTERACTION": "G{next_gen:02d}_INTERACTION" in ctrl,
    "PORTFOLIO": "enabled_entry_owners" in ctrl,
    "ROBUSTNESS": "G{next_gen:02d}_ROBUSTNESS" in ctrl,
}
real_axis_mechanisms = {
    "FREQUENCY": {
        "entry_regime_gate": "entry_regime" in overlay or "htf_bias" in overlay,
        "entry_session_gate": "session" in overlay,
        "setup_quality_gate": "min_confidence" in overlay,
        "cooldown": "cooldown_min" in overlay,
    },
    "COST_EXECUTION": {
        "fee_bps": "fee_bps" in overlay,
        "slippage_bps": "slippage_bps" in overlay,
        "latency_ms": "latency_ms" in overlay,
        "fill_model": "fill_model" in overlay or "fill_probability" in overlay,
    },
    "RISK_SIZING": {
        "position_size_pct": "position_size_pct" in overlay,
        "risk_per_trade_pct": "risk_per_trade_pct" in overlay,
        "leverage": "leverage" in overlay,
        "max_hold_min": "max_hold_min" in overlay,
    },
    "INTERACTION": {
        "conflict_policy": "conflict_policy" in overlay,
        "correlation_limit": "correlation" in overlay,
        "duplicate_exposure_guard": "duplicate_exposure" in overlay,
    },
    "PORTFOLIO": {
        "enabled_entry_owners": "enabled_entry_owners" in overlay,
        "strategy_weights": "strategy_weights" in overlay,
        "no_mandatory_owner": not mandatory_vwap,
    },
    "ROBUSTNESS": {
        "fresh_oos_windows": False,
        "parameter_neighborhood": False,
        "symbol_holdout": False,
        "regime_holdout": False,
    },
}
axis_truth = {
    axis: {
        "legacy_named_axis_present": legacy_axes[axis],
        "mechanisms": mechanisms,
        "real_mechanism_count": sum(1 for value in mechanisms.values() if value),
        "required_mechanism_count": len(mechanisms),
        "fully_implemented": all(mechanisms.values()),
    }
    for axis, mechanisms in real_axis_mechanisms.items()
}

entry_management_contract_risk = {
    "generic_long_scope_used": "def _zel_is_long" in overlay,
    "explicit_entry_action_scope_present": "def _zel_is_entry_action" in overlay,
    "cooldown_updates_on_generic_long": "if state is None and _zel_is_long(adjusted)" in overlay,
    "geometry_applies_after_generic_long": "if not _zel_is_long(result):" in overlay and "_zel_adjust_geometry" in overlay,
}
entry_management_contract_risk["contract_proven_safe"] = (
    entry_management_contract_risk["explicit_entry_action_scope_present"]
    and not entry_management_contract_risk["cooldown_updates_on_generic_long"]
)

consumed_windows = ["1m_w1", "1m_w2", "1m_w3"]

blockers = []
if mandatory_vwap:
    blockers.append("PORTFOLIO_CANNOT_DROP_VWAP")
if scalar_score_primary:
    blockers.append("LEGACY_OBJECTIVE_NOT_PNL_WR_HARD_GATE")
if not entry_management_contract_risk["contract_proven_safe"]:
    blockers.append("ENTRY_MANAGEMENT_CONTRACT_UNPROVEN")
for axis, node in axis_truth.items():
    if not node["fully_implemented"]:
        blockers.append(f"AXIS_NOT_REAL:{axis}")
blockers.append("W1_W2_W3_ALREADY_CONSUMED_FOR_ITERATION")

result = {
    "schema_version": "zel.structural_premium.v2.audit.v1",
    "state": "HARD_PAUSE_LEGACY_AUTO_IMPROVEMENT" if blockers else "PASS_V2_READY",
    "dataset": {
        "total_trades": len(rows),
        "strategy_count": len(strategy_summary),
        "strategies": strategy_summary,
        "dominant_trade_owner": dominant_strategy,
        "dominant_trade_share": strategy_summary[dominant_strategy]["trade_share"],
        "worst_net_owner": worst_strategy,
        "worst_net_R": strategy_summary[worst_strategy]["metrics"].get("net_R"),
        "worst_negative_loss_share": strategy_summary[worst_strategy]["negative_loss_share"],
    },
    "legacy_controller": {
        "mandatory_vwap": mandatory_vwap,
        "scalar_score_primary": scalar_score_primary,
        "objective_alignment_with_v2": not scalar_score_primary,
    },
    "axis_truth": axis_truth,
    "entry_management_contract": entry_management_contract_risk,
    "oos": {
        "consumed_windows": consumed_windows,
        "fresh_final_oos_required": True,
        "reuse_w1_w2_w3_as_final_oos_forbidden": True,
    },
    "blockers": blockers,
    "next": [
        "FREEZE_LEGACY_CONTROLLER",
        "PROVE_REPLAY_ENTRY_EXIT_CAUSAL_CONTRACT",
        "IMPLEMENT_TRUE_AXIS_MECHANISMS",
        "ALLOW_ANY_STRATEGY_DROP_OR_REWEIGHT",
        "USE_PNL_AND_WR_AS_PRIMARY_HARD_GATES",
        "CREATE_FRESH_OOS_WINDOWS_AFTER_SELECTION",
    ],
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "action": "hold",
}
out_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")

print("STATE", result["state"])
print("TOTAL_TRADES", result["dataset"]["total_trades"])
print("DOMINANT", dominant_strategy, result["dataset"]["dominant_trade_share"])
print("WORST", worst_strategy, result["dataset"]["worst_net_R"], result["dataset"]["worst_negative_loss_share"])
print("MANDATORY_VWAP", mandatory_vwap)
print("LEGACY_SCALAR_SCORE", scalar_score_primary)
print("ENTRY_CONTRACT_SAFE", entry_management_contract_risk["contract_proven_safe"])
for axis, node in axis_truth.items():
    print("AXIS", axis, node["real_mechanism_count"], "/", node["required_mechanism_count"], "FULL", node["fully_implemented"])
print("BLOCKERS", json.dumps(blockers, sort_keys=True))
PY

cat "$OUT/audit.json"
