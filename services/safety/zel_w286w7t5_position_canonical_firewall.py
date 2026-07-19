#!/usr/bin/env python3
import json, os, tempfile, time, fcntl, sys
from pathlib import Path
from datetime import datetime, timezone

API=Path("/var/www/z-os-alimi/api")
RUN=Path("/home/z/z/runtime")
LOCK=RUN/"w286w7t5_position_canonical_firewall.lock"

POS=API/"paper_position_latest.json"
STATE=API/"paper_position_state.json"
W278C=API/"w278c_position_meta_guard_latest.json"
OUT=API/"w286w7t5_position_canonical_firewall_latest.json"

TARGET_ID="paper.20260609153022.f8af718e"

EVIDENCE=[
  API/"paper_closed_position_event_latest.json",
  API/"paper_exit_close_event_latest.json",
  API/"paper_close_verification_latest.json",
  API/"paper_trade_close_journal_latest.json",
  API/"paper_order_latest.json",
]

SAFE={
  "order_authority":"blocked",
  "execution_authority":"none",
  "paper_execution_allowed":False,
  "paper_request_allowed":False,
  "close_allowed":False,
  "actual_close_written":False,
  "route_allowed":False,
  "write_to_actual_request":False,
  "real_order_enabled":False,
  "live_execution_allowed":False,
  "auto_live_enable_allowed":False
}

def now():
    return datetime.now(timezone.utc).isoformat()

def load(p, default=None):
    if default is None: default={}
    try:
        return json.load(open(p,encoding="utf-8"))
    except Exception:
        return default

def raw(p):
    try:
        return p.read_text(encoding="utf-8",errors="ignore")
    except Exception:
        return ""

def write_json(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=p.name+".",dir=str(p.parent))
    with os.fdopen(fd,"w",encoding="utf-8") as fp:
        json.dump(d,fp,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
        fp.write("\n")
    os.replace(tmp,p)
    os.chmod(p,0o644)

def unwrap_position(d):
    if isinstance(d.get("position"),dict):
        x=dict(d["position"])
        x["_outer_status"]=d.get("status")
        x["_outer_scope"]=d.get("scope")
        x["_outer_owner"]=d.get("owner")
        return x
    return dict(d)

def closed_evidence(pid):
    ev=[]
    for p in EVIDENCE:
        d=load(p,{})
        t=raw(p)
        low=t.lower()
        if not pid or pid not in t:
            if p.name=="paper_order_latest.json" and "paper_position_closed" not in low:
                continue
            elif p.name!="paper_order_latest.json":
                continue
        st=str(d.get("status") or "").lower()
        closedish=("closed" in st or "closed_at" in low or "exit_price" in low or "realized_pnl" in low or "realized_r" in low or "paper_position_closed" in low)
        needs_review=("needs_review" in st and ("close" in low or "closed" in low))
        if closedish or needs_review:
            ev.append({
              "file":str(p),
              "status":d.get("status"),
              "reason":d.get("reason"),
              "position_id":d.get("position_id") or d.get("id") or d.get("paper_position_id"),
              "symbol":d.get("symbol"),
              "side":d.get("side"),
              "strategy":d.get("strategy")
            })
    return ev

def make_closed(src, ev, reason):
    pid=src.get("position_id") or src.get("id") or TARGET_ID
    return {
      "owner":"W286W7T5_POSITION_CANONICAL_FIREWALL",
      "status":"closed",
      "position_status":"closed",
      "paper_status":"closed",
      "ghost_cleaned":True,
      "ghost_position_id":pid,
      "position_id":pid,
      "previous_status":src.get("status") or src.get("_outer_status"),
      "previous_owner":src.get("owner") or src.get("_outer_owner"),
      "previous_scope":src.get("scope") or src.get("_outer_scope"),
      "symbol":src.get("symbol") or "SOLUSDT",
      "side":src.get("side") or "long",
      "strategy":src.get("strategy") or src.get("strategy_id") or "turtle_trend",
      "entry_price":src.get("entry_price") or src.get("entry"),
      "entry_ts":src.get("entry_ts"),
      "opened_at":src.get("opened_at"),
      "closed_reason":reason,
      "closed_evidence_count":len(ev),
      "closed_evidence":ev[:10],
      "flat_ready_for_new_entry_gate":True,
      "mutation_scope":"w286w7t5_canonical_position_firewall_no_force_close_no_order_no_live",
      "updated_at":now(),
      **SAFE
    }

def once():
    with open(LOCK,"w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)

        outer=load(POS,{})
        src=unwrap_position(outer)
        st=str(outer.get("status") or src.get("status") or "").lower()
        pid=str(src.get("position_id") or outer.get("position_id") or outer.get("id") or "").strip()
        scope=str(outer.get("scope") or src.get("scope") or src.get("_outer_scope") or "")
        owner=str(outer.get("owner") or src.get("owner") or src.get("_outer_owner") or "")

        ev=closed_evidence(pid or TARGET_ID)

        bad_pnl_scope = st=="open" and "PAPER_PNL_CLOSE_ENGINE_ONLY" in scope
        bad_target_reopen = st=="open" and (pid==TARGET_ID or not pid) and len(ev)>=2
        bad_restored_meta = st=="open" and src.get("recover_note")=="restored_missing_open_position_metadata" and len(ev)>=2

        action="no_action"
        reason="canonical_position_ok"

        if bad_pnl_scope or bad_target_reopen or bad_restored_meta:
            reason="blocked_reopen_from_pnl_close_engine_or_target_ghost"
            closed=make_closed(src,ev,reason)
            write_json(POS,closed)
            write_json(STATE,closed)
            write_json(W278C,{
              "owner":"W286W7T5_POSITION_CANONICAL_FIREWALL",
              "status":"blocked_reopen_no_open_restore",
              "position_id":closed.get("position_id"),
              "closed_evidence_count":len(ev),
              "blocked_previous_owner":owner,
              "blocked_previous_scope":scope,
              "mutation_scope":"w278c_restore_neutralized_by_w7t5_firewall_for_target_ghost",
              "updated_at":now(),
              **SAFE
            })
            action="blocked_reopen_and_restored_closed"

        audit={
          "owner":"W286W7T5_POSITION_CANONICAL_FIREWALL",
          "status":"PASS_FIREWALL_ACTIVE",
          "action":action,
          "reason":reason,
          "seen_status":st,
          "seen_position_id":pid,
          "seen_owner":owner,
          "seen_scope":scope,
          "closed_evidence_count":len(ev),
          "post_status":load(POS,{}).get("status"),
          "post_position_id":load(POS,{}).get("position_id"),
          "mutation_scope":"canonical_position_firewall_only_no_force_close_no_order_no_live",
          "updated_at":now(),
          **SAFE
        }
        write_json(OUT,audit)
        print(json.dumps(audit,ensure_ascii=False,sort_keys=True))

def loop():
    while True:
        try:
            once()
        except Exception as e:
            write_json(OUT,{
              "owner":"W286W7T5_POSITION_CANONICAL_FIREWALL",
              "status":"ERROR",
              "error":str(e),
              "updated_at":now(),
              **SAFE
            })
        time.sleep(0.25)

if __name__=="__main__":
    if "--loop" in sys.argv:
        loop()
    else:
        once()
