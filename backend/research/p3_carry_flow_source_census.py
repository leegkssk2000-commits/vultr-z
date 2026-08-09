#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
SCAN_ROOTS = [ROOT / x for x in ("backend", "config", "policies", "research", "runtime", "scripts", "tools")]
TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".md", ".txt", ".csv", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "archive", "artifacts", "cache", ".cache"}
MAX_FILE_BYTES = 3_000_000
MAX_READ_BYTES = 512_000
MAX_SCAN_FILES = 6000
ENDPOINT_RE = re.compile(r"/openApi/[A-Za-z0-9_./-]+")
URL_RE = re.compile(r"https://(?:open-api\.bingx\.(?:com|pro)|api\.bingx\.com)[^\s'\"<>]+")

CATEGORY_PATTERNS = {
    "funding": [r"fundingRate", r"funding_rate", r"lastFundingRate", r"funding_history"],
    "basis": [r"\bbasis\b", r"premiumIndex", r"premium_index", r"markPrice", r"mark_price", r"indexPrice", r"index_price"],
    "open_interest": [r"openInterest", r"open_interest", r"open interest"],
    "flow": [r"longShort", r"long_short", r"positionRatio", r"position_ratio", r"takerBuy", r"taker_buy", r"buySell", r"buy_sell", r"orderflow", r"order_flow"],
    "weak_volume": [r"turnover", r"quoteVolume", r"quote_volume", r"volume"],
}
COMPILED = {k: [re.compile(x, re.I) for x in vals] for k, vals in CATEGORY_PATTERNS.items()}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files():
    emitted = 0
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                yield p
                emitted += 1
                if emitted >= MAX_SCAN_FILES:
                    return


def safe_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return str(path)


