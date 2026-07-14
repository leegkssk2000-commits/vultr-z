#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_TRADE_METHOD_READINESS_WORKTREE:-/tmp/q4r3-exact25-trade-method-projection-readiness}
PYTHON_BIN=$ROOT/.venv/bin/python
LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
OUTDIR=$ROOT/runtime/exact25_edge_v1/trade_method_projection_readiness
REPORT=$OUTDIR/report_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_trade_method_projection_readiness_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_trade_method_projection_readiness_job.log
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods

exec > >(tee -a "$LOG") 2>&1

fail() {
  local stage=$1
  local reason=$2
  "$PYTHON_BIN" - "$JOB_STATUS" "$stage" "$reason" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
p=Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
  "job":"q4r3_exact25_trade_method_projection_readiness",
  "state":"FAILED","current_stage":sys.argv[2],"reason":sys.argv[3],
  "updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "order_authority":"blocked","execution_authority":"none",
  "strategy_modified":False,"trade_method_modified":False,
  "producer_modified":False,"writer_modified":False,"formal_ledger_modified":False
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$WORKTREE" "$PYTHON_BIN" "$LEDGER"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done
mkdir -p "$OUTDIR"

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_BEFORE=$(sha256sum "$LEDGER" | awk '{print $1}')
ACTIVE_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

"$PYTHON_BIN" - "$JOB_STATUS" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({"job":"q4r3_exact25_trade_method_projection_readiness","state":"RUNNING","current_stage":"audit_projection_input_contract","updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold"},indent=2),encoding="utf-8")
PY

"$PYTHON_BIN" - "$LEDGER" "$ROOT/runtime/exact25_edge_v1" "$REPORT" <<'PY'
from __future__ import annotations
import json,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

ledger=Path(sys.argv[1]); runtime=Path(sys.argv[2]); report=Path(sys.argv[3])

ALIASES={
"strategy_id":("strategy_id","strategy","strategy_name"),"symbol":("symbol","pair"),"side":("side","direction"),
"signal_ts":("signal_ts_epoch_ms","signal_ts","entry_ts","opened_at"),"evaluation_ts":("evaluation_ts_epoch_ms","evaluation_ts","closed_at","exit_ts"),
"reference_price":("reference_price","entry_price"),"expected_gross_edge_bps":("expected_gross_edge_bps","gross_edge_bps","expected_edge_bps"),
"method":("method","trade_method"),"method_subtype":("method_subtype","subtype","trade_method_subtype"),
"entry_style":("entry_style",),"hold_horizon":("hold_horizon",),"risk_mode":("risk_mode",),
"fee_bps_round_trip":("fee_bps_round_trip","round_trip_fee_bps","fee_bps"),"spread_bps":("spread_bps",),
"slippage_bps":("slippage_bps",),"funding_bps_horizon":("funding_bps_horizon","funding_horizon_bps","funding_bps"),
"market_impact_bps":("market_impact_bps",),"latency_adverse_selection_bps":("latency_adverse_selection_bps","latency_bps"),
"available_depth_usdt":("available_depth_usdt","depth_usdt"),"requested_notional_usdt":("requested_notional_usdt","notional_usdt"),
"realized_vol_bps":("realized_vol_bps","volatility_bps"),"atr_bps":("atr_bps",),"regime":("regime","market_regime"),
"session_bucket":("session_bucket","session","session_window"),"position_size_pct":("position_size_pct","pos_pct"),
"leverage":("leverage","lev"),"dd_day_pct":("dd_day_pct","daily_drawdown_pct"),"dd_total_pct":("dd_total_pct","total_drawdown_pct"),
"liq_buffer_pct":("liq_buffer_pct","liquidation_buffer_pct"),"realized_r":("realized_r","R","pnl_r"),"realized_pnl_usdt":("realized_pnl_usdt","pnl_usdt")}
REQUIRED=tuple(k for k in ALIASES if k not in {"realized_r","realized_pnl_usdt"})
IDS=("event_id","position_id","signal_id","trade_id","close_event_id","open_event_id")


def flatten(v):
 out={}
 if isinstance(v,dict):
  for k,x in v.items():
   key=str(k).strip().lower().replace("-","_")
   if isinstance(x,dict): out.update(flatten(x))
   else: out.setdefault(key,x)
 return out

def present(flat,names): return any(flat.get(n) not in (None,"") for n in names)
def records(v):
 if isinstance(v,dict):
  yield v
  for x in v.values(): yield from records(x)
 elif isinstance(v,list):
  for x in v: yield from records(x)
def read_json(path):
 try: return json.loads(path.read_text(encoding="utf-8"))
 except Exception: return None

def read_rows(path):
 out=[]
 for n,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
  if not line.strip(): continue
  v=json.loads(line)
  if not isinstance(v,dict): raise SystemExit(f"NON_OBJECT_ROW:{n}")
  out.append(v)
 return out

rows=read_rows(ledger)
# Only explicit observer outputs are inspected; no historical/backfill surfaces.
artifact_paths=[]
for pattern in (
 "trade_method_consumer_proof/*.json","trade_method_lineage_observer/*.json",
 "ict_feature_attribution_observer/*.json","six_layer_observer_suite/*.json",
 "market_context_observer/*.json","cost_exit_efficiency_cube/*.json","outcome_contract/*.json"):
 artifact_paths.extend(runtime.glob(pattern))

