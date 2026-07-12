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
FREEZE_IN = RUNTIME / "q4r3_raschke_freeze_manifest_latest.json"
SURFACE_IN = RUNTIME / "q4r3_forward_r_writer_surface_latest.json"
DECISION_IN = RUNTIME / "q4r3_forward_r_writer_decision_latest.json"

AUTHORITY_OUT = RUNTIME / "q4r3_forward_r_source_authority_latest.json"
LINEAGE_OUT = RUNTIME / "q4r3_forward_r_writer_lineage_latest.json"
DECISION_OUT = RUNTIME / "q4r3_forward_r_source_lineage_decision_latest.json"
HTML_OUT = RUNTIME / "q4r3_forward_r_source_lineage_latest.html"

MAX_JSON_BYTES = 120 * 1024 * 1024
MAX_CODE_BYTES = 3 * 1024 * 1024
MAX_DEPTH = 10
JOIN_GATE_PCT = 80.0

IDENTITY_KEYS = ("trade_id", "position_id", "event_id", "request_id", "order_id", "client_order_id")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "created_at")
EXIT_TS_KEYS = ("exit_ts", "close_ts", "closed_ts", "closed_at", "updated_at")
RISK_KEYS = ("initial_risk_usdt", "position_risk_usdt", "risk_usdt", "planned_risk_usdt")
REALIZED_R_KEYS = ("realized_R", "realized_r", "pnl_R", "pnl_r", "net_R", "net_r")
REALIZED_USDT_KEYS = ("realized_pnl_usdt", "pnl_usdt", "net_pnl_usdt", "realized_usdt")
STATUS_KEYS = ("status", "state", "trade_status", "position_status")
STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key")
SYMBOL_KEYS = ("symbol", "market", "ticker")
SIDE_KEYS = ("side", "direction", "position_side")

OPEN_STATUS = {"open", "active", "running", "pending", "opened", "new"}
CLOSED_STATUS = {"closed", "done", "settled", "exited", "complete", "completed", "final"}

REPLAY_TOKENS = (
    "replay", "forensic", "tournament", "causal_split", "regime_router", "probe", "capture",
    "audit", "test", "backfill", "adapter", "factorial", "raschke_v", "route_a", "simulation",
    "diagnostic", "mfe_mae", "post_close", "research", "sample", "inventory", "coverage",
)
DERIVED_TOKENS = (
    "canonical", "bind_cache", "cache", "snapshot", "summary", "report", "ranking", "aggregate",
    "mirror", "projection", "view", "telegram", "handoff", "decision", "latest.html",
)
AUTHORITATIVE_TOKENS = (
    "paper_order_ledger", "shadow_closed_ledger", "closed_ledger", "trade_ledger", "order_ledger",
    "position_state", "active_position", "execution_ledger", "fills_ledger", "paper_position",
    "shadow_position", "close_writer", "open_writer",
)
FORWARD_TOKENS = ("paper", "shadow", "forward", "execution", "order", "position", "trade", "fill", "closed")

CODE_ROOTS = (
    ROOT / "backend",
    ROOT / "tools",
    ROOT / "services",
    ROOT / "scripts",
    ROOT / "systemd",
    Path("/etc/systemd/system"),
)
CODE_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".yaml", ".yml", ".toml"}
DIAGNOSTIC_CODE_TOKENS = (
    "test", "probe", "replay", "audit", "forensic", "tournament", "diagnostic", "research",
    "capture", "backfill", "route_a", "raschke_v", "factorial", "snapshot",
)
WRITER_TERMS = ("write_text", "json.dump", "json.dumps", "open(", "append", "replace(", "os.replace", "rename(")
ENTRY_TERMS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "initial_risk_usdt", "position_risk_usdt")
CLOSE_TERMS = ("exit_ts", "close_ts", "closed_at", "status_closed", "realized_pnl_usdt", "realized_r", "pnl_r")
IDENTITY_TERMS = ("trade_id", "position_id", "event_id", "request_id", "client_order_id")
RISK_TERMS = ("initial_risk_usdt", "position_risk_usdt", "risk_usdt", "planned_risk_usdt")


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


