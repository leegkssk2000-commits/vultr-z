from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "zel.production_ssot_source_recovery.v2"

TARGETS = {
    "ZEL_DATA_STALE_MS": ("ZEL_DATA_STALE_MS", "DATA_STALE_MS", "market_data_stale_ms", "data_stale_ms"),
    "ZEL_ACCOUNT_STALE_MS": ("ZEL_ACCOUNT_STALE_MS", "account_state_stale_ms", "account_stale_ms"),
    "ZEL_MAX_DD_DAY_PCT": ("ZEL_MAX_DD_DAY_PCT", "max_dd_day_pct", "dd_day_limit_pct", "daily_drawdown_limit_pct"),
    "ZEL_MAX_DD_TOTAL_PCT": ("ZEL_MAX_DD_TOTAL_PCT", "max_dd_total_pct", "dd_total_limit_pct", "total_drawdown_limit_pct"),
    "ZEL_ALPHA_SIGNAL_STALE_MS": ("ZEL_ALPHA_SIGNAL_STALE_MS", "alpha_signal_stale_ms", "signal_stale_ms"),
    "ZEL_PAPER_INITIAL_EQUITY_USDT": ("ZEL_PAPER_INITIAL_EQUITY_USDT", "paper_initial_equity_usdt", "initial_equity_usdt"),
    "ZEL_RISK_DAY_TZ": ("ZEL_RISK_DAY_TZ", "risk_day_timezone", "risk_day_tz"),
    "ZEL_IMPROVE_MIN_TRADES": ("ZEL_IMPROVE_MIN_TRADES", "improve_min_trades", "min_evidence_samples", "min_trades"),
    "ZEL_IMPROVE_MIN_EXPECTANCY": ("ZEL_IMPROVE_MIN_EXPECTANCY", "improve_min_expectancy", "min_expectancy", "minimum_expectancy"),
    "ZEL_IMPROVE_MIN_PF": ("ZEL_IMPROVE_MIN_PF", "improve_min_profit_factor", "min_profit_factor", "min_pf"),
    "ZEL_IMPROVE_MIN_NET_PNL": ("ZEL_IMPROVE_MIN_NET_PNL", "improve_min_net_pnl", "min_net_pnl"),
    "ZEL_IMPROVE_MAX_DD_PCT": ("ZEL_IMPROVE_MAX_DD_PCT", "improve_max_dd_pct", "max_dd_pct"),
    "ZEL_IMPROVE_MIN_SCORE_GAIN": ("ZEL_IMPROVE_MIN_SCORE_GAIN", "improve_min_score_gain", "min_score_gain"),
    "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT": ("ZEL_IMPROVE_MAX_DD_REGRESSION_PCT", "improve_max_dd_regression_pct", "max_dd_regression_pct"),
    "ZEL_IMPROVE_ERROR_BUDGET": ("ZEL_IMPROVE_ERROR_BUDGET", "improve_error_budget", "error_budget"),
}

ALIAS_TO_TARGET = {alias.lower(): target for target, aliases in TARGETS.items() for alias in aliases}
TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt", ".py", ".sh"}
EXCLUDED_PARTS = {
    ".git", "ledger", "node_modules", ".venv", "venv", "__pycache__", "artifacts", "artifact",
    "logs", "log", "datasets", "dataset", "historical-oos-v1", "data-b-1m-v2",
}
NON_AUTHORITY_PARTS = {
    "tests", "test", "research", ".github", "fixtures", "fixture", "examples", "example",
    "archive", "archives", "backup", "backups", "tmp", "temp",
}
EXPLICIT_AUTHORITY_MARKERS = ("z_policy", "z-policy", "z policy", "ssot")
CURRENT_POLICY_HINTS = ("policy", "config", "ssot", "z_policy", "z-policy")

NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
TZ_RE = re.compile(r"^(?:UTC|Etc/[A-Za-z0-9_+\-]+|[A-Za-z_]+/[A-Za-z0-9_+\-]+)$")
PAIR_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=|:)\s*(?P<value>[^#;,}\]]+)", re.IGNORECASE
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_value(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    raw = str(value).strip().strip("'\"")
    if not raw or raw.lower() in {"none", "null", "true", "false", "unbound", "missing"}:
        return None
    if NUMERIC_RE.fullmatch(raw) or TZ_RE.fullmatch(raw):
        return raw
    return None


def classify(root: Path, path: Path, text: str) -> tuple[bool, str]:
    rel = path.relative_to(root)
    lowered_parts = {part.lower() for part in rel.parts}
    name = path.name.lower()
    if lowered_parts & NON_AUTHORITY_PARTS or name.endswith(".example") or ".env" in name:
        return False, "NON_AUTHORITY_PATH"

    full = str(rel).lower()
    sample = text[:250_000].lower()
    explicit = any(marker in full or marker in sample for marker in EXPLICIT_AUTHORITY_MARKERS)
    if explicit:
        return True, "EXPLICIT_Z_POLICY_OR_SSOT_MARKER"

    # Only the immutable current production release may use a generic policy/config
    # path as authority. The dirty legacy checkout is evidence-only unless it
    # explicitly declares Z_POLICY/SSOT. This prevents local risk/runtime snapshots
    # from silently becoming production policy.
    current_release = root.name == "zel-production-current"
    if current_release and any(hint in full for hint in CURRENT_POLICY_HINTS):
        return True, "CURRENT_PRODUCTION_RELEASE_POLICY_CONFIG"

    if current_release:
        return False, "CURRENT_RELEASE_NON_POLICY_PATH"
    return False, "LEGACY_REQUIRES_EXPLICIT_Z_POLICY_SSOT"


def target_for_key(key: str) -> str | None:
    normalized = key.strip().strip("'\"").lower()
    if normalized in ALIAS_TO_TARGET:
        return ALIAS_TO_TARGET[normalized]
    tail = normalized.split(".")[-1]
    return ALIAS_TO_TARGET.get(tail)


def add_hit(
    hits: list[dict[str, Any]],
    *,
    root: Path,
    path: Path,
    key: str,
    value: Any,
    line: int | None,
    authority: bool,
    authority_reason: str,
) -> None:
    target = target_for_key(key)
    cleaned = clean_value(value)
    if target is None or cleaned is None:
        return
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    hits.append({
        "target": target,
        "matched_key": key,
        "value": cleaned,
        "source": rel,
        "line": line,
        "source_sha256": sha256_file(path),
        "authority_candidate": authority,
        "authority_reason": authority_reason,
    })


def walk_json(
    obj: Any,
    *,
    root: Path,
    path: Path,
    hits: list[dict[str, Any]],
    authority: bool,
    authority_reason: str,
    prefix: str = "",
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            add_hit(
                hits, root=root, path=path, key=str(key), value=value, line=None,
                authority=authority, authority_reason=authority_reason,
            )
            add_hit(
                hits, root=root, path=path, key=dotted, value=value, line=None,
                authority=authority, authority_reason=authority_reason,
            )
            walk_json(
                value, root=root, path=path, hits=hits, authority=authority,
                authority_reason=authority_reason, prefix=dotted,
            )
    elif isinstance(obj, list):
        for value in obj:
            walk_json(
                value, root=root, path=path, hits=hits, authority=authority,
                authority_reason=authority_reason, prefix=prefix,
            )


def scan_file(root: Path, path: Path, hits: list[dict[str, Any]]) -> None:
    try:
        if path.stat().st_size > 2_000_000:
            return
    except OSError:
        return
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    authority, authority_reason = classify(root, path, text)
    if path.suffix.lower() == ".json":
        try:
            walk_json(
                json.loads(text), root=root, path=path, hits=hits,
                authority=authority, authority_reason=authority_reason,
            )
        except Exception:
            pass
    alias_tokens = tuple(ALIAS_TO_TARGET)
    for line_no, raw in enumerate(text.splitlines(), 1):
        lowered = raw.lower()
        if not any(alias in lowered for alias in alias_tokens):
            continue
        for match in PAIR_RE.finditer(raw):
            add_hit(
                hits,
                root=root,
                path=path,
                key=match.group("key"),
                value=match.group("value").strip(),
                line=line_no,
                authority=authority,
                authority_reason=authority_reason,
            )


def scan_root(root: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not root.is_dir():
        return hits
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        rel_parts = {part.lower() for part in path.relative_to(root).parts}
        if rel_parts & EXCLUDED_PARTS:
            continue
        scan_file(root, path, hits)
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for hit in hits:
        key = (
            hit["target"], hit["value"], hit["source"], hit["line"],
            hit["authority_candidate"], hit["authority_reason"],
        )
        unique[key] = hit
    return sorted(unique.values(), key=lambda h: (h["target"], h["source"], h["line"] or 0, h["value"]))


def build_receipt(roots: list[Path]) -> dict[str, Any]:
    all_hits: list[dict[str, Any]] = []
    root_summaries = []
    for root in roots:
        hits = scan_root(root)
        all_hits.extend([{**hit, "root": str(root)} for hit in hits])
        root_summaries.append({"root": str(root), "exists": root.is_dir(), "hit_count": len(hits)})

    targets: dict[str, Any] = {}
    resolved_count = 0
    conflict_count = 0
    for target in TARGETS:
        rows = [hit for hit in all_hits if hit["target"] == target]
        authority_rows = [hit for hit in rows if hit["authority_candidate"]]
        distinct = sorted({hit["value"] for hit in authority_rows})
        if len(distinct) == 1:
            state = "RESOLVED_SINGLE_AUTHORITY_VALUE"
            resolved_count += 1
        elif len(distinct) > 1:
            state = "HOLD_AUTHORITY_VALUE_CONFLICT"
            conflict_count += 1
        else:
            state = "HOLD_NO_AUTHORITY_VALUE"
        targets[target] = {
            "state": state,
            "authority_distinct_values": distinct,
            "authority_sources": authority_rows,
            "all_hit_count": len(rows),
            "non_authority_hit_count": len(rows) - len(authority_rows),
        }

    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_SOURCE_RECOVERY_AUDIT_COMPLETE",
        "target_count": len(TARGETS),
        "resolved_single_value_count": resolved_count,
        "conflict_count": conflict_count,
        "unresolved_count": len(TARGETS) - resolved_count,
        "roots": root_summaries,
        "targets": targets,
        "legacy_generic_policy_is_authority": False,
        "env_mutated": False,
        "service_mutated": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ZEL production SSOT source recovery")
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_receipt(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "target_count": result["target_count"],
        "resolved_single_value_count": result["resolved_single_value_count"],
        "conflict_count": result["conflict_count"],
        "unresolved_count": result["unresolved_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
