#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_START' \
  'MODE=READ_ONLY_15_REPRESENTATIVE_SCENARIO_FULL_EXCEPTION_DIAGNOSE' \
  'PROBE_ARCHITECTURE_COUNT=3' \
  'PROBE_SYMBOL_COUNT=5' \
  'PROBE_SCENARIO_TARGET_COUNT=15' \
  'FULL_110_REEXECUTION_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'DISTANCE_THRESHOLD_RELAXATION_ALLOWED=false' \
  'SOURCE_FILE_MUTATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json" \
  "$ROOT/runtime/r7a4d2_short_scalp_timeframe_candidate_discovery_36/candidate_discovery_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-scalp-discovery-causality.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_candidate_trace_patch.py \
  tools/r7a4d2_short_discovery_trace_only_patch.py \
  tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py \
  tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

python3 "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  --input "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --output "$TMP/tools/runner_entry.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  --input "$TMP/tools/runner_entry.py" \
  --output "$TMP/tools/runner_short.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  --input "$TMP/tools/runner_short.py" \
  --output "$TMP/tools/runner_rr_linear.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  --input "$TMP/tools/runner_rr_linear.py" \
  --output "$TMP/tools/runner_rr.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  --input "$TMP/tools/runner_rr.py" \
  --output "$TMP/tools/runner_trace.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  --input "$TMP/tools/runner_trace.py" \
  --output "$TMP/tools/runner_discovery.py" || exit 2

if ! python3 -m py_compile \
  "$TMP/tools/runner_discovery.py" \
  "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py" \
  "$TMP/tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 - "$ROOT" "$TMP" <<'PY'
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

root = Path(sys.argv[1]).resolve()
tmp = Path(sys.argv[2]).resolve()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

runner = load_module(tmp / "tools/runner_discovery.py", "r7a4d2_probe_runner")
adapter = load_module(tmp / "tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py", "r7a4d2_probe_adapter")
discovery = load_module(tmp / "tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py", "r7a4d2_probe_discovery")
contract = load_json(tmp / "backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json")
bind_path = root / "runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json"
prior_path = root / "runtime/r7a4d2_short_scalp_timeframe_candidate_discovery_36/candidate_discovery_v1.json"
registry_path = root / str(contract["registry_path"])
bind = load_json(bind_path)
prior = load_json(prior_path)
registry = load_json(registry_path)

blockers = []
if int(prior.get("failure_count", -1)) != 110:
    blockers.append(f"PRIOR_FAILURE_COUNT_UNEXPECTED:{prior.get('failure_count')}:110")
if int(prior.get("selected_candidate_count", -1)) != 0:
    blockers.append(f"PRIOR_SELECTED_COUNT_UNEXPECTED:{prior.get('selected_candidate_count')}:0")

allowlist = discovery.validate_bind(bind)
entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
scalp_entry = entries.get("scalp_snap")
if not isinstance(scalp_entry, dict):
    raise ValueError("SCALP_SNAP_REGISTRY_ENTRY_MISSING")
engine = scalp_entry.get("canonical_engine") if isinstance(scalp_entry.get("canonical_engine"), dict) else {}
implementation_path = str(engine.get("implementation_path") or "")
implementation = root / runner.safe_repo_path(implementation_path)
expected_source_sha = str(engine.get("source_sha256") or "")
if not expected_source_sha or runner.sha256_file(implementation) != expected_source_sha:
    raise ValueError("SCALP_SNAP_SOURCE_REGISTRY_SHA_MISMATCH")

frames = {}
protected = [bind_path, prior_path, registry_path, implementation]
for row in allowlist:
    path = root / adapter.safe_repo_path(str(row["source_path"]))
    protected.append(path)
    frame_1m = adapter.load_audited_market_frame(path, str(row["source_sha256"]))
    frames[str(row["symbol"])] = {
        5: adapter.resample_complete_bars(frame_1m, 5),
        15: adapter.resample_complete_bars(frame_1m, 15),
    }

