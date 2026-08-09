#!/usr/bin/env bash
set -euo pipefail

PY=/home/z/z/.venv/bin/python
ROOT=/opt/zel/research-runtime/jobs/structural-premium-v2
SRC=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/engine/replay_v1_no_trend.py
OUT=$ROOT/engine/replay_v1_v2.py
RECEIPT=$ROOT/engine/build_receipt.json
mkdir -p "$ROOT/engine"
test -s "$SRC"
cp "$SRC" "$OUT.tmp"

"$PY" - "$OUT.tmp" "$OUT" "$RECEIPT" "$SRC" <<'PY'
from __future__ import annotations
import hashlib,json,py_compile,sys
from pathlib import Path

src,out,receipt,original_src=map(Path,sys.argv[1:])
text=src.read_text()
before_sha=hashlib.sha256(text.encode()).hexdigest()
marker='# ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH_V2_SIX_AXIS'
main_guard='if __name__ == "__main__":'
if text.count(marker)!=1: raise SystemExit(f'LEGACY_MARKER_COUNT:{text.count(marker)}')
marker_i=text.index(marker)
prefix=text[:marker_i].rstrip()+"\n\n"
if '_ZEL_OVERLAY' in prefix: raise SystemExit('LEGACY_OVERLAY_LEAK_PREFIX')
if 'EXPECTED_STRATEGY_COUNT = 3' not in prefix: raise SystemExit('EXPECTED_THREE_STRATEGIES_REQUIRED')

v2_helpers=r'''
V2_REPLAY_CONTRACT_VERSION = "ZEL_STRUCTURAL_PREMIUM_V2_NEXT_OPEN_3"
V2_ENTRY_EXECUTION_MODEL = "NEXT_BAR_OPEN_PRESERVE_ABS_RISK_REWARD_DISTANCE"
_V2_BASE_RESTORE = _restore_structural_premium_registry

def _restore_structural_premium_registry(source_root, raw_registry):
    restored = dict(_V2_BASE_RESTORE(source_root, raw_registry))
    restored.pop("trend_rider", None)
    expected = {"vwap_revert", "support_resistance", "liquidity_sweep"}
    if set(restored) != expected:
        raise RuntimeError(f"V2_RESTORED_REGISTRY_MISMATCH:{sorted(restored)}")
    return restored

def _v2_shift_geometry(side, signal_entry, stop, target, execution_price):
    side = str(side).lower()
    signal_entry = float(signal_entry)
    stop = float(stop)
    target = float(target)
    execution_price = float(execution_price)
    if min(signal_entry, stop, target, execution_price) <= 0:
        return None
    if side == "long":
        stop_distance = signal_entry - stop
        target_distance = target - signal_entry
        if stop_distance <= 0 or target_distance <= 0:
            return None
        return execution_price - stop_distance, execution_price + target_distance
    if side == "short":
        stop_distance = stop - signal_entry
        target_distance = signal_entry - target
        if stop_distance <= 0 or target_distance <= 0:
            return None
        return execution_price + stop_distance, execution_price - target_distance
    return None

def _v2_reprice_pending_entry(producer, pending, execution_price):
    validated = pending.get("validated")
    if not isinstance(validated, (tuple, list)) or len(validated) != 4:
        return None
    side, signal_entry, stop, target = validated
    shifted = _v2_shift_geometry(side, signal_entry, stop, target, execution_price)
    if shifted is None:
        return None
    shifted_stop, shifted_target = shifted
    result = dict(pending.get("result") or {})
    result["entry"] = float(execution_price)
    result["sl"] = shifted_stop
    result["tp"] = shifted_target
    check = producer.valid_entry(result, float(execution_price))
    if check is None:
        return None
    if str(check[0]).lower() != str(side).lower():
        return None
    return result
'''
text=prefix+v2_helpers+"\n\n"+main_guard+'\n    raise SystemExit(main())\n'

anchor='    position: MutableMapping[str, Any] | None = None\n    closed: list[dict[str, Any]] = []'
replace='    position: MutableMapping[str, Any] | None = None\n    pending_entry: dict[str, Any] | None = None\n    pending_entry_rejects = 0\n    closed: list[dict[str, Any]] = []'
if text.count(anchor)!=1: raise SystemExit(f'POSITION_ANCHOR_COUNT:{text.count(anchor)}')
text=text.replace(anchor,replace,1)

# A queued entry is consumed exactly once at bar t+1 OPEN. It is cleared BEFORE any
# helper/make_position call so an exception can never retry the same signal at t+2.
try_anchor='''        try:\n            if isinstance(position, dict):'''
try_replace='''        try:\n            if pending_entry is not None and not isinstance(position, dict):\n                queued_entry = pending_entry\n                pending_entry = None\n                execution_price = float(last["open"])\n                execution_result = _v2_reprice_pending_entry(producer, queued_entry, execution_price)\n                if execution_result is None:\n                    pending_entry_rejects += 1\n                else:\n                    new_position = producer.make_position(\n                        strategy_id,\n                        str(getattr(owner, "owner_sha256", "")),\n                        symbol,\n                        interval,\n                        execution_result,\n                        current,\n                        RISK_UNIT_USDT,\n                        FEE_RATE,\n                        SLIPPAGE_BPS,\n                    )\n                    if new_position is None:\n                        pending_entry_rejects += 1\n                    else:\n                        new_position["position_id"] = f"historical.{interval}.{window_id}.{new_position['position_id']}"\n                        new_position["event_id"] = new_position["position_id"]\n                        new_position["entry_features"] = dict(queued_entry.get("signal_features") or {})\n                        new_position["entry_signal_ts"] = str(queued_entry.get("signal_ts") or "")\n                        new_position["entry_signal_price"] = float(queued_entry["validated"][1])\n                        new_position["entry_execution_price"] = execution_price\n                        new_position["entry_gap_abs"] = execution_price - float(queued_entry["validated"][1])\n                        new_position["entry_execution_model"] = V2_ENTRY_EXECUTION_MODEL\n                        position = new_position\n                        opens += 1\n\n            if isinstance(position, dict):'''
if text.count(try_anchor)!=1: raise SystemExit(f'TRY_ANCHOR_COUNT:{text.count(try_anchor)}')
text=text.replace(try_anchor,try_replace,1)

