from __future__ import annotations

import argparse, hashlib, hmac, json, math, os, re, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_BINGX_REAL_CALIBRATION_V1"
BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT")
BUCKETS = (100.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0)


def sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def pct(values: list[float], q: float) -> float:
    a = sorted(values)
    if not a:
        raise RuntimeError("EMPTY_SAMPLE")
    x = (len(a) - 1) * q
    lo, hi = math.floor(x), math.ceil(x)
    return a[lo] if lo == hi else a[lo] * (hi - x) + a[hi] * (x - lo)


def read_env(path: Path) -> dict[str, str]:
    out = {}
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in {"BINGX_API_KEY", "BINGX_SECRET_KEY", "BINGX_API_SECRET", "BINGX_SECRET"}:
            out[k.strip()] = v.strip().strip("'\"")
    return out


def credential_candidates() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    key = os.getenv("BINGX_API_KEY", "").strip()
    sec = next((os.getenv(k, "").strip() for k in ("BINGX_SECRET_KEY", "BINGX_API_SECRET", "BINGX_SECRET") if os.getenv(k, "").strip()), "")
    if key and sec:
        rows.append((key, sec, "process_env"))
    candidates = [Path(p) for p in (
        "/etc/z-alimi/bingx.env",
        "/home/z/z/config/bingx_openapi.env",
        "/home/z/z/z1355_real_bingx_api_bind.sh",
        "/home/z/z/.env", "/home/z/z/backend/.env", "/home/z/z/.env.production",
        "/opt/zel/.env", "/opt/zel/config/.env", "/etc/zel/.env", "/etc/zel/zel.env",
        "/etc/default/zel", "/etc/default/z-os")]
    explicit = os.getenv("BINGX_ENV_FILE")
    if explicit:
        candidates.insert(0, Path(explicit))
    for p in candidates:
        try:
            if not p.is_file() or p.stat().st_size > 1_000_000:
                continue
            env = read_env(p)
        except OSError:
            continue
        key = env.get("BINGX_API_KEY", "")
        sec = next((env.get(k, "") for k in ("BINGX_SECRET_KEY", "BINGX_API_SECRET", "BINGX_SECRET") if env.get(k, "")), "")
        if key and sec:
            rows.append((key, sec, "file_sha256:" + hashlib.sha256(str(p).encode()).hexdigest()))
    dedup: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for key, sec, source in rows:
        fp = hashlib.sha256((key + "\0" + sec).encode()).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        dedup.append((key, sec, source))
    if not dedup:
        raise RuntimeError("BINGX_READ_ONLY_CREDENTIALS_NOT_FOUND")
    return dedup