idx={}
declared={}
for path in sorted(set(artifact_paths)):
 v=read_json(path)
 if v is None: continue
 for rec in records(v):
  f=flatten(rec)
  strategy=next((f.get(a) for a in ALIASES["strategy_id"] if f.get(a) not in (None,"")),None)
  method=next((f.get(a) for a in ALIASES["method"] if f.get(a) not in (None,"")),None)
  subtype=next((f.get(a) for a in ALIASES["method_subtype"] if f.get(a) not in (None,"")),None)
  if strategy and method:
   candidate=(str(method),str(subtype) if subtype is not None else None)
   if strategy in declared and declared[str(strategy)]!=candidate: declared[str(strategy)]=("CONFLICT",None)
   else: declared[str(strategy)]=candidate
  for key in IDS:
   if f.get(key) not in (None,""):
    idx.setdefault(str(f[key]),[]).append((str(path),f))

field_counts={k:Counter() for k in REQUIRED}
missing=Counter(); declaration_only=Counter(); ready=0; outcome_ready=0; exact_join_rows=0
for row in rows:
 f=flatten(row); joined=[]
 for key in IDS:
  if f.get(key) not in (None,""): joined.extend(idx.get(str(f[key]),[]))
 if joined: exact_join_rows+=1
 strategy=next((f.get(a) for a in ALIASES["strategy_id"] if f.get(a) not in (None,"")),None)
 states={}
 for field in REQUIRED:
  if present(f,ALIASES[field]): state="direct"
  elif any(present(jf,ALIASES[field]) for _,jf in joined): state="runtime_exact"
  elif field in {"method","method_subtype"} and strategy is not None and str(strategy) in declared and declared[str(strategy)][0]!="CONFLICT": state="declaration_only"
  else: state="missing"
  states[field]=state; field_counts[field][state]+=1
  if state=="missing": missing[field]+=1
  if state=="declaration_only": declaration_only[field]+=1
 if all(v in {"direct","runtime_exact"} for v in states.values()): ready+=1
 if present(f,ALIASES["realized_r"]) or present(f,ALIASES["realized_pnl_usdt"]): outcome_ready+=1

total=len(rows)
if total==0: state="HOLD"; verdict="NO_FORMAL_ROWS"; next_action="ACCUMULATE_FORMAL_CLOSE_ROWS"
elif ready==total: state="PASS"; verdict="METHOD_PROJECTION_INPUT_CONTRACT_READY"; next_action="RUN_READONLY_METHOD_PROJECTION_REPLAY"
elif not declared: state="HOLD"; verdict="NO_UNIQUE_STRATEGY_METHOD_MAPPING"; next_action="BUILD_CANDIDATE_ONLY_STRATEGY_METHOD_MAPPING_SSOT"
else: state="HOLD"; verdict="MISSING_PREENTRY_METHOD_CONTEXT"; next_action="INSTALL_READONLY_PREENTRY_METHOD_CONTEXT_CAPTURE"

payload={"schema":"q4r3_exact25_trade_method_projection_readiness_v1","generated_at":datetime.now(timezone.utc).isoformat(),
"state":state,"verdict":verdict,"action":"hold","observer_only":True,"formal_row_count":total,
"declared_strategy_mapping_count":len(declared),"rows_with_runtime_exact_join":exact_join_rows,
"projection_ready_count":ready,"projection_ready_pct":round(100*ready/total,4) if total else 0.0,
"replay_outcome_ready_count":outcome_ready,"replay_outcome_ready_pct":round(100*outcome_ready/total,4) if total else 0.0,
"field_coverage":{k:{s:c.get(s,0) for s in ("direct","runtime_exact","declaration_only","missing")} for k,c in field_counts.items()},
"top_missing_fields":missing.most_common(),"declaration_only_fields":declaration_only.most_common(),"next_action":next_action,
"paper_enabled":False,"live_enabled":False,"order_enabled":False,"order_authority":"blocked","execution_authority":"none"}
report.parent.mkdir(parents=True,exist_ok=True); tmp=report.with_suffix(".tmp"); tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(report)
print(json.dumps(payload,ensure_ascii=False,sort_keys=True))

# Minimal deterministic contract self-checks.
assert "expected_gross_edge_bps" in REQUIRED
assert "realized_r" not in REQUIRED
assert payload["projection_ready_count"] <= payload["formal_row_count"]
PY

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_AFTER=$(sha256sum "$LEDGER" | awk '{print $1}')
ACTIVE_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER" ] || fail immutability FORMAL_LEDGER_HASH_CHANGED
[ "$ACTIVE_HASH_BEFORE" = "$ACTIVE_HASH_AFTER" ] || fail immutability ACTIVE_TRADE_METHOD_SOURCE_CHANGED

"$PYTHON_BIN" - "$JOB_STATUS" "$REPORT" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
r=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload={"job":"q4r3_exact25_trade_method_projection_readiness","state":"PASS","current_stage":"complete",
"status":"PASS_Q4R3_EXACT25_TRADE_METHOD_PROJECTION_READINESS","verdict":r["verdict"],"observer_state":r["state"],
"formal_row_count":r["formal_row_count"],"projection_ready_count":r["projection_ready_count"],
"projection_ready_pct":r["projection_ready_pct"],"next_action":r["next_action"],
"updated_at":datetime.now(timezone.utc).isoformat(),"producer_pid_unchanged":True,"writer_pid_unchanged":True,
"formal_ledger_hash_unchanged":True,"active_trade_method_hash_unchanged":True,"strategy_modified":False,
"trade_method_modified":False,"producer_modified":False,"writer_modified":False,"formal_ledger_modified":False,
"paper_enabled":False,"live_enabled":False,"order_enabled":False,"order_authority":"blocked","execution_authority":"none","action":"hold"}
Path(sys.argv[1]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(payload,ensure_ascii=False,sort_keys=True))
PY

echo Q4R3_EXACT25_TRADE_METHOD_PROJECTION_READINESS_PASS