old='''            else:\n                if producer.valid_entry(result, current_price) is not None:\n                    valid_entries += 1\n                new_position = producer.make_position(\n                    strategy_id,\n                    str(getattr(owner, "owner_sha256", "")),\n                    symbol,\n                    interval,\n                    result,\n                    current,\n                    RISK_UNIT_USDT,\n                    FEE_RATE,\n                    SLIPPAGE_BPS,\n                )\n                if new_position is not None:\n                    new_position["position_id"] = f"historical.{interval}.{window_id}.{new_position['position_id']}"\n                    new_position["event_id"] = new_position["position_id"]\n                    position = new_position\n                    opens += 1'''
new='''            else:\n                validated_entry = producer.valid_entry(result, current_price)\n                if validated_entry is not None:\n                    valid_entries += 1\n                    pending_entry = {\n                        "result": dict(result),\n                        "validated": tuple(validated_entry),\n                        "signal_features": dict(features),\n                        "signal_ts": last_ts_iso,\n                        "signal_bar_index": index,\n                    }'''
if text.count(old)!=1: raise SystemExit(f'SAME_BAR_OPEN_BLOCK_COUNT:{text.count(old)}')
text=text.replace(old,new,1)

meta_anchor='''                        "historical_oos": True,'''
meta_replace='''                        "historical_oos": True,\n                        "entry_execution_model": position.get("entry_execution_model"),\n                        "entry_signal_ts": position.get("entry_signal_ts"),\n                        "entry_signal_price": position.get("entry_signal_price"),\n                        "entry_execution_price": position.get("entry_execution_price"),\n                        "entry_gap_abs": position.get("entry_gap_abs"),'''
count=text.count(meta_anchor)
if count!=2: raise SystemExit(f'CLOSE_METADATA_ANCHOR_COUNT:{count}')
text=text.replace(meta_anchor,meta_replace)

if '_ZEL_OVERLAY' in text or 'ZEL_STRUCTURAL_PREMIUM_OVERLAY_PATCH' in text:
    raise SystemExit('LEGACY_OVERLAY_REMAINS')
if text.count('V2_ENTRY_EXECUTION_MODEL') < 2: raise SystemExit('V2_EXECUTION_MARKER_MISSING')
if text.count('pending_entry = {') != 1: raise SystemExit('PENDING_QUEUE_COUNT')
if text.count('queued_entry = pending_entry') != 1 or text.count('pending_entry = None') < 2: raise SystemExit('PENDING_SINGLE_USE_CONTRACT')
if text.count('execution_price = float(last["open"])') != 1: raise SystemExit('NEXT_OPEN_EXECUTION_COUNT')
if text.count('producer.valid_entry(result, current_price)') != 1: raise SystemExit('ENTRY_PREDICATE_COUNT')
if text.count('def _v2_shift_geometry') != 1: raise SystemExit('SHIFT_GEOMETRY_HELPER_COUNT')

# Side-explicit distance self-test.
def shift(side, signal_entry, stop, target, execution):
    if side == 'long':
        sd=signal_entry-stop; td=target-signal_entry
        return execution-sd, execution+td
    sd=stop-signal_entry; td=signal_entry-target
    return execution+sd, execution-td
ls,lt=shift('long',100.0,95.0,110.0,102.0)
ss,st=shift('short',100.0,105.0,90.0,102.0)
assert (ls,lt)==(97.0,112.0) and abs(102-ls)==5 and abs(lt-102)==10
assert (ss,st)==(107.0,92.0) and abs(ss-102)==5 and abs(102-st)==10

out.write_text(text)
py_compile.compile(str(out),doraise=True)
after_sha=hashlib.sha256(out.read_bytes()).hexdigest()
rec={
 'schema_version':'zel.structural_premium.v2.replay_engine.build.v3',
 'state':'PASS_V2_NEXT_OPEN_ENGINE_BUILT',
 'source_path':str(original_src),'output_path':str(out),
 'source_sha256':before_sha,'output_sha256':after_sha,
 'legacy_overlay_removed':True,'expected_strategy_count':3,
 'entry_predicate':'producer.valid_entry(result,current_price)',
 'execution_model':'NEXT_BAR_OPEN_PRESERVE_ABS_RISK_REWARD_DISTANCE',
 'pending_entry_single_use':True,
 'geometry_self_test_long':True,'geometry_self_test_short':True,
 'signal_features_preserved':True,'stateful_management_modified':False,
 'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'action':'hold'
}
receipt.write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
print(json.dumps(rec,sort_keys=True))
PY

mv -f "$OUT.tmp" "$OUT.source_snapshot"
"$PY" -m py_compile "$OUT"

echo '===V2_BUILD_RECEIPT==='
cat "$RECEIPT"
echo '===V2_CONTRACT_MARKERS==='
grep -nE 'V2_REPLAY_CONTRACT|_v2_shift_geometry|queued_entry|pending_entry|execution_price = float\(last\["open"\]\)|validated_entry = producer.valid_entry|entry_execution_model' "$OUT" | head -120
