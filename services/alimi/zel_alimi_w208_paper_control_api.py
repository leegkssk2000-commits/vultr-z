#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
import json, os, hashlib, urllib.parse

API = Path("/var/www/z-os-alimi/api")
CMD = API / "paper_control_command_latest.json"
STATE = API / "paper_control_api_w208_latest.json"
BASE = API / "paper_base_equity_lock_latest.json"

ALLOWED_ACTIONS = {"hold", "stop"}
ALLOWED_LEV = {10, 15, 20, 25}
ALLOWED_SIZE = {5, 10, 15, 20}

def now():
    return datetime.now(timezone.utc).isoformat()

def load(path, default=None):
    if default is None:
        default = {}
    try:
        if not Path(path).exists():
            return default
        return json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        return {"_load_error": str(e)}

def atomic_write(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def shash(x):
    raw=json.dumps(x,ensure_ascii=False,sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def json_resp(h, code, data):
    raw=json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type","application/json; charset=utf-8")
    h.send_header("Cache-Control","no-store")
    h.send_header("Content-Length",str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)

def current_state():
    cmd=load(CMD,{})
    base=load(BASE,{})
    return {
        "schema_version":"z.os.alimi.w208.paper_control_api.v1",
        "status":"ok",
        "mode":"paper_only",
        "paper_base_equity_usdt":float(base.get("paper_base_equity_usdt") or 5025.0),
        "command_status":cmd.get("status"),
        "pending":cmd.get("pending"),
        "action":cmd.get("action"),
        "leverage_x":cmd.get("leverage_x"),
        "size_pct":cmd.get("size_pct"),
        "order_authority":"blocked",
        "execution_authority":"none",
        "real_order_enabled":False,
        "live_execution_allowed":False,
        "updated_at":now(),
        "owner":"W208_PAPER_CONTROL_API"
    }

class Handler(BaseHTTPRequestHandler):
    server_version = "ZELW208/1.0"

    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","same-origin")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","content-type")
        self.end_headers()

    def do_GET(self):
        data=current_state()
        atomic_write(STATE,data)
        json_resp(self,200,data)

    def do_POST(self):
        try:
            n=int(self.headers.get("content-length","0") or "0")
            if n > 4096:
                return json_resp(self,413,{"status":"rejected","reason":"payload_too_large","order_authority":"blocked","execution_authority":"none"})
            body=self.rfile.read(n).decode("utf-8") if n else "{}"
            payload=json.loads(body or "{}")
        except Exception as e:
            return json_resp(self,400,{"status":"rejected","reason":"bad_json","error":str(e),"order_authority":"blocked","execution_authority":"none"})

        action=str(payload.get("action") or "hold").lower()
        lev=int(payload.get("leverage_x") or payload.get("lev") or 10)
        size=int(payload.get("size_pct") or payload.get("position_pct") or 5)
        scope=str(payload.get("scope") or "next_position")
        dry=bool(payload.get("dry_run") is True)

        errors=[]
        if action not in ALLOWED_ACTIONS: errors.append("action_not_allowed")
        if lev not in ALLOWED_LEV: errors.append("leverage_not_allowed")
        if size not in ALLOWED_SIZE: errors.append("size_not_allowed")
        if scope != "next_position": errors.append("scope_not_next_position")
        if payload.get("real_order_enabled") is True: errors.append("real_order_flag_true")
        if payload.get("live_execution_allowed") is True: errors.append("live_flag_true")

        base=load(BASE,{})
        paper_base=float(base.get("paper_base_equity_usdt") or 5025.0)

        if errors:
            out={
                "schema_version":"z.os.alimi.w208.paper_control_api.v1",
                "status":"rejected",
                "errors":errors,
                "mode":"paper_only",
                "order_authority":"blocked",
                "execution_authority":"none",
                "real_order_enabled":False,
                "live_execution_allowed":False,
                "updated_at":now(),
                "owner":"W208_PAPER_CONTROL_API"
            }
            atomic_write(STATE,out)
            return json_resp(self,422,out)

        cmd={
            "schema_version":"z.os.alimi.w208.paper_control_command.v1",
            "status":"pending",
            "pending":True,
            "enabled":True,
            "mode":"paper_only",
            "scope":"next_position",
            "action":action,
            "leverage_x":lev,
            "size_pct":size,
            "paper_base_equity_usdt":paper_base,
            "apply_at_next_position":True,
            "command_id":"w208."+shash({"action":action,"lev":lev,"size":size,"ts":now()}),
            "source":"ALIMI_UI_W208",
            "dry_run":dry,
            "order_authority":"blocked",
            "execution_authority":"none",
            "real_order_enabled":False,
            "live_execution_allowed":False,
            "updated_at":now(),
            "owner":"W208_PAPER_CONTROL_API"
        }

        if dry:
            out=dict(cmd)
            out["status"]="dryrun_ok"
            out["pending"]=False
            atomic_write(STATE,out)
            return json_resp(self,200,out)

        atomic_write(CMD,cmd)
        out=dict(cmd)
        out["status"]="accepted"
        atomic_write(STATE,out)
        return json_resp(self,200,out)

if __name__ == "__main__":
    host="127.0.0.1"
    port=8792
    srv=ThreadingHTTPServer((host,port),Handler)
    srv.serve_forever()
