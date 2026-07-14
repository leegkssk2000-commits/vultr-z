#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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


def fnum(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
            value = json.loads(line)
        except Exception as exc:
            errors.append({"line": line_no, "error": f"{type(exc).__name__}:{exc}"})
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            errors.append({"line": line_no, "error": "ROW_NOT_OBJECT"})
    return rows, errors


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def append_jsonl_once(path: Path, row: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    event_id = str(row.get("event_id") or "")
    if not event_id:
        raise RuntimeError("EVENT_ID_REQUIRED")
    if path.exists():
        for prior in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(prior)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and str(payload.get("event_id") or "") == event_id:
                return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def first(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def normalized(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", "_").split())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def issue(code: str, severity: str, detail: str, source: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, "source": source}


def event_id(parts: Sequence[Any]) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_registry(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], set[str]]:
    payload = load_json(path, {})
    skills = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(skills, list):
        raise RuntimeError("SKILL_REGISTRY_SKILLS_REQUIRED")
    by_id: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for row in skills:
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("skill_id") or "").strip()
        if not skill_id:
            continue
        by_id[skill_id] = row
        aliases[normalized(skill_id)] = skill_id
        label = row.get("label_ko")
        if label:
            aliases[normalized(label)] = skill_id
    if len(by_id) != 18:
        raise RuntimeError(f"SKILL_REGISTRY_NOT_EXACT18:{len(by_id)}")
    return by_id, aliases, set(by_id)


def discover_preentry(root: Path, patterns: Sequence[str], max_files: int, max_age_hours: float) -> dict[str, dict[str, Any]]:
    cutoff = datetime.now(UTC).timestamp() - max_age_hours * 3600.0
    candidates: list[tuple[float, Path]] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file() and stat.st_mtime >= cutoff:
                candidates.append((stat.st_mtime, path))
    result: dict[str, dict[str, Any]] = {}
    for _mtime, path in sorted(candidates, reverse=True)[:max_files]:
        try:
            payload = load_json(path)
        except Exception:
            continue
        for obj in walk(payload):
            position_id = str(obj.get("position_id") or "").strip()
            if position_id and position_id not in result:
                result[position_id] = {**obj, "_source_path": str(path)}
    return result


def open_positions(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("positions")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def explicit_skill_values(position: Mapping[str, Any], aliases: Mapping[str, Sequence[str]]) -> list[str]:
    values: list[str] = []
    for name in aliases.get("skill", []):
        raw = position.get(name)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif raw is not None and str(raw).strip():
            values.append(str(raw))
    return values


def resolve_skill(raw: str, known: set[str], alias_map: Mapping[str, str], manual: Mapping[str, str], ambiguous: set[str]) -> tuple[str | None, str | None]:
    text = str(raw or "").strip()
    if not text:
        return None, "EMPTY_SKILL"
    if text in known:
        return text, None
    key = normalized(text)
    if key in ambiguous or text in ambiguous:
        return None, "AMBIGUOUS_LEGACY_SKILL_ALIAS"
    target = manual.get(key) or alias_map.get(key)
    if target in known:
        return target, None
    return None, "UNKNOWN_SKILL_ALIAS"


def select_open_path(root: Path, candidates: Sequence[str]) -> Path:
    existing = [root / item for item in candidates if (root / item).is_file()]
    if not existing:
        raise RuntimeError("OPEN_POSITION_SURFACE_MISSING")
    return max(existing, key=lambda path: path.stat().st_mtime)


def build_context(position: Mapping[str, Any], preentry: Mapping[str, Any], aliases: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    merged = dict(preentry)
    merged.update(position)
    return {
        "position_id": first(merged, aliases["position_id"]),
        "strategy_id": first(merged, aliases["strategy_id"]),
        "method_id": first(merged, aliases["method_id"]),
        "symbol": first(merged, aliases["symbol"]),
        "side": first(merged, aliases["side"]),
        "entry_ts": first(merged, aliases["entry_ts"]),
        "event_ts": first(merged, aliases["event_ts"]) or first(merged, aliases["entry_ts"]),
        "preentry_context_id": merged.get("preentry_context_id"),
        "market_context_snapshot_id": merged.get("market_context_snapshot_id"),
        "reference_price": merged.get("reference_price") or merged.get("entry_price"),
        "position_size_pct": merged.get("position_size_pct"),
        "leverage": merged.get("leverage"),
        "entry_price": merged.get("entry_price"),
        "stop_price": merged.get("stop_price") or merged.get("sl"),
        "liq_price_or_buffer_pct": merged.get("liq_price_or_buffer_pct") or merged.get("liq_buffer_pct") or merged.get("liq_price"),
        "funding_8h_pct": merged.get("funding_8h_pct") or merged.get("funding_8h"),
        "dd_day_pct": merged.get("dd_day_pct"),
        "dd_total_pct": merged.get("dd_total_pct"),
        "mfe_r": merged.get("mfe_r") or merged.get("MFE_R"),
        "mae_r": merged.get("mae_r") or merged.get("MAE_R"),
        "unrealized_r": merged.get("unrealized_r"),
        "remaining_size_pct": merged.get("remaining_size_pct"),
        "elapsed_min": merged.get("elapsed_min"),
        "preentry_source_path": preentry.get("_source_path") if isinstance(preentry, dict) else None,
    }


def close_payload(row: Mapping[str, Any], aliases: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    return {name: first(row, names) for name, names in aliases.items()}


def load_matrix(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_coverage(matrix: list[dict[str, str]], events: list[dict[str, Any]]) -> dict[str, Any]:
    triggers: Counter[tuple[str, str, str]] = Counter()
    joins: Counter[tuple[str, str, str]] = Counter()
    for row in events:
        key = (str(row.get("strategy_id") or ""), str(row.get("method_id") or ""), str(row.get("skill_id") or ""))
        if row.get("event_type") == "skill_triggered":
            triggers[key] += 1
        elif row.get("event_type") == "close_outcome_joined":
            joins[key] += 1
    output: list[dict[str, Any]] = []
    for row in matrix:
        key = (row["strategy_id"], row["method_id"], row["skill_id"])
        trigger_count = triggers[key]
        join_count = joins[key]
        output.append({
            **row,
            "runtime_trigger_count": trigger_count,
            "runtime_outcome_join_count": join_count,
            "runtime_trigger_proven": trigger_count > 0,
            "runtime_outcome_join_proven": join_count > 0,
            "decision_enabled": False,
            "promotion_enabled": False,
            "action": "hold",
        })
    return {
        "schema": "q4r3_exact25_skill_trigger_lineage_coverage_v1",
        "generated_at": now_iso(),
        "matrix_rows": len(output),
        "triggered_matrix_rows": sum(bool(row["runtime_trigger_proven"]) for row in output),
        "outcome_joined_matrix_rows": sum(bool(row["runtime_outcome_join_proven"]) for row in output),
        "rows": output,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "observer_only": True,
        "action": "hold",
    }


def run(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    ssot = load_json(args.ssot, {})
    registry = load_json(args.registry, {})
    contract = load_json(args.contract, {})
    audit = load_json(args.audit_result, {})
    activation = load_json(args.activation, {})
    if audit.get("state") != "PASS" or not str(audit.get("verdict") or "").startswith(ssot["required_skill_audit_verdict_prefix"]):
        raise RuntimeError("SKILL_ACTIVE_LINEAGE_AUDIT_NOT_PASS")
    if registry.get("activation_allowed") is not False or registry.get("runtime_mutation_allowed") is not False:
        raise RuntimeError("UNSAFE_SKILL_REGISTRY_FLAGS")
    if contract.get("historical_backfill_allowed") is not False:
        raise RuntimeError("UNSAFE_SKILL_EVENT_CONTRACT_FLAGS")
    activated_at = parse_ts(activation.get("activated_at"))
    if activated_at is None:
        raise RuntimeError("ACTIVATION_TIMESTAMP_REQUIRED")

    skills, registry_aliases, known = load_registry(args.registry)
    manual = {normalized(key): value for key, value in ssot.get("manual_skill_aliases", {}).items()}
    ambiguous = {normalized(value) for value in ssot.get("ambiguous_aliases", [])}
    aliases = ssot["identity_aliases"]
    open_path = select_open_path(root, ssot["open_position_candidates"])
    ledger_path = root / ssot["formal_ledger"]
    preentry = discover_preentry(root, ssot["preentry_globs"], int(ssot["runtime_scan_max_files"]), float(ssot["runtime_scan_max_age_hours"]))
    baseline_positions = {str(value) for value in activation.get("baseline_position_ids", [])}
    issues: list[dict[str, Any]] = []

    prior_events, event_errors = read_jsonl(args.events)
    for error in event_errors:
        issues.append(issue("SKILL_EVENT_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "events"))

    new_event_count = 0
    seen_position_ids = {str(row.get("position_id") or "") for row in prior_events if row.get("event_type") in {"skill_triggered", "skill_blocked"}}
    for position in open_positions(open_path):
        context = build_context(position, preentry.get(str(position.get("position_id") or ""), {}), aliases)
        position_id = str(context.get("position_id") or "").strip()
        entry_ts = parse_ts(context.get("entry_ts"))
        if not position_id or position_id in baseline_positions or position_id in seen_position_ids:
            continue
        if entry_ts is None or entry_ts < activated_at:
            continue
        raw_skills = explicit_skill_values(position, aliases)
        if not raw_skills:
            issues.append(issue("FORWARD_POSITION_WITHOUT_EXPLICIT_SKILL", "M", f"position_id={position_id}:strategy={context.get('strategy_id')}", "open_positions"))
            continue
        resolved: list[str] = []
        for raw in raw_skills:
            skill_id, error = resolve_skill(raw, known, registry_aliases, manual, ambiguous)
            if error:
                issues.append(issue(error, "C" if error == "AMBIGUOUS_LEGACY_SKILL_ALIAS" else "M", f"position_id={position_id}:raw={raw}", "open_positions"))
                continue
            if skill_id and skill_id not in resolved:
                resolved.append(skill_id)
        for skill_id in resolved:
            skill = skills[skill_id]
            event_ts = str(context.get("event_ts") or context.get("entry_ts") or now_iso())
            identity_missing = [key for key in ("position_id", "strategy_id", "method_id", "symbol", "side") if not context.get(key)]
            required_context = [str(key) for key in contract.get("required_pretrigger_context", [])]
            context_missing = [key for key in required_context if context.get(key) is None]
            event_type = "skill_triggered" if not identity_missing and not context_missing else "skill_blocked"
            payload = {
                "schema": "zos_skill_event_v1",
                "event_id": event_id([ssot["epoch_id"], position_id, context.get("strategy_id"), context.get("method_id"), skill_id, registry.get("version"), event_type, event_ts]),
                "epoch_id": ssot["epoch_id"],
                "position_id": position_id,
                "strategy_id": context.get("strategy_id"),
                "method_id": context.get("method_id"),
                "skill_id": skill_id,
                "skill_version": registry.get("version"),
                "skill_source_sha256": sha256_file(args.registry),
                "event_type": event_type,
                "event_ts": event_ts,
                "symbol": context.get("symbol"),
                "side": context.get("side"),
                "category": skill.get("category"),
                "risk_tier": skill.get("risk_tier"),
                "identity_missing": identity_missing,
                "pretrigger_context_missing": context_missing,
                "pretrigger_context": context,
                "runtime_mutation_allowed": False,
                "decision_eligible": False,
                "paper_enabled": False,
                "live_enabled": False,
                "order_enabled": False,
                "order_authority": "blocked",
                "execution_authority": "none",
                "action": "hold",
            }
            if append_jsonl_once(args.events, payload):
                prior_events.append(payload)
                new_event_count += 1
            if event_type == "skill_blocked":
                issues.append(issue("SKILL_TRIGGER_CONTEXT_INCOMPLETE", "M", f"position_id={position_id}:skill={skill_id}:identity_missing={identity_missing}:context_missing={context_missing}", "preentry"))

    ledger_rows, ledger_errors = read_jsonl(ledger_path)
    for error in ledger_errors:
        issues.append(issue("FORMAL_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "ledger"))
    prior_events, _ = read_jsonl(args.events)
    trigger_by_position: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    joined_close_ids = {str(row.get("close_event_id") or "") for row in prior_events if row.get("event_type") == "close_outcome_joined"}
    for row in prior_events:
        if row.get("event_type") == "skill_triggered" and row.get("position_id"):
            trigger_by_position[str(row["position_id"])].append(row)
    for close in ledger_rows[int(activation.get("baseline_ledger_rows") or 0):]:
        selected = close_payload(close, ssot["close_aliases"])
        position_id = str(selected.get("position_id") or "").strip()
        close_id = str(selected.get("close_event_id") or "").strip()
        if not position_id or not close_id or close_id in joined_close_ids:
            continue
        for trigger in trigger_by_position.get(position_id, []):
            event_ts = str(selected.get("closed_at") or now_iso())
            payload = {
                "schema": "zos_skill_event_v1",
                "event_id": event_id([ssot["epoch_id"], position_id, trigger.get("strategy_id"), trigger.get("method_id"), trigger.get("skill_id"), trigger.get("skill_version"), "close_outcome_joined", event_ts]),
                "epoch_id": ssot["epoch_id"],
                "position_id": position_id,
                "strategy_id": trigger.get("strategy_id"),
                "method_id": trigger.get("method_id"),
                "skill_id": trigger.get("skill_id"),
                "skill_version": trigger.get("skill_version"),
                "skill_source_sha256": trigger.get("skill_source_sha256"),
                "event_type": "close_outcome_joined",
                "event_ts": event_ts,
                "symbol": close.get("symbol") or trigger.get("symbol"),
                "side": close.get("side") or trigger.get("side"),
                "close_event_id": close_id,
                "closed_at": selected.get("closed_at"),
                "realized_r": fnum(selected.get("realized_r")),
                "realized_pnl_usdt": fnum(selected.get("realized_pnl_usdt")),
                "fee_bps": fnum(selected.get("fee_bps")),
                "fee": fnum(selected.get("fee")),
                "slippage_bps": fnum(selected.get("slippage_bps")),
                "slippage": fnum(selected.get("slippage")),
                "mfe_r": fnum(selected.get("mfe_r")),
                "mae_r": fnum(selected.get("mae_r")),
                "exposure_time_min": fnum(selected.get("exposure_time_min")),
                "exit_reason": selected.get("exit_reason"),
                "runtime_mutation_allowed": False,
                "decision_eligible": False,
                "paper_enabled": False,
                "live_enabled": False,
                "order_enabled": False,
                "order_authority": "blocked",
                "execution_authority": "none",
                "action": "hold",
            }
            if append_jsonl_once(args.events, payload):
                new_event_count += 1
        joined_close_ids.add(close_id)

    all_events, final_errors = read_jsonl(args.events)
    for error in final_errors:
        issues.append(issue("SKILL_EVENT_LEDGER_PARSE_ERROR", "C", f"line={error['line']}:{error['error']}", "events"))
    coverage = build_coverage(load_matrix(args.matrix), all_events)
    if coverage["matrix_rows"] != int(ssot["expected_matrix_rows"]):
        issues.append(issue("SKILL_MATRIX_ROW_COUNT_MISMATCH", "C", f"expected={ssot['expected_matrix_rows']}:observed={coverage['matrix_rows']}", "matrix"))
    severity_rank = {"m": 1, "M": 2, "C": 3}
    severity = max((row["severity"] for row in issues), key=lambda value: severity_rank[value]) if issues else None
    trigger_count = sum(row.get("event_type") == "skill_triggered" for row in all_events)
    blocked_count = sum(row.get("event_type") == "skill_blocked" for row in all_events)
    joined_count = sum(row.get("event_type") == "close_outcome_joined" for row in all_events)
    state = "PASS" if not any(row["severity"] == "C" for row in issues) else "HOLD"
    verdict = "SKILL_TRIGGER_LINEAGE_OBSERVER_HEALTHY_WAITING_FORWARD_EVIDENCE" if state == "PASS" and trigger_count == 0 else "SKILL_TRIGGER_LINEAGE_OBSERVER_HEALTHY" if state == "PASS" else "SKILL_TRIGGER_LINEAGE_OBSERVER_CRITICAL_GAP"
    status = {
        "schema": "q4r3_exact25_skill_trigger_lineage_observer_status_v1",
        "state": state,
        "verdict": verdict,
        "generated_at": now_iso(),
        "activated_at": activation.get("activated_at"),
        "open_position_surface": str(open_path),
        "preentry_context_count": len(preentry),
        "formal_ledger_rows": len(ledger_rows),
        "event_count": len(all_events),
        "new_event_count": new_event_count,
        "skill_triggered_count": trigger_count,
        "skill_blocked_count": blocked_count,
        "close_outcome_joined_count": joined_count,
        "matrix_rows": coverage["matrix_rows"],
        "triggered_matrix_rows": coverage["triggered_matrix_rows"],
        "outcome_joined_matrix_rows": coverage["outcome_joined_matrix_rows"],
        "violation_count": len(issues),
        "violation_severity": severity,
        "historical_backfill_performed": False,
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
        "comparison_decision_enabled": False,
        "promotion_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
    }
    violations = {
        "schema": "q4r3_exact25_skill_trigger_lineage_violations_v1",
        "generated_at": now_iso(),
        "state": "CLEAR" if not issues else "VIOLATION",
        "count": len(issues),
        "severity": severity,
        "notify": bool(any(row["severity"] == "C" for row in issues)),
        "violations": issues,
        "action": "hold",
    }
    atomic_json(args.coverage, coverage)
    atomic_json(args.violations, violations)
    atomic_json(args.status, status)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if state == "PASS" else 2


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser()
    for name in ("root", "ssot", "registry", "contract", "audit_result", "matrix", "activation", "events", "coverage", "violations", "status"):
        command.add_argument("--" + name.replace("_", "-"), dest=name, type=Path, required=True)
    return command


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