before = runner.snapshot(protected)
sys.path.insert(0, str(root))
side_effect_attempts = []
probes = []
try:
    strategy_module = runner.load_module(root, runner.safe_repo_path(implementation_path), "scalp_snap_failure_probe")
    owner, method_name = runner.resolve_callable(strategy_module, str(engine.get("callable") or ""))
    costs = {str(row.get("id")): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row.get("id")): row for row in contract.get("perturbations", []) if isinstance(row, dict)}
    cost = costs.get("cost_profile_0")
    perturbation = perturbations.get("perturbation_0")
    if not isinstance(cost, dict) or not isinstance(perturbation, dict):
        raise ValueError("BASELINE_COST_OR_PERTURBATION_MISSING")
    probe_contract = dict(contract)
    probe_contract.update({
        "indicator_preroll_bars": discovery.PREROLL_BARS,
        "segment_bars": discovery.EVALUATION_BARS,
        "short_execution_enabled": True,
        "short_target_strategy_ids": ["scalp_snap"],
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })
    with runner.side_effect_guard(side_effect_attempts):
        for architecture_id, structure_minutes, trigger_minutes in discovery.ARCHITECTURES:
            for symbol in sorted(frames):
                trigger = frames[symbol][trigger_minutes]
                starts = discovery.window_starts(len(trigger))
                if not starts:
                    probes.append({
                        "architecture_id": architecture_id,
                        "symbol": symbol,
                        "status": "failed",
                        "exception_type": "ValueError",
                        "error": "WINDOW_START_UNAVAILABLE",
                        "traceback_tail": [],
                    })
                    continue
                start = starts[0]
                sample = trigger.iloc[start:start + discovery.WINDOW_BARS].reset_index(drop=True)
                scenario_id = f"{architecture_id}:{symbol}:{start}:causality_probe"
                scenario = {
                    "scenario_id": scenario_id,
                    "strategy_id": "scalp_snap",
                    "segment_id": scenario_id,
                    "regime": "trend_down",
                    "cost_profile": str(cost.get("id") or "cost_profile_0"),
                    "perturbation": str(perturbation.get("id") or "perturbation_0"),
                }
                try:
                    result = runner.simulate_scenario(
                        scenario,
                        sample,
                        owner,
                        method_name,
                        cost,
                        perturbation,
                        probe_contract,
                    )
                    traces = [row for row in result.get("short_candidate_trace", []) if isinstance(row, dict)]
                    probes.append({
                        "architecture_id": architecture_id,
                        "symbol": symbol,
                        "status": "success",
                        "trace_count": len(traces),
                        "trade_count": len(result.get("trade_sample", [])) if isinstance(result.get("trade_sample"), list) else 0,
                    })
                except Exception as exc:
                    tb = traceback.format_exc().strip().splitlines()
                    probes.append({
                        "architecture_id": architecture_id,
                        "symbol": symbol,
                        "status": "failed",
                        "exception_type": type(exc).__name__,
                        "error": str(exc),
                        "exception_signature": f"{type(exc).__name__}:{exc}",
                        "traceback_tail": tb[-12:],
                    })
finally:
    try:
        sys.path.remove(str(root))
    except ValueError:
        pass

after = runner.snapshot(protected)
mutations = sorted(path for path in before if before[path] != after[path])
failed = [row for row in probes if row.get("status") == "failed"]
succeeded = [row for row in probes if row.get("status") == "success"]
signature_histogram = Counter(str(row.get("exception_signature") or row.get("error") or "") for row in failed)
exception_type_histogram = Counter(str(row.get("exception_type") or "") for row in failed)
architecture_failure_histogram = Counter(str(row.get("architecture_id") or "") for row in failed)
symbol_failure_histogram = Counter(str(row.get("symbol") or "") for row in failed)
primary_signature = signature_histogram.most_common(1)[0][0] if signature_histogram else ""
primary_count = signature_histogram.most_common(1)[0][1] if signature_histogram else 0
single_cause = len(probes) == 15 and len(failed) == 15 and len(signature_histogram) == 1

if side_effect_attempts:
    blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
if mutations:
    blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
if len(probes) != 15:
    blockers.append(f"PROBE_COUNT_INVALID:{len(probes)}:15")
if not failed:
    blockers.append("REPRESENTATIVE_FAILURE_NOT_REPRODUCED")

