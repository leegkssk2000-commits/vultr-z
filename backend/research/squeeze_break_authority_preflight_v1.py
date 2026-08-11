from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.squeeze_break.authority_preflight.v1"
STRATEGY_ID = "squeeze_break"
SKIP_PARTS = {"archive", "backup", "snapshot", "restore", "artifacts", "cache", ".git", "node_modules"}
MAX_FILES = 5000
MAX_BYTES = 1_000_000


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def strategy_match(obj: Mapping[str, Any], parent_key: str | None) -> bool:
    if parent_key == STRATEGY_ID:
        return True
    for key in ("strategy_id", "legacy_name", "name", "id"):
        if str(obj.get(key) or "").strip() == STRATEGY_ID:
            return True
    return False


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def walk(value: Any, path: Path, out: list[dict[str, Any]], policy_hits: list[dict[str, Any]], parent_key: str | None = None, depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(value, Mapping):
        if strategy_match(value, parent_key):
            risk = value.get("risk_request") if isinstance(value.get("risk_request"), Mapping) else None
            leverage = numeric((risk or {}).get("leverage_x")) if risk else numeric(value.get("leverage_x"))
            position = numeric((risk or {}).get("position_pct")) if risk else numeric(value.get("position_pct"))
            symbol = str(value.get("symbol") or (risk or {}).get("symbol") or "").replace("-", "").upper()
            row = {
                "path": str(path),
                "file_sha256": file_sha(path),
                "explicit_risk_request_object": risk is not None,
                "leverage_x": leverage,
                "position_pct": position,
                "symbol": symbol or None,
                "risk_complete": leverage is not None and position is not None,
            }
            out.append(row)
        keys = {
            "max_dd_pct", "max_drawdown_pct", "initial_equity_usdt", "paper_initial_equity_usdt",
            "retention_pct", "minimum_retention_pct", "min_retention_pct", "retention_gte",
        }
        present = {k: value.get(k) for k in keys if k in value}
        if present:
            policy_hits.append({
                "path": str(path),
                "file_sha256": file_sha(path),
                "fields": {k: present[k] for k in sorted(present)},
            })
        for key, child in value.items():
            walk(child, path, out, policy_hits, str(key), depth + 1)
    elif isinstance(value, list):
        for child in value:
            walk(child, path, out, policy_hits, parent_key, depth + 1)


def candidate_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.json"):
            parts = {part.lower() for part in p.parts}
            if parts & SKIP_PARTS:
                continue
            files.append(p)
            if len(files) >= MAX_FILES:
                return files
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-root", type=Path, required=True)
    ap.add_argument("--production-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()
    roots = [
        ns.legacy_root / "config",
        ns.legacy_root / "backend" / "config",
        ns.legacy_root / "backend" / "strategy25",
        ns.legacy_root / "policies",
        ns.production_root / "config",
        ns.production_root / "backend" / "config",
        ns.production_root / "policies",
    ]
    files = candidate_files(roots)
    risk_rows: list[dict[str, Any]] = []
    policy_hits: list[dict[str, Any]] = []
    for path in files:
        row = read_json(path)
        if row is not None:
            walk(row, path, risk_rows, policy_hits)
    unique_risk: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in risk_rows:
        key = (r["path"], r["leverage_x"], r["position_pct"], r["symbol"], r["explicit_risk_request_object"])
        unique_risk[key] = r
    unique_policy: dict[tuple[str, str], dict[str, Any]] = {}
    for r in policy_hits:
        key = (r["path"], json.dumps(r["fields"], sort_keys=True, default=str))
        unique_policy[key] = r
    risks = sorted(unique_risk.values(), key=lambda r: (not r["risk_complete"], r["path"]))
    policies = sorted(unique_policy.values(), key=lambda r: r["path"])
    exact_risk = [r for r in risks if r["explicit_risk_request_object"] and r["risk_complete"]]
    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_EXPLICIT_RISK_AUTHORITY_CANDIDATE_FOUND" if exact_risk else "HOLD_EXPLICIT_RISK_AUTHORITY_NOT_FOUND",
        "strategy_id": STRATEGY_ID,
        "json_files_scanned": len(files),
        "risk_candidates": risks,
        "explicit_complete_risk_candidate_count": len(exact_risk),
        "dd_retention_policy_hits": policies,
        "authority_adopted": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_mutated": False,
        "service_mutated": False,
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": receipt["state"],
        "json_files_scanned": receipt["json_files_scanned"],
        "risk_candidates": len(risks),
        "explicit_complete_risk_candidate_count": len(exact_risk),
        "dd_retention_policy_hits": len(policies),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
