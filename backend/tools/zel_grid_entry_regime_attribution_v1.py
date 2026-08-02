from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_ENTRY_REGIME_ATTRIBUTION_V1"
SCHEMA = "zel.grid_entry_regime.attribution.receipt.v1"
STRATEGY_ID = "grid_rebalance"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or "").strip()


def window_id(row: Mapping[str, Any]) -> str:
    return str(row.get("window_id") or row.get("window") or "unknown")


def entry_regime(row: Mapping[str, Any]) -> str:
    features = row.get("entry_features")
    if isinstance(features, Mapping):
        value = features.get("regime") or features.get("market_regime")
        if value is not None:
            return str(value)
    return "missing"


def exit_regime(row: Mapping[str, Any]) -> str:
    return str(row.get("regime") or row.get("market_regime") or "missing")


def pnl_r(row: Mapping[str, Any]) -> float:
    return safe_float(row.get("realized_R") if row.get("realized_R") is not None else row.get("net_R") if row.get("net_R") is not None else row.get("pnl_r"))


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("exit_ts") or row.get("exit_time") or row.get("captured_at") or ""),
        event_id(row),
    )


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=timestamp_key)
    values = [pnl_r(row) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    pf = gross_profit / gross_loss_abs if gross_loss_abs > 0 else None
    return {
        "trade_count": len(rows),
        "net_R": sum(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "profit_factor": pf,
        "max_drawdown_R": max_dd,
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "") == STRATEGY_ID:
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2/trades.jsonl.gz"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    rows = read_rows(args.trades)
    ids = [event_id(row) for row in rows]
    entry_counts = Counter(entry_regime(row) for row in rows)
    exit_counts = Counter(exit_regime(row) for row in rows)
    by_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_entry_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        regime = entry_regime(row)
        by_entry[regime].append(row)
        by_entry_window[(regime, window_id(row))].append(row)

    entry_neutral = [row for row in rows if entry_regime(row) == "neutral"]
    exit_neutral = [row for row in rows if exit_regime(row) == "neutral"]
    entry_set = {event_id(row) for row in entry_neutral}
    exit_set = {event_id(row) for row in exit_neutral}
    union = entry_set | exit_set
    intersection = entry_set & exit_set

    blockers: list[str] = []
    if len(rows) != 580:
        blockers.append("GRID_TRADE_COUNT_MISMATCH")
    if not all(ids) or len(set(ids)) != len(ids):
        blockers.append("GRID_EVENT_ID_INTEGRITY_FAILED")
    if entry_counts.get("missing", 0) != 0:
        blockers.append("GRID_ENTRY_REGIME_MISSING")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_ENTRY_REGIME_ATTRIBUTION" if not blockers else "HOLD_GRID_ENTRY_REGIME_ATTRIBUTION_INCOMPLETE",
        "strategy_id": STRATEGY_ID,
        "trade_count": len(rows),
        "entry_regime_counts": dict(sorted(entry_counts.items())),
        "exit_regime_counts": dict(sorted(exit_counts.items())),
        "all_metrics": metrics(rows),
        "entry_regime_metrics": {key: metrics(value) for key, value in sorted(by_entry.items())},
        "entry_regime_window_metrics": {f"{regime}|{window}": metrics(value) for (regime, window), value in sorted(by_entry_window.items())},
        "entry_neutral_metrics": metrics(entry_neutral),
        "exit_neutral_metrics": metrics(exit_neutral),
        "entry_exit_neutral_comparison": {
            "entry_neutral_count": len(entry_set),
            "exit_neutral_count": len(exit_set),
            "intersection_count": len(intersection),
            "entry_only_count": len(entry_set - exit_set),
            "exit_only_count": len(exit_set - entry_set),
            "jaccard": len(intersection) / len(union) if union else None,
            "entry_neutral_event_set_sha256": stable_sha(sorted(entry_set)),
            "exit_neutral_event_set_sha256": stable_sha(sorted(exit_set)),
            "intersection_event_set_sha256": stable_sha(sorted(intersection)),
        },
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "REVIEW_ENTRY_NEUTRAL_ECONOMIC_EDGE" if not blockers else "RESOLVE_ENTRY_REGIME_ATTRIBUTION_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
