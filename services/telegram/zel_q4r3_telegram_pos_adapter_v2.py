#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

API = Path("/var/www/z-os-alimi/api")
DISPLAY_STATUS = Path("/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json")
STATE = API / "q4r3_telegram_pos_adapter_v2_state.json"
REPORT = API / "q4r3_telegram_pos_adapter_v2_latest.json"
LEDGER = API / "q4r3_shadow_closed_ledger_latest.json"
TRACE = API / "q4r3_recent_ledger_trace_latest.json"
VIEW = API / "view_contract_latest.json"
OWNER = "ZEL_Q4R3_TELEGRAM_POS_ADAPTER_V2"
SUPPORTED_COMMANDS = ("/pos", "/pnl", "/view")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def awrite(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def nested_first(value: Any, keys: set[str], default: Any = None) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys and child is not None:
                return child
        for child in value.values():
            found = nested_first(child, keys, default=None)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = nested_first(child, keys, default=None)
            if found is not None:
                return found
    return default


def number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.strip().rstrip("Rr%").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def plain(value: Any, default: float = 0.0) -> str:
    result = number(value, default)
    if result.is_integer():
        return str(int(result))
    return f"{result:.9f}".rstrip("0").rstrip(".")


def fmt_r(value: Any) -> str:
    return plain(value) + "R"


def fmt_pct(value: Any) -> str:
    return plain(value) + "%"


def last_close_text(value: Any) -> str:
    if value in (None, "", "none", "None", {}):
        return "none"
    if not isinstance(value, dict):
        return str(value)
    parts = [str(value[key]) for key in ("symbol", "strategy", "side", "reason") if value.get(key) not in (None, "")]
    pnl = first(value, "realized_r", "pnl_r", "net_r", "pnl")
    if pnl is not None:
        parts.append(fmt_r(pnl))
    return " ".join(parts) if parts else "none"


def canonical_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return load(DISPLAY_STATUS), load(LEDGER), load(TRACE), load(VIEW)


def common_safety(status: dict[str, Any], view: dict[str, Any]) -> tuple[str, str, bool]:
    order = first(status, "order_authority", default=nested_first(view, {"order_authority"}, "blocked"))
    execution = first(status, "execution_authority", default=nested_first(view, {"execution_authority"}, "none"))
    real_order = nested_first(view, {"real_order_enabled"}, False)
    return str(order or "blocked"), str(execution or "none"), bool(real_order)


def pos_text() -> str:
    status, ledger, trace, view = canonical_inputs()
    closed = first(status, "closed_count", "closed", default=first(ledger, "closed_count", "closed", default=0))
    pnl = first(status, "pnl_r", "net_r", "pnl", default=first(ledger, "pnl_r", "net_r", "pnl", default=0))
    last_close = first(status, "last_close", "last_closed", default=first(ledger, "last_close", "last_closed", default="none"))
    active = number(first(status, "open", default=0)) == 1 and number(first(status, "shadow_open", default=0)) == 1
    order, execution, _ = common_safety(status, view)

    lines = [
        "ZEL POS",
        f"lane={first(status, 'lane', default='ZEL_FOCUS')} mode={first(status, 'mode', default='shadow')} epoch={first(status, 'epoch', default='Q4R3')}",
        f"candidate={plain(first(status, 'candidate', default=0))} admitted={plain(first(status, 'admitted', default=0))} open={plain(first(status, 'open', default=0))} closed={plain(closed)} pnl={fmt_r(pnl)}",
        f"shadow_open={plain(first(status, 'shadow_open', default=0))} paper_open={plain(first(status, 'paper_open', default=0))} live_open={plain(first(status, 'live_open', default=0))}",
    ]
    if active:
        lines.extend([
            f"symbol={first(status, 'symbol', default='none')} strategy={first(status, 'strategy', default='none')} side={first(status, 'side', default='none')}",
            f"entry={first(status, 'entry', default='none')} sl={first(status, 'sl', default='none')} tp={first(status, 'tp', default='none')} price={first(status, 'price', default='none')}",
        ])
    else:
        lines.append("last_close=" + last_close_text(last_close))
    lines.extend([
        f"state={first(status, 'state', 'status', default='HOLD_ZERO_EPOCH_PENDING')} action={first(status, 'action', default='hold')}",
        f"order={order} exec={execution}",
        "src=telegram_status_latest.json",
    ])
    return "\n".join(lines)


def pnl_text() -> str:
    status, ledger, trace, view = canonical_inputs()
    rows = first(trace, "rows", default=first(ledger, "rows", default=[]))
    row_count = len(rows) if isinstance(rows, list) else plain(first(trace, "recent_rows", "row_count", default=0))
    closed = first(status, "closed_count", "closed", default=first(ledger, "closed_count", "closed", default=0))
    pnl = first(status, "pnl_r", "net_r", "pnl", default=first(ledger, "pnl_r", "net_r", "pnl", default=0))
    last12 = first(status, "last12_r", "last12_pnl_r", default=first(trace, "last12_r", "last12_pnl_r", default=0))
    winrate = first(status, "winrate_pct", "wr_pct", "wr", default=first(trace, "winrate_pct", "wr_pct", "wr", default=0))
    ev = first(status, "ev_r", "ev", default=first(trace, "ev_r", "ev", default=0))
    last_close = first(status, "last_close", "last_closed", default=first(ledger, "last_close", "last_closed", default="none"))
    order, execution, _ = common_safety(status, view)
    return "\n".join([
        "ZEL PNL",
        f"epoch={first(status, 'epoch', default='Q4R3')} mode={first(status, 'mode', default='shadow')}",
        f"closed={plain(closed)} pnl={fmt_r(pnl)}",
        f"recent_rows={row_count} last12={fmt_r(last12)} wr={fmt_pct(winrate)} ev={fmt_r(ev)}",
        "last_close=" + last_close_text(last_close),
        f"state={first(status, 'state', 'status', default='HOLD_ZERO_EPOCH_PENDING')} action={first(status, 'action', default='hold')}",
        f"order={order} exec={execution}",
        "src=telegram_status_latest.json",
    ])


def view_text() -> str:
    status, ledger, trace, view = canonical_inputs()
    configured = nested_first(view, {"configured_writer_count", "writer_registry_count", "configured_count"}, 7)
    active_writers = nested_first(view, {"active_writer_count", "writer_count", "active_count"}, 0)
    closed = first(status, "closed_count", "closed", default=first(ledger, "closed_count", "closed", default=0))
    rows = first(trace, "rows", default=[])
    row_count = len(rows) if isinstance(rows, list) else first(trace, "recent_rows", "row_count", default=0)
    order, execution, real_order = common_safety(status, view)
    return "\n".join([
        "ZEL VIEW",
        f"epoch={first(status, 'epoch', default='Q4R3')} lane={first(status, 'lane', default='ZEL_FOCUS')} mode={first(status, 'mode', default='shadow')}",
        f"candidate={plain(first(status, 'candidate', default=0))} admitted={plain(first(status, 'admitted', default=0))} open={plain(first(status, 'open', default=0))} closed={plain(closed)}",
        f"shadow_open={plain(first(status, 'shadow_open', default=0))} paper_open={plain(first(status, 'paper_open', default=0))} live_open={plain(first(status, 'live_open', default=0))}",
        f"writers_configured={plain(configured)} writers_active={plain(active_writers)} recent_rows={plain(row_count)}",
        f"state={first(status, 'state', 'status', default='HOLD_ZERO_EPOCH_PENDING')} action={first(status, 'action', default='hold')}",
        f"order={order} exec={execution} real_order={str(real_order).lower()}",
        "src=view_contract_latest.json",
    ])


def normalize_command(text: str) -> str:
    head = (text or "").strip().split(maxsplit=1)[0].lower()
    return head.split("@", 1)[0]


def render_command(command: str) -> tuple[str, str]:
    renderers: dict[str, tuple[str, Callable[[], str]]] = {
        "/pos": ("POS", pos_text),
        "/pnl": ("PNL", pnl_text),
        "/view": ("VIEW", view_text),
    }
    response_kind, renderer = renderers[command]
    return response_kind, renderer()


def api(token: str, method: str, params: dict[str, Any] | None = None, request_timeout: int = 15) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "ZEL-Q4R3-TG-POS-V2/1.1"})
    raw = urllib.request.urlopen(request, timeout=request_timeout).read().decode("utf-8", "ignore")
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def main() -> None:
    token = os.environ.get("ZEL_TELEGRAM_BOT_TOKEN", "")
    allowed_chat_id = os.environ.get("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "")
    source = "env:ZEL_TELEGRAM_BOT_TOKEN"
    if not token or not allowed_chat_id:
        awrite(REPORT, {
            "owner": OWNER,
            "updated_at": now(),
            "status": "HOLD_CANONICAL_ENVIRONMENT_NOT_BOUND",
            "token_source": source,
            "sent_count": 0,
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
        })
        time.sleep(5)
        return

    try:
        api(token, "deleteWebhook", {"drop_pending_updates": "false"}, request_timeout=15)
    except Exception:
        pass

    state = load(STATE)
    offset = int(state.get("offset", 0) or 0)
    sent = 0
    error: str | None = None
    last_command: str | None = None
    last_response_kind: str | None = None
    last_response_title: str | None = None

    try:
        result = api(
            token,
            "getUpdates",
            {"timeout": 25, "offset": offset, "allowed_updates": json.dumps(["message"])},
            request_timeout=35,
        )
        if result.get("ok"):
            for update in result.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message") or {}
                command = normalize_command(str(message.get("text") or ""))
                incoming_chat_id = str((message.get("chat") or {}).get("id") or "")
                if command not in SUPPORTED_COMMANDS or incoming_chat_id != str(allowed_chat_id):
                    continue
                response_kind, response_text = render_command(command)
                api(token, "sendMessage", {
                    "chat_id": allowed_chat_id,
                    "text": response_text,
                    "disable_web_page_preview": "true",
                }, request_timeout=15)
                sent += 1
                last_command = command
                last_response_kind = response_kind
                last_response_title = response_text.splitlines()[0] if response_text else None
    except Exception as exc:
        error = str(exc)[:300]

    awrite(STATE, {"offset": offset, "updated_at": now()})
    awrite(REPORT, {
        "owner": OWNER,
        "updated_at": now(),
        "status": "PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING" if error is None else "HOLD_TELEGRAM_POS_ADAPTER_V2_ERROR",
        "token_source": source,
        "offset": offset,
        "sent_count": sent,
        "error": error,
        "last_command": last_command,
        "last_response_kind": last_response_kind,
        "last_response_title": last_response_title,
        "supported_commands": list(SUPPORTED_COMMANDS),
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "next_if_pass": "SEND_/pos_/pnl_/view_AND_EXPECT_DISTINCT_REPLIES",
    })


def run_forever() -> None:
    while True:
        main()
        time.sleep(1)


if __name__ == "__main__":
    run_forever()
