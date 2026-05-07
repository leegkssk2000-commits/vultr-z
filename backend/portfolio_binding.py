"""Read-only portfolio artifact binding for P0 virtual asset readiness."""

from __future__ import annotations

import json
import os
import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Any


ARTIFACT_VERSION = "v7_3_1_4"
ARTIFACT_NAMES = {
    "state": f"zops_portfolio_state_{ARTIFACT_VERSION}_latest.json",
    "virtual": f"zops_portfolio_virtual_{ARTIFACT_VERSION}_latest.json",
    "positions": f"zops_portfolio_positions_{ARTIFACT_VERSION}_latest.json",
}
REQUIRED_MINDATA_FIELDS = (
    "price",
    "pos_pct",
    "lev",
    "entry_ts",
    "liq_price",
    "liq_buffer_pct",
    "funding_8h_pct",
    "DD_day_pct",
    "DD_total_pct",
)
READ_ONLY_FLAGS = {
    "execution_allowed": False,
    "mutation_allowed": False,
    "may_emit_to_bot": False,
}

FIELD_ALIASES = {
    "price": ("price", "mark_price", "last_price", "current_price", "close"),
    "pos_pct": ("pos_pct", "position_pct", "allocation_pct", "pos_percent"),
    "lev": ("lev", "leverage"),
    "entry_ts": ("entry_ts", "entry_time", "opened_at", "created_at"),
    "liq_price": ("liq_price", "liquidation_price"),
    "liq_buffer_pct": ("liq_buffer_pct", "liq_buffer", "liquidation_buffer_pct"),
    "funding_8h_pct": ("funding_8h_pct", "funding_rate_8h_pct", "funding_8h"),
    "DD_day_pct": ("DD_day_pct", "dd_day_pct", "daily_drawdown_pct"),
    "DD_total_pct": ("DD_total_pct", "dd_total_pct", "total_drawdown_pct"),
}
STATE_ALIASES = {
    "equity_series": ("equity_series", "equity_curve", "equity"),
    "virtual_equity": ("virtual_equity", "virtual_equity_value"),
    "virtual_asset_pnl": ("virtual_asset_pnl", "virtual_pnl"),
    "bot_team_stats": ("bot_team_stats", "team_stats", "bots"),
}
BOT_TEAM_REQUIRED_FIELDS = ("win_rate", "contribution")


def repo_root() -> Path:
    return Path(os.getenv("Z_HOME", Path(__file__).resolve().parents[1])).resolve()


def artifact_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "portfolio"


