from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_ROOT = Path("/home/z/z/backend/data")
CONFIG_ROOT = Path("/home/z/z/backend/config")
SETTINGS_FILE = DATA_ROOT / "settings" / "gsheets_settings.json"
DEFAULT_CREDS_FILE = CONFIG_ROOT / "gs_service_account.json"

READWRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _safe_dict(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, dict) else {}


def _safe_list(v: Any) -> List[Any]:
    return list(v) if isinstance(v, list) else []


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        s = str(v).strip()
        return s if s else default
    except Exception:
        return default


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _load_settings() -> Dict[str, Any]:
    env_cfg = {
        "enabled": os.getenv("GSHEETS_ENABLED", ""),
        "write_enabled": os.getenv("GSHEETS_WRITE_ENABLED", ""),
        "dry_run": os.getenv("GSHEETS_DRY_RUN", ""),
        "credentials_file": os.getenv("GSHEETS_CREDENTIALS_FILE", ""),
        "spreadsheet_id": os.getenv("GSHEETS_SPREADSHEET_ID", ""),
        "default_tab": os.getenv("GSHEETS_DEFAULT_TAB", ""),
        "default_range": os.getenv("GSHEETS_DEFAULT_RANGE", ""),
    }
    file_cfg = _read_json(SETTINGS_FILE)

    out: Dict[str, Any] = {}
    out["enabled"] = (
        _safe_bool(env_cfg["enabled"], False)
        if _safe_str(env_cfg["enabled"]) != ""
        else _safe_bool(file_cfg.get("enabled"), True)
    )
    out["write_enabled"] = (
        _safe_bool(env_cfg["write_enabled"], False)
        if _safe_str(env_cfg["write_enabled"]) != ""
        else _safe_bool(file_cfg.get("write_enabled"), False)
    )
    out["dry_run"] = (
        _safe_bool(env_cfg["dry_run"], True)
        if _safe_str(env_cfg["dry_run"]) != ""
        else _safe_bool(file_cfg.get("dry_run"), True)
    )
    out["credentials_file"] = _safe_str(
        env_cfg["credentials_file"] or file_cfg.get("credentials_file") or str(DEFAULT_CREDS_FILE)
    )
    out["spreadsheet_id"] = _safe_str(env_cfg["spreadsheet_id"] or file_cfg.get("spreadsheet_id"))
    out["default_tab"] = _safe_str(env_cfg["default_tab"] or file_cfg.get("default_tab"))
    out["default_range"] = _safe_str(env_cfg["default_range"] or file_cfg.get("default_range") or "A:Z")
    return out


def _import_google() -> Tuple[Any, Any, str]:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        return service_account, build, ""
    except Exception as e:
        return None, None, repr(e)


def _build_service(credentials_file: str):
    service_account, build, import_err = _import_google()
    if import_err:
        raise RuntimeError(f"google_client_import_failed: {import_err}")

    cred_path = Path(credentials_file)
    if not cred_path.exists():
        raise FileNotFoundError(f"credentials_file_not_found: {credentials_file}")

    creds = service_account.Credentials.from_service_account_file(
        str(cred_path),
        scopes=READWRITE_SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _normalize_headers(header_row: List[Any]) -> List[str]:
    seen: Dict[str, int] = {}
    headers: List[str] = []

    for i, cell in enumerate(header_row, start=1):
        base = _safe_str(cell, f"col_{i}")
        if not base:
            base = f"col_{i}"

        count = seen.get(base, 0) + 1
        seen[base] = count

        if count > 1:
            base = f"{base}_{count}"

        headers.append(base)

    return headers


def _compose_range(tab: str, a1_range: str) -> str:
    tab = _safe_str(tab)
    a1_range = _safe_str(a1_range)

    if "!" in a1_range:
        return a1_range
    if tab and a1_range:
        return f"{tab}!{a1_range}"
    if tab:
        return f"{tab}!A:Z"
    if a1_range:
        return a1_range
    return "A:Z"


def _col_letters(n: int) -> str:
    if n <= 0:
        return "A"
    out = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def _stringify_key(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip()


def _cell_value(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return v


def _ordered_values(row: Dict[str, Any], headers: List[str]) -> List[Any]:
    return [_cell_value(row.get(h, "")) for h in headers]


def _get_values(service, spreadsheet_id: str, rng: str) -> List[List[Any]]:
    out = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=rng,
            majorDimension="ROWS",
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="FORMATTED_STRING",
        )
        .execute()
    )
    return _safe_list(out.get("values"))


def _update_values(service, spreadsheet_id: str, rng: str, values: List[List[Any]]) -> Dict[str, Any]:
    return (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=rng,
            valueInputOption="USER_ENTERED",
            body={"majorDimension": "ROWS", "values": values},
        )
        .execute()
    )


