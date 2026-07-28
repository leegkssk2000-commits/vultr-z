from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
import urllib.request
import urllib.parse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

VERSION = "ZOPS_LICO_CSV_BRIDGE_V8"
DEFAULT_ROOT = Path(os.environ.get("Z_HOME", Path(__file__).resolve().parents[1])).resolve()
DEFAULT_KEY_VERSION = "v7.3.1.3"
REQUIRED_MIN_FIELDS = ["price", "pos_pct", "lev", "entry_ts", "funding_8h_pct", "dd_day_pct", "dd_total_pct"]
LIQ_ALTERNATIVES = [("liq_price", "liq_buffer_pct")]
SOURCE_PRIORITY = {"cf": 1, "sheets": 2, "gs": 2, "other": 9}

CF_PATHS = [
    "data/sources/cf_signal_latest.json",
    "data/sources/cf/latest_signal.json",
    "data/cf/latest_signal.json",
    "data/fastlane/cf_signal_latest.json",
    "fastlane/cf_signal_latest.json",
    "backend/data/cf_signal_latest.json",
    "backend/data/cf_signal.json",
    "runtime/cf_signal_latest.json",
    "reports/cf/latest_signal.json",
]
SHEETS_PATHS = [
    "data/sources/sheets_signal_latest.json",
    "data/sources/gs_signal_latest.json",
    "data/sources/sheets/latest_signal.json",
    "data/gs/latest_signal.json",
    "data/sheets/latest_signal.json",
    "data/fastlane/sheets_signal_latest.json",
    "fastlane/sheets_signal_latest.json",
    "backend/data/sheets_signal_latest.json",
    "backend/data/sheets_signal.json",
    "backend/data/gs_signal_latest.json",
    "runtime/sheets_signal_latest.json",
    "reports/sheets/latest_signal.json",
]
CSV_PATHS = ["data/sources/sheets_signal_latest.csv", "data/sheets/latest_signal.csv", "backend/data/sheets_signal_latest.csv"]
CF_SAMPLE_PATHS = ["adapters/samples/cf_signal_sample.json"]
SHEETS_SAMPLE_PATHS = ["adapters/samples/sheets_signal_sample.json", "gs_export/sheets_signal_sample.json"]


def now_ms() -> int:
    return int(time.time() * 1000)


