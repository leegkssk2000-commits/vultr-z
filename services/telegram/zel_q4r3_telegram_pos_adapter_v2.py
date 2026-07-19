#!/usr/bin/env python3

# R7.3B4U9 final outbound ZEL POS single-source boundary
import json as _r73b4u9_json
import re as _r73b4u9_re
from pathlib import Path as _R73B4U9Path
_R73B4U9_ARTIFACT = _R73B4U9Path('/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json')

def _r73b4u9_first(payload, *keys, default=None):
    for key in keys:
        if key in payload:
            return payload[key]
    return default

def _r73b4u9_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def _r73b4u9_plain(value):
    number = _r73b4u9_number(value)
    return str(int(number)) if number.is_integer() else (f"{number:.9f}".rstrip("0").rstrip("."))

def _r73b4u9_r(value):
    return _r73b4u9_plain(value) + "R"

def _r73b4u9_pct(value):
    return _r73b4u9_plain(value) + "%"

def _r73b4u9_last_close(value):
    if value in (None, "", "none", "None") or value == {}:
        return "none"
    if isinstance(value, dict):
        fields = []
        for key in ("symbol", "strategy", "side", "reason"):
            if value.get(key) not in (None, ""):
                fields.append(str(value[key]))
        pnl = _r73b4u9_first(value, "pnl_r", "net_r", "pnl")
        if pnl is not None:
            fields.append(_r73b4u9_r(pnl))
        return " ".join(fields) if fields else "none"
    return str(value)