def _append_values(
    service,
    spreadsheet_id: str,
    rng: str,
    values: List[List[Any]],
    insert_data_option: str = "INSERT_ROWS",
) -> Dict[str, Any]:
    return (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=rng,
            valueInputOption="USER_ENTERED",
            insertDataOption=insert_data_option,
            body={"majorDimension": "ROWS", "values": values},
        )
        .execute()
    )


def _clear_values(service, spreadsheet_id: str, rng: str) -> Dict[str, Any]:
    return (
        service.spreadsheets()
        .values()
        .clear(
            spreadsheetId=spreadsheet_id,
            range=rng,
            body={},
        )
        .execute()
    )


def binding_check() -> Dict[str, Any]:
    cfg = _load_settings()
    _, _, import_err = _import_google()
    cred_path = Path(cfg["credentials_file"]) if cfg["credentials_file"] else DEFAULT_CREDS_FILE

    return {
        "module": "backend.engine.gsheets_readwrite",
        "imports_ok": import_err == "",
        "import_error": import_err,
        "settings_file": str(SETTINGS_FILE),
        "settings_exists": SETTINGS_FILE.exists(),
        "enabled": cfg["enabled"],
        "write_enabled": cfg["write_enabled"],
        "dry_run": cfg["dry_run"],
        "credentials_file": str(cred_path),
        "credentials_exists": cred_path.exists(),
        "spreadsheet_id": cfg["spreadsheet_id"],
        "default_tab": cfg["default_tab"],
        "default_range": cfg["default_range"],
        "scopes": list(READWRITE_SCOPES),
        "read_write": True,
    }


