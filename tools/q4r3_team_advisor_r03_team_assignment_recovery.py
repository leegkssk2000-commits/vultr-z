#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC = timezone.utc
TEAMS = ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam")
BOTS = ("LBot", "MBot", "OBot", "SBot")
ROLE_KEYS = {
    "team_id": "team_id",
    "team": "team_id",
    "main": "main_bot",
    "main_bot": "main_bot",
    "lead": "main_bot",
    "lead_bot": "main_bot",
    "support": "support_bot",
    "support_bot": "support_bot",
    "watcher": "watchers",
    "watchers": "watchers",
    "watcher_bots": "watchers",
    "helper": "helper_bot",
    "helper_bot": "helper_bot",
    "helper_trigger": "helper_trigger",
}
SENSITIVE = re.compile(r"(?i)(api[_-]?key|secret|token|password|passphrase|private[_-]?key)")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, path)


def canonical_team(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    mapping = {
        "alpha": "AlphaTeam", "alphateam": "AlphaTeam",
        "beta": "BetaTeam", "betateam": "BetaTeam",
        "gamma": "GammaTeam", "gammateam": "GammaTeam",
        "delta": "DeltaTeam", "deltateam": "DeltaTeam",
    }
    return mapping.get(text)


def canonical_bot(value: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    mapping = {
        "l": "LBot", "lbot": "LBot", "leadbot": "LBot",
        "m": "MBot", "mbot": "MBot", "methodbot": "MBot",
        "o": "OBot", "obot": "OBot", "observerbot": "OBot",
        "s": "SBot", "sbot": "SBot", "safetybot": "SBot",
    }
    return mapping.get(text)


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def safe_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, str) and SENSITIVE.search(value):
            return "<redacted>"
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted_name(node)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [safe_value(item) for item in node.elts]
    if isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                continue
            key = safe_value(key_node)
            if not isinstance(key, (str, int, float, bool)):
                continue
            key_text = str(key)
            if SENSITIVE.search(key_text):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = safe_value(value_node)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = safe_value(node.operand)
        if isinstance(value, (int, float)):
            return -value if isinstance(node.op, ast.USub) else value
    return None


def normalize_bots(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        bot = canonical_bot(item)
        if bot and bot not in result:
            result.append(bot)
    return result


def normalize_explicit_record(raw: Mapping[str, Any], line: int, source: str) -> dict[str, Any] | None:
    normalized: dict[str, Any] = {"line": line, "source": source}
    for key, value in raw.items():
        role = ROLE_KEYS.get(re.sub(r"[^a-z0-9_]", "", str(key).lower()))
        if not role:
            continue
        if role == "team_id":
            team = canonical_team(value)
            if team:
                normalized[role] = team
        elif role in {"main_bot", "support_bot", "helper_bot"}:
            bots = normalize_bots(value)
            if bots:
                normalized[role] = bots[0]
        elif role == "watchers":
            bots = normalize_bots(value)
            if bots:
                normalized[role] = bots
        elif role == "helper_trigger":
            if isinstance(value, str) and value != "<redacted>" and len(value) <= 200:
                normalized[role] = value
    if not normalized.get("team_id"):
        return None
    if not any(key in normalized for key in ("main_bot", "support_bot", "watchers", "helper_bot")):
        return None
    return normalized


def explicit_records(tree: ast.AST, source: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        value = safe_value(node)
        if not isinstance(value, dict):
            continue
        direct = normalize_explicit_record(value, getattr(node, "lineno", 0), source)
        if direct:
            found.append(direct)
        for key, nested in value.items():
            team = canonical_team(key)
            if not team or not isinstance(nested, dict):
                continue
            combined = dict(nested)
            combined.setdefault("team_id", team)
            record = normalize_explicit_record(combined, getattr(node, "lineno", 0), source)
            if record:
                found.append(record)
    dedup: dict[str, dict[str, Any]] = {}
    for row in found:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        dedup[key] = row
    return list(dedup.values())


def numeric_bot_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        bot = canonical_bot(key)
        if bot and isinstance(raw, (int, float)) and not isinstance(raw, bool):
            result[bot] = float(raw)
    return result


def weight_profiles(tree: ast.AST, source: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        value = safe_value(node)
        if not isinstance(value, dict):
            continue
        for key, nested in value.items():
            team = canonical_team(key)
            weights = numeric_bot_map(nested)
            if team and len(weights) >= 2:
                ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
                found.append({
                    "team_id": team,
                    "weights": dict(sorted(weights.items())),
                    "ranked_bots": [bot for bot, _ in ranked],
                    "line": getattr(node, "lineno", 0),
                    "source": source,
                    "evidence_class": "WEIGHT_PROFILE_NOT_ROLE_PROOF",
                })
        direct_weights = numeric_bot_map(value)
        if len(direct_weights) >= 2:
            parent_team: str | None = None
            for ancestor in ast.walk(tree):
                if ancestor is node:
                    continue
            # Direct bot maps without an explicit Team key are retained as unscoped evidence only.
            found.append({
                "team_id": parent_team,
                "weights": dict(sorted(direct_weights.items())),
                "ranked_bots": [bot for bot, _ in sorted(direct_weights.items(), key=lambda item: (-item[1], item[0]))],
                "line": getattr(node, "lineno", 0),
                "source": source,
                "evidence_class": "UNSCOPED_WEIGHT_PROFILE",
            })
    dedup: dict[str, dict[str, Any]] = {}
    for row in found:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        dedup[key] = row
    return list(dedup.values())


def bot_team_symbol_references(tree: ast.AST, source: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        names: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
            elif isinstance(child, ast.Attribute):
                dotted = dotted_name(child)
                if dotted:
                    names.add(dotted)
            elif isinstance(child, ast.Constant) and isinstance(child.value, str) and len(child.value) <= 80:
                if not SENSITIVE.search(child.value):
                    names.add(child.value)
        teams = sorted({team for value in names if (team := canonical_team(value))})
        bots = sorted({bot for value in names if (bot := canonical_bot(value))})
        if teams and bots and isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return, ast.Call)):
            found.append({
                "line": getattr(node, "lineno", 0),
                "node_type": type(node).__name__,
                "teams": teams,
                "bots": bots,
                "source": source,
            })
    dedup: dict[str, dict[str, Any]] = {}
    for row in found:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        dedup[key] = row
    return list(dedup.values())[:300]


def analyze_source(path: Path, expected_sha: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "expected_sha256": expected_sha,
        "sha256": None,
        "sha_match": False,
        "line_count": None,
        "parse_error": None,
        "explicit_records": [],
        "weight_profiles": [],
        "symbol_references": [],
        "raw_source_included": False,
    }
    if not path.is_file():
        result["parse_error"] = "FILE_MISSING"
        return result
    result["sha256"] = sha256(path)
    result["sha_match"] = result["sha256"] == expected_sha
    text = path.read_text(encoding="utf-8", errors="replace")
    result["line_count"] = len(text.splitlines())
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        result["parse_error"] = f"SYNTAX_ERROR:{exc.lineno}:{exc.msg}"
        return result
    result["explicit_records"] = explicit_records(tree, str(path))
    result["weight_profiles"] = weight_profiles(tree, str(path))
    result["symbol_references"] = bot_team_symbol_references(tree, str(path))
    return result


def merge_team_evidence(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for team in TEAMS:
        explicit: list[dict[str, Any]] = []
        weights: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        for source in sources:
            explicit.extend(row for row in source.get("explicit_records", []) if row.get("team_id") == team)
            weights.extend(row for row in source.get("weight_profiles", []) if row.get("team_id") == team)
            references.extend(row for row in source.get("symbol_references", []) if team in row.get("teams", []))
        complete = [
            row for row in explicit
            if row.get("main_bot") and row.get("support_bot") and len(row.get("watchers", [])) >= 2
        ]
        if len(complete) == 1:
            state = "EXPLICIT_ASSIGNMENT_RECOVERED"
            canonical_candidate = complete[0]
            action = "hold"
        elif len(complete) > 1:
            state = "CONFLICTING_EXPLICIT_ASSIGNMENTS"
            canonical_candidate = None
            action = "hold"
        elif explicit:
            state = "PARTIAL_EXPLICIT_ASSIGNMENT"
            canonical_candidate = None
            action = "hold"
        elif weights:
            state = "WEIGHT_PROFILE_ONLY_NOT_ROLE_PROOF"
            canonical_candidate = None
            action = "hold"
        elif references:
            state = "SYMBOL_REFERENCE_ONLY"
            canonical_candidate = None
            action = "hold"
        else:
            state = "NO_ASSIGNMENT_EVIDENCE"
            canonical_candidate = None
            action = "hold"
        result[team] = {
            "state": state,
            "canonical_assignment_candidate": canonical_candidate,
            "explicit_records": explicit,
            "weight_profiles": weights,
            "symbol_references": references,
            "action": action,
        }
    return result


def markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Q4R3 R0.3 Team Assignment Recovery — Latest",
        "",
        f"- State: `{payload['state']}`",
        f"- Verdict: `{payload['verdict']}`",
        f"- Source SHA parity: `{payload['source_sha_parity_count']}/2`",
        f"- Complete explicit assignments: `{payload['complete_explicit_assignment_count']}/4`",
        "- Canonical spelling: **Zico**, **Lico**",
        "",
        "## Team evidence",
        "",
        "| Team | State | Explicit | Weight profiles | References |",
        "|---|---|---:|---:|---:|",
    ]
    for team in TEAMS:
        row = payload["teams"][team]
        lines.append(
            f"| {team} | `{row['state']}` | {len(row['explicit_records'])} | "
            f"{len(row['weight_profiles'])} | {len(row['symbol_references'])} |"
        )
    lines.extend([
        "",
        "## Rule",
        "",
        "- A numeric weight profile is evidence, not proof of Main/Support/Watcher/Helper assignment.",
        "- No Team package is created until exactly one complete explicit assignment is proven per Team or a new canonical contract is approved.",
        "- Runtime, services, Strategy, Method, Skill, Team and Advisor behavior remain unchanged.",
    ])
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    sources = [
        analyze_source(args.ranking_source, args.ranking_sha256),
        analyze_source(args.lane_source, args.lane_sha256),
    ]
    blockers: list[str] = []
    for source in sources:
        if not source["exists"]:
            blockers.append(f"SOURCE_MISSING:{source['path']}")
        if source["exists"] and not source["sha_match"]:
            blockers.append(f"SOURCE_SHA_CHANGED:{source['path']}")
        if source.get("parse_error"):
            blockers.append(f"SOURCE_PARSE_ERROR:{source['path']}:{source['parse_error']}")
    teams = merge_team_evidence(sources)
    complete_count = sum(row["state"] == "EXPLICIT_ASSIGNMENT_RECOVERED" for row in teams.values())
    source_parity = sum(bool(source["sha_match"]) for source in sources)
    if blockers:
        state = "HOLD"
        verdict = "R03_TEAM_ASSIGNMENT_SOURCE_INTEGRITY_FAILED"
    elif complete_count == 4:
        state = "PASS"
        verdict = "R03_TEAM_ASSIGNMENTS_EXPLICITLY_RECOVERED"
    else:
        state = "HOLD"
        verdict = "R03_TEAM_ASSIGNMENT_EVIDENCE_READY_CONTRACT_REQUIRED"
    payload = {
        "schema": "q4r3_team_advisor_r03_team_assignment_recovery_v1",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "source_sha_parity_count": source_parity,
        "complete_explicit_assignment_count": complete_count,
        "sources": sources,
        "teams": teams,
        "blockers": blockers,
        "next_route": (
            "CREATE_CANONICAL_TEAM_PACKAGES_FROM_RECOVERED_ASSIGNMENTS"
            if complete_count == 4 and not blockers
            else "BUILD_CANONICAL_TEAM_CONTRACT_FROM_RECOVERED_EVIDENCE_WITHOUT_GUESSING"
        ),
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "order_authority": "blocked",
            "execution_authority": "none",
        },
        "action": "hold",
    }
    atomic_json(args.output_json, payload)
    atomic_text(args.output_md, markdown(payload))
    print(json.dumps({
        "state": state,
        "verdict": verdict,
        "source_sha_parity_count": source_parity,
        "complete_explicit_assignment_count": complete_count,
        "blocker_count": len(blockers),
    }, ensure_ascii=False, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--ranking-source", type=Path, required=True)
    value.add_argument("--ranking-sha256", required=True)
    value.add_argument("--lane-source", type=Path, required=True)
    value.add_argument("--lane-sha256", required=True)
    value.add_argument("--output-json", type=Path, required=True)
    value.add_argument("--output-md", type=Path, required=True)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
