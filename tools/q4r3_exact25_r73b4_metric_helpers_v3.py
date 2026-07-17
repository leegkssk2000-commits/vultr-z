#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

BASE = Path(__file__).with_name("q4r3_exact25_r73b4_metric_helpers_v2.py")
SPEC = importlib.util.spec_from_file_location("r73b4_metrics_v2", BASE)
assert SPEC and SPEC.loader
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)

number = base.number
nested_values = base.nested_values
last_value = base.last_value
closed_event = base.closed_event
ledger_metrics = base.ledger_metrics
plain_text = base.plain_text
parity = base.parity


def text_metrics(text: str) -> dict[str, Any]:
    result = base.text_metrics(text)
    searchable = plain_text(text) + "\n" + text
    expressions = {
        "closed_count": r"(?:closed_count|state_closed|closed_positions)\s*[\"']?\s*[:=]\s*[\"']?\s*(\d+)",
        "winrate_pct": r"(?:winrate_pct|win_rate|wr_pct)\s*[\"']?\s*[:=]\s*[\"']?\s*([0-9]+(?:\.[0-9]+)?)",
        "total_r": r"(?:total_r|net_r|pnl_r|cumulative_r)\s*[\"']?\s*[:=]\s*[\"']?\s*([+-]?\d+(?:\.\d+)?)",
        "latest_trace_id": r"(?:latest_trace_id|trace_id|latest_position_id|position_id)\s*[\"']?\s*[:=]\s*[\"']?\s*([A-Za-z0-9_.:-]+)",
    }
    for key, expression in expressions.items():
        matches = re.findall(expression, searchable, flags=re.I)
        if not matches:
            continue
        value = matches[-1]
        if key == "closed_count":
            result[key] = int(value)
        elif key in {"winrate_pct", "total_r"}:
            result[key] = float(value)
        else:
            result[key] = value
    return result
