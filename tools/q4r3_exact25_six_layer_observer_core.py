from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

SEV = {None: 0, "m": 1, "M": 2, "C": 3}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000.0 if value > 10_000_000_000 else value
    text = str(value).strip()
    if not text:
        return None
    try:
        return ts(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def rnd(value: float | None, digits: int = 8) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def avg(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def pf(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return gains / losses if losses else None


def mdd(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(body, encoding="utf-8")
    temp.replace(path)
    return hashlib.sha256(body.encode()).hexdigest()


def load_json(path: Path, optional: bool = False) -> dict[str, Any]:
    if optional and not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def problem(code: str, severity: str, detail: str, metric: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail, "metric": metric}


def read_jsonl(path: Path, optional: bool = False) -> tuple[list[dict[str, Any]], str, list[dict[str, str]]]:
    if not path.exists():
        return ([], "", []) if optional else ([], "", [problem("LEDGER_MISSING", "C", str(path), "ledger")])
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        return [], digest, [problem("LEDGER_ENCODING_INVALID", "C", str(exc), "ledger")]
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(problem("LEDGER_JSON_MALFORMED", "C", f"line={line_no}:{exc.msg}", "ledger"))
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            issues.append(problem("LEDGER_ROW_NOT_OBJECT", "C", f"line={line_no}", "ledger"))
    return rows, digest, issues


def owners(manifest: Mapping[str, Any], expected: int) -> dict[str, str]:
    items = manifest.get("strategies")
    if not isinstance(items, list) or len(items) != expected:
        raise RuntimeError(f"MANIFEST_COUNT_MISMATCH:{len(items) if isinstance(items, list) else -1}:{expected}")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise RuntimeError("MANIFEST_ENTRY_NOT_OBJECT")
        name = str(item.get("strategy_id") or item.get("id") or item.get("name") or item.get("strategy") or "")
        sha = str(item.get("owner_sha256") or item.get("sha256") or item.get("owner_sha") or "").lower()
        if not sha and isinstance(item.get("owner"), Mapping):
            sha = str(item["owner"].get("sha256") or item["owner"].get("owner_sha256") or "").lower()
        if not name or len(sha) < 32 or name in result:
            raise RuntimeError(f"MANIFEST_OWNER_INVALID:{name or 'unknown'}")
        result[name] = sha
    return result


def validate(rows: Sequence[Mapping[str, Any]], owner_map: Mapping[str, str], ssot: Mapping[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        event = str(row.get("event_id") or "")
        loc = event or f"row={index}"
        if not event:
            issues.append(problem("EVENT_ID_MISSING", "C", loc, "event_id"))
        elif event in seen:
            issues.append(problem("DUPLICATE_EVENT_ID", "C", loc, "event_id"))
        seen.add(event)
        strategy = str(row.get("strategy_id") or "")
        if strategy not in owner_map:
            issues.append(problem("STRATEGY_NOT_IN_MANIFEST", "C", f"{loc}:{strategy}", "strategy_id"))
        elif str(row.get("owner_sha256") or "").lower() != owner_map[strategy]:
            issues.append(problem("OWNER_SHA_MISMATCH", "C", f"{loc}:{strategy}", "owner_sha256"))
        if row.get("epoch_id") != ssot.get("expected_epoch") or row.get("measurement_namespace") != ssot.get("expected_namespace"):
            issues.append(problem("EVENT_IDENTITY_MISMATCH", "C", loc, "identity"))
        for key in ("paper_enabled", "live_enabled", "order_enabled"):
            if row.get(key) is not False:
                issues.append(problem("UNSAFE_EVENT_FLAG", "C", f"{loc}:{key}={row.get(key)}", key))
        risk, pnl, realized = num(row.get("initial_risk_usdt")), num(row.get("realized_pnl_usdt")), num(row.get("realized_R"))
        if risk is None or risk <= 0 or pnl is None or realized is None:
            issues.append(problem("REALIZED_OUTCOME_INVALID", "C", loc, "realized_outcome"))
        elif abs(realized - pnl / risk) > max(1e-10, abs(pnl / risk) * 1e-9):
            issues.append(problem("REALIZED_R_FORMULA_MISMATCH", "C", loc, "realized_R"))
    return issues


def exit_reason(row: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    raw = str(row.get("exit_reason") or row.get("close_reason") or "").lower().strip()
    aliases = cfg.get("exit_reason_aliases") if isinstance(cfg.get("exit_reason_aliases"), Mapping) else {}
    value = str(aliases.get(raw) or raw or "unknown")
    return value if value in {str(item) for item in cfg.get("allowed_exit_reasons", [])} else "unknown"


def outcome_layer(rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    required = [str(key) for key in cfg.get("required_fields", [])]
    coverage = Counter()
    reason_counts = Counter()
    projections: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    core = full = funding_count = 0
    numeric = {"entry_price", "exit_price", "initial_risk_usdt", "gross_pnl_usdt", "realized_pnl_usdt", "realized_R", "fee", "slippage", "latency_ms", "MFE_R", "MAE_R", "time_exposure_min"}
    for index, row in enumerate(rows, 1):
        missing = []
        for key in required:
            valid = num(row.get(key)) is not None if key in numeric else bool(str(row.get(key) or "").strip())
            coverage[key] += int(valid)
            if not valid:
                missing.append(key)
        reason = exit_reason(row, cfg)
        reason_counts[reason] += 1
        event = str(row.get("event_id") or f"row={index}")
        if reason == "unknown":
            issues.append(problem("EXIT_REASON_UNKNOWN", "M", event, "exit_reason"))
        risk, pnl, realized = num(row.get("initial_risk_usdt")), num(row.get("realized_pnl_usdt")), num(row.get("realized_R"))
        formula = bool(risk is not None and risk > 0 and pnl is not None and realized is not None and abs(realized - pnl / risk) <= max(1e-10, abs(pnl / risk) * 1e-9))
        funding = num(row.get("funding_usdt"))
        net = num(row.get("net_pnl_usdt")) if num(row.get("net_pnl_usdt")) is not None else pnl
        core_ok = not missing and reason != "unknown" and formula
        full_ok = core_ok and funding is not None and net is not None
        core += int(core_ok); full += int(full_ok); funding_count += int(funding is not None)
        projections.append({
            "schema": "q4r3_exact25_outcome_contract_projection_v1",
            "schema_version": cfg.get("schema_version"), "event_id": row.get("event_id"),
            "position_id": row.get("position_id"), "strategy_id": row.get("strategy_id"),
            "symbol": row.get("symbol"), "side": row.get("side"), "entry_ts": row.get("entry_ts"),
            "exit_ts": row.get("exit_ts"), "entry_price": num(row.get("entry_price")),
            "exit_price": num(row.get("exit_price")), "exit_reason": reason,
            "gross_pnl_usdt": num(row.get("gross_pnl_usdt")), "fee_usdt": num(row.get("fee")),
            "slippage_usdt": num(row.get("slippage")), "funding_usdt": funding, "net_pnl_usdt": net,
            "latency_ms": num(row.get("latency_ms")), "initial_risk_usdt": risk, "realized_R": realized,
            "MFE_R": num(row.get("MFE_R")), "MAE_R": num(row.get("MAE_R")),
            "time_exposure_min": num(row.get("time_exposure_min")), "formula_verified": formula,
            "core_contract_complete": core_ok, "full_contract_complete": full_ok,
            "funding_accounted": funding is not None, "observer_projection_only": True,
            "formal_ledger_mutated": False,
            "source_event_sha256": hashlib.sha256(json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        })
    total = len(rows)
    report = {
        "schema": "q4r3_exact25_outcome_contract_report_v1", "generated_at": now_iso(),
        "schema_version": cfg.get("schema_version"), "row_count": total, "core_complete_count": core,
        "full_complete_count": full, "funding_present_count": funding_count,
        "funding_missing_count": total - funding_count,
        "field_coverage_pct": {key: rnd(coverage[key] / total * 100.0, 6) if total else None for key in required},
        "exit_reason_counts": dict(sorted(reason_counts.items())), "projection_only": True,
        "formal_ledger_mutated": False, "action": "hold",
    }
    return projections, report, issues


def funnel_layer(rows: Sequence[Mapping[str, Any]], owner_map: Mapping[str, str], status: Mapping[str, Any], state: Mapping[str, Any], opens: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = lambda first, second: int(num(status.get(first)) if num(status.get(first)) is not None else num(state.get(second)) or 0)
    signals, opened, closed = value("signal_count", "signal_count"), value("open_event_count", "open_count"), value("close_event_count", "close_count")
    active = int(num(status.get("open_position_count")) if num(status.get("open_position_count")) is not None else num(opens.get("open_count")) or 0)
    formal = len(rows); issues: list[dict[str, str]] = []; verdict = "HEALTHY_OR_ACCUMULATING"
    if signals == 0: verdict = "WAITING_FOR_SIGNAL"
    elif opened == 0: verdict = "SIGNAL_TO_OPEN_STALL"
    elif opened > 0 and closed == 0 and active == 0:
        verdict = "OPEN_TO_CLOSE_COUNTER_GAP"; issues.append(problem("OPEN_CLOSE_COUNTER_GAP", "M", f"opened={opened}:closed={closed}:active={active}", "funnel"))
    if closed > formal:
        verdict = "CLOSE_TO_FORMAL_LEDGER_GAP"; issues.append(problem("CLOSE_TO_FORMAL_LEDGER_GAP", "C", f"producer_closed={closed}:formal={formal}", "funnel"))
    elif formal > closed:
        issues.append(problem("FORMAL_LEDGER_EXCEEDS_PRODUCER_COUNTER", "M", f"formal={formal}:producer_closed={closed}", "funnel"))
    close_counts = Counter(str(row.get("strategy_id") or "unknown") for row in rows)
    active_counts = Counter(str(row.get("strategy_id") or "unknown") for row in opens.get("positions", []) if isinstance(row, Mapping)) if isinstance(opens.get("positions"), list) else Counter()
    return {
        "schema": "q4r3_exact25_strategy_funnel_observer_v1", "generated_at": now_iso(), "verdict": verdict,
        "observable_global_funnel": {"signal": signals, "candidate": None, "admitted": None, "opened_total": opened, "opened_active": active, "producer_closed": closed, "formal_ledger": formal},
        "unsupported_stages": ["candidate", "admitted", "per_strategy_signal", "per_strategy_open_total"],
        "unsupported_stage_policy": "UNKNOWN_NEVER_TREATED_AS_ZERO_OR_FAILURE",
        "zero_formal_close_strategies": sorted(name for name in owner_map if close_counts[name] == 0),
        "per_strategy": [{"strategy_id": name, "signal_count": None, "candidate_count": None, "admitted_count": None, "opened_active_count": active_counts[name], "formal_closed_count": close_counts[name], "dead_route_decision": "UNAVAILABLE_UNTIL_PER_STRATEGY_STAGE_COUNTERS_EXIST"} for name in sorted(owner_map)],
        "observer_only": True, "action": "hold",
    }, issues


def cost_metrics(rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> dict[str, Any]:
    metrics: dict[str, list[float]] = defaultdict(list); reasons = Counter(); funding_missing = 0
    for row in rows:
        risk, realized, gross = num(row.get("initial_risk_usdt")), num(row.get("realized_R")), num(row.get("gross_pnl_usdt"))
        fee, slip, funding = num(row.get("fee")), num(row.get("slippage")), num(row.get("funding_usdt"))
        mfe, mae, exposure = num(row.get("MFE_R")), num(row.get("MAE_R")), num(row.get("time_exposure_min"))
        reasons[exit_reason(row, cfg)] += 1; funding_missing += int(funding is None)
        if realized is not None: metrics["net_R"].append(realized)
        if gross is not None and risk and risk > 0: metrics["gross_R"].append(gross / risk)
        if fee is not None and slip is not None and risk and risk > 0: metrics["known_cost_drag_R"].append((fee + slip + (funding or 0.0)) / risk)
        if realized is not None and mfe is not None:
            metrics["profit_giveback_R"].append(mfe - realized)
            if mfe > 0: metrics["mfe_capture_ratio"].append(realized / mfe)
        if realized is not None and mae is not None:
            metrics["mae_recovery_R"].append(realized - mae)
            if realized < 0 and mae < 0: metrics["stop_loss_to_mae_ratio"].append(abs(realized) / abs(mae))
        if realized is not None and exposure and exposure > 0: metrics["time_decay_R_per_hour"].append(realized / (exposure / 60.0))
    rs = metrics.get("net_R", [])
    summarize = lambda values: {"count": len(values), "mean": rnd(avg(values)), "min": rnd(min(values)) if values else None, "max": rnd(max(values)) if values else None}
    return {"closed_count": len(rows), "net_R_sum": rnd(sum(rs)), "net_expectancy_R": rnd(avg(rs)), "win_rate_pct": rnd(sum(x > 0 for x in rs) / len(rs) * 100.0, 6) if rs else None, "profit_factor": rnd(pf(rs)), "max_drawdown_R": rnd(mdd(rs)), "funding_missing_count": funding_missing, "exit_reason_counts": dict(sorted(reasons.items())), "metrics": {key: summarize(values) for key, values in sorted(metrics.items())}, "decision": "OBSERVE_ONLY"}


def cost_layer(rows: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows: groups[str(row.get("strategy_id") or "unknown")].append(row)
    return {"schema": "q4r3_exact25_cost_exit_efficiency_cube_v1", "generated_at": now_iso(), "overall": cost_metrics(rows, cfg), "by_strategy": {name: cost_metrics(items, cfg) for name, items in sorted(groups.items())}, "funding_policy": "MISSING_FUNDING_IS_NOT_ASSUMED_ZERO;KNOWN_COST_DRAG_EXCLUDES_UNOBSERVED_FUNDING", "observer_only": True, "action": "hold"}

