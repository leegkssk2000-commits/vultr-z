#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

CANONICAL_SOURCE = "shadow_aggregate_snapshot/latest.json"
STALE_MARKERS = (
    "q4r3_shadow_closed_ledger_latest.json",
    "telegram_pos_status_latest.json",
    "forward_r_ledger.jsonl",
)
ZERO_NUMERIC_KEYS = {
    "sample_count", "closed_count", "closed", "closed_shadow", "shadow_closed",
    "wins", "losses", "breakeven", "row_count", "rows_count", "rows",
    "recent_rows", "candidate", "candidate_count", "admitted", "admitted_count",
    "open", "open_count", "active_count", "shadow_open", "paper_open", "live_open",
    "writer_count", "last12", "last12_r", "ev", "ev_r", "expectancy", "expectancy_r",
    "pnl", "pnl_r", "total_r", "net_r", "gross_r", "winrate", "winrate_pct",
    "wr", "wr_pct", "win_rate"
}
EMPTY_KEYS = {
    "recent_ledger_trace", "ledger_rows", "trace_rows", "recent_rows_data",
    "closed_trades", "recent_trades", "events", "positions", "current_positions",
    "trade_rows", "closed_rows", "history_rows"
}
TRACE_KEYS = {"latest_trace_id", "last_trace_id", "trace_id"}
SOURCE_KEYS = {"src", "source", "display_source", "ledger_source", "source_path"}


def norm(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def atomic_json(path: Path, payload: Any, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.chmod(mode)
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(mode)
    finally:
        tmp.unlink(missing_ok=True)


def trade_like_list(value: list[Any]) -> bool:
    for item in value:
        if not isinstance(item, dict):
            continue
        keys = {norm(str(key)) for key in item}
        score = sum(token in keys for token in ("symbol", "strategy", "side", "reason", "pnl_r"))
        if score >= 2:
            return True
    return False


def scrub_text(value: str) -> str:
    for marker in STALE_MARKERS:
        value = value.replace(marker, CANONICAL_SOURCE)
    value = re.sub(r"\bclosed\s*=\s*-?\d+", "closed=0", value, flags=re.I)
    value = re.sub(r"\brecent_rows\s*=\s*-?\d+", "recent_rows=0", value, flags=re.I)
    value = re.sub(r"\brows\s*=\s*-?\d+", "rows=0", value, flags=re.I)
    value = re.sub(r"\bpnl(?:_r)?\s*=\s*[+-]?\d+(?:\.\d+)?R?", "pnl=0R", value, flags=re.I)
    value = re.sub(r"\blast12\s*=\s*[+-]?\d+(?:\.\d+)?R?", "last12=0R", value, flags=re.I)
    value = re.sub(r"\bev\s*=\s*[+-]?\d+(?:\.\d+)?R?", "ev=0R", value, flags=re.I)
    value = re.sub(r"\bwr\s*=\s*[+-]?\d+(?:\.\d+)?%?", "wr=0%", value, flags=re.I)
    value = re.sub(r"\blast_close\s*=.*?(?=\s(?:state|action|recent_rows|order|src)=|$)", "last_close=none", value, flags=re.I)
    value = value.replace("SL_TOUCH_CLOSED", "NONE").replace("TP_TOUCH_CLOSED", "NONE")
    return value


def scrub(value: Any, snapshot: dict[str, Any], key: str = "") -> Any:
    normalized = norm(key)
    if isinstance(value, dict):
        cleaned = {child_key: scrub(child_value, snapshot, str(child_key)) for child_key, child_value in value.items()}
        return cleaned
    if isinstance(value, list):
        if normalized in EMPTY_KEYS or trade_like_list(value):
            return []
        return [scrub(item, snapshot, key) for item in value]
    if normalized in TRACE_KEYS or "trace_id" in normalized:
        return None
    if normalized in SOURCE_KEYS or normalized.endswith("_source"):
        return CANONICAL_SOURCE
    if normalized in {"last_close", "last_closed", "last_trade", "last_event"}:
        return "none"
    if normalized in {"epoch", "epoch_id"}:
        return snapshot.get("epoch_id")
    if normalized == "runtime_active":
        return False
    if normalized in {"order", "order_authority"}:
        return "blocked"
    if normalized in {"exec", "execution_authority"}:
        return "none"
    if normalized in {"state", "status"} and isinstance(value, str):
        return "PREBIND"
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and (
        normalized in ZERO_NUMERIC_KEYS or normalized.endswith("_count") or
        normalized.endswith("_pct") or normalized.endswith("_r")
    ):
        return 0.0 if isinstance(value, float) else 0
    if isinstance(value, str):
        return scrub_text(value)
    return value


def build_payload(template: Any, snapshot: dict[str, Any], surface: str) -> dict[str, Any]:
    base = scrub(deepcopy(template), snapshot) if isinstance(template, dict) else {}
    base.update({
        "schema": f"q4r3_exact25_{surface}_display_contract_v2",
        "display_source": CANONICAL_SOURCE,
        "source": CANONICAL_SOURCE,
        "src": CANONICAL_SOURCE,
        "source_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "epoch_id": snapshot.get("epoch_id"),
        "mode": "shadow",
        "state": "PREBIND",
        "sample_count": 0,
        "closed_count": 0,
        "active_count": 0,
        "candidate": 0,
        "admitted": 0,
        "open": 0,
        "shadow_open": 0,
        "paper_open": 0,
        "live_open": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "rows": 0,
        "recent_rows": 0,
        "last12": 0.0,
        "last12_r": 0.0,
        "ev": 0.0,
        "ev_r": 0.0,
        "wr": 0.0,
        "winrate_pct": 0.0,
        "pnl_r": 0.0,
        "net_r": 0.0,
        "latest_trace_id": None,
        "last_close": "none",
        "order_authority": "blocked",
        "execution_authority": "none",
        "runtime_active": False,
        "recent_ledger_trace": [],
        "ledger_rows": [],
        "trace_rows": [],
        "closed_trades": [],
        "recent_trades": [],
        "events": [],
    })
    if surface == "telegram":
        base["action"] = "hold"
    return base


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--alimi-template", type=Path, required=True)
    parser.add_argument("--telegram-template", type=Path, required=True)
    parser.add_argument("--alimi-output", type=Path, required=True)
    parser.add_argument("--telegram-output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = load_json(args.snapshot)
    if snapshot.get("owner_id") != "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER":
        raise SystemExit("SNAPSHOT_OWNER_INVALID")
    if snapshot.get("sample_count") != 0 or snapshot.get("closed_count") != 0:
        raise SystemExit("SNAPSHOT_NOT_ZERO")
    if snapshot.get("runtime_active") is not False or snapshot.get("formal_ledger_bound") is not False:
        raise SystemExit("SNAPSHOT_AUTHORITY_INVALID")
    alimi = build_payload(load_json(args.alimi_template), snapshot, "alimi")
    telegram = build_payload(load_json(args.telegram_template), snapshot, "telegram")
    atomic_json(args.alimi_output, alimi)
    atomic_json(args.telegram_output, telegram)
    print(json.dumps({"state": "PASS", "alimi_rows": alimi["rows"], "telegram_recent_rows": telegram["recent_rows"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
