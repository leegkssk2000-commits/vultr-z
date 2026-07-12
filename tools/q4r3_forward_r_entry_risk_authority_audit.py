from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
AUTHORITY_IN = RUNTIME / "q4r3_forward_r_source_authority_latest.json"
LINEAGE_IN = RUNTIME / "q4r3_forward_r_writer_lineage_latest.json"
DECISION_IN = RUNTIME / "q4r3_forward_r_source_lineage_decision_latest.json"
FREEZE_IN = RUNTIME / "q4r3_raschke_freeze_manifest_latest.json"

AUDIT_OUT = RUNTIME / "q4r3_forward_r_entry_risk_authority_latest.json"
WRITER_OUT = RUNTIME / "q4r3_forward_r_entry_writer_lineage_latest.json"
DECISION_OUT = RUNTIME / "q4r3_forward_r_entry_risk_decision_latest.json"
HTML_OUT = RUNTIME / "q4r3_forward_r_entry_risk_authority_latest.html"

MAX_JSON_BYTES = 120 * 1024 * 1024
MAX_CODE_BYTES = 3 * 1024 * 1024
MAX_DEPTH = 10
JOIN_GATE_PCT = 80.0

IDENTITY_KEYS = ("trade_id", "position_id", "event_id", "request_id", "order_id", "client_order_id")
STATUS_KEYS = ("status", "state", "trade_status", "position_status")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "created_at")
ENTRY_PRICE_KEYS = ("entry_price", "avg_entry_price", "average_entry_price", "open_price", "fill_price")
STOP_PRICE_KEYS = ("initial_stop_price", "stop_loss_price", "sl_price", "stop_price", "stop_loss", "native_stop")
BASE_QTY_KEYS = ("quantity", "qty", "position_qty", "base_qty", "filled_qty")
CONTRACT_QTY_KEYS = ("contracts", "contract_qty")
CONTRACT_MULTIPLIER_KEYS = ("contract_size", "contract_multiplier", "multiplier")
NOTIONAL_KEYS = ("position_notional_usdt", "notional_usdt", "position_value_usdt", "position_size_usdt")
EXPLICIT_RISK_KEYS = ("initial_risk_usdt", "position_risk_usdt", "risk_usdt", "planned_risk_usdt")
SIDE_KEYS = ("side", "direction", "position_side")
STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key")
SYMBOL_KEYS = ("symbol", "market", "ticker")
OPEN_STATUS = {"open", "active", "running", "pending", "opened", "new"}
CLOSED_STATUS = {"closed", "done", "settled", "exited", "complete", "completed", "final"}

CODE_ROOTS = (
    ROOT / "backend",
    ROOT / "tools",
    ROOT / "services",
    ROOT / "scripts",
    ROOT / "systemd",
    Path("/etc/systemd/system"),
)
CODE_SUFFIXES = {".py", ".sh", ".service", ".timer"}
DIAGNOSTIC_PATH_PARTS = (
    "/tests/", "/test_", "_test.py", "probe", "replay", "audit", "forensic", "tournament",
    "diagnostic", "research", "capture", "backfill", "route_a", "raschke_v", "factorial", "snapshot",
)
WRITER_TERMS = ("write_text", "json.dump", "json.dumps", "open(", "append", "replace(", "os.replace", "rename(")
IDENTITY_TERMS = IDENTITY_KEYS
ENTRY_PRICE_TERMS = ENTRY_PRICE_KEYS
STOP_TERMS = STOP_PRICE_KEYS
QTY_TERMS = BASE_QTY_KEYS + CONTRACT_QTY_KEYS + NOTIONAL_KEYS
RISK_TERMS = EXPLICIT_RISK_KEYS
ENTRY_TERMS = ENTRY_TS_KEYS + ("status_open", "is_open")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors="ignore"))


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def timestamp_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        integer = int(value)
        return integer * 1000 if abs(integer) < 100_000_000_000 else integer
    text = str(value).strip()
    if not text:
        return None
    try:
        integer = int(float(text))
        return integer * 1000 if abs(integer) < 100_000_000_000 else integer
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def first_key(obj: Dict[str, Any], keys: Sequence[str], positive: bool = False) -> Optional[str]:
    for key in keys:
        if key not in obj:
            continue
        value = safe_float(obj.get(key))
        if value is None:
            continue
        if positive and value <= 0:
            continue
        return key
    return None