def first_value(obj: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def classify_source(path: Path) -> Tuple[str, List[str]]:
    lower = str(path).lower()
    reasons: List[str] = []
    if any(token in lower for token in REPLAY_TOKENS):
        reasons.append("replay_or_diagnostic_token")
        return "REPLAY_DIAGNOSTIC", reasons
    if any(token in lower for token in DERIVED_TOKENS):
        reasons.append("derived_or_aggregate_token")
        return "DERIVED", reasons
    if any(token in lower for token in AUTHORITATIVE_TOKENS):
        reasons.append("authoritative_ledger_token")
        return "AUTHORITATIVE_FORWARD", reasons
    if any(token in lower for token in FORWARD_TOKENS):
        reasons.append("forward_like_token_without_authority_proof")
        return "FORWARD_CANDIDATE", reasons
    reasons.append("no_forward_authority_evidence")
    return "OTHER", reasons


def runtime_json_paths() -> List[Path]:
    if not RUNTIME.exists():
        return []
    result = []
    for path in RUNTIME.glob("*.json"):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if 0 < size <= MAX_JSON_BYTES:
            result.append(path)
    return sorted(result)


def row_state(obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    status = normalize(first_value(obj, STATUS_KEYS))
    entry_ts = timestamp_ms(first_value(obj, ENTRY_TS_KEYS))
    exit_ts = timestamp_ms(first_value(obj, EXIT_TS_KEYS))
    explicit_closed = bool(obj.get("status_closed") is True or obj.get("is_closed") is True or obj.get("closed") is True)
    explicit_open = bool(obj.get("is_open") is True or obj.get("open") is True)
    if status in OPEN_STATUS or explicit_open:
        return "OPEN", entry_ts, exit_ts
    if status in CLOSED_STATUS or explicit_closed or exit_ts is not None:
        return "CLOSED", entry_ts, exit_ts
    return None, entry_ts, exit_ts


def iter_contract_rows(obj: Any, source: str, depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        state, entry_ts, exit_ts = row_state(obj)
        identity_key = next((key for key in IDENTITY_KEYS if obj.get(key) not in (None, "")), None)
        risk_key = next((key for key in RISK_KEYS if safe_float(obj.get(key)) is not None and float(obj[key]) > 0), None)
        r_key = next((key for key in REALIZED_R_KEYS if safe_float(obj.get(key)) is not None), None)
        usdt_key = next((key for key in REALIZED_USDT_KEYS if safe_float(obj.get(key)) is not None), None)
        if state and (identity_key or entry_ts or exit_ts or risk_key or r_key or usdt_key):
            identity_value = str(obj.get(identity_key)) if identity_key else ""
            identity_hash = hashlib.sha256(identity_value.encode("utf-8")).hexdigest()[:20] if identity_value else None
            yield {
                "source": source,
                "state": state,
                "identity_key": identity_key,
                "identity_hash": identity_hash,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "risk_key": risk_key,
                "risk_usdt": float(obj[risk_key]) if risk_key else None,
                "realized_r_key": r_key,
                "realized_R": float(obj[r_key]) if r_key else None,
                "realized_usdt_key": usdt_key,
                "realized_pnl_usdt": float(obj[usdt_key]) if usdt_key else None,
                "strategy_present": first_value(obj, STRATEGY_KEYS) not in (None, ""),
                "symbol_present": first_value(obj, SYMBOL_KEYS) not in (None, ""),
                "side_present": first_value(obj, SIDE_KEYS) not in (None, ""),
            }
        for value in obj.values():
            yield from iter_contract_rows(value, source, depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_contract_rows(value, source, depth + 1)


def source_inventory() -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    files = []
    rows_by_class: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for path in runtime_json_paths():
        source_class, reasons = classify_source(path)
        record: Dict[str, Any] = {"path": str(path), "class": source_class, "reasons": reasons, "size_bytes": path.stat().st_size}
        try:
            rows = list(iter_contract_rows(load_json(path), str(path)))
            rows_by_class[source_class].extend(rows)
            record.update({
                "parsed": True,
                "rows": len(rows),
                "open_rows": sum(1 for row in rows if row["state"] == "OPEN"),
                "closed_rows": sum(1 for row in rows if row["state"] == "CLOSED"),
                "stable_id_rows": sum(1 for row in rows if row["identity_hash"]),
                "risk_rows": sum(1 for row in rows if row["risk_key"]),
                "realized_r_rows": sum(1 for row in rows if row["realized_r_key"]),
                "realized_usdt_rows": sum(1 for row in rows if row["realized_usdt_key"]),
            })
        except Exception as exc:
            record.update({"parsed": False, "rows": 0, "error": repr(exc)})
        files.append(record)
    class_counts = {
        source_class: {
            "files": sum(1 for item in files if item["class"] == source_class),
            "rows": len(rows),
            "open_rows": sum(1 for row in rows if row["state"] == "OPEN"),
            "closed_rows": sum(1 for row in rows if row["state"] == "CLOSED"),
        }
        for source_class, rows in rows_by_class.items()
    }
    authority_files = [item for item in files if item["class"] == "AUTHORITATIVE_FORWARD" and item.get("rows", 0) > 0]
    authority_files.sort(key=lambda item: (int(item.get("stable_id_rows", 0)), int(item.get("closed_rows", 0)) + int(item.get("open_rows", 0))), reverse=True)
    return {
        "status": "PASS_Q4R3_FORWARD_R_SOURCE_AUTHORITY_INVENTORY",
        "files_scanned": len(files),
        "class_counts": class_counts,
        "authoritative_files": authority_files,
        "files": files,
        "contract": "Replay, forensic, tournament, capture, probe, audit and aggregate files are excluded from forward authority even when they contain valid-looking trade rows.",
    }, rows_by_class


def lineage_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    opens: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    closes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        identity_hash = row.get("identity_hash")
        if not identity_hash:
            continue
        if row["state"] == "OPEN":
            opens[identity_hash].append(row)
        elif row["state"] == "CLOSED":
            closes[identity_hash].append(row)
    joined = sorted(set(opens) & set(closes))
    close_with_id = sum(len(value) for value in closes.values())
    join_rate = len(joined) / max(len(closes), 1) * 100.0
    joined_with_risk = 0
    joined_formula_ready = 0
    joined_with_explicit_r = 0
    lineage_pairs = Counter()
    for identity_hash in joined:
        open_rows = opens[identity_hash]
        close_rows = closes[identity_hash]
        open_risk = next((row for row in open_rows if row["risk_key"]), None)
        close_risk = next((row for row in close_rows if row["risk_key"]), None)
        close_usdt = next((row for row in close_rows if row["realized_usdt_key"]), None)
        close_r = next((row for row in close_rows if row["realized_r_key"]), None)
        if open_risk or close_risk:
            joined_with_risk += 1
        if (open_risk or close_risk) and close_usdt:
            joined_formula_ready += 1
        if close_r:
            joined_with_explicit_r += 1
        for open_row in open_rows:
            for close_row in close_rows:
                lineage_pairs[(open_row["source"], close_row["source"])] += 1
    pair_rows = [
        {"open_source": pair[0], "close_source": pair[1], "joined_ids": count}
        for pair, count in lineage_pairs.most_common(30)
    ]
    return {
        "status": "PASS_Q4R3_FORWARD_R_AUTHORITATIVE_LINEAGE",
        "open_record_count": sum(1 for row in rows if row["state"] == "OPEN"),
        "close_record_count": sum(1 for row in rows if row["state"] == "CLOSED"),
        "open_with_stable_id_count": sum(len(value) for value in opens.values()),
        "close_with_stable_id_count": close_with_id,
        "unique_open_ids": len(opens),
        "unique_close_ids": len(closes),
        "joined_unique_ids": len(joined),
        "stable_id_join_rate_pct": round(join_rate, 3),
        "joined_with_explicit_risk_count": joined_with_risk,
        "joined_formula_ready_count": joined_formula_ready,
        "joined_with_explicit_realized_r_count": joined_with_explicit_r,
        "top_source_pairs": pair_rows,
        "raw_ids_emitted": False,
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
    lowered_terms = tuple(term.lower() for term in terms)
    return [index for index, line in enumerate(text.splitlines(), start=1) if any(term in line.lower() for term in lowered_terms)]


def service_references() -> Dict[str, List[str]]:
    references: Dict[str, List[str]] = defaultdict(list)
    for path in code_paths():
        if path.suffix not in {".service", ".timer"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("ExecStart=") or stripped.startswith("ExecStartPre="):
                for token in re.findall(r"/[A-Za-z0-9_./-]+\.(?:py|sh)", stripped):
                    references[token].append(str(path))
    return references


def code_lineage(authority: Dict[str, Any]) -> Dict[str, Any]:
    authoritative_basenames = {Path(item["path"]).name for item in authority.get("authoritative_files", [])}
    unit_refs = service_references()
    candidates = []
    for path in code_paths():
        if path.suffix.lower() not in {".py", ".sh", ".service"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        lower_path = str(path).lower()
        diagnostic = any(token in lower_path for token in DIAGNOSTIC_CODE_TOKENS)
        writer_hits = line_hits(text, WRITER_TERMS)
        source_refs = sorted(name for name in authoritative_basenames if name in text)
        identity_hits = line_hits(text, IDENTITY_TERMS)
        entry_hits = line_hits(text, ENTRY_TERMS)
        close_hits = line_hits(text, CLOSE_TERMS)
        risk_hits = line_hits(text, RISK_TERMS)
        if not writer_hits and not source_refs:
            continue
        service_units = sorted({unit for executable, units in unit_refs.items() if Path(executable).name == path.name for unit in units})
        score = 0
        score += min(len(source_refs), 3) * 8
        score += 4 if writer_hits else 0
        score += 4 if identity_hits else 0
        score += 4 if entry_hits else 0
        score += 4 if close_hits else 0
        score += 6 if risk_hits else 0
        score += 5 if service_units else 0
        score -= 12 if diagnostic else 0
        candidates.append({
            "path": str(path),
            "score": score,
            "diagnostic_or_replay": diagnostic,
            "authoritative_source_refs": source_refs,
            "writer_lines": writer_hits[:20],
            "identity_lines": identity_hits[:20],
            "entry_lines": entry_hits[:20],
            "close_lines": close_hits[:20],
            "risk_lines": risk_hits[:20],
            "service_units": service_units,
        })
    candidates.sort(key=lambda row: (not row["diagnostic_or_replay"], int(row["score"]), len(row["service_units"])), reverse=True)
    production = [row for row in candidates if not row["diagnostic_or_replay"] and row["score"] > 0]
    top = production[0] if production else None
    second_score = int(production[1]["score"]) if len(production) > 1 else 0
    dominant = bool(top and int(top["score"]) >= 16 and int(top["score"]) >= second_score + 4)
    return {
        "status": "PASS_Q4R3_FORWARD_R_CODE_AND_SYSTEMD_LINEAGE",
        "files_scanned": len(code_paths()),
        "candidate_count": len(candidates),
        "production_candidate_count": len(production),
        "dominant_single_writer": dominant,
        "dominant_writer": top,
        "second_score": second_score,
        "production_candidates": production[:20],
        "excluded_diagnostic_candidates": [row for row in candidates if row["diagnostic_or_replay"]][:20],
    }


def decide(authority: Dict[str, Any], lineage: Dict[str, Any], code: Dict[str, Any]) -> Dict[str, Any]:
    authoritative_files = len(authority.get("authoritative_files", []))
    join_rate = float(lineage["stable_id_join_rate_pct"])
    formula_ready = int(lineage["joined_formula_ready_count"])
    risk_ready = int(lineage["joined_with_explicit_risk_count"])
    dominant = bool(code["dominant_single_writer"])
    if authoritative_files == 0:
        verdict = "AUTHORITATIVE_FORWARD_SOURCE_NOT_FOUND"
        next_action = "BIND_REAL_FORWARD_OPEN_AND_CLOSE_SOURCES_BEFORE_ANY_WRITER_PATCH"
    elif join_rate < JOIN_GATE_PCT:
        verdict = "AUTHORITATIVE_STABLE_ID_LINEAGE_GAP"
        next_action = "PATCH_STABLE_ID_PROPAGATION_AT_OPEN_CLOSE_BOUNDARY"
    elif risk_ready == 0:
        verdict = "AUTHORITATIVE_ENTRY_RISK_DENOMINATOR_GAP"
        next_action = "PATCH_INITIAL_RISK_USDT_AT_ENTRY_AUTHORITY"
    elif formula_ready == 0:
        verdict = "AUTHORITATIVE_CLOSE_PNL_CONTRACT_GAP"
        next_action = "PATCH_FINAL_REALIZED_PNL_USDT_AT_CLOSE_AUTHORITY"
    elif not dominant:
        verdict = "JOIN_READY_BUT_WRITER_SURFACE_DISTRIBUTED"
        next_action = "INSTALL_APPEND_ONLY_FORWARD_R_SIDECAR_CANARY"
    else:
        verdict = "COMMON_FORWARD_R_WRITER_PATCH_READY"
        next_action = "PATCH_SINGLE_COMMON_ENTRY_CLOSE_R_CONTRACT"
    return {
        "status": "PASS_Q4R3_FORWARD_R_SOURCE_LINEAGE_DECISION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "authoritative_file_count": authoritative_files,
        "stable_id_join_rate_pct": join_rate,
        "joined_with_explicit_risk_count": risk_ready,
        "joined_formula_ready_count": formula_ready,
        "dominant_single_writer": dominant,
        "dominant_writer": code.get("dominant_writer"),
        "gates": {
            "stable_id_join_rate_min_pct": JOIN_GATE_PCT,
            "explicit_risk_required": True,
            "final_realized_pnl_usdt_required": True,
            "diagnostic_replay_sources_forbidden": True,
        },
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


def write_html(authority: Dict[str, Any], lineage: Dict[str, Any], code: Dict[str, Any], decision: Dict[str, Any]) -> None:
    source_rows = []
    for item in authority.get("authoritative_files", [])[:20]:
        source_rows.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td><td>{item.get('open_rows', 0)}</td>"
            f"<td>{item.get('closed_rows', 0)}</td><td>{item.get('stable_id_rows', 0)}</td>"
            f"<td>{item.get('risk_rows', 0)}</td><td>{item.get('realized_usdt_rows', 0)}</td>"
            "</tr>"
        )
    writer_rows = []
    for item in code.get("production_candidates", [])[:20]:
        writer_rows.append(
            "<tr>"
            f"<td>{html.escape(item['path'])}</td><td>{item['score']}</td>"
            f"<td>{html.escape(', '.join(item['authoritative_source_refs']))}</td>"
            f"<td>{html.escape(', '.join(item['service_units']))}</td>"
            "</tr>"
        )
    page = "".join([
        "<!doctype html><html><head><meta charset='utf-8'><title>Forward R source authority and lineage</title>",
        "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px;vertical-align:top}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
        "<h1>Forward realized-R source authority and writer lineage</h1>",
        "<h2>Authoritative runtime sources</h2><table><thead><tr><th>Path</th><th>Open</th><th>Closed</th><th>Stable ID</th><th>Risk</th><th>Realized USDT</th></tr></thead><tbody>",
        "".join(source_rows), "</tbody></table>",
        "<h2>Authoritative lineage</h2><pre>", html.escape(json.dumps(lineage, ensure_ascii=False, indent=2)), "</pre>",
        "<h2>Production writer candidates</h2><table><thead><tr><th>Path</th><th>Score</th><th>Source refs</th><th>Units</th></tr></thead><tbody>",
        "".join(writer_rows), "</tbody></table>",
        "<h2>Decision</h2><pre>", html.escape(json.dumps(decision, ensure_ascii=False, indent=2)), "</pre></body></html>",
    ])
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    authority, rows_by_class = source_inventory()
    authoritative_rows = rows_by_class.get("AUTHORITATIVE_FORWARD", [])
    lineage = lineage_metrics(authoritative_rows)
    code = code_lineage(authority)
    decision = decide(authority, lineage, code)
    freeze = load_json(FREEZE_IN) if FREEZE_IN.exists() else {}
    authority["raschke_state"] = freeze.get("state")
    authority["prior_surface_verdict"] = load_json(DECISION_IN).get("verdict") if DECISION_IN.exists() else None
    authority["updated_at"] = utc_now()
    lineage["updated_at"] = utc_now()
    code["updated_at"] = utc_now()
    combined_lineage = {"runtime": lineage, "code": code}
    write_html(authority, lineage, code, decision)
    atomic_json(AUTHORITY_OUT, authority)
    atomic_json(LINEAGE_OUT, combined_lineage)
    atomic_json(DECISION_OUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps({"authoritative_files": authority["authoritative_files"], "runtime": lineage, "code": code}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