state = "PASS_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE" if not blockers else "HOLD_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_INPUT"
if not blockers and single_cause:
    classification = "SINGLE_COMMON_RUNNER_FAILURE"
    next_stage = "R7.A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_RUNNER_MINIMAL_PATCH_PLAN"
elif not blockers:
    classification = "MIXED_OR_PARTIAL_FAILURE"
    next_stage = "R7.A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_SUBCAUSE_DIAGNOSE"
else:
    classification = "DIAGNOSE_INPUT_INVALID"
    next_stage = "R7.A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE"

result = {
    "schema": "r7a4d2_short_scalp_timeframe_discovery_failure_causality_diagnose_v1",
    "official_stage": "R7.A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE",
    "state": state,
    "blocker_count": len(blockers),
    "blockers": blockers,
    "prior_failure_count": prior.get("failure_count"),
    "probe_target_count": 15,
    "probe_count": len(probes),
    "probe_failure_count": len(failed),
    "probe_success_count": len(succeeded),
    "single_common_cause": single_cause,
    "classification": classification,
    "primary_exception_signature": primary_signature,
    "primary_exception_count": primary_count,
    "exception_signature_histogram": dict(sorted(signature_histogram.items())),
    "exception_type_histogram": dict(sorted(exception_type_histogram.items())),
    "architecture_failure_histogram": dict(sorted(architecture_failure_histogram.items())),
    "symbol_failure_histogram": dict(sorted(symbol_failure_histogram.items())),
    "probe_results": probes,
    "side_effect_attempt_count": len(side_effect_attempts),
    "protected_mutation_path_count": len(mutations),
    "protected_mutation_paths": mutations,
    "strategy_mutation_allowed": False,
    "registry_mutation_allowed": False,
    "shadow_start_allowed": False,
    "paper_live_order_allowed": False,
    "next_stage": next_stage,
}
output = root / "runtime/r7a4d2_short_scalp_timeframe_discovery_failure_causality_diagnose/causality_diagnose_v1.json"
output.parent.mkdir(parents=True, exist_ok=True)
temporary = output.with_suffix(".tmp")
temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
temporary.replace(output)

print("STATE=" + state)
print("BLOCKER_COUNT=" + str(len(blockers)))
print("PRIOR_FAILURE_COUNT=" + str(prior.get("failure_count")))
print("PROBE_TARGET_COUNT=15")
print("PROBE_COUNT=" + str(len(probes)))
print("PROBE_FAILURE_COUNT=" + str(len(failed)))
print("PROBE_SUCCESS_COUNT=" + str(len(succeeded)))
print("SINGLE_COMMON_CAUSE=" + str(single_cause).lower())
print("CLASSIFICATION=" + classification)
print("PRIMARY_EXCEPTION_SIGNATURE=" + json.dumps(primary_signature, ensure_ascii=False))
print("PRIMARY_EXCEPTION_COUNT=" + str(primary_count))
print("EXCEPTION_SIGNATURE_HISTOGRAM=" + json.dumps(dict(sorted(signature_histogram.items())), ensure_ascii=False, sort_keys=True))
print("EXCEPTION_TYPE_HISTOGRAM=" + json.dumps(dict(sorted(exception_type_histogram.items())), sort_keys=True))
print("ARCHITECTURE_FAILURE_HISTOGRAM=" + json.dumps(dict(sorted(architecture_failure_histogram.items())), sort_keys=True))
print("SYMBOL_FAILURE_HISTOGRAM=" + json.dumps(dict(sorted(symbol_failure_histogram.items())), sort_keys=True))
print("PROBE_RESULTS=" + json.dumps(probes, ensure_ascii=False, sort_keys=True))
print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutations)))
print("DIAGNOSE_JSON=" + str(output))
print("NEXT_STAGE=" + next_stage)
print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
print("RC=" + ("0" if not blockers else "2"))
raise SystemExit(0 if not blockers else 2)
PY
RC=$?

echo 'R7A4D2_SHORT_SCALP_TIMEFRAME_DISCOVERY_FAILURE_CAUSALITY_DIAGNOSE_COMPLETE'
echo "RC=$RC"
exit "$RC"