def load_json(path: str | Path, fallback: Any = None) -> Any:
    p = Path(path)
    try:
        if p.exists() and p.is_file():
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                return json.loads(raw)
    except Exception:
        return fallback
    return fallback


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _clean_key(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").strip().lower())


def _clean_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip()
    return v


def _read_csv_last_row(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists() or not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8-sig")
        row = _best_valid_csv_row(raw)
        if row is not None:
            try:
                row["_file_mtime_ms"] = int(path.stat().st_mtime * 1000)
            except Exception:
                pass
        return row
    except Exception:
        return None


def _last_nonempty_csv_row(csv_text: str) -> Optional[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with io.StringIO(csv_text) as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            row = {str(k or "").strip(): _clean_value(v) for k, v in r.items() if k is not None}
            if any(v not in (None, "") for v in row.values()):
                rows.append(row)
    return rows[-1] if rows else None


def _csv_row_has(row: Mapping[str, Any], aliases: Iterable[str]) -> bool:
    found, _, _ = _lookup(row, aliases)
    return found


def _csv_row_score(row: Mapping[str, Any]) -> int:
    aliases = _base_aliases()
    if not _csv_row_has(row, aliases["symbol"]):
        return -1
    has_px = _csv_row_has(row, aliases["price"]) or _csv_row_has(row, aliases["entry_price"])
    if not has_px:
        return -1
    score = 0
    for key in ("symbol", "strategy", "side", "price", "entry_price", "qty", "pos_pct", "lev", "entry_ts", "liq_price", "liq_buffer_pct", "funding_8h_pct", "dd_day_pct", "dd_total_pct", "source_ts_ms"):
        if key in aliases and _csv_row_has(row, aliases[key]):
            score += 1
    return score


def _best_valid_csv_row(csv_text: str) -> Optional[Dict[str, Any]]:
    candidates: List[tuple[int, int, Dict[str, Any]]] = []
    fallback: List[Dict[str, Any]] = []
    with io.StringIO(csv_text) as f:
        reader = csv.DictReader(f)
        for idx, r in enumerate(reader):
            if not r:
                continue
            row = {str(k or "").strip(): _clean_value(v) for k, v in r.items() if k is not None}
            if not any(v not in (None, "") for v in row.values()):
                continue
            fallback.append(row)
            score = _csv_row_score(row)
            if score >= 2:
                candidates.append((score, idx, row))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[-1][2]
    return fallback[-1] if fallback else None


def _unwrap_payload(obj: Any) -> Optional[Dict[str, Any]]:
    if isinstance(obj, list):
        return _unwrap_payload(obj[-1]) if obj else None
    if not isinstance(obj, Mapping):
        return None
    d = dict(obj)
    # v5 normalized JSON can carry min_data; use it as core payload while preserving provenance.
    if isinstance(d.get("min_data"), Mapping):
        inner = dict(d.get("min_data") or {})
        for meta in (
            "source", "source_ref", "source_ts_ms", "ingress_observed_ts_ms", "observed_ts_ms", "ts_ms",
            "timestamp_ms", "snapshot_ts_ms", "key_version", "correlation_id", "csv_adapter",
            "ingress_version", "authority", "may_emit_final_action",
        ):
            if meta in d and meta not in inner:
                inner[meta] = d[meta]
        return inner
    for key in ("normalized", "signal", "data", "payload", "row", "latest", "result"):
        v = d.get(key)
        if isinstance(v, Mapping):
            inner = dict(v)
            for meta in (
                "source", "source_ref", "source_ts_ms", "ingress_observed_ts_ms", "observed_ts_ms", "ts_ms",
                "timestamp_ms", "snapshot_ts_ms", "key_version", "correlation_id",
            ):
                if meta in d and meta not in inner:
                    inner[meta] = d[meta]
            return inner
        if isinstance(v, list) and v:
            return _unwrap_payload(v[-1])
    return d


def _load_bridge_config(root: Path) -> Dict[str, Any]:
    cfg = load_json(root / "config" / "lico_source_bridge.json", {})
    return cfg if isinstance(cfg, dict) else {}


def _read_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        if not path.exists() or not path.is_file():
            return out
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            out[k.strip()] = v
    except Exception:
        return out
    return out


def _with_cache_bust(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        qs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        qs = [(k, v) for k, v in qs if k != "zops_cb"]
        qs.append(("zops_cb", str(now_ms())))
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(qs), parts.fragment))
    except Exception:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}zops_cb={now_ms()}"


def _fetch_text_http(url: str, timeout_ms: int, source: str) -> Tuple[Optional[str], str, str]:
    if not url or not str(url).startswith(("http://", "https://")):
        return None, "", "bad_url"
    fetch_url = _with_cache_bust(str(url))
    ua = f"zops-lico-csv-bridge-v8/{source}"
    accept = "text/csv, application/json;q=0.9, */*;q=0.1" if source in {"sheets", "gs"} else "application/json, text/csv;q=0.7, */*;q=0.1"
    req = urllib.request.Request(fetch_url, headers={"accept": accept, "user-agent": ua, "cache-control": "no-cache", "pragma": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=max(0.5, timeout_ms / 1000.0)) as resp:
            status = int(getattr(resp, "status", 200))
            if status >= 400:
                return None, "", f"http_status:{status}"
            ct = resp.headers.get("content-type", "") if hasattr(resp, "headers") else ""
            raw = resp.read(1024 * 1024).decode("utf-8-sig", errors="replace")
            return raw, ct, "urllib"
    except Exception as e:
        first_error = f"urllib:{type(e).__name__}:{str(e)[:120]}"
    # VPS 현실 보정: urllib/redirect/Google edge 이슈 시 curl -L fallback. read-only.
    try:
        cp = subprocess.run(
            ["curl", "-LfsS", "--max-time", str(max(2, int(timeout_ms / 1000.0))), "-H", f"User-Agent: {ua}", "-H", "Cache-Control: no-cache", fetch_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=max(3, int(timeout_ms / 1000.0) + 2), check=False,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            return cp.stdout, "", "curl"
        return None, "", f"{first_error};curl_rc:{cp.returncode}:{cp.stderr[:120]}"
    except Exception as e:
        return None, "", f"{first_error};curl:{type(e).__name__}:{str(e)[:120]}"


def _as_path_list(root: Path, values: Iterable[str]) -> List[Path]:
    out: List[Path] = []
    for v in values:
        if not v:
            continue
        p = Path(str(v))
        if not p.is_absolute():
            p = root / p
        out.append(p)
    return out


def _split_env_paths(name: str) -> List[str]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return []
    sep = ";" if ";" in raw else ":"
    return [x.strip() for x in raw.split(sep) if x.strip()]


def _url_kind(url: str, content_type: str, text: str) -> str:
    u = str(url or "").lower()
    ct = str(content_type or "").lower()
    head = text[:256].lower()
    if "output=csv" in u or "text/csv" in ct or "csv" in ct:
        return "csv"
    if head.lstrip().startswith(("{", "[")):
        return "json"
    if "," in head and "sym" in head:
        return "csv"
    return "json"


def _fetch_payload_url(url: str, timeout_ms: int, source: str) -> Optional[Dict[str, Any]]:
    fetch_ts = now_ms()
    raw, ct, method = _fetch_text_http(url, timeout_ms, source)
    if raw is None:
        return None
    try:
        kind = _url_kind(url, ct, raw)
        if kind == "csv":
            row = _best_valid_csv_row(raw)
            if not row:
                return None
            row["_fetch_observed_ts_ms"] = fetch_ts
            row["_fetched_url_kind"] = "csv"
            row["_fetch_method"] = method
            return row
        obj = json.loads(raw)
        d = _unwrap_payload(obj)
        if isinstance(d, dict):
            d.setdefault("_fetch_observed_ts_ms", fetch_ts)
            d.setdefault("_fetched_url_kind", "json")
            d.setdefault("_fetch_method", method)
            return d
    except Exception:
        return None
    return None

def _keymap(root: Path, source: str) -> Dict[str, Any]:
    p = root / "adapters" / ("cf_worker_keymap.json" if source == "cf" else "google_sheets_keymap.json")
    obj = load_json(p, {})
    return obj if isinstance(obj, dict) else {}


def _base_aliases() -> Dict[str, List[str]]:
    return {
        "symbol": ["symbol", "sym", "Symbol", "ticker", "pair"],
        "strategy": ["strategy", "Strategy", "strategy_id", "strat", "algo", "model"],
        "side": ["side", "direction", "pos_side"],
        "price": ["price", "Price", "mark", "mark_price", "last", "last_price"],
        "entry_price": ["entry_price", "entry", "Entry", "avg_entry", "avgEntry"],
        "qty": ["qty", "size", "contracts", "amount"],
        "pos_pct": ["pos_pct", "pos%", "Position %", "position_pct", "position%", "exposure_pct", "exposure%"],
        "lev": ["lev", "Leverage", "leverage", "leverage_x"],
        "entry_ts": ["entry_ts", "Entry TS", "entry_time", "opened_at", "ts", "timestamp", "time"],
        "liq_price": ["liq_price", "liq", "Liq Price", "liquidation_price"],
        "liq_buffer_pct": ["liq_buffer_pct", "liq_buffer", "liq_buffer%", "Liq Buffer %", "liquidation_buffer_pct"],
        "funding_8h_pct": ["funding_8h_pct", "funding_8h", "funding_8h%", "Funding 8h %"],
        "dd_day_pct": ["dd_day_pct", "DD Day %", "DD_day%", "day_drawdown_pct"],
        "dd_total_pct": ["dd_total_pct", "DD Total %", "DD_total%", "total_drawdown_pct"],
        "source_ts_ms": ["source_ts_ms", "Snapshot TS ms", "snapshot_ts_ms", "timestamp_ms", "ts_ms", "source_ts", "observed_ts_ms", "ingress_observed_ts_ms"],
        "key_version": ["key_version", "Key Version", "contract_version", "schema_version"],
        "correlation_id": ["correlation_id", "Correlation ID", "trace_id", "request_id"],
        "spread_bp": ["spread_bp", "spread_bps", "Spread BP", "spread"],
        "slip_bp": ["slip_bp", "slippage_bps", "Slippage BP", "slip"],
        "depth_notional": ["depth_notional", "depth_notional_usdt", "Depth Notional", "depth"],
    }


def _lookup(payload: Mapping[str, Any], aliases: Iterable[str]) -> Tuple[bool, Any, Optional[str]]:
    for key in aliases:
        if key in payload and payload[key] not in (None, ""):
            return True, payload[key], str(key)
    folded = {_clean_key(k): k for k in payload.keys()}
    for key in aliases:
        fk = _clean_key(key)
        if fk in folded:
            real = folded[fk]
            if payload.get(real) not in (None, ""):
                return True, payload.get(real), str(real)
    return False, None, None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            s = value.strip().replace(" ", "")
            if s.upper() in {"TRUE", "FALSE", "N/A", "NA", "NULL", "NONE", "-", "—"}:
                return None
            if s.endswith("%"):
                s = s[:-1]
            # German locale: 0,01 -> 0.01. US thousands: 104,500.25 -> 104500.25.
            if "," in s and "." not in s:
                parts = s.split(",")
                if len(parts) == 2 and 1 <= len(parts[1]) <= 4:
                    s = parts[0] + "." + parts[1]
                else:
                    s = s.replace(",", "")
            elif "," in s and "." in s:
                s = s.replace(",", "")
            return float(s)
        return float(value)
    except Exception:
        return None


def _as_int_ms(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # Google serial date: days since 1899-12-30.
        if 20_000 <= v <= 80_000:
            return int((v - 25569.0) * 86400.0 * 1000.0)
        if 1_000_000_000 <= v < 10_000_000_000:
            v *= 1000
        return int(v)
    s = str(value).strip()
    if not s or s in {"-", "—"}:
        return None
    try:
        v = float(s)
        if 20_000 <= v <= 80_000:
            return int((v - 25569.0) * 86400.0 * 1000.0)
        if 1_000_000_000 <= v < 10_000_000_000:
            v *= 1000
        return int(v)
    except Exception:
        pass
    try:
        ss = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _coerce_side(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"long", "buy", "l"}:
        return "long"
    if s in {"short", "sell", "s"}:
        return "short"
    return s


def _compute_liq_buffer(price: Optional[float], liq: Optional[float], side: str) -> Optional[float]:
    if price is None or liq is None or price <= 0:
        return None
    if side == "short":
        return max(0.0, (liq - price) / price * 100.0)
    return max(0.0, (price - liq) / price * 100.0)


def _merge_aliases(root: Path, source: str) -> Dict[str, List[str]]:
    aliases = _base_aliases()
    km = _keymap(root, source)
    ext = km.get("input_aliases", {}) if isinstance(km.get("input_aliases"), dict) else {}
    for k, vals in ext.items():
        if not isinstance(vals, list):
            continue
        aliases.setdefault(str(k), [])
        for v in vals:
            sv = str(v)
            if sv not in aliases[str(k)]:
                aliases[str(k)].append(sv)
    return aliases


def normalize_source_payload(payload: Mapping[str, Any], source: str, root: str | Path | None = None, source_ref: str = "") -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    source = "sheets" if source == "gs" else str(source or "other")
    p = _unwrap_payload(payload) or {}
    aliases = _merge_aliases(root_path, source)
    normalized: Dict[str, Any] = {}
    used_by: Dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        found, value, used = _lookup(p, alias_list)
        if found:
            normalized[canonical] = value
            if used:
                used_by[canonical] = used

    # Provenance defaults for CSV/ingress snapshots.
    normalized["source"] = source
    normalized["source_ref"] = source_ref or str(p.get("source_ref") or "")
    normalized.setdefault("key_version", p.get("key_version") or DEFAULT_KEY_VERSION)
    if normalized.get("strategy") in (None, ""):
        cfg = _load_bridge_config(root_path)
        normalized["strategy"] = cfg.get("default_strategy") or "Alpha"

    if normalized.get("source_ts_ms") in (None, ""):
        for k in ("_fetch_observed_ts_ms", "ingress_observed_ts_ms", "observed_ts_ms", "_file_mtime_ms"):
            if p.get(k) not in (None, ""):
                normalized["source_ts_ms"] = p.get(k)
                used_by["source_ts_ms"] = k
                break

    numeric_fields = ["price", "entry_price", "qty", "pos_pct", "lev", "liq_price", "liq_buffer_pct", "funding_8h_pct", "dd_day_pct", "dd_total_pct", "spread_bp", "slip_bp", "depth_notional"]
    for k in numeric_fields:
        if k in normalized:
            f = _as_float(normalized[k])
            if f is not None:
                normalized[k] = f
    for k in ["entry_ts", "source_ts_ms"]:
        if k in normalized:
            v = _as_int_ms(normalized[k])
            if v is not None:
                normalized[k] = v

    if "side" in normalized:
        normalized["side"] = _coerce_side(normalized.get("side"))

    # Keep MinData price canonical as mark/last; entry_price remains reference-only.
    price = _as_float(normalized.get("price"))
    liq = _as_float(normalized.get("liq_price"))
    if normalized.get("liq_buffer_pct") in (None, ""):
        computed = _compute_liq_buffer(price, liq, _coerce_side(normalized.get("side")))
        if computed is not None:
            normalized["liq_buffer_pct"] = round(computed, 4)
            used_by["liq_buffer_pct"] = "computed:price_liq_side"

    missing: List[str] = []
    for k in ["symbol", "strategy", "source_ts_ms", "key_version"] + REQUIRED_MIN_FIELDS:
        if normalized.get(k) in (None, ""):
            missing.append(k)
    for alt in LIQ_ALTERNATIVES:
        if not any(normalized.get(k) not in (None, "") for k in alt):
            missing.append("any:" + "|".join(alt))
    status = "PASS" if not missing else "HOLD"
    return {
        "normalized": normalized,
        "integrity": {
            "status": status,
            "missing": missing,
            "fail_action": "hold" if missing else "none",
            "source": source,
            "source_rank": SOURCE_PRIORITY.get(source, 9),
            "used_by": used_by,
            "source_ref": normalized.get("source_ref") or source_ref,
            "version": VERSION,
            "authority": "none",
            "may_emit_final_action": False,
        },
    }


def _threshold_map(defaults: Dict[str, Any]) -> Dict[str, Any]:
    th = defaults.get("thresholds")
    if isinstance(th, dict):
        out: Dict[str, Any] = {}
        for k, v in th.items():
            if isinstance(v, dict):
                out[str(v.get("runtime_env", k))] = v.get("value", v.get("default"))
                out[str(k)] = v.get("value", v.get("default"))
        return out
    if isinstance(th, list):
        return {str(v.get("runtime_env", v.get("canonical_key"))): v.get("value", v.get("default")) for v in th if isinstance(v, dict)}
    return defaults.get("defaults", defaults) if isinstance(defaults, dict) else {}


def _limits(root: Path) -> Dict[str, int]:
    defaults = load_json(root / "ssot" / "defaults.json", {})
    vals = _threshold_map(defaults if isinstance(defaults, dict) else {})
    def get(*names: str, fallback: int) -> int:
        for name in names:
            try:
                if name in vals and vals.get(name) not in (None, ""):
                    return int(float(vals.get(name)))
                if isinstance(defaults, dict) and name in defaults and defaults.get(name) not in (None, ""):
                    return int(float(defaults.get(name)))
            except Exception:
                pass
        return fallback
    return {
        "max_signal_age_ms": get("ZOS_MAX_SIGNAL_AGE_MS", "MAX_SIGNAL_AGE_MS", fallback=1500),
        "data_stale_ms": get("ZOS_DATA_STALE_MS", "DATA_STALE_MS", fallback=1500),
    }


def _snapshot_hash_short(obj: Mapping[str, Any]) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def build_snapshot_from_normalized(candidate: Mapping[str, Any], root: str | Path | None = None, now: Optional[int] = None) -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    ts = int(now if now is not None else now_ms())
    normalized = dict(candidate.get("normalized", {})) if isinstance(candidate.get("normalized"), Mapping) else {}
    integrity = dict(candidate.get("integrity", {})) if isinstance(candidate.get("integrity"), Mapping) else {}
    limits = _limits(root_path)
    src_ts = _as_int_ms(normalized.get("source_ts_ms")) or 0
    age_ms = max(0, ts - src_ts) if src_ts > 0 else None
    fresh_limit = min(int(limits["max_signal_age_ms"]), int(limits["data_stale_ms"]))
    stale_state = "FRESH" if src_ts > 0 and age_ms is not None and age_ms <= fresh_limit else "STALE"
    source = str(normalized.get("source") or integrity.get("source") or "other")
    prefix = "cf" if source == "cf" else "sheets" if source in {"sheets", "gs"} else "other"
    fields_for_src = ["price", "pos_pct", "lev", "entry_ts", "liq_price", "liq_buffer_pct", "funding_8h_pct", "dd_day_pct", "dd_total_pct"]
    src_keys = [f"{prefix}:/{k}" for k in fields_for_src if normalized.get(k) not in (None, "")]
    src_keys += [f"{prefix}:/source_ts_ms", f"{prefix}:/symbol", f"{prefix}:/strategy", "ssot:ZOS_MAX_SIGNAL_AGE_MS", "ssot:ZOS_DATA_STALE_MS"]
    snap: Dict[str, Any] = {
        "snapshot_id": f"lico_live_{source}_{src_ts}_{_snapshot_hash_short(normalized)}",
        "canonical_node_id": "P3_fast_signal_lane",
        "phase_workstream": "P3_fast_signal_lane",
        "symbol": normalized.get("symbol"),
        "strategy": normalized.get("strategy"),
        "source": source,
        "source_ts_ms": src_ts,
        "observed_ts_ms": ts,
        "age_ms": age_ms,
        "max_signal_age_ms": int(limits["max_signal_age_ms"]),
        "data_stale_ms": int(limits["data_stale_ms"]),
        "stale_state": stale_state,
        "route_change_reason": "" if stale_state == "FRESH" else f"age_ms {age_ms} > fresh_limit_ms {fresh_limit}",
        "fail_action": "hold",
        "src_keys": src_keys,
        "normalized": normalized,
        "bridge_version": VERSION,
        "bridge_integrity": integrity,
        "source_ref": normalized.get("source_ref") or integrity.get("source_ref") or "unknown",
        "authority": "none",
        "may_emit_final_action": False,
        "autotrade_effect": "none_until_p4_final_action",
    }
    for k, v in normalized.items():
        if k not in snap:
            snap[k] = v
    return snap


def collect_source_payloads(root: str | Path | None = None) -> List[Dict[str, Any]]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    cfg = _load_bridge_config(root_path)
    include_samples = str(os.environ.get("ZOPS_LICO_INCLUDE_SAMPLES", cfg.get("include_samples", False))).lower() in {"1", "true", "yes", "on"}
    env_file = _read_env_file(Path("/etc/zops/lico_source.env"))
    timeout_ms = int(os.environ.get("ZOPS_LICO_SOURCE_TIMEOUT_MS", env_file.get("ZOPS_LICO_SOURCE_TIMEOUT_MS", cfg.get("timeout_ms", 8000))) or 8000)
    records: List[Dict[str, Any]] = []

    def add(source: str, payload: Optional[Dict[str, Any]], ref: str) -> None:
        if isinstance(payload, dict) and payload:
            records.append({"source": "sheets" if source == "gs" else source, "payload": payload, "ref": ref})

    cf_urls = [os.environ.get("ZOPS_CF_SIGNAL_URL", ""), env_file.get("ZOPS_CF_SIGNAL_URL", ""), str(cfg.get("cf_url", ""))]
    gs_urls = [os.environ.get("ZOPS_GS_SIGNAL_URL", ""), os.environ.get("ZOPS_SHEETS_SIGNAL_URL", ""), env_file.get("ZOPS_GS_SIGNAL_URL", ""), env_file.get("ZOPS_SHEETS_SIGNAL_URL", ""), str(cfg.get("sheets_url", cfg.get("gs_url", cfg.get("sheets_csv_url", ""))))]
    for url in dict.fromkeys([u for u in cf_urls if u]):
        add("cf", _fetch_payload_url(url, timeout_ms, "cf"), f"url:{url}")
    for url in dict.fromkeys([u for u in gs_urls if u]):
        add("sheets", _fetch_payload_url(url, timeout_ms, "sheets"), f"url:{url}")

    cf_paths = list(cfg.get("cf_paths", []) or []) + _split_env_paths("ZOPS_CF_SIGNAL_PATHS") + CF_PATHS
    sheets_paths = list(cfg.get("sheets_paths", cfg.get("gs_paths", [])) or []) + _split_env_paths("ZOPS_GS_SIGNAL_PATHS") + SHEETS_PATHS
    if include_samples:
        cf_paths += CF_SAMPLE_PATHS
        sheets_paths += SHEETS_SAMPLE_PATHS
    for p in _as_path_list(root_path, cf_paths):
        obj = _unwrap_payload(load_json(p, None))
        if isinstance(obj, dict):
            try:
                obj.setdefault("_file_mtime_ms", int(p.stat().st_mtime * 1000))
            except Exception:
                pass
        add("cf", obj, str(p))
    for p in _as_path_list(root_path, sheets_paths):
        obj = _unwrap_payload(load_json(p, None))
        if isinstance(obj, dict):
            try:
                obj.setdefault("_file_mtime_ms", int(p.stat().st_mtime * 1000))
            except Exception:
                pass
        add("sheets", obj, str(p))
    for p in _as_path_list(root_path, list(cfg.get("sheets_csv_paths", []) or []) + CSV_PATHS):
        add("sheets", _read_csv_last_row(p), str(p))
    return records


def select_best_snapshot(payload_records: Iterable[Mapping[str, Any]], root: str | Path | None = None, now: Optional[int] = None) -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    normalized: List[Dict[str, Any]] = []
    hold_reasons: List[Dict[str, Any]] = []
    for rec in payload_records:
        source = str(rec.get("source") or "other")
        payload = rec.get("payload") if isinstance(rec.get("payload"), Mapping) else rec
        ref = str(rec.get("ref") or "inline")
        n = normalize_source_payload(payload, source, root=root_path, source_ref=ref)  # type: ignore[arg-type]
        normalized.append(n)
        if n.get("integrity", {}).get("status") != "PASS":
            hold_reasons.append(n.get("integrity", {}))
    snaps = [build_snapshot_from_normalized(n, root=root_path, now=now) for n in normalized if n.get("integrity", {}).get("status") == "PASS"]
    fresh = [s for s in snaps if s.get("stale_state") == "FRESH"]
    pool = fresh or snaps
    if pool:
        pool.sort(key=lambda s: (SOURCE_PRIORITY.get(str(s.get("source")), 9), int(s.get("age_ms") or 10**12)))
        chosen = pool[0]
        chosen["bridge_state"] = "PASS" if chosen.get("stale_state") == "FRESH" else "HOLD"
        chosen["bridge_reason"] = "source_priority_cf_then_sheets_live_or_ingress_v8" if chosen.get("stale_state") == "FRESH" else "valid_but_stale_snapshot"
        chosen["bridge_candidates"] = [
            {"source": x.get("source"), "stale_state": x.get("stale_state"), "age_ms": x.get("age_ms"), "source_ref": x.get("source_ref"), "price": x.get("price"), "symbol": x.get("symbol")}
            for x in snaps[:8]
        ]
        try:
            write_json_atomic(root_path / "reports" / "lico" / "source_bridge_latest_snapshot.json", chosen)
        except Exception:
            pass
        return chosen
    ts = int(now if now is not None else now_ms())
    out = {
        "snapshot_id": "lico_live_cf_gs_missing",
        "canonical_node_id": "P3_fast_signal_lane",
        "phase_workstream": "P3_fast_signal_lane",
        "symbol": os.environ.get("ZOS_SYMBOL", "UNKNOWN"),
        "strategy": os.environ.get("ZOS_STRATEGY", "UNKNOWN"),
        "source": "none",
        "source_ts_ms": 0,
        "observed_ts_ms": ts,
        "age_ms": None,
        "stale_state": "HOLD",
        "route_change_reason": "no_valid_cf_gs_snapshot",
        "fail_action": "hold",
        "src_keys": ["ssot:ZOS_MAX_SIGNAL_AGE_MS", "ssot:ZOS_DATA_STALE_MS"],
        "bridge_version": VERSION,
        "bridge_state": "HOLD",
        "bridge_reason": "no_valid_cf_gs_snapshot",
        "bridge_hold_reasons": hold_reasons[:8],
        "source_ref": "none",
        "authority": "none",
        "may_emit_final_action": False,
    }
    return out


def build_lico_input_snapshot(root: str | Path | None = None, now: Optional[int] = None) -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    return select_best_snapshot(collect_source_payloads(root_path), root=root_path, now=now)


def bridge_diagnostics(root: str | Path | None = None) -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    records = collect_source_payloads(root_path)
    snap = select_best_snapshot(records, root=root_path)
    return {
        "ok": snap.get("bridge_state") == "PASS",
        "version": VERSION,
        "config": str(root_path / "config" / "lico_source_bridge.json"),
        "sheets_url_set": bool(_load_bridge_config(root_path).get("sheets_url") or _read_env_file(Path("/etc/zops/lico_source.env")).get("ZOPS_GS_SIGNAL_URL") or os.environ.get("ZOPS_GS_SIGNAL_URL") or os.environ.get("ZOPS_SHEETS_SIGNAL_URL")),
        "records_seen": len(records),
        "chosen_source": snap.get("source"),
        "chosen_ref": snap.get("source_ref"),
        "bridge_state": snap.get("bridge_state"),
        "stale_state": snap.get("stale_state"),
        "age_ms": snap.get("age_ms"),
        "reason": snap.get("bridge_reason") or snap.get("route_change_reason"),
        "symbol": snap.get("symbol"),
        "strategy": snap.get("strategy"),
        "price": snap.get("price"),
        "pos_pct": snap.get("pos_pct"),
        "lev": snap.get("lev"),
        "liq_buffer_pct": snap.get("liq_buffer_pct"),
        "src_keys": snap.get("src_keys", []),
        "bridge_candidates": snap.get("bridge_candidates", []),
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Build P3/LICO input snapshot from CF/Google Sheets JSON or published CSV")
    p.add_argument("root", nargs="?", default=str(DEFAULT_ROOT))
    p.add_argument("--diagnostics", action="store_true")
    args = p.parse_args()
    obj = bridge_diagnostics(args.root) if args.diagnostics else build_lico_input_snapshot(args.root)
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
