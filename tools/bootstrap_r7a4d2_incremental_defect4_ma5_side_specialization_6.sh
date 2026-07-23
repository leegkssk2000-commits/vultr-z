#!/usr/bin/env bash
set -uo pipefail
ROOT="${1:-/home/z/z}"
PARENT_DIR="$ROOT/runtime/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6"
OUTDIR="$ROOT/runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6"
SUMMARY="$PARENT_DIR/incremental_defect3b_single_axis_payoff_summary_v1.json"
TRADES="$PARENT_DIR/incremental_defect3b_child_trade_rows_v1.jsonl"
EXPECTED_SUMMARY_SHA='8b2deaa6ea2362ae6f3ab486a6306b91f6899becb110a2366ca546baa744ddd4'
EXPECTED_TRADES_SHA='9897831bda1be731560a2903b08f310e8eacbdeb26dc8838f7fd28690da18782'
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/ma5_side_specialization_${STAMP}.log"
mkdir -p "$OUTDIR"
python3 - "$ROOT" "$OUTDIR" "$EXPECTED_SUMMARY_SHA" "$EXPECTED_TRADES_SHA" <<'PY' 2>&1 | tee "$LOG"
from __future__ import annotations
import hashlib, json, math, os, statistics, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

root = Path(sys.argv[1]).resolve()
outdir = Path(sys.argv[2]).resolve()
expected_summary_sha = sys.argv[3]
expected_trades_sha = sys.argv[4]
parent_dir = root / 'runtime/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6'
summary_path = parent_dir / 'incremental_defect3b_single_axis_payoff_summary_v1.json'
trades_path = parent_dir / 'incremental_defect3b_child_trade_rows_v1.jsonl'
CHILD_ID = 'ma5_long_only_side_specialization'
PARENT_ID = 'ma5_state_reset_cooldown_2bar'
LANE_ID = 'dual_ma_trend_bot:5m'
EXPECTED_CELLS = {(f'cost_profile_{i}', f'timing_{j}') for i in range(3) for j in range(2)}
EPS = 1e-12

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as h:
        h.write(text)
        tmp = Path(h.name)
    os.replace(tmp, path)

def atomic_json(path: Path, value) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')

def atomic_jsonl(path: Path, rows) -> None:
    atomic_text(path, ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows))

def load_jsonl(path: Path):
    out=[]
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row=json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f'JSONL_OBJECT_REQUIRED:{n}')
        out.append(row)
    return out

def event_key(r):
    return (int(r.get('fold', -1)), str(r.get('symbol') or ''), int(r.get('entry_index', -1)), str(r.get('segment_id') or ''), str(r.get('timing_id') or ''))

def metrics(rows):
    ordered=sorted(rows, key=event_key)
    vals=[float(r.get('net_r') or 0.0) for r in ordered]
    pnl=[float(r.get('net_return_pct') or 0.0) for r in ordered]
    wins=[v for v in vals if v>0]
    losses=[-v for v in vals if v<0]
    folds=defaultdict(float)
    eq=peak=mdd=0.0
    eqp=peakp=mddp=0.0
    for r,v,p in zip(ordered,vals,pnl):
        folds[int(r.get('fold', -1))]+=v
        eq+=v; peak=max(peak,eq); mdd=max(mdd,peak-eq)
        eqp+=p; peakp=max(peakp,eqp); mddp=max(mddp,peakp-eqp)
    gw=sum(wins); gl=sum(losses)
    return {
      'trade_count':len(rows), 'symbol_count':len({str(r.get('symbol') or '') for r in rows}),
      'fold_count':len(folds), 'positive_fold_count':sum(v>0 for v in folds.values()),
      'win_count':len(wins), 'loss_count':len(losses),
      'win_rate_pct':(len(wins)/len(rows)*100.0 if rows else 0.0),
      'net_r_sum':sum(vals), 'net_pnl_sum_pct':sum(pnl),
      'expectancy_r':(statistics.mean(vals) if vals else 0.0),
      'profit_factor':(gw/gl if gl>EPS else (math.inf if gw>0 else 0.0)),
      'max_drawdown_r':mdd, 'max_drawdown_pct':mddp,
      'fold_net_r':{str(k):v for k,v in sorted(folds.items())},
      'symbol_histogram':dict(sorted(Counter(str(r.get('symbol') or '') for r in rows).items())),
      'regime_histogram':dict(sorted(Counter(str(r.get('regime') or '') for r in rows).items())),
      'side_histogram':dict(sorted(Counter(str(r.get('side') or '') for r in rows).items())),
    }

