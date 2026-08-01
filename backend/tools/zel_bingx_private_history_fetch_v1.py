from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.parse
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
KNOWN_PAIRS = (
    ("BINGX_API_KEY", "BINGX_API_SECRET"),
    ("BINGX_API_KEY", "BINGX_SECRET_KEY"),
    ("BINGX_APIKEY", "BINGX_SECRET"),
    ("BINGX_KEY", "BINGX_SECRET"),
    ("BX_API_KEY", "BX_SECRET_KEY"),
)
ROOTS = (Path("/home/z/z"), Path("/opt/zel"), Path("/etc/zel"), Path("/etc/systemd/system"))
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".cache", "logs", "log"}
SUFFIX = {".env", ".conf", ".service", ".json", ".yaml", ".yml", ".py", ".sh"}
DAY_MS = 86_400_000


class BingXApplicationError(RuntimeError):
    pass


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


def usable(value: str) -> bool:
    lowered = value.lower()
    return (
        len(value) >= 8
        and not any(token in value for token in ("${", "{{", "}}"))
        and not any(token in lowered for token in ("changeme", "your_api", "example", "placeholder"))
        and "\n" not in value
    )


def key_names(values: dict[str, str]) -> list[str]:
    result = []
    for name, value in values.items():
        upper = name.upper()
        if not usable(value) or "BINGX" not in upper:
            continue
        if "SECRET" in upper or "PASSPHRASE" in upper or "PRIVATE" in upper:
            continue
        if "API_KEY" in upper or upper.endswith("KEY") or upper.endswith("APIKEY"):
            result.append(name)
    return result


def secret_names(values: dict[str, str]) -> list[str]:
    result = []
    for name, value in values.items():
        upper = name.upper()
        if not usable(value) or "BINGX" not in upper:
            continue
        if "API_SECRET" in upper or "SECRET_KEY" in upper or upper.endswith("SECRET"):
            result.append(name)
    return result


