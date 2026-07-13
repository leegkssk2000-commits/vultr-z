from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SOURCE = "q4r3_exact25_dedicated_shadow_producer"
ADAPTER = "q4r3_exact25_single_event_measurement_adapter"
SEV = {"m": 1, "M": 2, "C": 3}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def num(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def epoch(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000.0 if value > 10_000_000_000 else value
    text = str(value).strip()
    if not text:
        return None
    try:
        return epoch(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def identity(item: Mapping[str, Any]) -> str:
    for key in ("strategy_id", "id", "name", "strategy"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def sha(item: Mapping[str, Any]) -> str:
    for key in ("owner_sha256", "sha256", "owner_sha", "source_sha256", "sha"):
        value = item.get(key)
        if isinstance(value, str) and len(value.strip()) >= 32:
            return value.strip().lower()
    owner = item.get("owner")
    return sha(owner) if isinstance(owner, dict) else ""


def owners(manifest: Mapping[str, Any], expected: int) -> dict[str, str]:
    rows = manifest.get("strategies")
    if not isinstance(rows, list) or len(rows) != expected:
        raise RuntimeError(f"MANIFEST_COUNT_MISMATCH:{len(rows) if isinstance(rows, list) else -1}:{expected}")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("MANIFEST_STRATEGY_OBJECT_REQUIRED")
        key, owner = identity(row), sha(row)
        if not key or not owner or key in result:
            raise RuntimeError(f"MANIFEST_OWNER_INVALID_OR_DUPLICATE:{key or 'unknown'}")
        result[key] = owner
    return result


def issue(code: str, severity: str, detail: str, metric: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail, "metric": metric}


def read_ledger(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not path.exists():
        return [], [issue("LEDGER_MISSING", "C", str(path), "ledger_exists")]
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        return [], [issue("LEDGER_ENCODING_INVALID", "C", str(exc), "ledger_integrity")]
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(issue("LEDGER_JSON_MALFORMED", "C", f"line={line_no}:{exc.msg}", "ledger_integrity"))
            continue
        if not isinstance(row, dict):
            problems.append(issue("LEDGER_ROW_NOT_OBJECT", "C", f"line={line_no}", "ledger_integrity"))
            continue
        rows.append(row)
    return rows, problems


def static_checks(
    ssot: Mapping[str, Any],
    gate: Mapping[str, Any],
    writer: Mapping[str, Any],
    producer: Mapping[str, Any],
    owner_map: Mapping[str, str],
    now: float,
) -> tuple[list[str], float, list[dict[str, str]]]:
    problems: list[dict[str, str]] = []
    expected_epoch = str(ssot["expected_epoch"])
    expected_ns = str(ssot["expected_namespace"])
    expected_symbols = int(ssot["expected_symbol_count"])
    stale = float(ssot["status_stale_sec"])
    skew = float(ssot.get("max_clock_skew_sec", 30))
    symbols = [str(x).upper() for x in gate.get("symbols", [])] if isinstance(gate.get("symbols"), list) else []

    def add(cond: bool, code: str, detail: str, metric: str, severity: str = "C") -> None:
        if cond:
            problems.append(issue(code, severity, detail, metric))

    add(gate.get("state") != "ACTIVE", "GATE_NOT_ACTIVE", str(gate.get("state")), "gate_state")
    add(
        gate.get("epoch_id") != expected_epoch or gate.get("measurement_namespace") != expected_ns,
        "GATE_IDENTITY_MISMATCH",
        f"epoch={gate.get('epoch_id')} namespace={gate.get('measurement_namespace')}",
        "gate_identity",
    )
    add(len(symbols) != expected_symbols or len(set(symbols)) != expected_symbols, "GATE_NOT_EXACT5", str(symbols), "symbols")
    required = {str(x).upper() for x in ssot.get("required_core_symbols", [])}
    add(bool(required - set(symbols)), "GATE_CORE_SYMBOL_MISSING", str(sorted(required - set(symbols))), "symbols")
    add(gate.get("strategy_count") != len(owner_map), "GATE_STRATEGY_COUNT_MISMATCH", str(gate.get("strategy_count")), "strategy_count")
    for key in ("paper_enabled", "live_enabled", "order_enabled", "historical_backfill_allowed"):
        add(gate.get(key) is not False, "UNSAFE_GATE_FLAG", f"{key}={gate.get(key)}", key)
    start = num(gate.get("start_epoch"))
    if start is None or start <= 0:
        problems.append(issue("GATE_START_EPOCH_INVALID", "C", str(gate.get("start_epoch")), "start_epoch"))
        start = 0.0

    def status(name: str, payload: Mapping[str, Any]) -> None:
        add(payload.get("state") != "RUNNING", f"{name}_NOT_RUNNING", str(payload.get("state")), f"{name.lower()}_state")
        updated = epoch(payload.get("updated_at"))
        if updated is None:
            problems.append(issue(f"{name}_UPDATED_AT_INVALID", "C", str(payload.get("updated_at")), f"{name.lower()}_freshness"))
            return
        age = now - updated
        add(age > stale, f"{name}_STALE", f"age_sec={age:.3f}>limit_sec={stale:.3f}", f"{name.lower()}_freshness")
        add(age < -skew, f"{name}_CLOCK_SKEW", f"future_sec={-age:.3f}>limit_sec={skew:.3f}", f"{name.lower()}_freshness", "M")

    status("WRITER", writer)
    status("PRODUCER", producer)
    add(writer.get("last_error") not in (None, ""), "WRITER_LAST_ERROR", str(writer.get("last_error")), "writer_error")
    add(writer.get("production_measurement_write_enabled") is not True, "WRITER_DISABLED", str(writer.get("production_measurement_write_enabled")), "writer_enabled")
    add(writer.get("historical_backfill_allowed") is not False, "WRITER_BACKFILL_UNSAFE", str(writer.get("historical_backfill_allowed")), "backfill")
    add(set(str(x).upper() for x in writer.get("symbols", [])) != set(symbols), "WRITER_SYMBOL_MISMATCH", str(writer.get("symbols")), "symbols")
    add(producer.get("processed_symbol_count") != expected_symbols, "PRODUCER_SYMBOL_COUNT_MISMATCH", str(producer.get("processed_symbol_count")), "processed_symbol_count")
    add(set(str(x).upper() for x in producer.get("symbols", [])) != set(symbols), "PRODUCER_SYMBOL_MISMATCH", str(producer.get("symbols")), "symbols")
    add(producer.get("cycle_errors") not in ({}, None), "PRODUCER_CYCLE_ERRORS", str(producer.get("cycle_errors")), "producer_errors")
    add(producer.get("feature_filter_enabled") not in (False, None), "FEATURE_FILTER_ENABLED", str(producer.get("feature_filter_enabled")), "feature_filter")
    return symbols, start, problems


def row_checks(
    rows: Sequence[Mapping[str, Any]],
    owner_map: Mapping[str, str],
    symbols: Sequence[str],
    start: float,
    expected_epoch: str,
    expected_ns: str,
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed = set(symbols)
    for index, row in enumerate(rows, 1):
        event = str(row.get("event_id") or "")
        loc = event or f"row={index}"

        def add(cond: bool, code: str, detail: str, metric: str, severity: str = "C") -> None:
            if cond:
                problems.append(issue(code, severity, detail, metric))

        add(not event, "EVENT_ID_MISSING", loc, "event_id")
        add(bool(event) and event in seen, "DUPLICATE_EVENT_ID", loc, "event_id")
        seen.add(event)
        strategy = str(row.get("strategy_id") or "")
        add(strategy not in owner_map, "STRATEGY_NOT_IN_MANIFEST", f"{loc}:{strategy}", "strategy_id")
        if strategy in owner_map:
            add(str(row.get("owner_sha256") or "").lower() != owner_map[strategy], "OWNER_SHA_MISMATCH", f"{loc}:{strategy}", "owner_sha256")
        add(str(row.get("symbol") or "").upper() not in allowed, "EVENT_SYMBOL_OUTSIDE_EXACT5", f"{loc}:{row.get('symbol')}", "symbol")
        add(row.get("epoch_id") != expected_epoch or row.get("measurement_namespace") != expected_ns, "EVENT_IDENTITY_MISMATCH", loc, "event_identity")
        add(row.get("source") != SOURCE, "EVENT_SOURCE_MISMATCH", f"{loc}:{row.get('source')}", "source")
        add(row.get("measurement_source") != ADAPTER, "MEASUREMENT_SOURCE_MISMATCH", f"{loc}:{row.get('measurement_source')}", "measurement_source")
        add(row.get("formula_verified") is not True or row.get("owner_lineage_verified") is not True, "VERIFICATION_FLAG_MISSING", loc, "verification_flags")
        add(str(row.get("mode") or "").lower() != "shadow" or row.get("shadow") is not True, "EVENT_NOT_SHADOW", loc, "mode")
        add(str(row.get("status") or "").upper() != "CLOSED" or row.get("closed") is not True, "EVENT_NOT_CLOSED", loc, "status")
        for key in ("paper_enabled", "live_enabled", "order_enabled"):
            add(row.get(key) is not False, "UNSAFE_EVENT_FLAG", f"{loc}:{key}={row.get(key)}", key)

        risk, pnl, realized = num(row.get("initial_risk_usdt")), num(row.get("realized_pnl_usdt")), num(row.get("realized_R"))
        add(risk is None or risk <= 0, "INITIAL_RISK_INVALID", loc, "initial_risk_usdt")
        add(pnl is None, "REALIZED_PNL_INVALID", loc, "realized_pnl_usdt")
        add(realized is None, "REALIZED_R_INVALID", loc, "realized_R")
        if risk and risk > 0 and pnl is not None and realized is not None:
            expected = pnl / risk
            add(abs(realized - expected) > max(1e-10, abs(expected) * 1e-9), "REALIZED_R_FORMULA_MISMATCH", f"{loc}:actual={realized:.12g} expected={expected:.12g}", "realized_R")

        entered, exited = epoch(row.get("entry_ts")), epoch(row.get("exit_ts"))
        add(entered is None or exited is None, "EVENT_TIMESTAMP_INVALID", loc, "timestamp")
        if entered is not None and exited is not None:
            add(entered < start or exited < start, "EVENT_PREDATES_GATE", loc, "timestamp")
            add(exited < entered, "EXIT_BEFORE_ENTRY", loc, "timestamp")
        for metric in ("fee", "slippage", "MFE_R", "MAE_R", "time_exposure_min"):
            add(num(row.get(metric)) is None, "MEASUREMENT_FIELD_INVALID", f"{loc}:{metric}", metric, "M")
        exposure = num(row.get("time_exposure_min"))
        add(exposure is not None and exposure < 0, "NEGATIVE_TIME_EXPOSURE", loc, "time_exposure_min", "M")
    return problems


def avg(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def rnd(value: float | None, digits: int = 8) -> float | None:
    return round(value, digits) if value is not None else None


def drawdown(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def loss_streak(values: Sequence[float]) -> int:
    current = maximum = 0
    for value in values:
        current = current + 1 if value < 0 else 0
        maximum = max(maximum, current)
    return maximum


def scoreboard(rows: Sequence[Mapping[str, Any]], strategies: Sequence[str], symbols: Sequence[str], expected_epoch: str) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("strategy_id") or "") in strategies:
            grouped[str(row["strategy_id"])].append(row)
    output: list[dict[str, Any]] = []
    for strategy in sorted(strategies):
        items = sorted(grouped[strategy], key=lambda row: epoch(row.get("exit_ts")) or 0.0)
        rs = [x for x in (num(row.get("realized_R")) for row in items) if x is not None]
        wins, losses = [x for x in rs if x > 0], [x for x in rs if x < 0]
        metric = lambda key: [x for x in (num(row.get(key)) for row in items) if x is not None]
        entry_session = lambda row: str(row.get("entry_features", {}).get("session_window") or "unknown").lower() if isinstance(row.get("entry_features"), dict) else "unknown"
        output.append({
            "strategy_id": strategy,
            "closed_count": len(items),
            "cumulative_R": rnd(sum(rs)),
            "expectancy_R": rnd(avg(rs)),
            "win_rate_pct": rnd(100.0 * len(wins) / len(rs) if rs else None, 4),
            "profit_factor": rnd(sum(wins) / abs(sum(losses)) if losses else None),
            "max_drawdown_R": rnd(drawdown(rs)),
            "max_consecutive_losses": loss_streak(rs),
            "fee_usdt_sum": rnd(sum(metric("fee"))),
            "slippage_usdt_sum": rnd(sum(metric("slippage"))),
            "MFE_R_avg": rnd(avg(metric("MFE_R"))),
            "MAE_R_avg": rnd(avg(metric("MAE_R"))),
            "time_exposure_min_avg": rnd(avg(metric("time_exposure_min"))),
            "symbol_counts": dict(sorted(Counter(str(row.get("symbol") or "unknown").upper() for row in items).items())),
            "side_counts": dict(sorted(Counter(str(row.get("side") or "unknown").lower() for row in items).items())),
            "regime_counts": dict(sorted(Counter(str(row.get("regime") or "unknown").lower() for row in items).items())),
            "session_counts": dict(sorted(Counter(entry_session(row) for row in items).items())),
            "decision_state": "MEASUREMENT_ONLY_NO_KEEP_REPAIR_RETIRE",
        })
    counts = [int(row["closed_count"]) for row in output]
    return {
        "schema": "q4r3_exact25_readonly_strategy_scoreboard_v1",
        "generated_at": now_iso(),
        "epoch_id": expected_epoch,
        "symbol_universe": "EXACT5",
        "symbols": list(symbols),
        "strategy_count": len(strategies),
        "ledger_row_count": len(rows),
        "strategy_closed_count_min": min(counts) if counts else 0,
        "strategy_closed_count_max": max(counts) if counts else 0,
        "strategy_zero_close_count": sum(x == 0 for x in counts),
        "comparison_decision_enabled": False,
        "comparison_ready": False,
        "comparison_block_reason": "DECISION_THRESHOLD_NOT_AUTHORIZED_ACCUMULATION_ONLY",
        "strategies": output,
    }


def matrix(rows: Sequence[Mapping[str, Any]], strategies: Sequence[str], symbols: Sequence[str], expected_epoch: str) -> dict[str, Any]:
    symbol_counts = {strategy: {symbol: 0 for symbol in symbols} for strategy in sorted(strategies)}
    sides = {strategy: Counter() for strategy in strategies}
    regimes = {strategy: Counter() for strategy in strategies}
    sessions = {strategy: Counter() for strategy in strategies}
    for row in rows:
        strategy, symbol = str(row.get("strategy_id") or ""), str(row.get("symbol") or "").upper()
        if strategy not in symbol_counts:
            continue
        if symbol in symbol_counts[strategy]:
            symbol_counts[strategy][symbol] += 1
        sides[strategy][str(row.get("side") or "unknown").lower()] += 1
        regimes[strategy][str(row.get("regime") or "unknown").lower()] += 1
        session = str(row.get("entry_features", {}).get("session_window") or "unknown").lower() if isinstance(row.get("entry_features"), dict) else "unknown"
        sessions[strategy][session] += 1
    totals = {strategy: sum(values.values()) for strategy, values in symbol_counts.items()}
    nonzero = [value for value in totals.values() if value > 0]
    concentration = max(nonzero) / min(nonzero) if len(nonzero) >= 2 else None
    return {
        "schema": "q4r3_exact25_readonly_sample_matrix_v1",
        "generated_at": now_iso(),
        "epoch_id": expected_epoch,
        "symbols": list(symbols),
        "ledger_row_count": len(rows),
        "strategy_symbol_counts": symbol_counts,
        "strategy_side_counts": {key: dict(sorted(value.items())) for key, value in sorted(sides.items())},
        "strategy_regime_counts": {key: dict(sorted(value.items())) for key, value in sorted(regimes.items())},
        "strategy_session_counts": {key: dict(sorted(value.items())) for key, value in sorted(sessions.items())},
        "strategy_totals": totals,
        "zero_close_strategies": sorted(key for key, value in totals.items() if value == 0),
        "nonzero_strategy_concentration_ratio": rnd(concentration),
        "interpretation": "OBSERVATION_ONLY_ZERO_OR_CONCENTRATION_IS_NOT_A_POLICY_VIOLATION_DURING_ACCUMULATION",
    }


def publish_alert(path: Path, problems: Sequence[Mapping[str, Any]]) -> tuple[bool, str | None, str | None]:
    if not problems:
        path.unlink(missing_ok=True)
        return False, None, None
    identities = Counter((str(x.get("code")), str(x.get("severity")), str(x.get("metric"))) for x in problems)
    stable = [{"code": key[0], "severity": key[1], "metric": key[2], "count": count} for key, count in sorted(identities.items())]
    fingerprint = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    severity = max((str(x.get("severity")) for x in problems), key=lambda value: SEV.get(value, 0))
    prior: dict[str, Any] = {}
    if path.exists():
        try:
            prior = load(path)
        except Exception:
            pass
    notify = prior.get("fingerprint") != fingerprint or prior.get("severity") != severity or prior.get("action") != "HOLD"
    atomic(path, {
        "schema": "q4r3_exact25_violation_only_alert_v1",
        "generated_at": now_iso(),
        "bundle": ["EXACT25", "formal_measurement"],
        "severity": severity,
        "action": "HOLD",
        "violation_count": len(problems),
        "fingerprint": fingerprint,
        "notify": notify,
        "violations": list(problems),
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
    })
    return notify, severity, fingerprint


def run(args: argparse.Namespace) -> int:
    now = args.now_epoch if args.now_epoch is not None else datetime.now(timezone.utc).timestamp()
    ssot, manifest, gate = load(args.ssot), load(args.manifest), load(args.gate)
    writer, producer = load(args.writer_status), load(args.producer_status)
    owner_map = owners(manifest, int(ssot["expected_strategy_count"]))
    symbols, start, problems = static_checks(ssot, gate, writer, producer, owner_map, now)
    rows, ledger_problems = read_ledger(args.ledger)
    problems.extend(ledger_problems)
    problems.extend(row_checks(rows, owner_map, symbols, start, str(ssot["expected_epoch"]), str(ssot["expected_namespace"])))

    writer_count = writer.get("ledger_row_count")
    if isinstance(writer_count, int) and writer_count != len(rows):
        time.sleep(1.0)
        writer = load(args.writer_status)
        retry_rows, retry_problems = read_ledger(args.ledger)
        if not retry_problems:
            rows = retry_rows
        writer_count = writer.get("ledger_row_count")
        if isinstance(writer_count, int) and writer_count != len(rows):
            problems.append(issue("WRITER_LEDGER_COUNT_MISMATCH", "C", f"writer={writer_count} observer={len(rows)}", "ledger_row_count"))

    board = scoreboard(rows, list(owner_map), symbols, str(ssot["expected_epoch"]))
    sample = matrix(rows, list(owner_map), symbols, str(ssot["expected_epoch"]))
    atomic(args.scoreboard, board)
    atomic(args.sample_matrix, sample)
    notify, severity, fingerprint = publish_alert(args.violations, problems)
    status = {
        "schema": "q4r3_exact25_readonly_scoreboard_watchdog_status_v1",
        "generated_at": now_iso(),
        "state": "VIOLATION" if problems else "HEALTHY",
        "action": "HOLD",
        "observer_mode": "read_only",
        "epoch_id": str(ssot["expected_epoch"]),
        "measurement_namespace": str(ssot["expected_namespace"]),
        "symbol_universe": "EXACT5",
        "symbols": symbols,
        "strategy_count": len(owner_map),
        "ledger_row_count": len(rows),
        "violation_count": len(problems),
        "violation_alert_exists": bool(problems),
        "violation_notify": notify,
        "violation_severity": severity,
        "violation_fingerprint": fingerprint,
        "comparison_decision_enabled": False,
        "comparison_ready": False,
        "scoreboard_path": str(args.scoreboard.resolve()),
        "sample_matrix_path": str(args.sample_matrix.resolve()),
        "violation_path": str(args.violations.resolve()) if problems else None,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
        "order_authority": "blocked",
        "execution_authority": "none",
    }
    atomic(args.status, status)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in ("ledger", "manifest", "gate", "writer-status", "producer-status", "ssot", "scoreboard", "sample-matrix", "status", "violations"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--now-epoch", type=float)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