def profile_name(row):
    return {'cost_profile_0':'base','cost_profile_1':'adverse','cost_profile_2':'severe'}.get(str(row.get('cost_profile_id') or ''),'other')

def ge(a,b): return a + EPS >= b

for p in (summary_path, trades_path):
    if not p.is_file():
        raise SystemExit(f'HOLD_REQUIRED_INPUT_MISSING:{p}')
actual_summary_sha=sha256(summary_path)
actual_trades_sha=sha256(trades_path)
print(f'SUMMARY_SHA={actual_summary_sha}')
print(f'TRADES_SHA={actual_trades_sha}')
if actual_summary_sha != expected_summary_sha or actual_trades_sha != expected_trades_sha:
    print('STATE=HOLD_MA5_SIDE_SPECIALIZATION_INPUT_HASH_MISMATCH')
    print('RC=2')
    raise SystemExit(2)

before={str(summary_path):actual_summary_sha,str(trades_path):actual_trades_sha}
summary=json.loads(summary_path.read_text(encoding='utf-8'))
parent_rows=load_jsonl(trades_path)
blockers=[]
if summary.get('state')!='PASS_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6': blockers.append('PARENT_STATE_NOT_PASS')
if not bool(summary.get('incremental_pass')): blockers.append('PARENT_INCREMENTAL_NOT_PASS')
if str(summary.get('child_variant_id') or '') != PARENT_ID: blockers.append('PARENT_VARIANT_UNEXPECTED')
if len(parent_rows)!=int(summary.get('child_trade_count') or -1): blockers.append('PARENT_TRADE_COUNT_MISMATCH')
if {str(r.get('lane_id') or '') for r in parent_rows}!={LANE_ID}: blockers.append('LANE_SET_CHANGED')
if {str(r.get('side') or '') for r in parent_rows}-{'long','short'}: blockers.append('SIDE_ENUM_INVALID')
cells={(str(r.get('cost_profile_id') or ''),str(r.get('timing_id') or '')) for r in parent_rows}
if cells != EXPECTED_CELLS: blockers.append(f'EXPECTED_SIX_CELLS:{sorted(cells)}')
if blockers:
    print('STATE=HOLD_MA5_SIDE_SPECIALIZATION_INPUT')
    print('BLOCKERS='+json.dumps(blockers))
    print('RC=2')
    raise SystemExit(2)

child_rows=[]; excluded_rows=[]
for r in parent_rows:
    base={**r, 'source_control_variant_id':str(r.get('control_variant_id') or r.get('variant_id') or ''), 'parent_variant_id':PARENT_ID}
    if str(r.get('side'))=='long':
        child_rows.append({**base, 'control_variant_id':CHILD_ID, 'variant_id':CHILD_ID, 'specialization_axis':'side', 'allowed_side':'long'})
    else:
        excluded_rows.append({**base, 'excluded_by':'SIDE_SPECIALIZATION', 'excluded_reason':'MA5_SHORT_STRUCTURAL_NEGATIVE_EDGE'})

parent_profiles={}; child_profiles={}; non_degrade={}
for profile in ('base','adverse','severe'):
    pr=[r for r in parent_rows if profile_name(r)==profile]
    cr=[r for r in child_rows if profile_name(r)==profile]
    pm=metrics(pr); cm=metrics(cr)
    parent_profiles[profile]=pm; child_profiles[profile]=cm
    non_degrade[profile]=(ge(cm['net_r_sum'],pm['net_r_sum']) and ge(cm['expectancy_r'],pm['expectancy_r']) and ge(cm['profit_factor'],pm['profit_factor']) and cm['max_drawdown_r'] <= pm['max_drawdown_r']+EPS)

cell_rows=[]
for cell in sorted(EXPECTED_CELLS):
    pr=[r for r in parent_rows if (str(r.get('cost_profile_id')),str(r.get('timing_id')))==cell]
    cr=[r for r in child_rows if (str(r.get('cost_profile_id')),str(r.get('timing_id')))==cell]
    cell_rows.append({'cost_profile_id':cell[0],'timing_id':cell[1],'profile':profile_name(pr[0]) if pr else 'other','parent_metrics':metrics(pr),'child_metrics':metrics(cr)})

