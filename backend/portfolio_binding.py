"""Read-only portfolio artifact binding for P0 virtual asset readiness."""

from __future__ import annotations

import json
import os
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def _candidate_paths(root: Path) -> list[Path]:
    env_names = (
        "ZOPS_PORTFOLIO_SOURCE",
        "PORTFOLIO_SOURCE_PATH",
        "CF_PORTFOLIO_SOURCE",
        "GS_PORTFOLIO_SOURCE",
    )
    out: list[Path] = []
    for name in env_names:
        raw = os.getenv(name)
        if raw:
            out.append(Path(raw).expanduser())

    for rel in (
        "data/portfolio/zops_portfolio_source_latest.json",
        "data/portfolio/portfolio_source_latest.json",
        "data/portfolio/portfolio_latest.json",
        "data/portfolio/source_latest.json",
        "db/portfolio_latest.json",
        "z/db/portfolio_latest.json",
    ):
        out.append(root / rel)

    artifacts = {artifact_path(kind, root).resolve() for kind in ARTIFACT_NAMES}
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in out:
        resolved = path if path.is_absolute() else root / path
        resolved = resolved.resolve()
        if resolved in seen or resolved in artifacts:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def find_portfolio_source(root: Path | None = None) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    base = root or repo_root()
    checked: list[str] = []
    for path in _candidate_paths(base):
        checked.append(str(path))
        if not path.is_file():
            continue
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return path, data, checked
    return None, None, checked


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
            "status": "HARD_PAUSE",
            "hold": True,
            "reason": "portfolio_source_missing",
            "missing_sources": checked,
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
    for field in ("equity_series", "virtual_asset_pnl", "bot_team_stats"):
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
        "missing_fields": sorted(set(missing_fields)),
        "missing_sources": [] if not missing_fields else [str(source_path)],
        **READ_ONLY_FLAGS,
    }
    state_artifact = {**state_payload, **common}
    virtual_artifact = {
        "source_path": str(source_path),
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
        "artifacts": {kind: str(artifact_path(kind, base)) for kind in artifacts},
        "missing_fields": common["missing_fields"],
        **READ_ONLY_FLAGS,
    }


def load_or_refresh_artifact(kind: str, root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    if kind not in ARTIFACT_NAMES:
        return {
            "status": "HARD_PAUSE",
            "hold": True,
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
                artifact.update(READ_ONLY_FLAGS)
                return artifact
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "status": "HARD_PAUSE",
        "hold": True,
        "reason": "portfolio_artifact_missing",
        "artifact": str(path),
        "refresh": refresh,
        **READ_ONLY_FLAGS,
    }