def candidates_from(values: dict[str, str], source_type: str, source_ref: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key_name, secret_name in KNOWN_PAIRS:
        if usable(values.get(key_name, "")) and usable(values.get(secret_name, "")):
            seen.add((key_name, secret_name))
            result.append(
                {
                    "key": values[key_name].strip(),
                    "secret": values[secret_name].strip(),
                    "key_name": key_name,
                    "secret_name": secret_name,
                    "source_type": source_type,
                    "source_ref": source_ref,
                }
            )
    for key_name in key_names(values):
        for secret_name in secret_names(values):
            if (key_name, secret_name) in seen:
                continue
            result.append(
                {
                    "key": values[key_name].strip(),
                    "secret": values[secret_name].strip(),
                    "key_name": key_name,
                    "secret_name": secret_name,
                    "source_type": source_type,
                    "source_ref": source_ref,
                }
            )
    return result[:64]


def discover_candidates() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    candidates.extend(candidates_from(dict(os.environ), "current_environment", "process_self"))
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
            if "BINGX" in name.upper():
                values[name] = value_raw.decode(errors="ignore")
        candidates.extend(candidates_from(values, "process_environment", path.parent.name))
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
                if "BINGX" not in text.upper():
                    continue
                candidates.extend(candidates_from(parse_env_text(text), "configuration_file", str(path)))
    deduplicated: list[dict[str, str]] = []
    identities: set[str] = set()
    for candidate in candidates:
        identity = hashlib.sha256((candidate["key"] + "\0" + candidate["secret"]).encode()).hexdigest()
        if identity in identities:
            continue
        identities.add(identity)
        candidate["fingerprint"] = identity[:12]
        deduplicated.append(candidate)
    return deduplicated[:128]


def safe_error(value: object, key: str, secret: str) -> str:
    return str(value).replace(key, "[API_KEY]").replace(secret, "[API_SECRET]")[:400]


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
    transport_errors: list[str] = []
    for base in BASES:
        url = base + path + "?" + query
        config = "\n".join(
            (
                "silent",
                "show-error",
                "fail-with-body",
                "connect-timeout = 15",
                "max-time = 30",
                f'url = "{url}"',
                f'header = "X-BX-APIKEY: {key}"',
                'header = "X-SOURCE-KEY: BX-AI-SKILL"',
                'header = "User-Agent: ZEL_BINGX_HISTORY_FETCH_V1"',
                "",
            )
        )
        completed = subprocess.run(
            ["curl", "--config", "-"],
            input=config,
            text=True,
            capture_output=True,
            timeout=40,
            check=False,
        )
        if completed.returncode != 0:
            transport_errors.append(f"CURL_{completed.returncode}:{completed.stderr.strip()}")
            continue
        payload = json.loads(completed.stdout)
        code = int(payload.get("code", -1))
        if code != 0:
            # An application response proves transport succeeded. Do not hide it
            # behind a fallback-host TLS error.
            raise BingXApplicationError(f"BINGX:{code}:{payload.get('msg', '')}")
        return payload.get("data")
    raise RuntimeError(" | ".join(transport_errors))


def rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for field in ("orders", "fills", "trades", "list", "data"):
            if isinstance(value.get(field), list):
                return [item for item in value[field] if isinstance(item, dict)]
        return [value]
    return []


def deduplicate(items: list[dict[str, Any]], identity_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = next((f"{field}:{item[field]}" for field in identity_keys if item.get(field) not in (None, "")), None)
        if not identity:
            identity = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
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
        "transport": "curl_tls_verified",
        "write_endpoint_called": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    candidates = discover_candidates()
    validation: list[dict[str, Any]] = []
    selected: dict[str, str] | None = None
    commission: Any = None
    for candidate in candidates:
        try:
            commission = signed_request(candidate["key"], candidate["secret"], ALLOWED["commission"], {})
            selected = candidate
            validation.append({
                "source_type": candidate["source_type"],
                "source_ref": candidate["source_ref"],
                "key_name": candidate["key_name"],
                "secret_name": candidate["secret_name"],
                "fingerprint": candidate["fingerprint"],
                "valid": True,
            })
            break
        except Exception as exc:
            validation.append({
                "source_type": candidate["source_type"],
                "source_ref": candidate["source_ref"],
                "key_name": candidate["key_name"],
                "secret_name": candidate["secret_name"],
                "fingerprint": candidate["fingerprint"],
                "valid": False,
                "error": safe_error(exc, candidate["key"], candidate["secret"]),
            })
    if not selected:
        state = "HOLD_BINGX_CREDENTIAL_NOT_FOUND" if not candidates else "HOLD_BINGX_VALID_CREDENTIAL_NOT_FOUND"
        output = {
            **base,
            "state": state,
            "credential_candidate_count": len(candidates),
            "credential_validation": validation,
            "history": None,
        }
    else:
        key = selected["key"]
        secret = selected["secret"]
        orders: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        income: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        end_ms = int(time.time() * 1000)
        days = max(1, min(args.days, 90))
        cursor = end_ms - days * DAY_MS
        while cursor < end_ms:
            stop = min(cursor + DAY_MS - 1, end_ms)
            calls = (
                ("orders", ALLOWED["orders"], {"currency": "USDT", "startTime": cursor, "endTime": stop, "limit": 1000}),
                ("fills", ALLOWED["fills"], {"currency": "USDT", "tradingUnit": "COIN", "startTs": cursor, "endTs": stop}),
                ("income", ALLOWED["income"], {"startTime": cursor, "endTime": stop, "limit": 1000}),
            )
            targets = {"orders": orders, "fills": fills, "income": income}
            for name, path, params in calls:
                try:
                    targets[name].extend(rows(signed_request(key, secret, path, params)))
                except Exception as exc:
                    errors.append({"endpoint": name, "start": cursor, "end": stop, "error": safe_error(exc, key, secret)})
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
            "credential_candidate_count": len(candidates),
            "credential_validation": validation,
            "credential_source": {
                "source_type": selected["source_type"],
                "source_ref": selected["source_ref"],
                "key_variable_name": selected["key_name"],
                "secret_variable_name": selected["secret_name"],
                "fingerprint": selected["fingerprint"],
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
    print(json.dumps({"state": output["state"], "read_only": True, "encrypted_transport_required": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
