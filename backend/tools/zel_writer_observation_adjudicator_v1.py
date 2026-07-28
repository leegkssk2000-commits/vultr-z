from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_WRITER_OBSERVATION_ADJUDICATOR_V1"
SCRIPT_RE = re.compile(r"/(?:home/z/z|usr/local/bin|opt/zel)/[A-Za-z0-9_./@\-]+\.(?:py|sh)")
TEMP_RE = re.compile(r"^(.+\.(?:json|jsonl|csv|log|db|sqlite))(?:\.(?:tmp|temp)|[._][A-Za-z0-9_-]{4,})$", re.I)


def canonical_target(path: str) -> str:
    match = TEMP_RE.match(path)
    return match.group(1) if match else path


def authority_id(command: str) -> str:
    scripts = SCRIPT_RE.findall(command)
    if scripts:
        return scripts[-1]
    normalized = " ".join(command.split())
    return normalized[:500]


def unique_authorities(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        command = str(row.get("command") or "")
        identity = authority_id(command)
        current = grouped.setdefault(
            identity,
            {
                "authority_id": identity,
                "pids": [],
                "commands": [],
                "access_modes": [],
                "observed_targets": [],
            },
        )
        if row.get("pid") is not None and row.get("pid") not in current["pids"]:
            current["pids"].append(row.get("pid"))
        if command and command not in current["commands"]:
            current["commands"].append(command)
        if row.get("access_mode") and row.get("access_mode") not in current["access_modes"]:
            current["access_modes"].append(row.get("access_mode"))
        if row.get("target") and row.get("target") not in current["observed_targets"]:
            current["observed_targets"].append(row.get("target"))
    return sorted(grouped.values(), key=lambda row: row["authority_id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    direct: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for observed_path, rows in source.get("direct_fd_writers", {}).items():
        final_path = canonical_target(str(observed_path))
        direct[final_path].extend(rows)

    authority_map: dict[str, list[dict[str, Any]]] = {
        path: unique_authorities(rows) for path, rows in sorted(direct.items())
    }
    true_conflicts = [
        {
            "path": path,
            "authority_count": len(authorities),
            "authorities": authorities,
            "severity": "CRITICAL",
        }
        for path, authorities in authority_map.items()
        if len(authorities) > 1
    ]

    changed_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in source.get("changed_paths", []):
        path = canonical_target(str(row.get("path")))
        exact = authority_map.get(path, [])
        referencer_authorities: dict[str, dict[str, Any]] = {}
        for ref in row.get("referencers", []):
            command = str(ref.get("command") or "")
            identity = authority_id(command)
            current = referencer_authorities.setdefault(
                identity,
                {"authority_id": identity, "kinds": [], "pids": [], "units": [], "commands": []},
            )
            if ref.get("kind") not in current["kinds"]:
                current["kinds"].append(ref.get("kind"))
            if ref.get("pid") is not None and ref.get("pid") not in current["pids"]:
                current["pids"].append(ref.get("pid"))
            if ref.get("unit") and ref.get("unit") not in current["units"]:
                current["units"].append(ref.get("unit"))
            if command and command not in current["commands"]:
                current["commands"].append(command)
        adjudicated = {
            "path": path,
            "before": row.get("before"),
            "after": row.get("after"),
            "exact_direct_authorities": exact,
            "referencer_authorities": sorted(referencer_authorities.values(), key=lambda value: value["authority_id"]),
            "writer_state": "EXACT_SINGLE" if len(exact) == 1 else ("EXACT_CONFLICT" if len(exact) > 1 else "UNRESOLVED_ATOMIC_OR_SHORT_LIVED"),
        }
        changed_rows.append(adjudicated)
        if not exact:
            unresolved.append(
                {
                    "path": path,
                    "referencer_authority_count": len(referencer_authorities),
                    "referencer_authorities": sorted(referencer_authorities),
                }
            )

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "source_version": source.get("version"),
        "observe_sec": source.get("observe_sec"),
        "raw_direct_conflict_count": len(source.get("direct_conflicts", [])),
        "canonical_direct_writer_path_count": len(authority_map),
        "true_independent_conflict_count": len(true_conflicts),
        "true_independent_conflicts": true_conflicts,
        "authority_map": authority_map,
        "changed_paths": changed_rows,
        "unresolved_changed_paths": unresolved,
        "state": "HOLD_TRUE_INDEPENDENT_MULTI_WRITER" if true_conflicts else "PASS_NO_DIRECT_INDEPENDENT_MULTI_WRITER",
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
        "next": "TRACE_UNRESOLVED_CHANGED_PATHS_BY_ATOMIC_RENAME_AND_ACTIVE_SURFACE_OWNER",
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": payload["state"], "true_conflicts": len(true_conflicts), "unresolved": len(unresolved)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
