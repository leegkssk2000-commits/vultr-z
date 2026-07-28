from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

VERSION = "ZEL_ACTIVE_OPENAPI_SNAPSHOT_V1"
URL = os.getenv("ACTIVE_OPENAPI_URL", "http://127.0.0.1:8000/openapi.json")
METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "zel-openapi-audit/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(20 * 1024 * 1024)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise RuntimeError("OPENAPI_PAYLOAD_NOT_OBJECT")
        return payload


def main() -> int:
    try:
        document = fetch_json(URL)
        fetch_error = None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, RuntimeError) as exc:
        document = {}
        fetch_error = str(exc)

    operations: list[dict[str, Any]] = []
    operation_ids: defaultdict[str, list[str]] = defaultdict(list)
    for path, path_item in sorted((document.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method, operation in sorted(path_item.items()):
            if method.lower() not in METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            key = f"{method.upper()} {path}"
            if operation_id:
                operation_ids[str(operation_id)].append(key)
            operations.append({
                "key": key,
                "method": method.upper(),
                "path": path,
                "operation_id": operation_id,
                "summary": operation.get("summary"),
                "tags": operation.get("tags") if isinstance(operation.get("tags"), list) else [],
                "deprecated": bool(operation.get("deprecated", False)),
                "security_declared": "security" in operation,
                "response_codes": sorted(str(code) for code in (operation.get("responses") or {}).keys()),
            })

    duplicate_ids = {operation_id: keys for operation_id, keys in operation_ids.items() if len(keys) > 1}
    schemas = ((document.get("components") or {}).get("schemas") or {}) if isinstance(document.get("components"), dict) else {}
    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "url": URL,
        "fetch_error": fetch_error,
        "openapi_version": document.get("openapi"),
        "title": (document.get("info") or {}).get("title") if isinstance(document.get("info"), dict) else None,
        "api_version": (document.get("info") or {}).get("version") if isinstance(document.get("info"), dict) else None,
        "operation_count": len(operations),
        "path_count": len(document.get("paths") or {}),
        "schema_count": len(schemas),
        "operations": operations,
        "duplicate_operation_ids": duplicate_ids,
        "state": "HOLD_OPENAPI_FETCH_FAILED" if fetch_error else ("HOLD_DUPLICATE_OPERATION_IDS" if duplicate_ids else "PASS_OPENAPI_SNAPSHOT"),
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "next": "ADJUDICATE_OPERATION_TO_ACTIVE_SOURCE_OWNERS",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