def read_text(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_READ_BYTES)
        return raw.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def classify_file(path: Path, text: str) -> dict[str, Any] | None:
    matched: dict[str, list[str]] = {}
    for category, pats in COMPILED.items():
        terms: set[str] = set()
        for pat in pats:
            m = pat.search(text)
            if m:
                terms.add(m.group(0)[:80])
        if terms:
            matched[category] = sorted(terms)
    endpoints = sorted(set(ENDPOINT_RE.findall(text)))
    urls = sorted(set(x.split("?")[0] for x in URL_RE.findall(text)))
    relevant_endpoints = [e for e in endpoints if any(x.lower() in e.lower() for x in ("fund", "interest", "premium", "mark", "index", "position", "ratio", "ticker", "price", "depth"))]
    relevant_urls = [u for u in urls if any(x.lower() in u.lower() for x in ("fund", "interest", "premium", "mark", "index", "position", "ratio", "ticker", "price", "depth"))]
    if not matched and not relevant_endpoints and not relevant_urls:
        return None
    row: dict[str, Any] = {
        "path": safe_rel(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "matched_categories": sorted(matched),
        "matched_terms": matched,
        "endpoint_literals": relevant_endpoints,
        "url_literals": relevant_urls,
    }
    if path.suffix.lower() == ".csv":
        first = text.splitlines()[0] if text.splitlines() else ""
        row["csv_header"] = first[:1000]
    elif path.suffix.lower() in {".json", ".jsonl"} and path.stat().st_size <= MAX_READ_BYTES:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                row["json_top_keys"] = sorted(str(k) for k in obj.keys())[:100]
            elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
                row["json_first_row_keys"] = sorted(str(k) for k in obj[0].keys())[:100]
                row["json_row_count"] = len(obj)
        except Exception:
            pass
    return row


def load_calibration_module():
    path = ROOT / "backend/tools/zel_bingx_real_calibration_v1.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("zel_bingx_real_calibration_v1", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def funding_time(row: dict[str, Any]) -> int | None:
    for key in ("fundingTime", "funding_time", "timestamp", "time"):
        v = row.get(key)
        if v is None:
            continue
        try:
            x = int(float(v))
            if x < 10_000_000_000:
                x *= 1000
            return x
        except Exception:
            continue
    return None


def funding_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("fundingRates", "data", "list", "rows"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [data]
    return []


def probe_funding_history() -> dict[str, Any]:
    mod = load_calibration_module()
    if mod is None:
        return {"state": "HOLD_CALIBRATION_MODULE_MISSING"}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    target_start_ms = now_ms - 90 * 86400000
    candidates = mod.credential_candidates()
    key = sec = source = ""
    errors: list[str] = []
    for k, s, src in candidates[:8]:
        try:
            mod.get(k, s, "/openApi/swap/v2/quote/fundingRate", {"symbol": "BTC-USDT", "startTime": target_start_ms, "endTime": now_ms, "limit": 1000})
        except Exception as exc:
            errors.append(f"{src}:{type(exc).__name__}:{str(exc)[:120]}")
            continue
        key, sec, source = k, s, src
        break
    if not key:
        return {"state": "HOLD_NO_VALID_READ_ONLY_CREDENTIAL", "error_classes": errors[:5]}

    out: dict[str, Any] = {"state": "PASS_FUNDING_HISTORY_PROBED", "credential_source_id": source, "symbols": {}}
    for symbol in ("BTC-USDT", "ETH-USDT"):
        data, latency_ms, base = mod.get(key, sec, "/openApi/swap/v2/quote/fundingRate", {"symbol": symbol, "startTime": target_start_ms, "endTime": now_ms, "limit": 1000})
        rows = funding_rows(data)
        times = sorted(x for x in (funding_time(r) for r in rows) if x is not None)
        keys = sorted({str(k) for r in rows[:20] for k in r.keys()})
        out["symbols"][symbol] = {
            "row_count": len(rows),
            "timestamp_count": len(times),
            "min_timestamp_ms": times[0] if times else None,
            "max_timestamp_ms": times[-1] if times else None,
            "coverage_days": ((times[-1] - times[0]) / 86400000.0) if len(times) >= 2 else 0.0,
            "row_keys": keys,
            "latency_ms": latency_ms,
            "base": base,
            "endpoint": "/openApi/swap/v2/quote/fundingRate",
            "requested_lookback_days": 90,
            "write_endpoint_called": False,
        }
    return out


def main() -> int:
    # Probe the one already-known official source first; then do bounded local discovery.
    funding_probe = probe_funding_history()
    file_rows: list[dict[str, Any]] = []
    category_paths: dict[str, set[str]] = {k: set() for k in CATEGORY_PATTERNS}
    endpoints: set[str] = set()
    urls: set[str] = set()
    scanned = 0
    for path in iter_files():
        scanned += 1
        text = read_text(path)
        if not text:
            continue
        row = classify_file(path, text)
        if row is None:
            continue
        file_rows.append(row)
        for category in row["matched_categories"]:
            category_paths[category].add(row["path"])
        endpoints.update(row["endpoint_literals"])
        urls.update(row["url_literals"])

    source_summary = {category: {"file_count": len(paths), "paths": sorted(paths)[:100]} for category, paths in category_paths.items()}
    funding_bound = funding_probe.get("state") == "PASS_FUNDING_HISTORY_PROBED" and all(
        int(v.get("row_count", 0)) > 0 and v.get("min_timestamp_ms") is not None
        for v in funding_probe.get("symbols", {}).values()
    )
    basis_discovered = source_summary["basis"]["file_count"] > 0
    oi_discovered = source_summary["open_interest"]["file_count"] > 0
    flow_discovered = source_summary["flow"]["file_count"] > 0
    blockers: list[str] = []
    if not funding_bound:
        blockers.append("FUNDING_HISTORY_NOT_BOUND")
    if not basis_discovered:
        blockers.append("HISTORICAL_BASIS_SOURCE_NOT_DISCOVERED")
    if not (oi_discovered or flow_discovered):
        blockers.append("HISTORICAL_OI_OR_FLOW_SOURCE_NOT_DISCOVERED")
    state = "PASS_P3_SOURCE_DISCOVERY_READY_FOR_BINDING_AUDIT" if not blockers else "HOLD_P3_SOURCE_BINDING_GAPS"
    receipt = {
        "schema_version": "zel.p3.carry_flow.source_census.v1",
        "state": state,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(ROOT),
        "scan_file_count_total_bounded": scanned,
        "scan_file_count_relevant": len(file_rows),
        "scan_cap": MAX_SCAN_FILES,
        "source_summary": source_summary,
        "bingx_endpoint_literals": sorted(endpoints),
        "bingx_url_literals": sorted(urls),
        "funding_history_probe": funding_probe,
        "discovery_flags": {
            "funding_history_bound": funding_bound,
            "basis_source_discovered": basis_discovered,
            "open_interest_source_discovered": oi_discovered,
            "flow_source_discovered": flow_discovered,
            "weak_volume_source_discovered": source_summary["weak_volume"]["file_count"] > 0,
        },
        "blockers": blockers,
        "file_rows": sorted(file_rows, key=lambda x: x["path"]),
        "interpretation": "Keyword or endpoint discovery is not economic-source authority. Historical timestamp coverage and causal alignment must be proven before any carry_flow signal thresholds are frozen.",
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
