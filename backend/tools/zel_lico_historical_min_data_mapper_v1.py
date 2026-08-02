from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_LICO_HISTORICAL_MIN_DATA_MAPPER_V1"
REQUIRED_FIELDS = ("price", "pos_pct", "lev", "entry_ts", "funding_8h_pct", "dd_day_pct", "dd_total_pct")
LIQ_FIELDS = ("liq_price", "liq_buffer_pct")
ACCEPTED_SOURCE_PREFIXES = ("cf:/", "sheets:/")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def nested(row: Mapping[str, Any], key: str) -> Any:
    if row.get(key) not in (None, ""):
        return row.get(key)
    for container in ("entry_features", "market_context", "execution_evidence", "risk_context"):
        value = row.get(container)
        if isinstance(value, Mapping) and value.get(key) not in (None, ""):
            return value.get(key)
    return None


def evidence_index(value: Any) -> dict[str, dict[str, Any]]:
    rows: list[Any]
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("rows"), list):
        rows = value["rows"]
    elif isinstance(value, dict):
        rows = [value]
    else:
        rows = []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "")
        if event_id:
            out[event_id] = row
    return out


def source_keys(row: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (row, evidence):
        raw = source.get("src_keys") if isinstance(source.get("src_keys"), list) else []
        values.extend(str(item) for item in raw if str(item))
    return sorted(set(values))


def source_ok(field: str, keys: list[str]) -> bool:
    return any(key in keys for key in (f"cf:/{field}", f"sheets:/{field}"))


def map_trade(row: Mapping[str, Any], evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, Mapping) else {}
    merged = dict(row)
    for key, value in evidence.items():
        if key not in merged or merged.get(key) in (None, ""):
            merged[key] = value
    snapshot = {
        "price": nested(merged, "price") or nested(merged, "entry_price"),
        "pos_pct": nested(merged, "pos_pct"),
        "lev": nested(merged, "lev"),
        "entry_ts": nested(merged, "entry_ts"),
        "liq_price": nested(merged, "liq_price"),
        "liq_buffer_pct": nested(merged, "liq_buffer_pct"),
        "funding_8h_pct": nested(merged, "funding_8h_pct"),
        "dd_day_pct": nested(merged, "dd_day_pct"),
        "dd_total_pct": nested(merged, "dd_total_pct"),
    }
    keys = source_keys(row, evidence)
    missing = [field for field in REQUIRED_FIELDS if snapshot.get(field) in (None, "")]
    if not any(snapshot.get(field) not in (None, "") for field in LIQ_FIELDS):
        missing.append("liq_price|liq_buffer_pct")
    source_fields = list(REQUIRED_FIELDS) + ["liq_price|liq_buffer_pct"]
    source_gaps: list[str] = []
    for field in source_fields:
        if "|" in field:
            if not any(source_ok(part, keys) for part in field.split("|")):
                source_gaps.append(field)
        elif not source_ok(field, keys):
            source_gaps.append(field)
    ready = not missing and not source_gaps
    return {
        "event_id": row.get("event_id"),
        "strategy_id": row.get("strategy_id") or row.get("strategy"),
        "window_id": row.get("window_id"),
        "state": "PASS_LICO_HISTORICAL_MIN_DATA" if ready else "HOLD_LICO_HISTORICAL_MIN_DATA_MISSING",
        "snapshot": snapshot,
        "src_keys": keys,
        "missing_fields": sorted(set(missing)),
        "source_gaps": sorted(set(source_gaps)),
        "historical_replay_ready": ready,
        "live_freshness_claim_allowed": False,
        "action": "hold",
    }


def build(trades_path: Path, evidence_path: Path | None = None) -> dict[str, Any]:
    evidence = evidence_index(load_json(evidence_path)) if evidence_path else {}
    rows: list[dict[str, Any]] = []
    missing_counts: Counter[str] = Counter()
    source_gap_counts: Counter[str] = Counter()
    with gzip.open(trades_path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            trade = json.loads(raw)
            if not isinstance(trade, dict):
                continue
            event_id = str(trade.get("event_id") or "")
            mapped = map_trade(trade, evidence.get(event_id))
            rows.append(mapped)
            missing_counts.update(mapped["missing_fields"])
            source_gap_counts.update(mapped["source_gaps"])
    ready_count = sum(1 for row in rows if row["historical_replay_ready"])
    if rows and ready_count == len(rows):
        state = "PASS_LICO_HISTORICAL_MIN_DATA_DATASET"
    else:
        state = "HOLD_LICO_HISTORICAL_MIN_DATA_DATASET"
    result: dict[str, Any] = {
        "schema_version": "zel.lico.historical_min_data_mapper.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "trade_count": len(rows),
        "ready_trade_count": ready_count,
        "blocked_trade_count": len(rows) - ready_count,
        "missing_counts": dict(sorted(missing_counts.items())),
        "source_gap_counts": dict(sorted(source_gap_counts.items())),
        "rows": rows,
        "accepted_source_prefixes": list(ACCEPTED_SOURCE_PREFIXES),
        "historical_values_fabricated": False,
        "live_freshness_claim_allowed": False,
        "economic_superiority_claim_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    trade = {"event_id": "e1", "strategy_id": "s1", "entry_price": 100, "entry_ts": "2026-01-01T00:00:00Z"}
    hold = map_trade(trade)
    assert hold["state"] == "HOLD_LICO_HISTORICAL_MIN_DATA_MISSING", hold
    evidence = {
        "pos_pct": 10,
        "lev": 10,
        "liq_buffer_pct": 15,
        "funding_8h_pct": 0.01,
        "dd_day_pct": -1,
        "dd_total_pct": -2,
        "src_keys": [
            "cf:/price", "cf:/pos_pct", "cf:/lev", "cf:/entry_ts", "cf:/liq_buffer_pct",
            "cf:/funding_8h_pct", "cf:/dd_day_pct", "cf:/dd_total_pct"
        ],
    }
    passed = map_trade(trade, evidence)
    assert passed["state"] == "PASS_LICO_HISTORICAL_MIN_DATA", passed
    assert passed["historical_replay_ready"] is True, passed
    fake = map_trade({**trade, **evidence, "src_keys": ["historical:/price"]})
    assert fake["state"].startswith("HOLD_"), fake
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.trades:
        parser.error("trades is required")
    row = build(args.trades, args.evidence)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