base=child_profiles['base']; severe=child_profiles['severe']
sample_gate=base['trade_count']>=24 and base['symbol_count']>=3
walk_forward_gate=all(child_profiles[p]['positive_fold_count']>=4 for p in ('base','adverse','severe'))
meaningful_severe=severe['net_r_sum']>0 and severe['profit_factor']>=1.20 and severe['positive_fold_count']>=4
side_defect_improved=len(excluded_rows)>0 and all(non_degrade.values())
repair_pass=all(non_degrade.values()) and side_defect_improved and sample_gate and walk_forward_gate and meaningful_severe
validation_severe_r=sum(float(r.get('net_r') or 0.0) for r in child_rows if profile_name(r)=='severe' and int(r.get('fold',-1)) in {3,4,5})
discovery_severe_r=sum(float(r.get('net_r') or 0.0) for r in child_rows if profile_name(r)=='severe' and int(r.get('fold',-1)) in {0,1,2})
robust_survivor=False

result={
 'state':'PASS_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6' if repair_pass else 'HOLD_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6',
 'lane_id':LANE_ID,'parent_variant_id':PARENT_ID,'child_variant_id':CHILD_ID,
 'specialization_axis':'side','allowed_side':'long','excluded_side':'short',
 'stress_cell_count':len(cells),'parent_trade_count':len(parent_rows),'child_trade_count':len(child_rows),'excluded_short_row_count':len(excluded_rows),
 'parent_profile_metrics':parent_profiles,'child_profile_metrics':child_profiles,'cell_comparison_rows':cell_rows,
 'pass_checks':{'base_non_degrade':non_degrade['base'],'adverse_non_degrade':non_degrade['adverse'],'severe_non_degrade':non_degrade['severe'],'side_defect_improved':side_defect_improved,'sample_gate':sample_gate,'walk_forward_gate':walk_forward_gate,'meaningful_severe':meaningful_severe,'repair_pass':repair_pass,'robust_survivor':robust_survivor},
 'discovery_severe_net_r':discovery_severe_r,'validation_severe_net_r':validation_severe_r,
 'confidence_claim_allowed':False,'confidence_blocker':'SIMPLEBOT_BENCHMARK_AND_INDEPENDENT_OOS_NOT_COMPLETED',
 'strategy_mutation_allowed':False,'registry_mutation_allowed':False,'router_mutation_allowed':False,'service_mutation_allowed':False,'shadow_start_allowed':False,'paper_live_order_allowed':False,
 'next_stage':'R7.A4D2_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL' if repair_pass else 'R7.A4D2_MA5_PARENT_PRESERVE_AND_SIDE_SPECIALIZATION_REVIEW'
}
atomic_json(outdir/'ma5_side_specialization_summary_v1.json',result)
atomic_jsonl(outdir/'ma5_long_only_child_trade_rows_v1.jsonl',child_rows)
atomic_jsonl(outdir/'ma5_excluded_short_evidence_rows_v1.jsonl',excluded_rows)
atomic_jsonl(outdir/'ma5_side_specialization_cell_comparison_rows_v1.jsonl',cell_rows)
after={str(summary_path):sha256(summary_path),str(trades_path):sha256(trades_path)}
if before != after:
    print('STATE=HOLD_INPUT_MUTATION_DETECTED')
    print('RC=2')
    raise SystemExit(2)
print('STATE='+result['state'])
print('BLOCKER_COUNT='+('0' if repair_pass else '1'))
print('STRESS_CELL_COUNT='+str(len(cells)))
print('PARENT_TRADE_COUNT='+str(len(parent_rows)))
print('CHILD_TRADE_COUNT='+str(len(child_rows)))
print('EXCLUDED_SHORT_ROW_COUNT='+str(len(excluded_rows)))
for profile in ('base','adverse','severe'):
    m=child_profiles[profile]
    print(f'{profile.upper()}_NET_R={m["net_r_sum"]:.12f}')
    print(f'{profile.upper()}_PF={m["profit_factor"]:.12f}')
    print(f'{profile.upper()}_POSITIVE_FOLDS={m["positive_fold_count"]}/6')
print(f'DISCOVERY_SEVERE_NET_R={discovery_severe_r:.12f}')
print(f'VALIDATION_SEVERE_NET_R={validation_severe_r:.12f}')
print('PASS_CHECKS='+json.dumps(result['pass_checks'],sort_keys=True))
print('ROBUST_SURVIVOR=false')
print('NEXT_STAGE='+result['next_stage'])
print('SUMMARY_JSON='+str(outdir/'ma5_side_specialization_summary_v1.json'))
print('INPUT_MUTATION_COUNT=0')
print('RC='+('0' if repair_pass else '2'))
raise SystemExit(0 if repair_pass else 2)
PY
RC=${PIPESTATUS[0]}
echo "FULL_LOG=$LOG"
echo "COMMAND_RC=$RC"
echo 'SSH_SESSION_PRESERVED=true'
echo 'WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
