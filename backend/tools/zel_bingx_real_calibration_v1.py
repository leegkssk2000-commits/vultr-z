from __future__ import annotations

import argparse, hashlib, hmac, json, math, os, re, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_BINGX_REAL_CALIBRATION_V1"
BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT")
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


def credentials() -> tuple[str, str, str]:
    key = os.getenv("BINGX_API_KEY", "").strip()
    sec = next((os.getenv(k, "").strip() for k in ("BINGX_SECRET_KEY", "BINGX_API_SECRET", "BINGX_SECRET") if os.getenv(k, "").strip()), "")
    if key and sec:
        return key, sec, "process_env"
    candidates = [Path(p) for p in (
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
            return key, sec, "file_sha256:" + hashlib.sha256(str(p).encode()).hexdigest()
    raise RuntimeError("BINGX_READ_ONLY_CREDENTIALS_NOT_FOUND")


def get(key: str, sec: str, path: str, params: Mapping[str, Any]) -> tuple[Any, float, str]:
    p = dict(params)
    p.update(timestamp=int(time.time() * 1000), recvWindow=5000)
    for k, v in p.items():
        if re.search(r"[&=?#\r\n]", str(v)):
            raise RuntimeError(f"BAD_PARAM:{k}")
    qs = "&".join(f"{k}={p[k]}" for k in sorted(p))
    sig = hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
    for i, base in enumerate(BASES):
        req = urllib.request.Request(
            f"{base}{path}?{qs}&signature={sig}",
            headers={"X-BX-APIKEY": key, "X-SOURCE-KEY": "BX-AI-SKILL", "User-Agent": VERSION},
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                payload = json.loads(r.read())
            ms = (time.perf_counter() - t0) * 1000
            if int(payload.get("code", -1)) != 0:
                raise RuntimeError(f"BINGX_ERROR:{payload.get('code')}:{payload.get('msg')}")
            return payload.get("data"), ms, base
        except Exception:
            if i == len(BASES) - 1:
                raise
    raise RuntimeError("BINGX_REQUEST_FAILED")


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


def adverse_bps(levels: list[tuple[float, float]], mid: float, notional: float, buy: bool) -> float:
    left, cost, qty = notional, 0.0, 0.0
    for price, size in levels:
        take = min(left, price * size)
        if take <= 0:
            continue
        cost += take
        qty += take / price
        left -= take
        if left <= 1e-9:
            break
    if left > 1e-6 or qty <= 0:
        raise RuntimeError("DEPTH_NOTIONAL_UNFILLED")
    avg = cost / qty
    return ((avg / mid - 1.0) if buy else (1.0 - avg / mid)) * 10000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/bingx_real_observation.json")
    ns = ap.parse_args()
    out = Path(ns.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    protected = [
        Path("backend/research/strategy11_v3_policy.json"), Path("backend/research/strategy11_gemini_v3_2_policy.json"),
        Path("backend/research/strategy11_unattended_improvement_policy_v2.json"), Path("backend/research/strategy11_archetype_registry_v1.json"),
        Path("research/evidence/evidence_alpha_v3_executable_specs_v1.json"),
    ]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
    endpoints = []
    try:
        key, sec, credential_source = credentials()
        now = int(time.time() * 1000)
        commission, ms, base = get(key, sec, "/openApi/swap/v2/user/commissionRate", {})
        endpoints.append({"path": "commissionRate", "symbol": None, "host": base, "latency_ms": round(ms, 3)})
        if not isinstance(commission, dict):
            raise RuntimeError("COMMISSION_INVALID")
        maker = f(commission.get("makerCommissionRate", commission.get("makerCommission"))) * 100.0
        taker = f(commission.get("takerCommissionRate", commission.get("takerCommission"))) * 100.0

        funding_all = []
        slip: dict[float, list[float]] = {b: [] for b in BUCKETS}
        for sym in SYMBOLS:
            hist, ms, host = get(key, sec, "/openApi/swap/v2/quote/fundingRate", {"symbol": sym, "startTime": now - 30 * 86400_000, "endTime": now, "limit": 200})
            vals = funding_values(hist)
            if not vals:
                raise RuntimeError(f"FUNDING_EMPTY:{sym}")
            funding_all.extend(vals)
            endpoints.append({"path": "fundingRate", "symbol": sym, "host": host, "latency_ms": round(ms, 3), "rows": len(vals)})
            for _ in range(5):
                book, ms, host = get(key, sec, "/openApi/swap/v2/quote/depth", {"symbol": sym, "limit": 100})
                bids, asks = depth(book)
                mid = (bids[0][0] + asks[0][0]) / 2.0
                endpoints.append({"path": "depth", "symbol": sym, "host": host, "latency_ms": round(ms, 3), "levels": min(len(bids), len(asks))})
                for b in BUCKETS:
                    slip[b].append(max(0.0, adverse_bps(asks, mid, b, True), adverse_bps(bids, mid, b, False)))
                time.sleep(0.15)

        floors = []
        for b in BUCKETS:
            floors.append({"max_notional_usdt": b, "slippage_bps_one_way": round(pct(slip[b], .95), 8), "sample_count": len(slip[b])})
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
        changed = [p for p in before if after.get(p) != before[p]]
        if changed:
            raise RuntimeError("PROTECTED_MUTATION:" + ",".join(changed))
        latencies = [f(e["latency_ms"]) for e in endpoints]
        row = {
            "version": VERSION,
            "state": "PASS_BINGX_REAL_OBSERVATION_COLLECTED_STRESS_PENDING",
            "calibration_mode": "real",
            "source_tier": "official",
            "source_identifier": "BINGX_READ_ONLY_ACCOUNT_COMMISSION_FUNDING_DEPTH",
            "source_url": "https://open-api.bingx.com",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "credential_source": credential_source,
            "account_fee_tier": "observed_account",
            "maker_fee_pct": round(maker, 8),
            "taker_fee_pct": round(taker, 8),
            "funding_p95_abs_pct_8h": round(pct(funding_all, .95), 8),
            "funding_sample_count": len(funding_all),
            "slippage_floor_bps_by_notional": floors,
            "depth_snapshot_count": sum(1 for e in endpoints if e["path"] == "depth"),
            "latency_ms_p50": round(pct(latencies, .50), 3),
            "latency_ms_p95": round(pct(latencies, .95), 3),
            "endpoints": endpoints,
            "account_commission_receipt": {
                "state": "PASS_BINGX_READ_ONLY_ACCOUNT_COMMISSION",
                "maker_fee_pct": round(maker, 8), "taker_fee_pct": round(taker, 8),
                "credential_source": credential_source,
            },
            "plus_one_bar_stress_receipt": None,
            "protected_mutations": 0,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "promotion_authority": False,
            "next": "deterministic +1 bar replay stress; promotion remains blocked",
        }
        row["receipt_sha256"] = sha(row)
        out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"state": row["state"], "maker_fee_pct": row["maker_fee_pct"], "taker_fee_pct": row["taker_fee_pct"], "funding_p95_abs_pct_8h": row["funding_p95_abs_pct_8h"], "latency_ms_p50": row["latency_ms_p50"], "latency_ms_p95": row["latency_ms_p95"], "receipt_sha256": row["receipt_sha256"]}, sort_keys=True))
        return 0
    except Exception as e:
        row = {
            "version": VERSION,
            "state": "HOLD_BINGX_REAL_OBSERVATION",
            "blocker": type(e).__name__ + ":" + str(e)[:300],
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "promotion_authority": False,
            "protected_mutations": 0,
        }
        row["receipt_sha256"] = sha(row)
        out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"state": row["state"], "blocker": row["blocker"], "receipt_sha256": row["receipt_sha256"]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
