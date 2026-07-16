#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc
TEXT_SUFFIXES = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".service", ".timer", ".md"}
CONTAMINATION_PARTS = {
    ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "__pycache__",
    "backup", "backups", "archive", "archives", "rollback", "restore", "snapshot", "snapshots",
    "quarantine", "trash", "old", "copies", "release_freeze", "release-freeze", "frozen",
}
NON_SOURCE_PARTS = {
    "data", "runtime", "evidence", "journal", "processed", "failed", "rejected", "work",
    "paper", "state", "logs", "log", "cache", "tmp",
}
CONTAMINATION_FRAGMENT = re.compile(
    r"(?:^|[._-])(backup|backups|bak|archive|archives|rollback|restore|snapshot|snapshots|"
    r"quarantine|trash|old|copy|copies|release[_-]?freeze|frozen)(?:[._-]|$)",
    re.I,
)
SUPPORT_PARTS = {"test", "tests", "tool", "tools", "script", "scripts"}
SUPPORT_PREFIXES = ("test_", "verify_", "apply_", "install_", "bootstrap_", "run_", "audit_", "probe_", "smoke_", "check_")
DIRECT_EXECUTION_CALLS = {"create_order", "place_order", "submit_order", "send_order", "cancel_order", "private_api", "private_endpoint"}
SENSITIVE_KEY = re.compile(r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)", re.I)
AUDIT_SCHEMA = "q4r3_team_advisor_r41_lico_sgrade_gap_audit_v1"

SURFACES: dict[str, tuple[str, ...]] = {
    "unique_canonical_owner": ("canonical/lico", "lico_owner", "lico_manifest"),
    "typed_context_contract": ("dataclass", "typed_input", "typed_output", "input_schema", "output_schema", "context_envelope"),
    "source_registry": ("source_registry", "source_id", "source_ids", "source_status"),
    "cf_sheets_parity": ("cf:", "sheets:", "source_parity"),
    "source_consensus": ("source_consensus", "consensus_score", "source_confidence", "source_disagreement"),
    "freshness_policy": ("freshness", "stale", "age_ms", "source_age_ms", "data_age"),
    "market_stream_capture": ("order_book", "orderbook", "l2", "best_bid", "best_ask", "mark_price", "index_price", "funding_rate", "trade_stream"),
    "venue_health": ("venue_health", "bingx", "reject_rate", "disconnect", "feed_latency", "latency_ms"),
    "execution_cost_model": ("spread_bps", "slippage_bps", "market_impact", "depth", "execution_cost", "fee_r", "funding_r"),
    "realistic_fill_model": ("order_book_walking", "book_walk", "partial_fill", "filled_qty", "no_fill", "queue_model", "first_fill_ts", "final_fill_ts"),
    "fee_funding_liquidation_model": ("maker_fee", "taker_fee", "funding", "liquidation", "liq_buffer", "mark_price"),
    "stress_scenarios": ("stress_scenario", "capital_stress", "liquidity_stress", "execution_degradation", "volatility_shock"),
    "team_context": ("team_context", "alphateam", "betateam", "gammateam", "deltateam", "selected_team"),
    "evidence_lineage": ("position_id", "decision_id", "strategy_id", "method_id", "skill_id", "source_ids", "evidence_ids", "contract_version"),
    "shadow_paper_calibration": ("actual_vs_simulated", "fill_price_error_bps", "fill_latency_error_ms", "partial_fill_match", "net_r_gap", "calibration"),
    "fail_closed_authority_boundary": ("fail_closed", "abstain", "hold", "route_change", "execution_authority", "runtime_enabled", "order_enabled"),
}

