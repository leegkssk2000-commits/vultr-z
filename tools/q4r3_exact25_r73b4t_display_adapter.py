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

COUNT_KEYS = {
    "sample_count", "closed_count", "closed", "closed_shadow", "shadow_closed",
    "wins", "losses", "breakeven", "row_count", "rows_count",
    "candidate", "candidate_count", "admitted", "admitted_count", "open", "open_count",
    "shadow_open", "paper_open", "live_open", "writer_count"
}
PNL_KEYS = {"pnl_r", "total_r", "net_r", "gross_r", "last12_r", "ev_r", "expectancy_r"}
WINRATE_KEYS = {"winrate_pct", "wr_pct", "win_rate", "winrate", "wr"}
TRACE_KEYS = {"latest_trace_id", "last_trace_id", "trace_id"}
EMPTY_LIST_KEYS = {
    "rows", "events", "closed_trades", "recent_trades", "recent_ledger_trace",
    "ledger_rows", "recent_rows", "recent_rows_data", "trace_rows", "positions", "current_positions"
}
STALE_SOURCE_TOKENS = (
    "q4r3_shadow_closed_ledger_latest.json",
    "telegram_pos_status_latest.json",
    "forward_r_ledger.jsonl",
)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def scrub_string(value: str, snapshot: dict[str, Any]) -> str:
    if any(token in value for token in STALE_SOURCE_TOKENS):
        value = value.replace("q4r3_shadow_closed_ledger_latest.json", "shadow_aggregate_snapshot/latest.json")
        value = value.replace("telegram_pos_status_latest.json", "shadow_aggregate_snapshot/latest.json")
        value = value.replace("forward_r_ledger.jsonl", "shadow_aggregate_snapshot/latest.json")
    value = re.sub(r"\bclosed\s*=\s*-?\d+", "closed=0", value, flags=re.IGNORECASE)
    value = re.sub(r"\bclosed\s*/\s*shadow\s*[:=]?\s*-?\d+", "Closed / shadow: 0", value, flags=re.IGNORECASE)
    value = re.sub(r"\brecent_rows\s*=\s*-?\d+", "recent_rows=0", value, flags=re.IGNORECASE)
    value = re.sub(r"\brows\s*=\s*-?\d+", "rows=0", value, flags=re.IGNORECASE)
    value = re.sub(r"\bpnl(?:_r)?\s*=\s*[+-]?\d+(?:\.\d+)?R?", "pnl=0R", value, flags=re.IGNORECASE)
    value = re.sub(r"\blast12\s*=\s*[+-]?\d+(?:\.\d+)?R?", "last12=0R", value, flags=re.IGNORECASE)
    value = re.sub(r"\bev\s*=\s*[+-]?\d+(?:\.\d+)?R?", "ev=0R", value, flags=re.IGNORECASE)
    value = re.sub(r"\bwr\s*=\s*[+-]?\d+(?:\.\d+)?%?", "wr=0%", value, flags=re.IGNORECASE)
    value = re.sub(r"\blast_close\s*=.*?(?=\s(?:state|action|recent_rows|order|src)=|$)", "last_close=none", value, flags=re.IGNORECASE)
    return value


def list_must_clear(normalized: str) -> bool:
    return normalized in EMPTY_LIST_KEYS or any(
        token in normalized for token in ("ledger", "closed_trade", "trade_trace", "recent_trace", "recent_event")
    )


def numeric_override(normalized: str, value: int | float, snapshot: dict[str, Any]) -> int | float | None:
    if normalized in COUNT_KEYS or any(token in normalized for token in ("closed_count", "closed_shadow", "candidate_count", "admitted_count")):
        if "closed" in normalized:
            return int(snapshot.get("closed_count", 0))
        return 0
    if normalized in PNL_KEYS or "pnl" in normalized or normalized.endswith("_r"):
        return float(snapshot.get("net_r", 0.0))
    if normalized in WINRATE_KEYS or "winrate" in normalized or normalized.endswith("_wr"):
        return float(snapshot.get("winrate_pct") or 0.0)
    if normalized in {"wins", "losses", "breakeven"}:
        return int(snapshot.get(normalized, 0))
    if any(token in normalized for token in ("shadow_open", "paper_open", "live_open", "open_count")):
        return 0
    return None


