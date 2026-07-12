from __future__ import annotations

import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"

ADAPTER_DECISION = RUNTIME / "q4r3_closed_pnl_contract_adapter_decision_latest.json"
ADAPTER_AUDIT = RUNTIME / "q4r3_closed_pnl_contract_adapter_audit_latest.json"
COVERAGE = RUNTIME / "q4r3_25_strategy_realized_r_coverage_latest.json"
FACTORIAL_DECISION = RUNTIME / "q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json"

FREEZE_OUT = RUNTIME / "q4r3_raschke_freeze_manifest_latest.json"
SURFACE_OUT = RUNTIME / "q4r3_forward_r_writer_surface_latest.json"
CONTRACT_OUT = RUNTIME / "q4r3_forward_r_contract_latest.json"
DECISION_OUT = RUNTIME / "q4r3_forward_r_writer_decision_latest.json"
HTML_OUT = RUNTIME / "q4r3_forward_r_writer_surface_latest.html"

CODE_ROOTS = (
    ROOT / "backend",
    ROOT / "tools",
    ROOT / "services",
    ROOT / "scripts",
)
RUNTIME_ROOTS = (RUNTIME, ROOT / "data")
ALLOWED_CODE_SUFFIXES = {".py", ".sh"}
MAX_CODE_BYTES = 3 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 10

STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key", "strategy_slug")
SYMBOL_KEYS = ("symbol", "market", "ticker")
SIDE_KEYS = ("side", "direction", "position_side")
ID_KEYS = ("trade_id", "position_id", "event_id", "request_id", "order_id")
STATUS_KEYS = ("status", "state", "trade_status", "position_status")
EXIT_TS_KEYS = ("exit_ts", "close_ts", "closed_ts", "closed_at", "exit_time", "close_time")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "created_at")
REALIZED_R_KEYS = ("realized_r", "realized_R", "pnl_r", "pnl_R", "net_r", "net_R", "result_r")
REALIZED_USDT_KEYS = (
    "realized_pnl_usdt",
    "realized_net_pnl_usdt",
    "net_realized_pnl_usdt",
    "net_pnl_usdt",
    "closed_pnl_usdt",
)
RISK_USDT_KEYS = (
    "initial_risk_usdt",
    "position_risk_usdt",
    "risk_usdt",
    "risk_amount_usdt",
    "initial_stop_risk_usdt",
    "planned_risk_usdt",
    "max_loss_usdt",
)
ENTRY_PRICE_KEYS = ("entry", "entry_price", "avg_entry", "average_entry_price")
STOP_PRICE_KEYS = ("sl", "stop", "stop_price", "stop_loss", "initial_stop")
QUANTITY_KEYS = ("qty", "quantity", "position_qty", "base_qty", "contracts")
CONTRACT_TYPE_KEYS = ("contract_type", "market_type", "instrument_type", "settlement_type")
LINEAR_CONTRACT_VALUES = {"linear", "linear_usdt", "usdt_m", "usdtm", "usdt_perpetual", "linear_perpetual"}
CLOSED_STATUS = {"closed", "done", "settled", "final", "resolved", "exited", "complete", "completed"}
OPEN_STATUS = {"open", "active", "running", "pending", "queued", "candidate"}
STRATEGY_PARENT_KEYS = {"by_strategy", "strategies", "strategy_trades", "trades_by_strategy", "closed_by_strategy", "ledger_by_strategy"}
SKIP_PATH_TOKENS = (
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "q4r3_forward_r_writer_surface",
    "q4r3_closed_pnl_contract_adapter",
    "q4r3_25_strategy_realized_r_extended",
)

CODE_TERM_GROUPS = {
    "close": ("closed_at", "close_ts", "exit_ts", "status_closed", "close_reason"),
    "pnl": ("realized_pnl_usdt", "net_pnl_usdt", "closed_pnl_usdt", "realized_r", "pnl_r"),
    "risk": ("initial_risk_usdt", "position_risk_usdt", "risk_usdt", "planned_risk_usdt"),
    "writer": ("write_text", "json.dump", "atomic_json", "append", "replace("),
    "identity": ("trade_id", "position_id", "event_id", "strategy"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors="ignore"))


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def first_present(obj: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[str], Any]:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return key, obj[key]
    return None, None


def first_numeric(obj: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[str], Optional[float]]:
    for key in keys:
        if key in obj:
            number = safe_float(obj[key])
            if number is not None:
                return key, number
    return None, None


