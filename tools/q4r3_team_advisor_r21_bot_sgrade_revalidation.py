#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOT_SPECS = {
    "LBot": ("trend", "strength", "continuation", "invalidation", "hysteresis", "conflict"),
    "MBot": ("method", "range", "timing", "retest", "conflict", "helper"),
    "OBot": ("breakout", "fake", "momentum", "anomaly", "mfe", "mae", "exhaustion"),
    "SBot": ("hard", "soft", "stop", "drawdown", "exposure", "buffer", "stale", "risk"),
}
BOT_FILES = {
    "LBot": "canonical/bots/lbot.py",
    "MBot": "canonical/bots/mbot.py",
    "OBot": "canonical/bots/obot.py",
    "SBot": "canonical/bots/sbot.py",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def inspect_bot(root: Path, bot: str) -> dict[str, Any]:
    path = root / BOT_FILES[bot]
    source = path.read_text(encoding="utf-8", errors="replace")
    lower = source.lower()
    base = (root / "canonical/bots/base.py").read_text(encoding="utf-8", errors="replace").lower()
    combined = lower + "\n" + base
    hits = sorted(token for token in BOT_SPECS[bot] if token in combined)
    passthrough = "advisory_assessment(" in source
    explicit_logic_lines = sum(
        1 for line in source.splitlines()
        if line.strip().startswith(("if ", "elif ", "for ", "while "))
    )
    readiness = len(hits) == len(BOT_SPECS[bot]) and not passthrough and explicit_logic_lines >= 2
    return {
        "path": BOT_FILES[bot],
        "required_capability_count": len(BOT_SPECS[bot]),
        "capability_hit_count": len(hits),
        "capability_hits": hits,
        "generic_passthrough": passthrough,
        "explicit_logic_lines": explicit_logic_lines,
        "s_grade_ready": readiness,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r10", type=Path, required=True)
    parser.add_argument("--r11", type=Path, required=True)
    parser.add_argument("--r12", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    foundation = {
        "R1.0": load(args.r10),
        "R1.1": load(args.r11),
        "R1.2": load(args.r12),
    }
    expected = {
        "R1.0": "PASS",
        "R1.1": "PASS",
        "R1.2": "PASS",
    }
    for stage, wanted in expected.items():
        if foundation[stage].get("state") != wanted:
            blockers.append(f"{stage}_NOT_PASS")

    contracts = (args.worktree / "canonical/bots/contracts.py").read_text(encoding="utf-8", errors="replace")
    if 'CONTRACT_VERSION = "canonical-bot/1.1.0"' not in contracts:
        blockers.append("BOT_CONTRACT_VERSION_INVALID")
    lineage_fields = (
        "event_id", "parent_event_id", "strategy_id", "method_id", "skill_id",
        "team_id", "team_role", "data_state", "freshness_ms", "latency_ms",
    )
    missing_lineage = [field for field in lineage_fields if field not in contracts]
    if missing_lineage:
        blockers.append("BOT_RESPONSE_LINEAGE_INCOMPLETE")

    bots = {bot: inspect_bot(args.worktree, bot) for bot in BOT_SPECS}
    thin = [bot for bot, row in bots.items() if row["generic_passthrough"]]
    ready = [bot for bot, row in bots.items() if row["s_grade_ready"]]
    gaps = {
        bot: sorted(set(BOT_SPECS[bot]) - set(row["capability_hits"]))
        for bot, row in bots.items()
    }

    architecture_ready = not blockers and len(missing_lineage) == 0
    data_ready = False
    state = "PASS" if architecture_ready and len(ready) == 4 else "HOLD"
    verdict = "R21_BOT_SGRADE_REVALIDATION_PASS" if state == "PASS" else "R21_BOT_SGRADE_UPDATE_REQUIRED"
    payload = {
        "schema": "q4r3_team_advisor_r21_bot_sgrade_revalidation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R2.1",
        "state": state,
        "verdict": verdict,
        "blockers": blockers,
        "report": {
            "foundation_pass_count": sum(1 for row in foundation.values() if row.get("state") == "PASS"),
            "bot_count": len(bots),
            "s_grade_ready_count": len(ready),
            "thin_wrapper_count": len(thin),
            "thin_wrappers": thin,
            "bots": bots,
            "capability_gaps": gaps,
            "performance_attribution_architecture_ready": architecture_ready,
            "performance_outcome_data_ready": data_ready,
            "legacy_r11_row_count": foundation["R1.1"].get("row_count", foundation["R1.1"].get("report", {}).get("row_count", 0)),
            "legacy_full_lineage_count": foundation["R1.1"].get("lineage_count", 0),
            "legacy_realized_r_count": foundation["R1.1"].get("realized_r_count", 0),
            "new_integrated_epoch_required": True,
            "runtime_binding": False,
            "next_route": "R2.2_BUILD_SGRADE_LBOT_MBOT_OBOT_SBOT" if state == "HOLD" else "R3.1_REVALIDATE_TEAM_ENGINE",
        },
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write(args.output, payload)
    print(json.dumps({
        "state": state,
        "foundation_pass_count": payload["report"]["foundation_pass_count"],
        "bot_count": len(bots),
        "s_grade_ready_count": len(ready),
        "thin_wrapper_count": len(thin),
        "blocker_count": len(blockers),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