def scrub(value: Any, snapshot: dict[str, Any], key: str = "") -> Any:
    normalized = normalize_key(key)
    if isinstance(value, list):
        if list_must_clear(normalized):
            return []
        return [scrub(item, snapshot, key) for item in value]
    if isinstance(value, dict):
        return {child_key: scrub(child_value, snapshot, child_key) for child_key, child_value in value.items()}
    if isinstance(value, bool):
        if normalized == "runtime_active":
            return bool(snapshot.get("runtime_active", False))
        return value
    if isinstance(value, (int, float)):
        override = numeric_override(normalized, value, snapshot)
        return value if override is None else override
    if normalized in TRACE_KEYS or "trace_id" in normalized:
        return snapshot.get("latest_trace_id")
    if normalized in {"epoch", "epoch_id"}:
        return snapshot.get("epoch_id")
    if normalized == "mode":
        return "shadow"
    if normalized in {"order_authority", "order"}:
        return "blocked"
    if normalized in {"execution_authority", "exec"}:
        return "none"
    if normalized in {"state", "status"} and isinstance(value, str):
        return "PREBIND" if not snapshot.get("runtime_active") else snapshot.get("state", value)
    if isinstance(value, str):
        return scrub_string(value, snapshot)
    return value


def build_payload(template: Any, snapshot: dict[str, Any], surface: str) -> dict[str, Any]:
    base: dict[str, Any]
    if isinstance(template, dict):
        base = scrub(deepcopy(template), snapshot)
    else:
        base = {}
    base.update({
        "schema": f"q4r3_exact25_{surface}_display_contract_v1",
        "display_source": "shadow_aggregate_snapshot/latest.json",
        "source_snapshot_sha256": snapshot.get("snapshot_sha256"),
        "epoch_id": snapshot.get("epoch_id"),
        "mode": "shadow",
        "state": "PREBIND" if not snapshot.get("runtime_active") else snapshot.get("state", "ACTIVE"),
        "sample_count": int(snapshot.get("sample_count", 0)),
        "closed_count": int(snapshot.get("closed_count", 0)),
        "active_count": int(snapshot.get("active_count", 0)),
        "wins": int(snapshot.get("wins", 0)),
        "losses": int(snapshot.get("losses", 0)),
        "breakeven": int(snapshot.get("breakeven", 0)),
        "winrate_pct": float(snapshot.get("winrate_pct") or 0.0),
        "pnl_r": float(snapshot.get("net_r", 0.0)),
        "net_r": float(snapshot.get("net_r", 0.0)),
        "latest_trace_id": snapshot.get("latest_trace_id"),
        "order_authority": "blocked",
        "execution_authority": "none",
        "runtime_active": bool(snapshot.get("runtime_active", False)),
        "recent_rows": [],
    })
    if surface == "telegram":
        base["src"] = "shadow_aggregate_snapshot/latest.json"
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
    if snapshot.get("formal_ledger_bound") is not False:
        raise SystemExit("FORMAL_LEDGER_BOUND")
    if snapshot.get("owner_id") != "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER":
        raise SystemExit("SNAPSHOT_OWNER_INVALID")
    alimi = build_payload(load_json(args.alimi_template), snapshot, "alimi")
    telegram = build_payload(load_json(args.telegram_template), snapshot, "telegram")
    atomic_json(args.alimi_output, alimi)
    atomic_json(args.telegram_output, telegram)
    print(json.dumps({
        "state": "PASS",
        "source": str(args.snapshot),
        "alimi_closed_count": alimi["closed_count"],
        "alimi_pnl_r": alimi["pnl_r"],
        "telegram_closed_count": telegram["closed_count"],
        "telegram_pnl_r": telegram["pnl_r"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