def _r73b4u9_visible_pos(text):
    if not isinstance(text, str) or "ZEL POS" not in text:
        return text
    try:
        payload = _r73b4u9_json.loads(_R73B4U9_ARTIFACT.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    closed = _r73b4u9_first(payload, "closed_count", "closed", default=0)
    pnl = _r73b4u9_first(payload, "pnl_r", "net_r", "pnl", default=0)
    last_close = _r73b4u9_last_close(_r73b4u9_first(payload, "last_close", "last_closed", default="none"))
    rows = _r73b4u9_first(payload, "recent_rows", "rows", default=0)
    last12 = _r73b4u9_first(payload, "last12_r", "last12", default=0)
    winrate = _r73b4u9_first(payload, "winrate_pct", "wr_pct", "wr", "winrate", "win_rate", default=0)
    ev = _r73b4u9_first(payload, "ev_r", "ev", "expectancy_r", "expectancy", default=0)
    state = _r73b4u9_first(payload, "state", default=None)
    action = _r73b4u9_first(payload, "action", default=None)
    rendered = []
    for line in text.splitlines():
        if line.startswith("last_close="):
            rendered.append("last_close=" + last_close)
            continue
        if line.startswith("recent_rows="):
            rendered.append(
                "recent_rows=" + _r73b4u9_plain(rows)
                + " last12=" + _r73b4u9_r(last12)
                + " wr=" + _r73b4u9_pct(winrate)
                + " ev=" + _r73b4u9_r(ev)
            )
            continue
        if "telegram_status_latest.json" in line and (line.startswith("/") or line.startswith("src=")):
            rendered.append("src=telegram_status_latest.json")
            continue
        line = _r73b4u9_re.sub(r"\bclosed=[^\s]+", "closed=" + _r73b4u9_plain(closed), line)
        line = _r73b4u9_re.sub(r"\bpnl=[^\s]+", "pnl=" + _r73b4u9_r(pnl), line)
        if line.startswith("state="):
            if state is not None:
                line = _r73b4u9_re.sub(r"\bstate=[^\s]+", "state=" + str(state), line)
            if action is not None:
                line = _r73b4u9_re.sub(r"\baction=[^\s]+", "action=" + str(action), line)
        rendered.append(line)
    return "\n".join(rendered)
import json, os, re, time, tempfile, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

API=Path("/var/www/z-os-alimi/api")
STATE=API/"q4r3_telegram_pos_adapter_v2_state.json"
REPORT=API/"q4r3_telegram_pos_adapter_v2_latest.json"
OWNER="ZEL_Q4R3_TELEGRAM_POS_ADAPTER_V2"

def now(): return datetime.now(timezone.utc).isoformat()

def load(p):
    try: return json.loads(p.read_text(errors="ignore"))
    except Exception: return {}

def awrite(p,o):
    fd,tmp=tempfile.mkstemp(prefix=p.name+".",dir=str(p.parent))
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(o,f,ensure_ascii=False,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,p); os.chmod(p,0o644)

def find_token():
    env=os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if env and re.match(r"^\d+:[A-Za-z0-9_-]{20,}$",env):
        return env, "env"
    roots=[Path("/etc"),Path("/var/www/z-os-alimi"),Path("/home/z/z"),Path("/usr/local/bin")]
    pat=re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
    for root in roots:
        if not root.exists(): continue
        for p in root.rglob("*"):
            if not p.is_file(): continue
            s=str(p)
            if any(x in s.lower() for x in ["backup","graveyard","archive",".bak",".dead","node_modules","__pycache__"]): continue
            if p.stat().st_size > 2_000_000: continue
            try: txt=p.read_text(errors="ignore")
            except Exception: continue
            m=pat.search(txt)
            if m:
                return m.group(0), str(p)
    return None, "not_found"

def api(token, method, params=None):
    url=f"https://api.telegram.org/bot{token}/{method}"
    data=urllib.parse.urlencode(params or {}).encode()
    req=urllib.request.Request(url,data=data,headers={"User-Agent":"ZEL-Q4R3-TG-POS-V2/1.0"})
    raw=urllib.request.urlopen(req,timeout=15).read().decode("utf-8","ignore")
    return json.loads(raw)

def pos_text():
    d=load(API/"/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
    led=load(API/"q4r3_shadow_closed_ledger_latest.json")
    tr=load(API/"q4r3_recent_ledger_trace_latest.json")

    closed=d.get("closed",led.get("closed"))
    pnl=d.get("pnl_r",led.get("pnl_r"))
    last=d.get("last_close") if isinstance(d.get("last_close"),dict) else led.get("last_close") if isinstance(led.get("last_close"),dict) else {}
    rows=tr.get("rows") if isinstance(tr.get("rows"),list) else led.get("rows") if isinstance(led.get("rows"),list) else []
    active = d.get("open")==1 and d.get("shadow_open")==1 and d.get("admitted")==1

    lines=[
      "ZEL POS",
      f"lane={d.get('lane','ZEL_FOCUS')} mode={d.get('mode','shadow')} epoch={d.get('epoch','Q4R3')}",
      f"candidate={d.get('candidate',0)} admitted={d.get('admitted',0)} open={d.get('open',0)} closed={closed} pnl={pnl}R",
      f"shadow_open={d.get('shadow_open',0)} paper_open={d.get('paper_open',0)} live_open={d.get('live_open',0)}",
    ]
    if active:
        lines += [
          f"current={{'entry': {d.get('entry')}, 'price': {d.get('price')}, 'rr': {d.get('rr')}, 'side': '{d.get('side')}', 'sl': {d.get('sl')}, 'strategy': '{d.get('strategy')}', 'symbol': '{d.get('symbol')}', 'tp': {d.get('tp')}}}",
          f"symbol={d.get('symbol')} strategy={d.get('strategy')} side={d.get('side')}",
          f"entry={d.get('entry')} sl={d.get('sl')} tp={d.get('tp')} price={d.get('price')}",
          f"state={d.get('status')} action={d.get('action','hold')}",
        ]
    else:
        lines += [
          "current={}",
          f"last_close={last.get('symbol')} {last.get('strategy')} {last.get('side')} {last.get('reason')} {last.get('realized_r')}R",
          f"state={d.get('status')} action={d.get('action','hold')}",
        ]
    lines += [
      f"recent_rows={len(rows)} last12={d.get('last12_pnl_r', tr.get('last12_pnl_r'))}R wr={d.get('wr_pct', tr.get('wr_pct'))}% ev={d.get('ev_r', tr.get('ev_r'))}R",
      f"order={d.get('order_authority','blocked')} exec={d.get('execution_authority','none')}",
      "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"
    ]
    return _r73b4u9_visible_pos("\n".join(lines))

def main():
    token = os.environ.get("ZEL_TELEGRAM_BOT_TOKEN", "")
    src = "env:ZEL_TELEGRAM_BOT_TOKEN"
    if not token:
        awrite(REPORT,{"owner":OWNER,"updated_at":now(),"status":"HOLD_TOKEN_NOT_FOUND","token_source":src})
        time.sleep(60)
        return

    try:
        # polling 전환. webhook stale이면 getUpdates가 막힘.
        api(token,"deleteWebhook",{"drop_pending_updates":"false"})
    except Exception:
        pass

    st=load(STATE)
    offset=int(st.get("offset",0) or 0)
    sent=0
    err=None

    try:
        res=api(token,"getUpdates",{"timeout":25,"offset":offset,"allowed_updates":json.dumps(["message"])})
        if res.get("ok"):
            for upd in res.get("result",[]):
                offset=max(offset, int(upd.get("update_id",0))+1)
                msg=upd.get("message") or {}
                text=(msg.get("text") or "").strip()
                chat=msg.get("chat") or {}
                chat_id = os.environ.get("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "")
                if not chat_id:
                    continue
                if text.startswith("/pos") or text.startswith("/view") or text.startswith("/pnl"):
                    api(token,"sendMessage",{
                        "chat_id":chat_id,
                        "text":pos_text(),
                        "disable_web_page_preview":"true"
                    })
                    sent+=1
    except Exception as e:
        err=str(e)[:300]

    awrite(STATE,{"offset":offset,"updated_at":now()})
    awrite(REPORT,{
        "owner":OWNER,
        "updated_at":now(),
        "status":"PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING" if err is None else "HOLD_TELEGRAM_POS_ADAPTER_V2_ERROR",
        "token_source":src,
        "offset":offset,
        "sent_count":sent,
        "error":err,
        "order_authority":"blocked",
        "execution_authority":"none",
        "real_order_enabled":False,
        "next_if_pass":"SEND_/pos_AND_EXPECT_V2_REPLY"
    })

while True:
    main()
    time.sleep(1)
