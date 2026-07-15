#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BOTS = ("LBot", "MBot", "OBot", "SBot")
ALIASES = {
    "LBot": ("lbot", "lead_bot", "leadbot"),
    "MBot": ("mbot", "method_bot", "methodbot"),
    "OBot": ("obot", "observer_bot", "observerbot"),
    "SBot": ("sbot", "safety_bot", "safetybot"),
}
ROLE_TERMS = {
    "LBot": ("lead", "trend", "primary", "direction", "hold", "reduce", "continuation"),
    "MBot": ("method", "range", "confirm", "mean_reversion", "helper", "retest", "timing"),
    "OBot": ("observer", "breakout", "momentum", "anomaly", "mfe", "mae", "fake_breakout"),
    "SBot": ("safety", "risk", "veto", "drawdown", "exposure", "liquidation", "stale", "stop_loss"),
}
CONTRACT_TERMS = (
    "contract_version", "decision_id", "position_id", "strategy_id", "method_id", "skill_id",
    "confidence", "abstain", "reason_codes", "freshness_ms", "latency_ms", "source_ids", "evidence_ids",
)
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "tests", "test", "backups", "backup", "archive", "rollback", "release_freeze", "evidence", "docs"}
SOURCE_SUFFIXES = {".py", ".sh", ".js", ".ts"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def collect_paths(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str) and value.startswith("/"):
        result.add(value)
    elif isinstance(value, list):
        for child in value:
            result |= collect_paths(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in ("path", "file", "script", "source", "exec")):
                result |= collect_paths(child)
    return result


def component_names(row: dict[str, Any]) -> set[str]:
    value = row.get("components", row.get("component", []))
    if isinstance(value, str):
        value = [value]
    return {str(item) for item in value if str(item) in BOTS}


def discover(inventory: Any, root: Path) -> dict[str, set[Path]]:
    found = {bot: set() for bot in BOTS}
    for row in walk(inventory):
        names = component_names(row)
        if not names:
            continue
        for raw in collect_paths(row):
            path = Path(raw)
            if path.exists() and path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                for bot in names:
                    found[bot].add(path.resolve())
    for base in (root / "backend", root / "scripts", root / "tools", Path("/usr/local/bin")):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            name = path.name.lower()
            for bot, aliases in ALIASES.items():
                if any(alias in name for alias in aliases):
                    found[bot].add(path.resolve())
    return found


def symbols(text: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    classes = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})
    functions = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
    return classes, functions


def inspect(bot: str, path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    classes, functions = symbols(text) if path.suffix.lower() == ".py" else ([], [])
    excluded = any(part.lower() in EXCLUDED_PARTS for part in path.parts)
    role_hits = sorted(term for term in ROLE_TERMS[bot] if term in lower)
    contract_hits = sorted(term for term in CONTRACT_TERMS if term in lower)
    exact = any(alias in path.name.lower() for alias in ALIASES[bot]) or any(bot.lower() in symbol.lower() for symbol in classes + functions)
    helper_surface = any(token in path.name.lower() for token in ("verify", "audit", "probe", "smoke", "install", "bootstrap", "viewer", "render", "display"))
    functional = exact or len(role_hits) >= 2
    if excluded:
        disposition = "QUARANTINE"
    elif helper_surface:
        disposition = "RESERVE"
    elif functional:
        disposition = "ABSORB"
    else:
        disposition = "ARCHIVE"
    return {
        "component": bot,
        "path": str(path),
        "sha256": digest(path),
        "size_bytes": path.stat().st_size,
        "classes": classes,
        "functions": functions,
        "exact_identity_signal": exact,
        "role_terms": role_hits,
        "contract_terms": contract_hits,
        "contract_coverage_pct": round(100.0 * len(contract_hits) / len(CONTRACT_TERMS), 4),
        "disposition": disposition,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--team-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    inventory = load(args.inventory)
    team = load(args.team_evidence)
    discovered = discover(inventory, args.root)
    components: dict[str, Any] = {}
    blockers: list[str] = []
    total = 0
    for bot in BOTS:
        rows = [inspect(bot, path) for path in sorted(discovered[bot])]
        total += len(rows)
        counts = {name: sum(1 for row in rows if row["disposition"] == name) for name in ("ABSORB", "RESERVE", "QUARANTINE", "ARCHIVE")}
        components[bot] = {
            "canonical_target": f"canonical/bots/{bot.lower()}",
            "canonical_owner_exists": False,
            "candidate_count": len(rows),
            "disposition_counts": counts,
            "candidates": rows,
        }
        if not rows:
            blockers.append(f"{bot}:NO_SOURCE_CANDIDATE")
        if counts["ABSORB"] == 0:
            blockers.append(f"{bot}:NO_ABSORB_SOURCE")

    if team.get("state") != "PASS" or team.get("package_owner_count") != 4:
        blockers.append("R05_TEAM_PACKAGE_INVALID")

    payload = {
        "schema": "q4r3_team_advisor_r06_bot_capability_inventory_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS" if not blockers else "HOLD",
        "verdict": "R06_BOT_CONSOLIDATION_PLAN_READY" if not blockers else "R06_BOT_CONSOLIDATION_BLOCKED",
        "components": components,
        "summary": {
            "component_count": 4,
            "candidate_count": total,
            "canonical_owner_count": 0,
            "next_route": "BUILD_CANONICAL_LBOT_MBOT_OBOT_SBOT_PACKAGES",
        },
        "blockers": blockers,
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none"
        },
        "action": "hold"
    }
    write(args.output, payload)
    print(json.dumps({"state": payload["state"], "candidate_count": total, "blocker_count": len(blockers)}, sort_keys=True))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
