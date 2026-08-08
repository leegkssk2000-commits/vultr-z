#!/usr/bin/env bash
set -euo pipefail
OLD=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2
SRC=/opt/zel/research-runtime/jobs/structural-premium-targeted-fix-v2
NEW=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1
PY=/home/z/z/.venv/bin/python
CANON=/opt/zel/forward-expansion-v1/source

for p in "$OLD/work/engine/replay_v1.py" "$OLD/work/engine/replay_v2.py" "$OLD/work/evaluate.py" "$OLD/work/data/manifest.json"; do test -s "$p"; done
test -d "$SRC/work/replay/lane_checkpoints"
test -d "$SRC/work/source"

CANON_SR=$(sha256sum "$CANON/backend/strategies/sr_levels.py" | awk '{print $1}')
CANON_TR=$(sha256sum "$CANON/backend/strategies/trend_rider.py" | awk '{print $1}')
CANON_MAN=$(sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" | awk '{print $1}')
CANON_BIND=$(sha256sum "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json" | awk '{print $1}')

if [ -s "$SRC/runner.pid" ]; then
  RP=$(cat "$SRC/runner.pid" || true)
  if [ -n "${RP:-}" ] && kill -0 "$RP" 2>/dev/null; then kill -TERM "$RP" || true; fi
fi
PIDS=$(pgrep -f 'lane_checkpoint_v2.py.*structural-premium-targeted-fix-v2|replay_v2.py.*structural-premium-targeted-fix-v2' || true)
if [ -n "$PIDS" ]; then kill -TERM $PIDS || true; fi
sleep 2
PIDS=$(pgrep -f 'lane_checkpoint_v2.py.*structural-premium-targeted-fix-v2|replay_v2.py.*structural-premium-targeted-fix-v2' || true)
if [ -n "$PIDS" ]; then kill -KILL $PIDS || true; fi
sleep 1
if pgrep -f 'lane_checkpoint_v2.py.*structural-premium-targeted-fix-v2|replay_v2.py.*structural-premium-targeted-fix-v2' >/dev/null; then echo TARGETED_RUNNER_STILL_ALIVE; exit 61; fi

rm -rf "$NEW"
mkdir -p "$NEW/work/replay/lane_checkpoints" "$NEW/work/engine" "$NEW/result" "$NEW/logs"
cp -a "$SRC/work/source" "$NEW/work/source"
cp "$OLD/work/engine/replay_v1.py" "$NEW/work/engine/replay_v1_no_trend.py"
cp "$OLD/work/engine/replay_v2.py" "$NEW/work/engine/replay_v2.py"
cp "$OLD/work/evaluate.py" "$NEW/work/evaluate.py"

cat >> "$NEW/work/engine/replay_v1_no_trend.py" <<'PYOVR'

_z_original_restore_structural_premium_registry = _restore_structural_premium_registry
def _restore_structural_premium_registry(source_root, registry):
    restored = dict(_z_original_restore_structural_premium_registry(source_root, registry))
    restored.pop("trend_rider", None)
    expected = {"vwap_revert", "support_resistance", "liquidity_sweep"}
    if set(restored) != expected:
        raise RuntimeError(f"NO_TREND_RESTORED_REGISTRY_MISMATCH:{sorted(restored)}")
    return restored
PYOVR

# replay_v2 has a structural-premium cardinality assertion fixed at four owners.
# This is a research-copy-only contract adaptation; canonical engine is untouched.
"$PY" - "$NEW/work/engine/replay_v2.py" <<'PYPATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1]); t=p.read_text()
old='if len(registry) != 4:'
if t.count(old) != 1:
    raise SystemExit(f'REGISTRY_CARDINALITY_ANCHOR_COUNT:{t.count(old)}')
p.write_text(t.replace(old,'if len(registry) != 3:',1))
print('PASS_REPLAY_V2_THREE_OWNER_CONTRACT')
PYPATCH

for s in liquidity_sweep vwap_revert support_resistance; do
  test -d "$SRC/work/replay/lane_checkpoints/$s"
  mkdir -p "$NEW/work/replay/lane_checkpoints/$s"
  cp "$SRC/work/replay/lane_checkpoints/$s"/*.json.gz "$NEW/work/replay/lane_checkpoints/$s/"
done

"$PY" - "$NEW/work/replay/lane_checkpoints" "$NEW/result/exclusion_receipt.json" <<'PYCHK'
from pathlib import Path
import gzip,json,sys
root=Path(sys.argv[1]); out=Path(sys.argv[2])
expected={"liquidity_sweep":15,"vwap_revert":15,"support_resistance":15}
counts={}; errors=[]
for s,n in expected.items():
    files=sorted((root/s).glob("*.json.gz")); counts[s]=len(files)
    if len(files)!=n: errors.append(f"{s}:{len(files)}!={n}")
    seen=set()
    for f in files:
        with gzip.open(f,"rt",encoding="utf-8") as h: p=json.load(h)
        if p.get("strategy_id")!=s: errors.append(f"bad_strategy:{f.name}")
        key=(p.get("window_id"),p.get("symbol"),p.get("interval"))
        if key in seen: errors.append(f"duplicate:{s}:{key}")
        seen.add(key)
        if not isinstance(p.get("result"),dict): errors.append(f"bad_result:{f.name}")
payload={"state":"PASS_TREND_RIDER_EXCLUDED_45_LANES_READY" if not errors else "HOLD_NO_TREND_LANE_INTEGRITY","retained_strategies":sorted(expected),"excluded_strategies":["trend_rider"],"lane_counts":counts,"completed_lanes":sum(counts.values()),"expected_lanes":45,"errors":errors,"canonical_mutations":0,"execution_authority":"NONE","order_authority":"BLOCKED","action":"hold"}
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
print(json.dumps(payload,sort_keys=True))
if errors: raise SystemExit(62)
PYCHK

"$PY" "$NEW/work/engine/replay_v2.py" --engine-v1 "$NEW/work/engine/replay_v1_no_trend.py" --source-root "$NEW/work/source" --data-root "$OLD/work/data" --interval 1m --output-dir "$NEW/work/replay" --workers 4 2>&1 | tee "$NEW/logs/aggregate.log"
test -s "$NEW/work/replay/report.json"
test -s "$NEW/work/replay/trades.jsonl.gz"

set +e
"$PY" "$NEW/work/evaluate.py" evaluate --report "$NEW/work/replay/report.json" --ledger "$NEW/work/replay/trades.jsonl.gz" --dataset-manifest "$OLD/work/data/manifest.json" --output "$NEW/result/coverage_revalidation.json" 2>&1 | tee "$NEW/logs/evaluate.log"
EVAL_RC=${PIPESTATUS[0]}
set -e

"$PY" - "$NEW/work/replay/report.json" "$NEW/result/coverage_revalidation.json" "$NEW/result/gate6_no_trend.json" "$EVAL_RC" <<'PYG6'
from pathlib import Path
import json,sys
r=json.loads(Path(sys.argv[1]).read_text())
cp=Path(sys.argv[2]); c=json.loads(cp.read_text()) if cp.exists() else {}
out=Path(sys.argv[3]); rc=int(sys.argv[4])
payload={"state":"PASS_GATE6_NO_TREND_INPUT_COMPLETE" if rc==0 else "HOLD_GATE6_EVALUATOR_CONTRACT","branch":"STRUCTURAL_PREMIUM_NO_TREND_V1","retained_strategies":["liquidity_sweep","support_resistance","vwap_revert"],"excluded_strategies":["trend_rider"],"lane_count":45,"report_state":r.get("state"),"coverage_state":c.get("state"),"coverage_restored":c.get("coverage_restored"),"selected_configuration":c.get("selected_configuration"),"survivor":c.get("survivor"),"evaluator_rc":rc,"execution_authority":"NONE","order_authority":"BLOCKED","action":"hold"}
out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
print(json.dumps(payload,sort_keys=True))
PYG6

test "$(sha256sum "$CANON/backend/strategies/sr_levels.py" | awk '{print $1}')" = "$CANON_SR"
test "$(sha256sum "$CANON/backend/strategies/trend_rider.py" | awk '{print $1}')" = "$CANON_TR"
test "$(sha256sum "$CANON/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" | awk '{print $1}')" = "$CANON_MAN"
test "$(sha256sum "$CANON/backend/config/q4r3_exact25_shadow_binding_v1.json" | awk '{print $1}')" = "$CANON_BIND"

echo ===EXCLUSION===
cat "$NEW/result/exclusion_receipt.json"
echo ===GATE6_NO_TREND===
cat "$NEW/result/gate6_no_trend.json"
echo ===COVERAGE===
cat "$NEW/result/coverage_revalidation.json" 2>/dev/null || true
