#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOTS = ("LBot", "MBot", "OBot", "SBot")
CORE_PATHS = {
    "LBot": "/home/z/z/backend/bots/lbot.py",
    "MBot": "/home/z/z/backend/bots/mbot.py",
    "OBot": "/home/z/z/backend/bots/obot.py",
    "SBot": "/home/z/z/backend/bots/sbot.py",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def boundary(bot: str, path: str) -> tuple[str, str]:
    name = Path(path).name.lower()
    if path == CORE_PATHS[bot]:
        return "CORE_SEMANTIC_OWNER", "one semantic owner per Bot"
    mapping = {
        "lbot_models.py": ("CONTRACT_MODEL", "typed data model"),
        "lbot_strategy_base.py": ("STRATEGY_BRIDGE", "strategy bridge outside Bot core"),
        "lbot_builtin_strategies.py": ("STRATEGY_BRIDGE", "strategy bridge outside Bot core"),
        "lbot_registry.py": ("REGISTRY_BRIDGE", "registry outside Bot core"),
        "lbot_registry_defaults.py": ("REGISTRY_BRIDGE", "registry defaults outside Bot core"),
        "lbot_core.py": ("LEGACY_ORCHESTRATOR", "mixed legacy orchestration"),
        "lbot_runtime.py": ("PERSISTENCE_ADAPTER", "state and journal adapter"),
        "lbot_bindings.py": ("BINDING_ADAPTER", "binding adapter outside Bot core"),
        "lbot_api.py": ("ROUTER_ADAPTER", "transport adapter outside Bot core"),
        "zel_alimi_teambot_ranking_p6_4.py": ("TEAM_RANKING", "Team ranking is not MBot core"),
    }
    return mapping.get(name, ("UNRESOLVED", "manual classification required"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = read_json(args.inventory)
    source_components = source.get("components", {})
    blockers: list[str] = []
    components: dict[str, Any] = {}
    candidate_count = 0
    unresolved_count = 0

    for bot in BOTS:
        result_rows = []
        for row in source_components.get(bot, {}).get("candidates", []):
            item = dict(row)
            item["boundary"], item["boundary_reason"] = boundary(bot, str(row.get("path", "")))
            result_rows.append(item)
            candidate_count += 1
            unresolved_count += int(item["boundary"] == "UNRESOLVED")
        core_rows = [item for item in result_rows if item["boundary"] == "CORE_SEMANTIC_OWNER"]
        if len(core_rows) != 1:
            blockers.append(f"{bot}:CORE_OWNER_COUNT={len(core_rows)}")
        components[bot] = {
            "core_owner": core_rows[0]["path"] if len(core_rows) == 1 else None,
            "core_owner_count": len(core_rows),
            "candidate_count": len(result_rows),
            "candidates": result_rows,
        }

    if source.get("state") != "PASS" or source.get("blockers") != []:
        blockers.append("R06_INPUT_NOT_CLEAN_PASS")
    if source.get("summary", {}).get("candidate_count") != candidate_count:
        blockers.append("CANDIDATE_COUNT_PARITY_FAILED")
    if unresolved_count:
        blockers.append(f"UNRESOLVED_COUNT={unresolved_count}")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_team_advisor_r061_bot_boundary_adjudication_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "verdict": "R061_BOT_BOUNDARIES_LOCKED" if state == "PASS" else "R061_BOT_BOUNDARIES_UNRESOLVED",
        "components": components,
        "summary": {
            "component_count": 4,
            "candidate_count": candidate_count,
            "core_owner_count": sum(value["core_owner_count"] for value in components.values()),
            "unresolved_boundary_count": unresolved_count,
            "next_route": "BUILD_CANONICAL_LBOT_MBOT_OBOT_SBOT_PACKAGES",
        },
        "blockers": blockers,
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write_json(args.output, payload)
    print(json.dumps({
        "state": state,
        "candidate_count": candidate_count,
        "core_owner_count": payload["summary"]["core_owner_count"],
        "unresolved_boundary_count": unresolved_count,
        "blocker_count": len(blockers),
    }, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
