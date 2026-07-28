from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    status_code: int
    reason: str
    ts: Optional[int] = None
    nonce: Optional[str] = None


def _parse_sig_header(sig: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    Expect: "t=<ts>,n=<nonce>,v1=<hex>"
    - separators: comma
    - keys: t, n, v1
    """
    if not sig:
        return None, None, None, "signature_missing"

    parts = [p.strip() for p in sig.split(",") if p.strip()]
    kv: Dict[str, str] = {}
    for p in parts:
        if "=" not in p:
            return None, None, None, "invalid_signature_format"
        k, v = p.split("=", 1)
        kv[k.strip().lower()] = v.strip()

    t = kv.get("t")
    n = kv.get("n")
    v1 = kv.get("v1")
    if not t or not n or not v1:
        return t, n, v1, "invalid_signature_format"

    # v1 must be hex
    v1_l = v1.lower()
    hexdigits = set("0123456789abcdef")
    if any(c not in hexdigits for c in v1_l):
        return t, n, v1, "invalid_signature_hex"

    return t, n, v1_l, ""


def _now_s() -> int:
    return int(time.time())


def _ts_to_seconds(ts_raw: str) -> Optional[int]:
    """
    Accept seconds or milliseconds.
    - if ts looks like ms (>= 1e12), convert to seconds for skew check only.
    """
    try:
        ts_int = int(ts_raw)
    except Exception:
        return None

    if ts_int >= 1_000_000_000_000:
        return int(ts_int // 1000)
    return ts_int


def _compute_mac(secret: str, t_raw: str, nonce: str, raw_body: bytes) -> str:
    # IMPORTANT: use t_raw exactly as provided in header for signing string
    msg = f"{t_raw}.{nonce}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _load_ledger(path: str) -> Dict[str, int]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            out: Dict[str, int] = {}
            for k, v in obj.items():
                try:
                    out[str(k)] = int(v)
                except Exception:
                    continue
            return out
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def _atomic_write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _prune_ledger(ledger: Dict[str, int], now_ms: int) -> Dict[str, int]:
    # ledger stores expiry_ms
    return {n: exp for n, exp in ledger.items() if exp > now_ms}


def verify_tv_hmac_only(
    *,
    raw_body: bytes,
    sig_header_value: Optional[str],
    secret: str,
    nonce_ttl_ms: int,
    max_skew_s: int,
    nonce_ledger_path: str,
) -> VerifyResult:
    """
    main.py middleware calls this with:
      raw_body=await request.body()
      sig_header_value=request.headers.get(...)
      secret=get_webhook_secret()
      nonce_ttl_ms=TV_NONCE_TTL_MS
      max_skew_s=TV_MAX_SKEW_S
      nonce_ledger_path=str(TV_NONCE_LEDGER_PATH)

    Contract:
      Header: X-TV-Signature: t=<ts>,n=<nonce>,v1=<hex>
      MAC: HMAC_SHA256(secret, b"{t}.{nonce}." + raw_body_bytes)
    """
    if not secret:
        return VerifyResult(False, 500, "secret_missing")

    t_raw, nonce, sig_hex, err = _parse_sig_header(sig_header_value)
    if err:
        return VerifyResult(False, 401, err, None, nonce)

    # skew check (seconds)
    ts_s = _ts_to_seconds(t_raw or "")
    if ts_s is None:
        return VerifyResult(False, 401, "invalid_signature_timestamp", None, nonce)

    now_s = _now_s()
    if abs(now_s - ts_s) > int(max_skew_s):
        return VerifyResult(False, 401, "timestamp_skew", int(t_raw), nonce)

    # verify signature first (do NOT burn nonce on mismatch)
    expected = _compute_mac(secret, t_raw, nonce, raw_body)
    if not hmac.compare_digest(expected, sig_hex or ""):
        return VerifyResult(False, 401, "signature_mismatch", int(t_raw), nonce)

    # replay protection (file ledger)
    now_ms = int(time.time() * 1000)
    ledger = _load_ledger(nonce_ledger_path)
    ledger = _prune_ledger(ledger, now_ms)

    if nonce in ledger:
        return VerifyResult(False, 409, "replay_nonce", int(t_raw), nonce)

    ledger[nonce] = now_ms + int(nonce_ttl_ms)
    _atomic_write_json(nonce_ledger_path, ledger)

    return VerifyResult(True, 200, "ok", int(t_raw), nonce)