def first_id(obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    for key in ID_KEYS:
        if key in obj and obj[key] not in (None, ""):
            return key, str(obj[key])
    return None, None


def timestamp_present(obj: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return key
    return None


def closed_evidence(obj: Dict[str, Any]) -> bool:
    status = normalize(first_present(obj, STATUS_KEYS)[1])
    if status in OPEN_STATUS:
        return False
    if status in CLOSED_STATUS:
        return True
    if obj.get("status_closed") is True or obj.get("is_closed") is True or obj.get("closed") is True:
        return True
    return timestamp_present(obj, EXIT_TS_KEYS) is not None


def open_evidence(obj: Dict[str, Any]) -> bool:
    status = normalize(first_present(obj, STATUS_KEYS)[1])
    if status in OPEN_STATUS:
        return True
    if closed_evidence(obj):
        return False
    return timestamp_present(obj, ENTRY_TS_KEYS) is not None and first_present(obj, ENTRY_PRICE_KEYS)[0] is not None


def explicit_linear_contract(obj: Dict[str, Any]) -> bool:
    _, value = first_present(obj, CONTRACT_TYPE_KEYS)
    return normalize(value) in LINEAR_CONTRACT_VALUES


def inherited_strategy(obj: Dict[str, Any], inherited: Optional[str]) -> Optional[str]:
    _, value = first_present(obj, STRATEGY_KEYS)
    strategy = normalize(value)
    return strategy or inherited


def iter_objects(obj: Any, inherited: Optional[str] = None, parent_key: str = "", depth: int = 0) -> Iterator[Tuple[Dict[str, Any], Optional[str]]]:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        strategy = inherited_strategy(obj, inherited)
        yield obj, strategy
        strategy_map = parent_key.lower() in STRATEGY_PARENT_KEYS
        for key, value in obj.items():
            next_strategy = strategy
            if strategy_map and isinstance(value, (dict, list)):
                candidate = normalize(key)
                if candidate:
                    next_strategy = candidate
            yield from iter_objects(value, next_strategy, str(key), depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_objects(value, inherited, parent_key, depth + 1)


def candidate_json_paths() -> List[Path]:
    result: List[Path] = []
    for root in RUNTIME_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            lower = str(path).lower()
            if any(token in lower for token in SKIP_PATH_TOKENS):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= MAX_JSON_BYTES:
                result.append(path)
    return sorted(set(result))


def runtime_contract_inventory() -> Dict[str, Any]:
    files = []
    close_records = []
    open_records = []
    field_counts = Counter()
    source_counts = Counter()
    strategy_counts = Counter()

    for path in candidate_json_paths():
        file_record: Dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
        try:
            payload = load_json(path)
        except Exception as exc:
            file_record.update({"parsed": False, "error": repr(exc), "close_rows": 0, "open_rows": 0})
            files.append(file_record)
            continue

        local_close = 0
        local_open = 0
        local_fields = Counter()
        for obj, strategy in iter_objects(payload):
            id_key, stable_id = first_id(obj)
            if closed_evidence(obj):
                r_key, realized_r = first_numeric(obj, REALIZED_R_KEYS)
                usdt_key, realized_usdt = first_numeric(obj, REALIZED_USDT_KEYS)
                risk_key, risk_usdt = first_numeric(obj, RISK_USDT_KEYS)
                exit_key = timestamp_present(obj, EXIT_TS_KEYS)
                record = {
                    "source": str(path),
                    "strategy": strategy,
                    "id_key": id_key,
                    "stable_id": stable_id,
                    "r_key": r_key,
                    "realized_r_present": realized_r is not None,
                    "usdt_key": usdt_key,
                    "realized_usdt_present": realized_usdt is not None,
                    "risk_key": risk_key,
                    "risk_usdt_positive": risk_usdt is not None and risk_usdt > 0,
                    "exit_key": exit_key,
                }
                close_records.append(record)
                local_close += 1
                source_counts[str(path)] += 1
                if strategy:
                    strategy_counts[strategy] += 1
                for name in (id_key, r_key, usdt_key, risk_key, exit_key):
                    if name:
                        field_counts[name] += 1
                        local_fields[name] += 1
            elif open_evidence(obj):
                entry_key, entry = first_numeric(obj, ENTRY_PRICE_KEYS)
                stop_key, stop = first_numeric(obj, STOP_PRICE_KEYS)
                qty_key, qty = first_numeric(obj, QUANTITY_KEYS)
                risk_key, risk = first_numeric(obj, RISK_USDT_KEYS)
                contract_key, contract_value = first_present(obj, CONTRACT_TYPE_KEYS)
                entry_ts_key = timestamp_present(obj, ENTRY_TS_KEYS)
                record = {
                    "source": str(path),
                    "strategy": strategy,
                    "id_key": id_key,
                    "stable_id": stable_id,
                    "entry_key": entry_key,
                    "entry_present": entry is not None,
                    "stop_key": stop_key,
                    "stop_present": stop is not None,
                    "qty_key": qty_key,
                    "qty_positive": qty is not None and qty > 0,
                    "risk_key": risk_key,
                    "risk_usdt_positive": risk is not None and risk > 0,
                    "contract_key": contract_key,
                    "linear_contract_explicit": normalize(contract_value) in LINEAR_CONTRACT_VALUES,
                    "entry_ts_key": entry_ts_key,
                }
                open_records.append(record)
                local_open += 1
                for name in (id_key, entry_key, stop_key, qty_key, risk_key, contract_key, entry_ts_key):
                    if name:
                        field_counts[name] += 1
                        local_fields[name] += 1

        if local_close or local_open:
            file_record.update({"parsed": True, "close_rows": local_close, "open_rows": local_open, "top_fields": dict(local_fields.most_common(20))})
            files.append(file_record)

    open_by_id = {record["stable_id"]: record for record in open_records if record.get("stable_id")}
    close_with_id = [record for record in close_records if record.get("stable_id")]
    joinable = [record for record in close_with_id if record["stable_id"] in open_by_id]
    explicit_r_ready = [record for record in close_records if record["realized_r_present"]]
    explicit_usdt_risk_ready = [record for record in close_records if record["realized_usdt_present"] and record["risk_usdt_positive"]]

    join_formula_ready = 0
    join_explicit_risk_ready = 0
    for close in joinable:
        opened = open_by_id[close["stable_id"]]
        if opened["risk_usdt_positive"]:
            join_explicit_risk_ready += 1
        if opened["entry_present"] and opened["stop_present"] and opened["qty_positive"] and opened["linear_contract_explicit"]:
            join_formula_ready += 1

    return {
        "status": "PASS_Q4R3_FORWARD_R_RUNTIME_CONTRACT_INVENTORY",
        "files_scanned": len(candidate_json_paths()),
        "files_with_trade_contract_rows": len(files),
        "files": files,
        "close_record_count": len(close_records),
        "open_record_count": len(open_records),
        "close_with_stable_id_count": len(close_with_id),
        "joinable_close_open_count": len(joinable),
        "join_explicit_risk_ready_count": join_explicit_risk_ready,
        "join_formula_ready_count": join_formula_ready,
        "close_explicit_realized_r_count": len(explicit_r_ready),
        "close_usdt_plus_explicit_risk_count": len(explicit_usdt_risk_ready),
        "stable_id_join_rate_pct": round(len(joinable) / max(len(close_with_id), 1) * 100.0, 3),
        "top_fields": dict(field_counts.most_common(40)),
        "top_close_sources": [{"path": path, "rows": count} for path, count in source_counts.most_common(20)],
        "top_strategies": [{"strategy": name, "rows": count} for name, count in strategy_counts.most_common(30)],
        "raw_ids_included": False,
        "raw_trade_rows_included": False,
    }


def code_paths() -> List[Path]:
    result = []
    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}]
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() not in ALLOWED_CODE_SUFFIXES:
                    continue
                lower = str(path).lower()
                if any(token in lower for token in SKIP_PATH_TOKENS):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if 0 < size <= MAX_CODE_BYTES:
                    result.append(path)
    return sorted(set(result))


def score_code_candidate(path: Path, text: str) -> Optional[Dict[str, Any]]:
    lower = text.lower()
    groups = {}
    score = 0
    weights = {"close": 3, "pnl": 4, "risk": 5, "writer": 3, "identity": 2}
    for group, terms in CODE_TERM_GROUPS.items():
        hits = sorted({term for term in terms if term.lower() in lower})
        groups[group] = hits
        if hits:
            score += weights[group] + min(len(hits) - 1, 3)
    if not groups["close"] or not groups["writer"]:
        return None
    if groups["pnl"]:
        score += 3
    if groups["risk"]:
        score += 4
    return {
        "path": str(path),
        "score": score,
        "groups": groups,
        "contains_realized_r": any(key.lower() in lower for key in REALIZED_R_KEYS),
        "contains_realized_usdt": any(key.lower() in lower for key in REALIZED_USDT_KEYS),
        "contains_risk_usdt": any(key.lower() in lower for key in RISK_USDT_KEYS),
    }


def code_writer_surface() -> Dict[str, Any]:
    candidates = []
    errors = []
    for path in code_paths():
        try:
            text = path.read_text(errors="ignore")
            candidate = score_code_candidate(path, text)
            if candidate:
                candidates.append(candidate)
        except Exception as exc:
            errors.append({"path": str(path), "error": repr(exc)})
    candidates.sort(key=lambda row: (int(row["score"]), bool(row["contains_risk_usdt"]), bool(row["contains_realized_r"])), reverse=True)
    top = candidates[0] if candidates else None
    second_score = int(candidates[1]["score"]) if len(candidates) > 1 else 0
    dominant = bool(top and int(top["score"]) >= 12 and int(top["score"]) >= second_score + 3)
    return {
        "status": "PASS_Q4R3_FORWARD_R_CODE_WRITER_SURFACE",
        "files_scanned": len(code_paths()),
        "candidate_count": len(candidates),
        "dominant_single_writer": dominant,
        "dominant_writer": top,
        "second_score": second_score,
        "candidates": candidates[:30],
        "errors": errors,
    }


def build_contract() -> Dict[str, Any]:
    return {
        "schema": "zel_forward_realized_r_contract_v1",
        "scope": "future closed events only; no historical backfill",
        "entry_required": [
            "strategy",
            "symbol",
            "side",
            "trade_id|position_id|event_id",
            "entry_ts",
            "initial_risk_usdt",
            "risk_source",
        ],
        "close_required": [
            "strategy",
            "symbol",
            "side",
            "trade_id|position_id|event_id",
            "exit_ts",
            "status=closed",
            "realized_pnl_usdt",
            "initial_risk_usdt",
            "realized_R",
        ],
        "formula": "realized_R = realized_pnl_usdt / initial_risk_usdt",
        "formula_preconditions": [
            "initial_risk_usdt is explicit, finite and > 0",
            "realized_pnl_usdt is final net realized PnL for the same trade identity",
            "entry and close rows share the same stable trade identity",
        ],
        "entry_risk_capture_preference": [
            "use an already explicit initial_risk_usdt from risk planner",
            "otherwise calculate once at entry only when contract type and quantity units are explicit",
            "persist the denominator; never reconstruct it after close",
        ],
        "forbidden_inference": [
            "rr",
            "TP/SL labels",
            "position percentage",
            "leverage alone",
            "realized_pnl_pct",
            "aggregate strategy PnL",
            "entry and stop without explicit quantity units and contract type",
        ],
        "append_only": True,
        "dedup_identity": "strategy + stable_trade_id",
    }


def build_freeze_manifest(adapter_decision: Dict[str, Any], factorial_decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "PASS_Q4R3_RASCHKE_FREEZE_MANIFEST",
        "strategy": "raschke_macd_ema200",
        "state": "FROZEN_OBSERVER_RESERVE",
        "execution_enabled": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_authority": "blocked",
        "production_strategy_modified": False,
        "reason": "independent gate pass count is zero and historical R denominators are unavailable for a complete portfolio role audit",
        "best_preserved_candidate": factorial_decision.get("best_independent_candidate"),
        "historical_contract_verdict": adapter_decision.get("verdict"),
        "restart_conditions": [
            "new forward realized-R records exist for the missing strategy universe",
            "Raschke has a pre-registered fresh forward sample outside the consumed 180-day history",
            "both forward subwindows are nonnegative after costs",
            "profit factor, drawdown, symbol breadth and bootstrap gates pass",
        ],
        "forbidden_until_restart": [
            "additional threshold tuning on consumed history",
            "paper promotion",
            "live promotion",
            "unsafe historical R reconstruction",
        ],
        "updated_at": utc_now(),
    }


def decide(runtime_inventory: Dict[str, Any], code_surface: Dict[str, Any]) -> Dict[str, Any]:
    join_rate = float(runtime_inventory["stable_id_join_rate_pct"])
    join_explicit = int(runtime_inventory["join_explicit_risk_ready_count"])
    join_formula = int(runtime_inventory["join_formula_ready_count"])
    dominant = bool(code_surface["dominant_single_writer"])

    if dominant and (join_explicit > 0 or join_formula > 0) and join_rate >= 80.0:
        verdict = "COMMON_CLOSE_WRITER_PATCH_READY"
        next_action = "PATCH_SINGLE_COMMON_ENTRY_CLOSE_R_CONTRACT"
    elif (join_explicit > 0 or join_formula > 0) and join_rate >= 80.0:
        verdict = "SIDECAR_FORWARD_R_WRITER_READY"
        next_action = "INSTALL_APPEND_ONLY_FORWARD_R_SIDECAR"
    elif dominant:
        verdict = "COMMON_WRITER_FOUND_ENTRY_RISK_CAPTURE_REQUIRED"
        next_action = "PATCH_ENTRY_RISK_DENOMINATOR_THEN_CLOSE_R_WRITER"
    else:
        verdict = "FORWARD_R_WRITER_SURFACE_NOT_SINGLETON"
        next_action = "TRACE_TOP_WRITER_CANDIDATES_BEFORE_ANY_PRODUCTION_PATCH"

    return {
        "status": "PASS_Q4R3_FORWARD_R_WRITER_SURFACE_DECISION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "dominant_writer": code_surface.get("dominant_writer"),
        "stable_id_join_rate_pct": join_rate,
        "join_explicit_risk_ready_count": join_explicit,
        "join_formula_ready_count": join_formula,
        "close_explicit_realized_r_count": runtime_inventory["close_explicit_realized_r_count"],
        "close_usdt_plus_explicit_risk_count": runtime_inventory["close_usdt_plus_explicit_risk_count"],
        "next_modules": [next_action, "FORWARD_R_CONTRACT_CANARY", "RERUN_25_STRATEGY_COVERAGE_AFTER_NEW_CLOSES"],
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
            "final_holdout_opened": False,
        },
    }