def get(key: str, sec: str, path: str, params: Mapping[str, Any]) -> tuple[Any, float, str]:
    p = dict(params)
    p.update(timestamp=int(time.time() * 1000), recvWindow=5000)
    for k, v in p.items():
        if re.search(r"[&=?#\r\n]", str(v)):
            raise RuntimeError(f"BAD_PARAM:{k}")
    qs = "&".join(f"{k}={p[k]}" for k in sorted(p))
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    transport_errors: list[str] = []
    for base in BASES:
        req = urllib.request.Request(
            f"{base}{path}?{qs}&signature={sig}",
            headers={"X-BX-APIKEY": key, "X-SOURCE-KEY": "BX-AI-SKILL", "User-Agent": VERSION},
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                payload = json.loads(r.read())
            ms = (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as e:
            body = e.read(4096)
            try:
                payload = json.loads(body)
            except Exception:
                raise RuntimeError(f"BINGX_HTTP_ERROR:{base}:{e.code}") from e
            code = payload.get("code") if isinstance(payload, dict) else None
            msg = payload.get("msg") if isinstance(payload, dict) else None
            raise RuntimeError(f"BINGX_API_HTTP_ERROR:{base}:{e.code}:{code}:{str(msg)[:160]}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            transport_errors.append(f"{base}:{type(e).__name__}:{str(e)[:180]}")
            continue
        if not isinstance(payload, dict):
            raise RuntimeError(f"BINGX_INVALID_PAYLOAD:{base}:{type(payload).__name__}")
        if int(payload.get("code", -1)) != 0:
            raise RuntimeError(f"BINGX_API_ERROR:{base}:{payload.get('code')}:{str(payload.get('msg'))[:160]}")
        return payload.get("data"), ms, base
    raise RuntimeError("BINGX_TRANSPORT_FAILED:" + " | ".join(transport_errors))


def f(v: Any) -> float:
    x = float(v)
    if not math.isfinite(x):
        raise RuntimeError("NON_FINITE")
    return x


def funding_values(data: Any) -> list[float]:
    rows = data if isinstance(data, list) else next((data[k] for k in ("fundingRates", "data", "list") if isinstance(data, dict) and isinstance(data.get(k), list)), [data])
    out = []
    for r in rows:
        if isinstance(r, dict):
            value = r.get("fundingRate", r.get("lastFundingRate"))
            if value is not None:
                out.append(abs(f(value)) * 100.0)
    return out


def depth(data: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if not isinstance(data, dict):
        raise RuntimeError("DEPTH_INVALID")
    bids = [(f(x[0]), f(x[1])) for x in data.get("bids", []) if isinstance(x, list) and len(x) >= 2]
    asks = [(f(x[0]), f(x[1])) for x in data.get("asks", []) if isinstance(x, list) and len(x) >= 2]
    if not bids or not asks:
        raise RuntimeError("DEPTH_EMPTY")
    return bids, asks


def slip(levels: list[tuple[float, float]], notional: float, ref: float) -> float | None:
    left, qty, spent = notional, 0.0, 0.0
    for price, size in levels:
        take = min(left, price * size)
        qty += take / price
        spent += take
        left -= take
        if left <= 1e-9:
            break
    if left > 1e-6 or qty <= 0:
        return None
    return abs((spent / qty) / ref - 1.0) * 10000.0


def collect() -> dict[str, Any]:
    observed = datetime.now(timezone.utc).isoformat()
    lats: list[float] = []
    endpoints: list[dict[str, Any]] = []
    credential_errors: list[str] = []
    raw = None
    key = sec = cred_source = base = ""
    ms = 0.0
    candidates = credential_candidates()
    for candidate_key, candidate_sec, candidate_source in candidates:
        try:
            candidate_raw, candidate_ms, candidate_base = get(candidate_key, candidate_sec, "/openApi/swap/v2/user/commissionRate", {})
        except RuntimeError as e:
            credential_errors.append(f"{candidate_source}:{str(e)[:220]}")
            continue
        key, sec, cred_source = candidate_key, candidate_sec, candidate_source
        raw, ms, base = candidate_raw, candidate_ms, candidate_base
        break
    if raw is None:
        raise RuntimeError("NO_VALID_BINGX_READ_ONLY_CREDENTIAL:" + " | ".join(credential_errors[:8]))

    lats.append(ms); endpoints.append({"path": "commissionRate", "base": base, "latency_ms": ms})
    c = raw.get("commission", raw) if isinstance(raw, dict) else None
    if not isinstance(c, dict):
        raise RuntimeError("COMMISSION_INVALID")
    maker, taker = f(c["makerCommissionRate"]) * 100.0, f(c["takerCommissionRate"]) * 100.0
    tier = str(c.get("accountFeeTier") or c.get("feeTier") or "ACCOUNT_ACTUAL_RATE")
    account = {
        "schema_version": "zel.bingx.account_commission.receipt.v1",
        "state": "PASS_BINGX_READ_ONLY_ACCOUNT_COMMISSION",
        "source": "BINGX_READ_ONLY_ACCOUNT_COMMISSION",
        "fixture_only": False,
        "account_fee_tier": tier,
        "maker_fee_pct": maker,
        "taker_fee_pct": taker,
        "payload_sha256": sha(raw),
        "credential_source_id": cred_source,
        "credential_candidate_count": len(candidates),
        "observed_at": observed,
        "write_endpoint_called": False,
        "order_authority": "BLOCKED",
    }
    account["receipt_sha256"] = sha(account)

    now_ms = int(time.time() * 1000)
    funds: list[float] = []
    for symbol in SYMBOLS:
        raw, ms, base = get(key, sec, "/openApi/swap/v2/quote/fundingRate", {"symbol": symbol, "startTime": now_ms - 30*86400000, "endTime": now_ms, "limit": 1000})
        lats.append(ms); endpoints.append({"path": "fundingRate", "symbol": symbol, "base": base, "latency_ms": ms})
        funds += funding_values(raw)
    if not funds:
        raise RuntimeError("FUNDING_HISTORY_EMPTY")

    samples = {b: [] for b in BUCKETS}
    snapshots = 0
    for n in range(5):
        for symbol in SYMBOLS:
            raw, ms, base = get(key, sec, "/openApi/swap/v2/quote/depth", {"symbol": symbol, "limit": 100})
            lats.append(ms); endpoints.append({"path": "depth", "symbol": symbol, "base": base, "latency_ms": ms})
            bids, asks = depth(raw); mid = (bids[0][0] + asks[0][0]) / 2.0
            for b in BUCKETS:
                for x in (slip(asks, b, mid), slip(bids, b, mid)):
                    if x is not None: samples[b].append(x)
            snapshots += 1
        if n < 4: time.sleep(1)
    floors = []
    for b in BUCKETS:
        if not samples[b]: raise RuntimeError(f"SLIPPAGE_EMPTY:{b}")
        floors.append({"max_notional_usdt": b, "slippage_bps_one_way": round(pct(samples[b], .95), 8), "sample_count": len(samples[b])})

    r = {
        "schema_version": "zel.bingx.real_calibration_observation.v1",
        "version": VERSION,
        "state": "PASS_BINGX_REAL_OBSERVATION_COLLECTED_STRESS_PENDING",
        "calibration_mode": "real",
        "observed_at": observed,
        "source_tier": "official",
        "source_identifier": "BingX OpenAPI commissionRate+fundingRate+depth",
        "source_url": "https://bingx-api.github.io/docs/",
        "api_key_fingerprint_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "account_fee_tier": tier,
        "maker_fee_pct": maker,
        "taker_fee_pct": taker,
        "funding_p95_abs_pct_8h": pct(funds, .95),
        "funding_sample_count": len(funds),
        "slippage_floor_bps_by_notional": floors,
        "depth_snapshot_count": snapshots,
        "latency_ms_p50": pct(lats, .50),
        "latency_ms_p95": pct(lats, .95),
        "latency_sample_count": len(lats),
        "account_commission_receipt": account,
        "plus_one_bar_stress_state": "PENDING_STRATEGY_TERMINAL_ARTIFACT",
        "endpoints": endpoints,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    r["receipt_sha256"] = sha(r)
    return r


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    try:
        r = collect()
    except Exception as e:
        r = {
            "schema_version": "zel.bingx.real_calibration_observation.v1",
            "version": VERSION,
            "state": "HOLD_BINGX_REAL_OBSERVATION",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "blocker": f"{type(e).__name__}:{e}",
            "protected_mutations": 0,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
        r["receipt_sha256"] = sha(r)
    p = Path(a.out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(r, indent=2, sort_keys=True)+"\n")
    print(json.dumps({k:r.get(k) for k in ("state","blocker","receipt_sha256")}, sort_keys=True))
    return 0 if r["state"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