def first_value(obj: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def is_open_record(obj: Dict[str, Any]) -> bool:
    status = normalize(first_value(obj, STATUS_KEYS))
    if status in CLOSED_STATUS or obj.get("status_closed") is True or obj.get("is_closed") is True or obj.get("closed") is True:
        return False
    if status in OPEN_STATUS or obj.get("is_open") is True or obj.get("open") is True:
        return True
    entry_ts = timestamp_ms(first_value(obj, ENTRY_TS_KEYS))
    exit_value = first_value(obj, ("exit_ts", "close_ts", "closed_ts", "closed_at"))
    return entry_ts is not None and exit_value in (None, "")


def risk_contract(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not is_open_record(obj):
        return None
    identity_key = next((key for key in IDENTITY_KEYS if obj.get(key) not in (None, "")), None)
    identity_value = str(obj.get(identity_key)) if identity_key else ""
    identity_hash = hashlib.sha256(identity_value.encode("utf-8")).hexdigest()[:20] if identity_value else None
    explicit_key = first_key(obj, EXPLICIT_RISK_KEYS, positive=True)
    entry_key = first_key(obj, ENTRY_PRICE_KEYS, positive=True)
    stop_key = first_key(obj, STOP_PRICE_KEYS, positive=True)
    base_qty_key = first_key(obj, BASE_QTY_KEYS, positive=True)
    contract_qty_key = first_key(obj, CONTRACT_QTY_KEYS, positive=True)
    multiplier_key = first_key(obj, CONTRACT_MULTIPLIER_KEYS, positive=True)
    notional_key = first_key(obj, NOTIONAL_KEYS, positive=True)

    method = "NOT_READY"
    calculated = None
    if explicit_key:
        method = "EXPLICIT_RISK_USDT"
        calculated = float(obj[explicit_key])
    elif entry_key and stop_key and base_qty_key:
        method = "PRICE_DISTANCE_X_BASE_QTY"
        calculated = abs(float(obj[entry_key]) - float(obj[stop_key])) * float(obj[base_qty_key])
    elif entry_key and stop_key and contract_qty_key and multiplier_key:
        method = "PRICE_DISTANCE_X_CONTRACT_QTY_X_MULTIPLIER"
        calculated = (
            abs(float(obj[entry_key]) - float(obj[stop_key]))
            * float(obj[contract_qty_key])
            * float(obj[multiplier_key])
        )
    elif entry_key and stop_key and notional_key:
        method = "PRICE_DISTANCE_RATIO_X_NOTIONAL"
        calculated = abs(float(obj[entry_key]) - float(obj[stop_key])) / float(obj[entry_key]) * float(obj[notional_key])

    if calculated is not None and (not math.isfinite(calculated) or calculated <= 0):
        method = "INVALID_NONPOSITIVE_RISK"
        calculated = None

    missing = []
    if not identity_key:
        missing.append("stable_id")
    if not explicit_key:
        if not entry_key:
            missing.append("entry_price")
        if not stop_key:
            missing.append("stop_price")
        if not (base_qty_key or notional_key or (contract_qty_key and multiplier_key)):
            missing.append("base_qty_or_notional_or_contract_multiplier")

    side = normalize(first_value(obj, SIDE_KEYS))
    orientation = "UNKNOWN"
    if entry_key and stop_key and side in {"long", "buy", "short", "sell"}:
        entry = float(obj[entry_key])
        stop = float(obj[stop_key])
        expected = stop < entry if side in {"long", "buy"} else stop > entry
        orientation = "VALID" if expected else "INVALID"

    return {
        "identity_key": identity_key,
        "identity_hash": identity_hash,
        "entry_ts": timestamp_ms(first_value(obj, ENTRY_TS_KEYS)),
        "strategy_present": first_value(obj, STRATEGY_KEYS) not in (None, ""),
        "symbol_present": first_value(obj, SYMBOL_KEYS) not in (None, ""),
        "side": side or None,
        "orientation": orientation,
        "explicit_risk_key": explicit_key,
        "entry_price_key": entry_key,
        "stop_price_key": stop_key,
        "base_qty_key": base_qty_key,
        "contract_qty_key": contract_qty_key,
        "multiplier_key": multiplier_key,
        "notional_key": notional_key,
        "formula_method": method,
        "formula_ready": calculated is not None,
        "calculated_initial_risk_usdt": calculated,
        "missing": missing,
    }


def iter_open_contracts(obj: Any, depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        contract = risk_contract(obj)
        if contract is not None:
            yield contract
        for value in obj.values():
            yield from iter_open_contracts(value, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_open_contracts(value, depth + 1)


def authoritative_paths(authority: Dict[str, Any]) -> List[Path]:
    paths = []
    for item in authority.get("authoritative_files", []):
        path = Path(str(item.get("path", "")))
        if path.exists() and path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= MAX_JSON_BYTES:
                paths.append(path)
    return sorted(set(paths))


def source_audit(authority: Dict[str, Any]) -> Dict[str, Any]:
    files = []
    all_contracts: List[Dict[str, Any]] = []
    for path in authoritative_paths(authority):
        record: Dict[str, Any] = {"path": str(path), "basename": path.name, "size_bytes": path.stat().st_size}
        try:
            contracts = list(iter_open_contracts(load_json(path)))
            for contract in contracts:
                contract["source"] = str(path)
            all_contracts.extend(contracts)
            missing_counter = Counter(item for contract in contracts for item in contract["missing"])
            method_counter = Counter(contract["formula_method"] for contract in contracts)
            record.update({
                "parsed": True,
                "open_contract_rows": len(contracts),
                "stable_id_rows": sum(1 for row in contracts if row["identity_hash"]),
                "explicit_risk_rows": sum(1 for row in contracts if row["explicit_risk_key"]),
                "formula_ready_rows": sum(1 for row in contracts if row["formula_ready"]),
                "valid_stop_orientation_rows": sum(1 for row in contracts if row["orientation"] == "VALID"),
                "invalid_stop_orientation_rows": sum(1 for row in contracts if row["orientation"] == "INVALID"),
                "formula_methods": dict(method_counter),
                "missing_fields": dict(missing_counter),
            })
        except Exception as exc:
            record.update({"parsed": False, "open_contract_rows": 0, "error": repr(exc)})
        files.append(record)

    all_missing = Counter(item for contract in all_contracts for item in contract["missing"])
    methods = Counter(contract["formula_method"] for contract in all_contracts)
    unique_ids = {contract["identity_hash"] for contract in all_contracts if contract["identity_hash"]}
    formula_ready_ids = {contract["identity_hash"] for contract in all_contracts if contract["identity_hash"] and contract["formula_ready"]}
    return {
        "status": "PASS_Q4R3_FORWARD_R_ENTRY_RISK_AUTHORITY_AUDIT",
        "authoritative_file_count": len(files),
        "open_contract_rows": len(all_contracts),
        "open_with_stable_id_count": sum(1 for row in all_contracts if row["identity_hash"]),
        "unique_open_ids": len(unique_ids),
        "explicit_risk_rows": sum(1 for row in all_contracts if row["explicit_risk_key"]),
        "formula_ready_rows": sum(1 for row in all_contracts if row["formula_ready"]),
        "formula_ready_unique_ids": len(formula_ready_ids),
        "formula_ready_rate_pct": round(len(formula_ready_ids) / max(len(unique_ids), 1) * 100.0, 3),
        "formula_methods": dict(methods),
        "missing_fields": dict(all_missing),
        "files": files,
        "raw_ids_emitted": False,
        "formula_contract": {
            "accepted": [
                "explicit initial_risk_usdt",
                "abs(entry_price-stop_price)*base_qty",
                "abs(entry_price-stop_price)*contracts*explicit_contract_multiplier",
                "abs(entry_price-stop_price)/entry_price*explicit_notional_usdt",
            ],
            "forbidden": ["leverage-only inference", "position-percent inference", "RR inference", "PnL-percent inference"],
        },
    }


def code_paths() -> List[Path]:
    result = []
    for root in CODE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= MAX_CODE_BYTES:
                result.append(path)
    return sorted(set(result))


def line_hits(text: str, terms: Iterable[str]) -> List[int]:
    lowered = tuple(term.lower() for term in terms)
    return [index for index, line in enumerate(text.splitlines(), start=1) if any(term in line.lower() for term in lowered)]


def service_references(paths: Sequence[Path]) -> Dict[str, List[str]]:
    references: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        if path.suffix not in {".service", ".timer"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("ExecStart=") or stripped.startswith("ExecStartPre=")):
                continue
            for token in re.findall(r"/[A-Za-z0-9_./-]+\.(?:py|sh)", stripped):
                references[Path(token).name].append(str(path))
    return references


def writer_lineage(audit: Dict[str, Any]) -> Dict[str, Any]:
    source_basenames = {Path(item["path"]).name for item in audit.get("files", []) if item.get("open_contract_rows", 0) > 0}
    paths = code_paths()
    unit_refs = service_references(paths)
    candidates = []
    for path in paths:
        if path.suffix.lower() not in {".py", ".sh", ".service"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        lower_path = str(path).replace("\\", "/").lower()
        diagnostic = any(part in lower_path for part in DIAGNOSTIC_PATH_PARTS)
        source_refs = sorted(name for name in source_basenames if name in text)
        writer_hits = line_hits(text, WRITER_TERMS)
        identity_hits = line_hits(text, IDENTITY_TERMS)
        entry_hits = line_hits(text, ENTRY_TERMS)
        entry_price_hits = line_hits(text, ENTRY_PRICE_TERMS)
        stop_hits = line_hits(text, STOP_TERMS)
        qty_hits = line_hits(text, QTY_TERMS)
        risk_hits = line_hits(text, RISK_TERMS)
        if not source_refs and not (writer_hits and identity_hits and entry_hits):
            continue
        services = sorted(set(unit_refs.get(path.name, [])))
        score = 0
        score += min(len(source_refs), 3) * 10
        score += 4 if writer_hits else 0
        score += 4 if identity_hits else 0
        score += 3 if entry_hits else 0
        score += 3 if entry_price_hits else 0
        score += 4 if stop_hits else 0
        score += 4 if qty_hits else 0
        score += 6 if risk_hits else 0
        score += 5 if services else 0
        score -= 14 if diagnostic else 0
        candidates.append({
            "path": str(path),
            "score": score,
            "diagnostic_or_replay": diagnostic,
            "authoritative_open_source_refs": source_refs,
            "writer_lines": writer_hits[:20],
            "identity_lines": identity_hits[:20],
            "entry_lines": entry_hits[:20],
            "entry_price_lines": entry_price_hits[:20],
            "stop_lines": stop_hits[:20],
            "qty_or_notional_lines": qty_hits[:20],
            "risk_lines": risk_hits[:20],
            "service_units": services,
        })
    candidates.sort(key=lambda row: (not row["diagnostic_or_replay"], int(row["score"]), len(row["authoritative_open_source_refs"]), len(row["service_units"])), reverse=True)
    production = [row for row in candidates if not row["diagnostic_or_replay"] and row["score"] > 0]
    top = production[0] if production else None
    second_score = int(production[1]["score"]) if len(production) > 1 else 0
    dominant = bool(
        top
        and int(top["score"]) >= 20
        and int(top["score"]) >= second_score + 5
        and (top["authoritative_open_source_refs"] or top["service_units"])
    )
    return {
        "status": "PASS_Q4R3_FORWARD_R_ENTRY_WRITER_LINEAGE",
        "files_scanned": len(paths),
        "candidate_count": len(candidates),
        "production_candidate_count": len(production),
        "dominant_single_entry_writer": dominant,
        "dominant_entry_writer": top,
        "second_score": second_score,
        "production_candidates": production[:20],
        "excluded_diagnostic_candidates": [row for row in candidates if row["diagnostic_or_replay"]][:20],
    }


def decide(audit: Dict[str, Any], writer: Dict[str, Any], prior_decision: Dict[str, Any]) -> Dict[str, Any]:
    prior_join = float(prior_decision.get("stable_id_join_rate_pct") or 0.0)
    open_ids = int(audit["unique_open_ids"])
    explicit = int(audit["explicit_risk_rows"])
    formula = int(audit["formula_ready_unique_ids"])
    dominant = bool(writer["dominant_single_entry_writer"])
    missing = Counter(audit.get("missing_fields", {}))

    if prior_join < JOIN_GATE_PCT:
        verdict = "ENTRY_RISK_BLOCKED_BY_STABLE_ID_GATE"
        next_action = "PATCH_STABLE_ID_PROPAGATION_FIRST"
    elif open_ids == 0:
        verdict = "AUTHORITATIVE_OPEN_CONTRACT_NOT_FOUND"
        next_action = "BIND_AUTHORITATIVE_OPEN_SOURCE"
    elif explicit > 0:
        verdict = "ENTRY_RISK_ALREADY_PRESENT_VERIFY_CLOSE_PROPAGATION"
        next_action = "VERIFY_INITIAL_RISK_USDT_SURVIVES_TO_CLOSE"
    elif formula > 0 and dominant:
        verdict = "ENTRY_RISK_SINGLE_WRITER_PATCH_READY"
        next_action = "PATCH_INITIAL_RISK_USDT_AT_CONFIRMED_ENTRY_WRITER_CANARY"
    elif formula > 0:
        verdict = "ENTRY_RISK_FORMULA_READY_WRITER_DISTRIBUTED"
        next_action = "INSTALL_APPEND_ONLY_ENTRY_RISK_SIDECAR_CANARY"
    else:
        stop_missing = int(missing.get("stop_price", 0))
        size_missing = int(missing.get("base_qty_or_notional_or_contract_multiplier", 0))
        entry_missing = int(missing.get("entry_price", 0))
        largest = max(stop_missing, size_missing, entry_missing)
        if largest == stop_missing and stop_missing > 0:
            verdict = "ENTRY_RISK_STOP_PRICE_PERSISTENCE_GAP"
            next_action = "PATCH_INITIAL_STOP_PRICE_AT_ENTRY_AUTHORITY"
        elif largest == size_missing and size_missing > 0:
            verdict = "ENTRY_RISK_SIZE_OR_NOTIONAL_PERSISTENCE_GAP"
            next_action = "PATCH_EXPLICIT_BASE_QTY_OR_NOTIONAL_AT_ENTRY_AUTHORITY"
        elif entry_missing > 0:
            verdict = "ENTRY_RISK_ENTRY_PRICE_PERSISTENCE_GAP"
            next_action = "PATCH_ENTRY_PRICE_AT_ENTRY_AUTHORITY"
        else:
            verdict = "ENTRY_RISK_CONTRACT_GAP_UNRESOLVED"
            next_action = "TRACE_TOP_ENTRY_WRITER_CALL_CHAIN"

    return {
        "status": "PASS_Q4R3_FORWARD_R_ENTRY_RISK_DECISION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "prior_stable_id_join_rate_pct": prior_join,
        "authoritative_open_unique_ids": open_ids,
        "explicit_risk_rows": explicit,
        "formula_ready_unique_ids": formula,
        "formula_ready_rate_pct": audit["formula_ready_rate_pct"],
        "missing_fields": dict(missing),
        "dominant_single_entry_writer": dominant,
        "dominant_entry_writer": writer.get("dominant_entry_writer"),
        "next_modules": [next_action, "FORWARD_ENTRY_RISK_CANARY", "VERIFY_CLOSE_R_FORMULA_ON_NEW_TRADES"],
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


def write_html(audit: Dict[str, Any], writer: Dict[str, Any], decision: Dict[str, Any]) -> None:
    source_rows = []
    for item in audit.get("files", []):
        source_rows.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td><td>{item.get('open_contract_rows', 0)}</td>"
            f"<td>{item.get('stable_id_rows', 0)}</td><td>{item.get('explicit_risk_rows', 0)}</td>"
            f"<td>{item.get('formula_ready_rows', 0)}</td><td>{html.escape(json.dumps(item.get('missing_fields', {})))}</td>"
            "</tr>"
        )
    writer_rows = []
    for item in writer.get("production_candidates", [])[:20]:
        writer_rows.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td><td>{item['score']}</td>"
            f"<td>{html.escape(', '.join(item['authoritative_open_source_refs']))}</td>"
            f"<td>{html.escape(', '.join(item['service_units']))}</td>"
            "</tr>"
        )
    page = "".join([
        "<!doctype html><html><head><meta charset='utf-8'><title>Forward entry-risk authority</title>",
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
        "<h1>Forward entry-risk authority and writer lineage</h1>",
        "<h2>Authoritative open sources</h2><table><thead><tr><th>Path</th><th>Open</th><th>Stable ID</th><th>Explicit risk</th><th>Formula ready</th><th>Missing</th></tr></thead><tbody>",
        "".join(source_rows), "</tbody></table>",
        "<h2>Writer candidates</h2><table><thead><tr><th>Path</th><th>Score</th><th>Source refs</th><th>Units</th></tr></thead><tbody>",
        "".join(writer_rows), "</tbody></table>",
        "<h2>Decision</h2><pre>", html.escape(json.dumps(decision, ensure_ascii=False, indent=2)), "</pre></body></html>",
    ])
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    authority = load_json(AUTHORITY_IN)
    prior_decision = load_json(DECISION_IN)
    freeze = load_json(FREEZE_IN) if FREEZE_IN.exists() else {}
    audit = source_audit(authority)
    writer = writer_lineage(audit)
    decision = decide(audit, writer, prior_decision)
    audit["raschke_state"] = freeze.get("state")
    audit["updated_at"] = utc_now()
    writer["updated_at"] = utc_now()
    decision["raschke_state"] = freeze.get("state")
    write_html(audit, writer, decision)
    atomic_json(AUDIT_OUT, audit)
    atomic_json(WRITER_OUT, writer)
    atomic_json(DECISION_OUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps({"audit": audit, "writer": writer}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
