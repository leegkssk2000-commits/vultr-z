#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*%?\s*", value)
        return float(match.group(1)) if match else None
    return None


def nested_values(value: Any, wanted: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in wanted and not isinstance(child, (dict, list)):
                found.append(child)
            found.extend(nested_values(child, wanted))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_values(child, wanted))
    return found


def last_value(value: Any, *names: str) -> Any:
    values = nested_values(value, {name.lower() for name in names})
    return values[-1] if values else None


def closed_event(payload: dict[str, Any]) -> bool:
    values = nested_values(payload, {"state", "status", "event", "event_type", "phase", "kind", "action"})
    tokens = {"close", "closed", "position_close", "position_closed", "trade_closed", "exit", "exited"}
    return any(str(value).strip().lower() in tokens for value in values)


def ledger_metrics(path: Path) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    closed: dict[str, tuple[int, float]] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for index, line in enumerate(handle, 1):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            count = number(last_value(payload, "closed_count", "state_closed", "closed_positions"))
            winrate = number(last_value(payload, "winrate_pct", "winrate", "win_rate", "wr_pct"))
            total_r = number(last_value(payload, "total_r", "net_r", "pnl_r", "cumulative_r"))
            trace = last_value(payload, "latest_trace_id", "trace_id", "latest_position_id")
            if count is not None and winrate is not None and total_r is not None:
                if 0 <= winrate <= 1 and count > 1:
                    winrate *= 100
                summaries.append({"closed_count": int(round(count)), "winrate_pct": winrate,
                                  "total_r": total_r, "latest_trace_id": str(trace or ""), "mode": "summary"})
            if closed_event(payload):
                pnl = number(last_value(payload, "net_r", "pnl_r", "realized_r", "result_r", "r_value"))
                identity = last_value(payload, "position_id", "trade_id", "event_id", "decision_id", "id")
                if pnl is not None:
                    closed[str(identity or f"line:{index}")] = (index, pnl)
    if summaries:
        result = summaries[-1]
        if not result["latest_trace_id"] and closed:
            result["latest_trace_id"] = max(closed.items(), key=lambda item: item[1][0])[0]
        return result
    ordered = sorted(closed.items(), key=lambda item: item[1][0])
    count = len(ordered)
    return {"closed_count": count,
            "winrate_pct": (sum(1 for _, (_, pnl) in ordered if pnl > 0) * 100 / count) if count else 0.0,
            "total_r": sum(pnl for _, (_, pnl) in ordered),
            "latest_trace_id": ordered[-1][0] if ordered else "", "mode": "events"}


def plain_text(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def text_metrics(text: str) -> dict[str, Any]:
    plain = plain_text(text)
    expressions = {
        "closed_count": r"\b(?:closed(?:\s+count|\s+positions?)?|closed_count)\s*[:=|]?\s*(\d+)\b",
        "winrate_pct": r"\b(?:win\s*rate|winrate|wr)\s*[:=|]?\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        "total_r": r"\b(?:total\s*r|total_r|net\s*r|net_r|pnl_r|pnl)\s*[:=|]?\s*([+-]?\d+(?:\.\d+)?)\s*R?\b",
        "latest_trace_id": r"\b(?:latest\s*trace|latest_trace_id|trace_id|latest\s*position|position_id)\s*[:=|]?\s*([A-Za-z0-9_.:-]+)",
    }
    result: dict[str, Any] = {}
    for key, expression in expressions.items():
        matches = re.findall(expression, plain, flags=re.I)
        if matches:
            result[key] = int(matches[-1]) if key == "closed_count" else (float(matches[-1]) if key in {"winrate_pct", "total_r"} else matches[-1])
    return result


def parity(canonical: dict[str, Any], observed: dict[str, Any], text: str,
           winrate_tolerance: float = 0.02, total_r_tolerance: float = 0.000001) -> list[str]:
    problems: list[str] = []
    if observed.get("closed_count") != canonical.get("closed_count"):
        problems.append("closed_count")
    if "winrate_pct" not in observed or abs(float(observed["winrate_pct"]) - float(canonical["winrate_pct"])) > winrate_tolerance:
        problems.append("winrate_pct")
    if "total_r" not in observed or abs(float(observed["total_r"]) - float(canonical["total_r"])) > total_r_tolerance:
        problems.append("total_r")
    trace = str(canonical.get("latest_trace_id", ""))
    if not trace or (observed.get("latest_trace_id") != trace and trace not in text):
        problems.append("latest_trace_id")
    return problems