def artifact_path(kind: str, root: Path | None = None) -> Path:
    return artifact_dir(root) / ARTIFACT_NAMES[kind]


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _ts_ms(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def _source_candidates(root: Path) -> list[dict[str, Any]]:
    env_names = (
        "ZOPS_PORTFOLIO_SOURCE",
        "PORTFOLIO_SOURCE_PATH",
        "CF_PORTFOLIO_SOURCE",
        "GS_PORTFOLIO_SOURCE",
        "SHEETS_PORTFOLIO_SOURCE",
        "PAPER_LEDGER_PATH",
    )
    out: list[dict[str, Any]] = []
    for name in env_names:
        raw = os.getenv(name)
        if raw:
            out.append({"kind": "env", "label": name, "path": Path(raw).expanduser()})

    for kind, rel in (
        ("portfolio", "data/portfolio/zops_portfolio_source_latest.json"),
        ("portfolio", "data/portfolio/portfolio_source_latest.json"),
        ("portfolio", "data/portfolio/portfolio_latest.json"),
        ("portfolio", "data/portfolio/source_latest.json"),
        ("cf", "data/cf/portfolio_latest.json"),
        ("cf", "data/cf/zops_portfolio_latest.json"),
        ("gs", "data/gs/portfolio_latest.json"),
        ("gs", "data/gs/zops_portfolio_latest.json"),
        ("sheets", "data/sources/sheets_signal_latest.json"),
        ("sheets", "data/sources/sheets_signal_latest.csv"),
        ("source", "data/source/portfolio_latest.json"),
        ("portfolio", "db/portfolio_latest.json"),
        ("portfolio", "z/db/portfolio_latest.json"),
        ("ledger", "db/z.sqlite"),
        ("ledger", "z/db/z.sqlite"),
        ("ledger", "db/logs.db"),
        ("ledger", "z/db/logs.db"),
    ):
        out.append({"kind": kind, "label": rel, "path": root / rel})

    for kind, path in (
        ("portfolio", Path("/home/z/z/data/portfolio/portfolio_source_latest.json")),
        ("cf", Path("/home/z/z/data/cf/portfolio_latest.json")),
        ("gs", Path("/home/z/z/data/gs/portfolio_latest.json")),
        ("sheets", Path("/home/z/z/data/sources/sheets_signal_latest.json")),
        ("sheets", Path("/home/z/z/data/sources/sheets_signal_latest.csv")),
        ("ledger", Path("/home/z/z/db/z.sqlite")),
        ("ledger", Path("/home/z/z/db/logs.db")),
    ):
        out.append({"kind": kind, "label": str(path), "path": path})

    artifacts = {artifact_path(kind, root).resolve() for kind in ARTIFACT_NAMES}
    unique: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for item in out:
        path = item["path"]
        resolved = path if path.is_absolute() else root / path
        resolved = resolved.resolve()
        if "backend/.venv" in resolved.as_posix():
            continue
        if resolved in seen or resolved in artifacts:
            continue
        seen.add(resolved)
        unique.append({**item, "path": resolved})
    return unique


def _inventory_item(candidate: dict[str, Any], usable: bool = False, reason: str | None = None) -> dict[str, Any]:
    path = candidate["path"]
    exists = path.is_file()
    return {
        "kind": candidate["kind"],
        "label": candidate["label"],
        "path": str(path),
        "exists": exists,
        "usable": usable,
        "reason": reason,
        "sha256": _sha256(path) if exists else None,
        "ts_ms": _ts_ms(path) if exists else None,
    }


def _read_csv_source(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return None
    if not rows:
        return None
    return {"positions": rows, "source_format": "csv"}


def _read_sqlite_source(path: Path) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            tables = {
                row["name"]
                for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            out: dict[str, Any] = {"source_format": "sqlite", "tables": sorted(tables)}
            if "positions" in tables:
                out["positions"] = [dict(row) for row in con.execute("SELECT * FROM positions").fetchall()]
            if "portfolio_positions" in tables and "positions" not in out:
                out["positions"] = [dict(row) for row in con.execute("SELECT * FROM portfolio_positions").fetchall()]
            if "equity_series" in tables:
                out["equity_series"] = [dict(row) for row in con.execute("SELECT * FROM equity_series").fetchall()]
            if "virtual_equity" in tables and "equity_series" not in out:
                rows = [dict(row) for row in con.execute("SELECT * FROM virtual_equity").fetchall()]
                out["equity_series"] = rows
                if rows:
                    latest = rows[-1]
                    out["virtual_equity"] = latest.get("equity", latest)
            if "virtual_asset_pnl" in tables:
                out["virtual_asset_pnl"] = [dict(row) for row in con.execute("SELECT * FROM virtual_asset_pnl").fetchall()]
            trade_cols: set[str] = set()
            if "trades" in tables:
                trade_cols = {
                    row["name"] for row in con.execute("PRAGMA table_info(trades)").fetchall()
                }
            if "bot_team_stats" in tables:
                out["bot_team_stats"] = [dict(row) for row in con.execute("SELECT * FROM bot_team_stats").fetchall()]
            if "trades" in tables and "virtual_asset_pnl" not in out:
                if "symbol" not in trade_cols or "pnl" not in trade_cols:
                    return out
                rows = [dict(row) for row in con.execute(
                    "SELECT symbol, SUM(pnl) AS pnl FROM trades GROUP BY symbol"
                ).fetchall()]
                if rows:
                    out["virtual_asset_pnl"] = rows
            if "trades" in tables and "bot_team_stats" not in out:
                group_col = "strategy" if "strategy" in trade_cols else "symbol"
                rows = [dict(row) for row in con.execute(
                    f"""
                    SELECT COALESCE({group_col}, '') AS name,
                           AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
                           SUM(pnl) AS contribution
                    FROM trades
                    GROUP BY COALESCE({group_col}, '')
                    """
                ).fetchall()]
                if rows:
                    out["bot_team_stats"] = rows
            return out
    except sqlite3.Error:
        return None


def _read_candidate_source(candidate: dict[str, Any]) -> dict[str, Any] | None:
    path = candidate["path"]
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None
    if suffix == ".csv":
        return _read_csv_source(path)
    if suffix in {".sqlite", ".db"}:
        return _read_sqlite_source(path)
    return None


def _source_has_bindable_data(source: dict[str, Any]) -> bool:
    return bool(
        _positions_from(source)
        or _state_value(source, "equity_series") is not None
        or _state_value(source, "virtual_equity") is not None
        or _state_value(source, "virtual_asset_pnl") is not None
        or _state_value(source, "bot_team_stats") is not None
    )


def find_portfolio_source(root: Path | None = None) -> tuple[Path | None, dict[str, Any] | None, list[dict[str, Any]]]:
    base = root or repo_root()
    inventory: list[dict[str, Any]] = []
    for candidate in _source_candidates(base):
        path = candidate["path"]
        if not path.is_file():
            inventory.append(_inventory_item(candidate, reason="missing"))
            continue
        source = _read_candidate_source(candidate)
        if source is None:
            inventory.append(_inventory_item(candidate, reason="unreadable_or_unsupported"))
            continue
        usable = _source_has_bindable_data(source)
        inventory.append(_inventory_item(candidate, usable=usable, reason="usable" if usable else "no_bindable_fields"))
        if usable:
            return path, source, inventory
    return None, None, inventory


def _pick(container: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in container and container[key] is not None:
            return container[key]
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positions_from(source: dict[str, Any]) -> list[dict[str, Any]]:
    raw = source.get("positions")
    if raw is None:
        raw = _as_dict(source.get("portfolio")).get("positions")
    if raw is None and any(key in source for key in FIELD_ALIASES):
        raw = [source]
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _normalize_position(position: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = dict(position)
    missing: list[str] = []
    for field in REQUIRED_MINDATA_FIELDS:
        value = _pick(position, FIELD_ALIASES[field])
        if value is None:
            missing.append(field)
        else:
            out[field] = value
    return out, missing


def _state_value(source: dict[str, Any], key: str) -> Any:
    direct = _pick(source, STATE_ALIASES[key])
    if direct is not None:
        return direct
    for nested_key in ("state", "portfolio", "virtual", "team"):
        nested = _as_dict(source.get(nested_key))
        direct = _pick(nested, STATE_ALIASES[key])
        if direct is not None:
            return direct
    return None


def _missing_bot_team_stats(value: Any) -> list[str]:
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = ((str(index), item) for index, item in enumerate(value))
    else:
        return ["bot_team_stats"]

    missing: list[str] = []
    for name, item in items:
        if not isinstance(item, dict):
            missing.append(f"bot_team_stats.{name}")
            continue
        for field in BOT_TEAM_REQUIRED_FIELDS:
            if item.get(field) is None:
                missing.append(f"bot_team_stats.{name}.{field}")
    return missing


def build_portfolio_artifacts(root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    source_path, source, checked = find_portfolio_source(base)
    if source is None or source_path is None:
        return {
            "status": "UNBOUND",
            "hold": True,
            "hard_pause": True,
            "portfolio_source_bound": False,
            "reason": "portfolio_source_missing",
            "source_inventory": checked,
            **READ_ONLY_FLAGS,
        }

    missing_fields: list[str] = []
    normalized_positions: list[dict[str, Any]] = []
    for index, position in enumerate(_positions_from(source)):
        normalized, missing = _normalize_position(position)
        normalized_positions.append(normalized)
        missing_fields.extend(f"positions[{index}].{field}" for field in missing)
    if not normalized_positions:
        missing_fields.append("positions")

    state_payload: dict[str, Any] = {
        "source_path": str(source_path),
        "positions_count": len(normalized_positions),
        **READ_ONLY_FLAGS,
    }
    for field in ("equity_series", "virtual_equity", "virtual_asset_pnl", "bot_team_stats"):
        value = _state_value(source, field)
        if value is None:
            missing_fields.append(field)
        else:
            state_payload[field] = value
            if field == "bot_team_stats":
                missing_fields.extend(_missing_bot_team_stats(value))

    status = "HARD_PAUSE" if missing_fields else "PASS"
    hold = bool(missing_fields)
    common = {
        "status": status,
        "hold": hold,
        "hard_pause": hold,
        "portfolio_source_bound": True,
        "missing_fields": sorted(set(missing_fields)),
        "missing_sources": [] if not missing_fields else [str(source_path)],
        "source_inventory": checked,
        **READ_ONLY_FLAGS,
    }
    state_artifact = {**state_payload, **common}
    virtual_artifact = {
        "source_path": str(source_path),
        "virtual_equity": state_payload.get("virtual_equity"),
        "virtual_asset_pnl": state_payload.get("virtual_asset_pnl"),
        **common,
    }
    positions_artifact = {
        "source_path": str(source_path),
        "positions": normalized_positions,
        "count": len(normalized_positions),
        **common,
    }

    artifacts = {
        "state": state_artifact,
        "virtual": virtual_artifact,
        "positions": positions_artifact,
    }
    for kind, payload in artifacts.items():
        _write_json(artifact_path(kind, base), payload)
    return {
        "status": status,
        "hold": hold,
        "source_path": str(source_path),
        "portfolio_source_bound": True,
        "artifacts": {kind: str(artifact_path(kind, base)) for kind in artifacts},
        "missing_fields": common["missing_fields"],
        "source_inventory": checked,
        **READ_ONLY_FLAGS,
    }


def load_or_refresh_artifact(kind: str, root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    if kind not in ARTIFACT_NAMES:
        return {
            "status": "UNBOUND",
            "hold": True,
            "hard_pause": True,
            "portfolio_source_bound": False,
            "reason": "portfolio_artifact_kind_unknown",
            **READ_ONLY_FLAGS,
        }

    refresh = build_portfolio_artifacts(base)
    path = artifact_path(kind, base)
    if path.is_file():
        try:
            artifact = _read_json(path)
            if isinstance(artifact, dict):
                artifact.setdefault("status", refresh.get("status", "HARD_PAUSE"))
                artifact.setdefault("hold", refresh.get("hold", True))
                artifact.setdefault("hard_pause", artifact.get("hold", True))
                artifact.setdefault("portfolio_source_bound", refresh.get("portfolio_source_bound", False))
                artifact.setdefault("source_inventory", refresh.get("source_inventory", []))
                artifact.update(READ_ONLY_FLAGS)
                return artifact
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "status": "UNBOUND",
        "hold": True,
        "hard_pause": True,
        "portfolio_source_bound": False,
        "reason": "portfolio_artifact_missing",
        "artifact": str(path),
        "refresh": refresh,
        **READ_ONLY_FLAGS,
    }
