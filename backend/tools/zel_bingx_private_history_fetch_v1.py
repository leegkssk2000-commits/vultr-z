from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
ALLOWED = {
    "orders": "/openApi/swap/v2/trade/allOrders",
    "fills": "/openApi/swap/v2/trade/allFillOrders",
    "income": "/openApi/swap/v2/user/income",
    "commission": "/openApi/swap/v2/user/commissionRate",
}
KEYS = ("BINGX_API_KEY", "BINGX_APIKEY", "BINGX_KEY", "BX_API_KEY")
SECRETS = ("BINGX_SECRET_KEY", "BINGX_API_SECRET", "BINGX_SECRET", "BX_SECRET_KEY")
ROOTS = (Path("/home/z/z"), Path("/opt/zel"), Path("/etc/zel"), Path("/etc/systemd/system"))
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".cache", "logs", "log"}
SUFFIX = {".env", ".conf", ".service", ".json", ".yaml", ".yml", ".py", ".sh"}
DAY_MS = 86_400_000


def ssl_context() -> ssl.SSLContext:
    # Prefer the host's CA bundle because VPS environments may use a private
    # egress CA that is absent from a venv's bundled certifi store.
    candidates = (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/cert.pem",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = ssl_context()


def pick(values: dict[str, str]) -> tuple[str, str, str, str] | None:
    key_name = next((name for name in KEYS if values.get(name)), None)
    secret_name = next((name for name in SECRETS if values.get(name)), None)
    if not key_name or not secret_name:
        return None
    return str(values[key_name]).strip(), str(values[secret_name]).strip(), key_name, secret_name


def parse_env_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        result[match.group(1)] = value
    return result


def discover_credentials() -> tuple[str, str, str, str, str] | None:
    current = pick(dict(os.environ))
    if current:
        return *current, "current_environment"

    for path in Path("/proc").glob("[0-9]*/environ"):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        values: dict[str, str] = {}
        for item in raw.split(b"\0"):
            if b"=" not in item:
                continue
            name_raw, value_raw = item.split(b"=", 1)
            name = name_raw.decode(errors="ignore")
            if name in KEYS + SECRETS:
                values[name] = value_raw.decode(errors="ignore")
        current = pick(values)
        if current:
            return *current, "process_environment"

    for root in ROOTS:
        if not root.exists():
            continue
        for current_dir, dirs, files in os.walk(root):
            dirs[:] = [directory for directory in dirs if directory not in SKIP]
            for filename in files:
                path = Path(current_dir) / filename
                try:
                    if path.is_symlink():
                        continue
                    if path.suffix.lower() not in SUFFIX and path.name not in {".env", "environment"}:
                        continue
                    if path.stat().st_size > 2_000_000:
                        continue
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                if "BINGX" not in text.upper() and "BX_API" not in text.upper():
                    continue
                current = pick(parse_env_text(text))
                if current:
                    return *current, "configuration_file"
    return None


def signed_request(key: str, secret: str, path: str, params: dict[str, Any]) -> Any:
    if path not in ALLOWED.values():
        raise RuntimeError("ENDPOINT_NOT_ALLOWED")
    signed = {**params, "recvWindow": 5000, "timestamp": int(time.time() * 1000)}
    canonical = "&".join(f"{name}={signed[name]}" for name in sorted(signed))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    query = urllib.parse.urlencode(
        [(name, str(signed[name])) for name in sorted(signed)] + [("signature", signature)],
        safe="-_.~",
    )
    headers = {
        "X-BX-APIKEY": key,
        "X-SOURCE-KEY": "BX-AI-SKILL",
        "User-Agent": "ZEL_BINGX_HISTORY_FETCH_V1",
    }
    last_error: Exception | None = None
    for base in BASES:
        try:
            request = urllib.request.Request(base + path + "?" + query, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=20, context=SSL_CONTEXT) as response:
                payload = json.loads(response.read().decode())
            if int(payload.get("code", -1)) != 0:
                raise RuntimeError(f"BINGX:{payload.get('code')}:{payload.get('msg', '')}")
            return payload.get("data")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error))


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("orders", "fills", "trades", "list", "data"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        return [value]
    return []


def deduplicate(items: list[dict[str, Any]], identity_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = next(
            (f"{key}:{item[key]}" for key in identity_keys if item.get(key) not in (None, "")),
            None,
        )
        if not identity:
            identity = hashlib.sha256(
                json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        result[identity] = item
    return list(result.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    base = {
        "schema_version": "zel.bingx.private_history.raw.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "write_endpoint_called": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    credentials = discover_credentials()
    if not credentials:
        output = {**base, "state": "HOLD_BINGX_CREDENTIAL_NOT_FOUND", "history": None}
    else:
        key, secret, key_name, secret_name, source = credentials
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        income: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        end_ms = int(time.time() * 1000)
        days = max(1, min(args.days, 90))
        cursor = end_ms - days * DAY_MS

        try:
            commission = signed_request(key, secret, ALLOWED["commission"], {})
        except Exception as exc:
            commission = None
            errors.append({"endpoint": "commission", "error": str(exc)[:300]})

        while cursor < end_ms:
            stop = min(cursor + DAY_MS - 1, end_ms)
            calls = (
                (
                    "orders",
                    ALLOWED["orders"],
                    {"currency": "USDT", "startTime": cursor, "endTime": stop, "limit": 1000},
                ),
                (
                    "fills",
                    ALLOWED["fills"],
                    {"currency": "USDT", "tradingUnit": "COIN", "startTs": cursor, "endTs": stop},
                ),
                (
                    "income",
                    ALLOWED["income"],
                    {"startTime": cursor, "endTime": stop, "limit": 1000},
                ),
            )
            targets = {"orders": orders, "fills": fills, "income": income}
            for name, path, params in calls:
                try:
                    targets[name].extend(rows(signed_request(key, secret, path, params)))
                except Exception as exc:
                    errors.append(
                        {"endpoint": name, "start": cursor, "end": stop, "error": str(exc)[:300]}
                    )
                time.sleep(0.24)
            cursor = stop + 1

        clean_orders = deduplicate(orders, ("orderID", "orderId", "clientOrderId"))
        clean_fills = deduplicate(fills, ("tradeId", "fillId", "orderId"))
        clean_income = deduplicate(income, ("tranId", "tradeId", "time"))
        any_payload = bool(clean_orders or clean_fills or clean_income or commission is not None)
        if errors and not any_payload:
            state = "HOLD_BINGX_PRIVATE_HISTORY_API_ERRORS"
        elif errors:
            state = "HOLD_BINGX_PRIVATE_HISTORY_PARTIAL_ERRORS"
        else:
            state = "PASS_BINGX_PRIVATE_HISTORY_READ_ONLY"

        output = {
            **base,
            "state": state,
            "lookback_days": days,
            "credential_source": {
                "source_type": source,
                "key_variable_name": key_name,
                "secret_variable_name": secret_name,
                "values_exposed": False,
            },
            "history": {
                "orders": clean_orders,
                "fills": clean_fills,
                "income": clean_income,
                "commission": commission,
                "errors": errors,
                "request_error_count": len(errors),
            },
        }

    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(
        json.dumps(
            {
                "state": output["state"],
                "read_only": True,
                "encrypted_transport_required": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