LICO_TEXT_IDENTITY = re.compile(
    r"(?:\bclass\s+Lico\w*\b|\bLicoContext\w*\b|\blico_(?:owner|manifest|context|snapshot|market|source|adapter|contract)\b|"
    r"\bLICO_(?:OWNER|MANIFEST|CONTEXT|SNAPSHOT|MARKET|SOURCE|ADAPTER|CONTRACT)\b|\"component\"\s*:\s*\"Lico\")"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contaminated(path: Path) -> bool:
    for part in path.parts:
        lower = part.lower()
        if lower in CONTAMINATION_PARTS or CONTAMINATION_FRAGMENT.search(lower):
            return True
        if lower.endswith((".bak", ".old", ".orig")):
            return True
    return False


def non_source(path: Path) -> bool:
    return any(part.lower() in NON_SOURCE_PARTS for part in path.parts)


def support_surface(path: Path) -> bool:
    return any(part.lower() in SUPPORT_PARTS for part in path.parts) or path.stem.lower().startswith(SUPPORT_PREFIXES)


def roots(root: Path) -> tuple[Path, ...]:
    values = [
        root / "backend",
        root / "canonical",
        root / "config",
        root / "services",
        root / "systemd",
    ]
    if (root / ".git").exists():
        values.append(Path("/usr/local/bin"))
    return tuple(path for path in values if path.exists())


def iter_files(root: Path) -> Iterable[Path]:
    seen: set[str] = set()
    for base in roots(root):
        iterator = [base] if base.is_file() else base.rglob("*")
        for path in iterator:
            try:
                scoped_path = Path(path.name) if base.is_file() else path.relative_to(base)
            except ValueError:
                continue
            if (
                not path.is_file()
                or path.suffix.lower() not in TEXT_SUFFIXES
                or contaminated(scoped_path)
                or non_source(scoped_path)
                or support_surface(scoped_path)
            ):
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def authority_evidence(path: Path, text: str) -> tuple[list[str], list[str]]:
    calls: list[str] = []
    credentials: list[str] = []
    if path.suffix.lower() != ".py":
        return calls, credentials
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return calls, credentials
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        leaf = name.rsplit(".", 1)[-1].lower()
        if leaf in DIRECT_EXECUTION_CALLS:
            calls.append(f"{name}:{getattr(node, 'lineno', 0)}")
        for arg in list(node.args) + [keyword.value for keyword in node.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and SENSITIVE_KEY.search(arg.value):
                credentials.append(f"{name}:{arg.value}:{getattr(node, 'lineno', 0)}")
    return sorted(set(calls)), sorted(set(credentials))


def identifier_char(value: str) -> bool:
    return value.isalnum() or value == "_"


def marker_present(marker: str, text: str) -> bool:
    start = 0
    while True:
        index = text.find(marker, start)
        if index < 0:
            return False
        end = index + len(marker)
        left_ok = index == 0 or not (identifier_char(marker[0]) and identifier_char(text[index - 1]))
        right_ok = end == len(text) or not (identifier_char(marker[-1]) and identifier_char(text[end]))
        if left_ok and right_ok:
            return True
        start = index + 1


def surface_hits(text_lower: str, path_lower: str) -> dict[str, list[str]]:
    combined = f"{path_lower}\n{text_lower}"
    return {
        surface: sorted({pattern for pattern in patterns if marker_present(pattern, combined)})
        for surface, patterns in SURFACES.items()
    }


def lico_affiliated(path: Path, text: str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    if "/canonical/lico/" in normalized or normalized.endswith("/canonical/lico.py"):
        return True
    if "lico" in path.stem.lower() or "lico" in name:
        return True
    return bool(LICO_TEXT_IDENTITY.search(text))


def git_metadata(root: Path, path: Path) -> dict[str, Any]:
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        return {"tracked": False, "last_commit": None}
    result = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%H", "--", relative], capture_output=True, text=True, check=False, timeout=5)
    value = result.stdout.strip()
    return {"tracked": bool(value), "last_commit": value or None}


def analyze(root: Path, r36_path: Path) -> dict[str, Any]:
    r36 = read_json(r36_path, {})
    candidates: list[dict[str, Any]] = []
    coverage: dict[str, list[str]] = {surface: [] for surface in SURFACES}
    forbidden_hits: list[dict[str, Any]] = []
    owner_paths: list[str] = []

    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not lico_affiliated(path, text):
            continue
        hits = surface_hits(text.lower(), str(path).lower())
        direct_calls, credential_access = authority_evidence(path, text)
        record = {
            "path": str(path),
            "sha256": sha256(path),
            "git": git_metadata(root, path),
            "support_surface": False,
            "surface_hits": {key: value for key, value in hits.items() if value},
            "direct_execution_calls": direct_calls,
            "sensitive_credential_access": credential_access,
        }
        candidates.append(record)
        for surface, values in hits.items():
            if values:
                coverage[surface].append(str(path))
        normalized = str(path).replace("\\", "/").lower()
        if "/canonical/lico/" in normalized or normalized.endswith("/canonical/lico.py"):
            owner_paths.append(str(path))
        if direct_calls or credential_access:
            forbidden_hits.append({
                "path": str(path),
                "direct_execution_calls": direct_calls,
                "sensitive_credential_access": credential_access,
            })

    owner_paths = sorted(set(owner_paths))
    coverage = {key: sorted(set(values)) for key, values in coverage.items()}
    missing = [surface for surface, paths in coverage.items() if not paths]
    if len(owner_paths) != 1 and "unique_canonical_owner" not in missing:
        missing.append("unique_canonical_owner")
    if len(owner_paths) == 1:
        coverage["unique_canonical_owner"] = owner_paths
        missing = [item for item in missing if item != "unique_canonical_owner"]

    blockers: list[str] = []
    if r36.get("state") != "PASS" or int(r36.get("report", {}).get("sgrade_ready_count", 0)) != 4:
        blockers.append("R36_FOUR_TEAM_SGRADE_LOCK_NOT_PROVEN")
    if forbidden_hits:
        blockers.append("LICO_PRIVATE_EXECUTION_OR_CREDENTIAL_SURFACE_FOUND")
    if len(owner_paths) > 1:
        blockers.append("LICO_DUPLICATE_CANONICAL_OWNER")

    state = "PASS" if not missing and not blockers else "HOLD"
    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": now_iso(),
        "official_stage": "R4.1",
        "state": state,
        "verdict": "R41_LICO_SGRADE_GAP_AUDIT_PASS" if state == "PASS" else "R41_LICO_SGRADE_GAPS_CLASSIFIED",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "blockers": blockers,
        "report": {
            "candidate_count": len(candidates),
            "canonical_owner_count": len(owner_paths),
            "canonical_owner_paths": owner_paths,
            "required_surface_count": len(SURFACES),
            "ready_surface_count": len(SURFACES) - len(missing),
            "missing_surface_count": len(missing),
            "missing_surfaces": sorted(missing),
            "surface_coverage": coverage,
            "forbidden_hit_count": len(forbidden_hits),
            "forbidden_hits": forbidden_hits,
            "r36_team_sgrade_ready_count": int(r36.get("report", {}).get("sgrade_ready_count", 0)),
            "historical_r0_surface_pct": 85.7143,
            "historical_r0_missing_surface": "source_consensus",
            "market_realism_required": True,
            "runtime_binding": False,
            "execution_authority": "none",
            "sgrade_ready": state == "PASS",
            "next_route": "R4.2_LICO_CANONICAL_OWNER_SOURCE_CONSENSUS" if state == "HOLD" else "R4.6_LICO_SGRADE_LOCK",
            "candidates": sorted(candidates, key=lambda item: item["path"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--r36", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze(args.root.resolve(), args.r36.resolve())
    atomic_json(args.output.resolve(), payload)
    report = payload["report"]
    print(json.dumps({
        "state": payload["state"],
        "candidate_count": report["candidate_count"],
        "canonical_owner_count": report["canonical_owner_count"],
        "ready_surface_count": report["ready_surface_count"],
        "missing_surface_count": report["missing_surface_count"],
        "forbidden_hit_count": report["forbidden_hit_count"],
        "blocker_count": len(payload["blockers"]),
        "verdict": payload["verdict"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