def write_html(freeze: Dict[str, Any], runtime_inventory: Dict[str, Any], code_surface: Dict[str, Any], decision: Dict[str, Any]) -> None:
    candidate_rows = []
    for item in code_surface.get("candidates", [])[:15]:
        candidate_rows.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td>"
            f"<td>{item['score']}</td>"
            f"<td>{html.escape(json.dumps(item['groups'], ensure_ascii=False))}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Forward R writer surface</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Forward realized-R writer surface audit</h1>",
            "<h2>Raschke freeze</h2><pre>", html.escape(json.dumps(freeze, ensure_ascii=False, indent=2)), "</pre>",
            "<h2>Runtime contract inventory</h2><pre>", html.escape(json.dumps(runtime_inventory, ensure_ascii=False, indent=2)), "</pre>",
            "<h2>Code writer candidates</h2><table><thead><tr><th>Path</th><th>Score</th><th>Evidence</th></tr></thead><tbody>",
            "".join(candidate_rows),
            "</tbody></table><h2>Decision</h2><pre>", html.escape(json.dumps(decision, ensure_ascii=False, indent=2)), "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    adapter_decision = load_json(ADAPTER_DECISION)
    adapter_audit = load_json(ADAPTER_AUDIT)
    coverage = load_json(COVERAGE)
    factorial_decision = load_json(FACTORIAL_DECISION)

    freeze = build_freeze_manifest(adapter_decision, factorial_decision)
    runtime_inventory = runtime_contract_inventory()
    code_surface = code_writer_surface()
    contract = build_contract()
    decision = decide(runtime_inventory, code_surface)
    decision["missing_strategy_count"] = len(coverage.get("missing_expected_strategies", []))
    decision["historical_contract_state_counts"] = adapter_decision.get("contract_state_counts", {})
    decision["historical_adapter_r_ready_rows_appended"] = adapter_decision.get("adapter_r_ready_rows_appended", 0)
    decision["raschke_state"] = freeze["state"]
    decision["adapter_audit_status"] = adapter_audit.get("status")

    atomic_json(FREEZE_OUT, freeze)
    atomic_json(SURFACE_OUT, {"runtime": runtime_inventory, "code": code_surface})
    atomic_json(CONTRACT_OUT, contract)
    atomic_json(DECISION_OUT, decision)
    write_html(freeze, runtime_inventory, code_surface, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
