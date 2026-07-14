#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_ts(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return rows, errors
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}:{exc}"})
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            errors.append({"line": line_no, "error": "ROW_NOT_OBJECT"})
    return rows, errors


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def issue(code: str, severity: str, detail: str, source: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, "source": source}


def identity(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("position_id") or ""),
        str(row.get("strategy_id") or ""),
        str(row.get("method_id") or ""),
        str(row.get("skill_id") or ""),
        str(row.get("skill_version") or ""),
    )


def pair_id(trigger_id: str, close_id: str) -> str:
    return hashlib.sha256(f"{trigger_id}|{close_id}".encode("utf-8")).hexdigest()


def ledger_index(rows: list[dict[str, Any]], baseline_rows: int) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_close: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for offset, row in enumerate(rows[baseline_rows:], baseline_rows + 1):
        close_id = str(first(row, ("event_id", "close_event_id")) or "").strip()
        if not close_id:
            continue
        if close_id in by_close:
            issues.append(issue("FORMAL_LEDGER_DUPLICATE_CLOSE_EVENT_ID", "C", f"close_event_id={close_id}:row={offset}", "formal_ledger"))
            continue
        by_close[close_id] = row
    return by_close, issues


def run(args: argparse.Namespace) -> int:
    trigger_status = load_json(args.trigger_status, {})
    projection_status = load_json(args.projection_status, {})
    activation = load_json(args.activation, {})
    if trigger_status.get("state") != "PASS" or trigger_status.get("observer_only") is not True:
        raise RuntimeError("TRIGGER_OBSERVER_NOT_HEALTHY")
    if projection_status.get("state") != "PASS" or projection_status.get("profile_count") != 6:
        raise RuntimeError("SIX_PROFILE_PROJECTION_NOT_HEALTHY")
    if activation.get("historical_backfill_allowed") is not False:
        raise RuntimeError("UNSAFE_ACTIVATION_BACKFILL_FLAG")

    events, event_errors = read_jsonl(args.events)
    ledger_rows, ledger_errors = read_jsonl(args.ledger)
    issues: list[dict[str, Any]] = []
    for error in event_errors:
        issues.append(issue("SKILL_EVENT_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "skill_events"))
    for error in ledger_errors:
        issues.append(issue("FORMAL_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "formal_ledger"))

    event_id_counts = Counter(str(row.get("event_id") or "") for row in events if row.get("event_id"))
    for event_id_value, count in event_id_counts.items():
        if count > 1:
            issues.append(issue("DUPLICATE_SKILL_EVENT_ID", "C", f"event_id={event_id_value}:count={count}", "skill_events"))

    triggers: defaultdict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    closes: defaultdict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    blocked_count = 0
    for row in events:
        event_type = row.get("event_type")
        if event_type == "skill_triggered":
            triggers[identity(row)].append(row)
        elif event_type == "close_outcome_joined":
            closes[identity(row)].append(row)
        elif event_type == "skill_blocked":
            blocked_count += 1

    baseline_rows = int(activation.get("baseline_ledger_rows") or 0)
    ledger_by_close, ledger_issues = ledger_index(ledger_rows, baseline_rows)
    issues.extend(ledger_issues)

    pairs: list[dict[str, Any]] = []
    pending_count = 0
    exact_pair_count = 0
    for key, trigger_rows in sorted(triggers.items()):
        if len(trigger_rows) != 1:
            issues.append(issue("DUPLICATE_TRIGGER_IDENTITY", "C", f"identity={key}:count={len(trigger_rows)}", "skill_events"))
        trigger = sorted(trigger_rows, key=lambda row: parse_ts(row.get("event_ts")) or 0.0)[0]
        close_rows = closes.get(key, [])
        if not close_rows:
            pending_count += 1
            pairs.append({
                "pair_state": "OPEN_PENDING_CLOSE",
                "position_id": key[0],
                "strategy_id": key[1],
                "method_id": key[2],
                "skill_id": key[3],
                "skill_version": key[4],
                "trigger_event_id": trigger.get("event_id"),
                "trigger_event_ts": trigger.get("event_ts"),
                "close_event_id": None,
                "exact_join": False,
                "action": "hold",
            })
            continue
        if len(close_rows) != 1:
            issues.append(issue("DUPLICATE_CLOSE_FOR_TRIGGER", "C", f"identity={key}:count={len(close_rows)}", "skill_events"))
        close = sorted(close_rows, key=lambda row: parse_ts(row.get("event_ts")) or 0.0)[0]
        trigger_ts = parse_ts(trigger.get("event_ts"))
        close_ts = parse_ts(close.get("event_ts") or close.get("closed_at"))
        if trigger_ts is None or close_ts is None:
            issues.append(issue("PAIR_TIMESTAMP_MISSING", "M", f"identity={key}", "skill_events"))
        elif close_ts < trigger_ts:
            issues.append(issue("CLOSE_BEFORE_TRIGGER", "C", f"identity={key}:trigger={trigger_ts}:close={close_ts}", "skill_events"))

        for field in ("position_id", "strategy_id", "method_id", "skill_id", "skill_version"):
            if str(trigger.get(field) or "") != str(close.get(field) or ""):
                issues.append(issue("PAIR_IDENTITY_MISMATCH", "C", f"field={field}:trigger={trigger.get(field)}:close={close.get(field)}", "skill_events"))
        for field in ("symbol", "side"):
            left = str(trigger.get(field) or "")
            right = str(close.get(field) or "")
            if left and right and left != right:
                issues.append(issue("PAIR_MARKET_IDENTITY_MISMATCH", "C", f"field={field}:trigger={left}:close={right}:position={key[0]}", "skill_events"))

        close_event_id = str(close.get("close_event_id") or "").strip()
        ledger_row = ledger_by_close.get(close_event_id)
        if not close_event_id or ledger_row is None:
            issues.append(issue("CLOSE_EVENT_NOT_FOUND_IN_FORMAL_LEDGER", "C", f"position={key[0]}:close_event_id={close_event_id}", "formal_ledger"))
        else:
            ledger_position = str(first(ledger_row, ("position_id", "positionId", "trade_id")) or "")
            if ledger_position != key[0]:
                issues.append(issue("FORMAL_LEDGER_CROSS_POSITION_JOIN", "C", f"expected={key[0]}:observed={ledger_position}:close_event_id={close_event_id}", "formal_ledger"))

        exact_pair_count += 1
        pairs.append({
            "pair_id": pair_id(str(trigger.get("event_id") or ""), close_event_id),
            "pair_state": "EXACT_CLOSE_JOINED",
            "position_id": key[0],
            "strategy_id": key[1],
            "method_id": key[2],
            "skill_id": key[3],
            "skill_version": key[4],
            "symbol": close.get("symbol") or trigger.get("symbol"),
            "side": close.get("side") or trigger.get("side"),
            "trigger_event_id": trigger.get("event_id"),
            "trigger_event_ts": trigger.get("event_ts"),
            "close_join_event_id": close.get("event_id"),
            "close_event_id": close_event_id,
            "closed_at": close.get("closed_at"),
            "realized_r": close.get("realized_r"),
            "realized_pnl_usdt": close.get("realized_pnl_usdt"),
            "fee_bps": close.get("fee_bps"),
            "slippage_bps": close.get("slippage_bps"),
            "mfe_r": close.get("mfe_r"),
            "mae_r": close.get("mae_r"),
            "exposure_time_min": close.get("exposure_time_min"),
            "exit_reason": close.get("exit_reason"),
            "exact_join": True,
            "action": "hold",
        })

    for key, close_rows in closes.items():
        if key not in triggers:
            issues.append(issue("ORPHAN_CLOSE_WITHOUT_TRIGGER", "C", f"identity={key}:count={len(close_rows)}", "skill_events"))

    severity_rank = {"m": 1, "M": 2, "C": 3}
    severity = max((row["severity"] for row in issues), key=lambda value: severity_rank[value]) if issues else None
    state = "HOLD" if any(row["severity"] == "C" for row in issues) else "PASS"
    if state != "PASS":
        verdict = "FUTURE_PAIR_JOIN_CRITICAL_GAP"
    elif not triggers:
        verdict = "FUTURE_PAIR_JOIN_HEALTHY_WAITING_FORWARD_TRIGGER"
    elif pending_count:
        verdict = "FUTURE_PAIR_JOIN_HEALTHY_WAITING_FORWARD_CLOSE"
    else:
        verdict = "FUTURE_PAIR_JOIN_HEALTHY_EXACT_PAIRS_ACTIVE"

    report = {
        "schema": "q4r3_exact25_future_pair_join_report_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "baseline_ledger_rows": baseline_rows,
        "formal_ledger_rows": len(ledger_rows),
        "event_count": len(events),
        "trigger_count": sum(len(rows) for rows in triggers.values()),
        "blocked_count": blocked_count,
        "close_join_event_count": sum(len(rows) for rows in closes.values()),
        "exact_pair_count": exact_pair_count,
        "pending_close_count": pending_count,
        "orphan_close_count": sum(len(rows) for key, rows in closes.items() if key not in triggers),
        "pairs": pairs,
        "observer_only": True,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    status = {key: value for key, value in report.items() if key != "pairs"}
    status.update({
        "violation_count": len(issues),
        "violation_severity": severity,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "historical_backfill_performed": False,
    })
    violations = {
        "schema": "q4r3_exact25_future_pair_join_violations_v1",
        "generated_at": now_iso(),
        "state": "CLEAR" if not issues else "VIOLATION",
        "count": len(issues),
        "severity": severity,
        "notify": bool(any(row["severity"] == "C" for row in issues)),
        "violations": issues,
        "action": "hold",
    }
    atomic_json(args.output, report)
    atomic_json(args.status, status)
    atomic_json(args.violations, violations)
    return 0 if state == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--trigger-status", type=Path, required=True)
    value.add_argument("--projection-status", type=Path, required=True)
    value.add_argument("--activation", type=Path, required=True)
    value.add_argument("--events", type=Path, required=True)
    value.add_argument("--ledger", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--status", type=Path, required=True)
    value.add_argument("--violations", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