def _guard_write(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not cfg.get("enabled", False):
        return {"ok": False, "reason": "gsheets_disabled", "binding": binding_check()}
    if not cfg.get("write_enabled", False):
        return {"ok": False, "reason": "gsheets_write_disabled", "binding": binding_check()}
    if not _safe_str(cfg.get("spreadsheet_id")):
        return {"ok": False, "reason": "spreadsheet_id_missing", "binding": binding_check()}
    return None


def get_headers(tab: str = "", header_row: int = 1) -> Dict[str, Any]:
    cfg = _load_settings()
    sid = _safe_str(cfg["spreadsheet_id"])
    if not sid:
        return {"ok": False, "reason": "spreadsheet_id_missing", "binding": binding_check()}

    service = _build_service(cfg["credentials_file"])
    rng = _compose_range(tab or cfg["default_tab"], f"{header_row}:{header_row}")
    values = _get_values(service, sid, rng)
    headers = _normalize_headers(values[0]) if values else []

    return {
        "ok": True,
        "spreadsheet_id": sid,
        "range": rng,
        "headers": headers,
        "headers_count": len(headers),
    }


def append_rows(
    rows: List[Dict[str, Any]],
    tab: str = "",
    create_header: bool = False,
) -> Dict[str, Any]:
    cfg = _load_settings()
    guard = _guard_write(cfg)
    if guard:
        return guard

    if not isinstance(rows, list) or not rows:
        return {"ok": False, "reason": "rows_missing"}

    tab_name = _safe_str(tab or cfg["default_tab"])
    if not tab_name:
        return {"ok": False, "reason": "tab_missing"}

    service = _build_service(cfg["credentials_file"])
    sid = _safe_str(cfg["spreadsheet_id"])

    current = _get_values(service, sid, _compose_range(tab_name, "A:Z"))
    headers = _normalize_headers(current[0]) if current else []

    if not headers:
        if not create_header:
            return {"ok": False, "reason": "header_missing", "tab": tab_name}
        first = _safe_dict(rows[0])
        headers = list(first.keys())
        if not headers:
            return {"ok": False, "reason": "header_missing", "tab": tab_name}
        if cfg.get("dry_run", True):
            return {
                "ok": True,
                "status": "dry_run_create_header_append",
                "tab": tab_name,
                "headers": headers,
                "rows_count": len(rows),
            }
        _update_values(
            service,
            sid,
            _compose_range(tab_name, f"A1:{_col_letters(len(headers))}1"),
            [headers],
        )

    ordered = [_ordered_values(_safe_dict(row), headers) for row in rows]

    if cfg.get("dry_run", True):
        return {
            "ok": True,
            "status": "dry_run_append",
            "tab": tab_name,
            "headers": headers,
            "rows_count": len(rows),
            "preview": ordered[:3],
        }

    out = _append_values(
        service,
        sid,
        _compose_range(tab_name, "A:Z"),
        ordered,
        insert_data_option="INSERT_ROWS",
    )

    updates = _safe_dict(out.get("updates"))
    return {
        "ok": True,
        "status": "appended",
        "tab": tab_name,
        "headers": headers,
        "rows_count": len(rows),
        "updated_range": _safe_str(updates.get("updatedRange")),
        "updated_rows": updates.get("updatedRows"),
        "updated_columns": updates.get("updatedColumns"),
        "updated_cells": updates.get("updatedCells"),
    }


def upsert_row(
    row: Dict[str, Any],
    key_field: str,
    tab: str = "",
    create_header: bool = False,
) -> Dict[str, Any]:
    cfg = _load_settings()
    guard = _guard_write(cfg)
    if guard:
        return guard

    row = _safe_dict(row)
    key_field = _safe_str(key_field)
    if not row:
        return {"ok": False, "reason": "row_missing"}
    if not key_field:
        return {"ok": False, "reason": "key_field_missing"}

    tab_name = _safe_str(tab or cfg["default_tab"])
    if not tab_name:
        return {"ok": False, "reason": "tab_missing"}

    service = _build_service(cfg["credentials_file"])
    sid = _safe_str(cfg["spreadsheet_id"])

    values = _get_values(service, sid, _compose_range(tab_name, "A:Z"))
    headers = _normalize_headers(values[0]) if values else []

    if not headers:
        if not create_header:
            return {"ok": False, "reason": "header_missing", "tab": tab_name}
        headers = list(row.keys())
        if key_field not in headers:
            headers.insert(0, key_field)
        if cfg.get("dry_run", True):
            return {
                "ok": True,
                "status": "dry_run_create_header_append",
                "tab": tab_name,
                "headers": headers,
                "key_field": key_field,
                "row": _ordered_values(row, headers),
            }
        _update_values(
            service,
            sid,
            _compose_range(tab_name, f"A1:{_col_letters(len(headers))}1"),
            [headers],
        )
        values = [headers]

    if key_field not in headers:
        return {"ok": False, "reason": "key_field_not_in_header", "tab": tab_name, "headers": headers}

    key_idx = headers.index(key_field)
    probe = _stringify_key(row.get(key_field))

    target_row_num: Optional[int] = None
    for i, existing in enumerate(values[1:], start=2):
        existing_key = _stringify_key(existing[key_idx] if key_idx < len(existing) else "")
        if existing_key == probe:
            target_row_num = i
            break

    ordered = _ordered_values(row, headers)

    if target_row_num is None:
        if cfg.get("dry_run", True):
            return {
                "ok": True,
                "status": "dry_run_append",
                "tab": tab_name,
                "key_field": key_field,
                "key_value": probe,
                "headers": headers,
                "row": ordered,
            }

        out = _append_values(
            service,
            sid,
            _compose_range(tab_name, "A:Z"),
            [ordered],
            insert_data_option="INSERT_ROWS",
        )
        updates = _safe_dict(out.get("updates"))
        return {
            "ok": True,
            "status": "appended",
            "tab": tab_name,
            "key_field": key_field,
            "key_value": probe,
            "updated_range": _safe_str(updates.get("updatedRange")),
            "updated_rows": updates.get("updatedRows"),
            "updated_columns": updates.get("updatedColumns"),
            "updated_cells": updates.get("updatedCells"),
        }

    rng = _compose_range(tab_name, f"A{target_row_num}:{_col_letters(len(headers))}{target_row_num}")

    if cfg.get("dry_run", True):
        return {
            "ok": True,
            "status": "dry_run_update",
            "tab": tab_name,
            "key_field": key_field,
            "key_value": probe,
            "row_num": target_row_num,
            "range": rng,
            "row": ordered,
        }

    out = _update_values(service, sid, rng, [ordered])
    return {
        "ok": True,
        "status": "updated",
        "tab": tab_name,
        "key_field": key_field,
        "key_value": probe,
        "row_num": target_row_num,
        "updated_range": _safe_str(out.get("updatedRange")),
        "updated_rows": out.get("updatedRows"),
        "updated_columns": out.get("updatedColumns"),
        "updated_cells": out.get("updatedCells"),
    }


def batch_upsert(
    rows: List[Dict[str, Any]],
    key_field: str,
    tab: str = "",
    create_header: bool = False,
) -> Dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "reason": "rows_missing"}

    results = []
    ok_count = 0
    for row in rows:
        out = upsert_row(row=row, key_field=key_field, tab=tab, create_header=create_header)
        results.append(out)
        if out.get("ok"):
            ok_count += 1

    return {
        "ok": ok_count == len(results),
        "count": len(results),
        "ok_count": ok_count,
        "results": results,
    }


def clear_range(tab: str = "", a1_range: str = "") -> Dict[str, Any]:
    cfg = _load_settings()
    guard = _guard_write(cfg)
    if guard:
        return guard

    tab_name = _safe_str(tab or cfg["default_tab"])
    rng = _compose_range(tab_name, a1_range or cfg["default_range"])
    service = _build_service(cfg["credentials_file"])
    sid = _safe_str(cfg["spreadsheet_id"])

    if cfg.get("dry_run", True):
        return {"ok": True, "status": "dry_run_clear", "range": rng}

    out = _clear_values(service, sid, rng)
    return {
        "ok": True,
        "status": "cleared",
        "range": _safe_str(out.get("clearedRange", rng)),
    }


__all__ = [
    "binding_check",
    "get_headers",
    "append_rows",
    "upsert_row",
    "batch_upsert",
    "clear_range",
]