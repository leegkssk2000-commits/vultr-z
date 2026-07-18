#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any

TOKENS = {
  "strategy25": ["strategy", "breakout", "momentum", "trend", "revert", "support_resistance", "liquidity_sweep"],
  "trade_lifecycle": ["candidate", "admission", "open", "manage", "close", "duplicate", "position_id"],
  "exit_policy4": ["native", "1.5r", "2.0r", "2.5r", "exit_policy"],
  "skill18": ["skill_registry", "long_beam", "short_beam", "dca", "avg_down", "water_add", "pyramiding", "partial", "trailing", "mfe", "runner", "time_stop", "break_even", "reduce25"],
  "teambots_and_advisors": ["lbot", "mbot", "obot", "sbot", "zbot", "zico", "lico", "zlice"],
  "data_math_cost_replay": ["replay", "simulation", "fee", "slippage", "funding", "latency", "mfe", "mae", "cvar", "drawdown", "point_in_time", "lookahead"],
  "display_ledger_observability": ["telegram", "alimi", "view_contract", "writer", "ledger", "recent_trace", "winrate", "pnl"]
}

def run(cmd:list[str])->str:
    p=subprocess.run(cmd,text=True,capture_output=True,timeout=40)
    return p.stdout

def sha(path:Path)->str:
    if not path.is_file(): return ""
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def atomic(path:Path,obj:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent); os.close(fd)
    p=Path(tmp); p.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding='utf-8'); os.replace(p,path)

def classify(found:int, runtime_hits:int, candidate_hits:int, conflicts:int)->str:
    if conflicts>0 or found==0: return "D"
    if runtime_hits>0 and candidate_hits==0: return "A"
    if runtime_hits>0: return "B"
    return "C"

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--contract',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    c=json.loads(a.contract.read_text()); root=Path(c['root']); runtime=Path(c['runtime_root'])
    before_runtime=sha(runtime/'shadow_aggregate_snapshot/latest.json')
    before_ledger=sha(runtime/'formal_exact5_measurement/forward_r_ledger.jsonl')
    files=[]
    for base in (root/'backend',root/'tools',root/'config',root/'tests'):
        if base.exists():
            for p in base.rglob('*'):
                if p.is_file() and p.suffix.lower() in {'.py','.json','.yaml','.yml','.toml','.service','.md'}:
                    files.append(p)
    units=run(['systemctl','list-unit-files','--type=service','--no-legend','--no-pager'])
    axes={}; all_text_cache={}
    for p in files:
        try: all_text_cache[p]=p.read_text(encoding='utf-8',errors='ignore').lower()
        except Exception: all_text_cache[p]=''
    for axis,tokens in TOKENS.items():
        matched=[]; runtime_hits=0; candidate_hits=0; conflicts=0
        for p,text in all_text_cache.items():
            hits=[t for t in tokens if t in text or t in p.name.lower()]
            if not hits: continue
            rel=str(p.relative_to(root)); matched.append({'path':rel,'tokens':hits[:8]})
            if any(x in text for x in ('candidate_only','observer_only','activation_allowed": false','runtime_mutation_allowed": false')): candidate_hits+=1
            if any(x in text for x in ('systemctl start','runtime_active','execstart','write_allowed')): runtime_hits+=1
            if any(x in text for x in ('legacy','superseded','duplicate writer','multiple writer','stale')): conflicts+=1
        axes[axis]={
          'grade':classify(len(matched),runtime_hits,candidate_hits,conflicts),
          'matched_file_count':len(matched),'runtime_evidence_count':runtime_hits,
          'candidate_only_evidence_count':candidate_hits,'conflict_evidence_count':conflicts,
          'sample_files':matched[:40]
        }
    strategy_ids=set(); skill_ids=set(); writer_ids=set(); advisors=set(); teambots=set()
    id_rx=re.compile(r'"(?:strategy_id|skill_id|writer_id)"\s*:\s*"([^"]+)"',re.I)
    for p,text in all_text_cache.items():
        for m in id_rx.finditer(text):
            v=m.group(1).upper()
            if 'SK_' in v: skill_ids.add(v)
            elif 'WRITER' in v or 'W_' in v: writer_ids.add(v)
            else: strategy_ids.add(v)
        for n in ('lbot','mbot','obot','sbot'):
            if n in text: teambots.add(n.upper())
        for n in ('zbot','zico','lico','zlice'):
            if n in text: advisors.add(n.upper())
    active_units=[ln.split()[0] for ln in units.splitlines() if ln and any(t in ln.lower() for t in ('exact25','q4r3','shadow','telegram','alimi'))]
    after_runtime=sha(runtime/'shadow_aggregate_snapshot/latest.json'); after_ledger=sha(runtime/'formal_exact5_measurement/forward_r_ledger.jsonl')
    blockers=[]
    req=c['required_counts']
    if len(strategy_ids)<req['strategy']: blockers.append(f"STRATEGY_ID_COUNT_{len(strategy_ids)}_LT_{req['strategy']}")
    if len(skill_ids)<req['skill']: blockers.append(f"SKILL_ID_COUNT_{len(skill_ids)}_LT_{req['skill']}")
    if len(teambots)<req['team_bot']: blockers.append(f"TEAM_BOT_COUNT_{len(teambots)}_LT_{req['team_bot']}")
    if len(advisors)<req['advisor']: blockers.append(f"ADVISOR_COUNT_{len(advisors)}_LT_{req['advisor']}")
    if before_runtime!=after_runtime: blockers.append('RUNTIME_SNAPSHOT_CHANGED_DURING_AUDIT')
    if before_ledger!=after_ledger: blockers.append('FORMAL_LEDGER_CHANGED_DURING_AUDIT')
    payload={
      'schema':'zos_r7a_full_runtime_readiness_audit_status_v1','state':'PASS' if not blockers else 'HOLD',
      'blockers':blockers,'blocker_count':len(blockers),'mutation_count':0,'axes':axes,
      'counts':{'strategy_ids':len(strategy_ids),'skill_ids':len(skill_ids),'writer_ids':len(writer_ids),'team_bots':len(teambots),'advisors':len(advisors),'scanned_files':len(files)},
      'ids':{'strategies':sorted(strategy_ids)[:100],'skills':sorted(skill_ids),'writers':sorted(writer_ids),'team_bots':sorted(teambots),'advisors':sorted(advisors)},
      'relevant_unit_files':active_units,'runtime_snapshot_change_count':0 if before_runtime==after_runtime else 1,
      'formal_ledger_change_count':0 if before_ledger==after_ledger else 1,'next_stage':c['next_stage_on_complete']
    }
    atomic(a.output,payload); print(json.dumps(payload,sort_keys=True)); return 0 if not blockers else 2
if __name__=='__main__': raise SystemExit(main())
