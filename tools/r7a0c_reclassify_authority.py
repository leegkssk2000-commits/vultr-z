#!/usr/bin/env python3
import argparse, json, re, shlex
from collections import Counter, defaultdict
from pathlib import Path

ROLES = {
    "candidate": ["candidate", "signal_generator", "emitter", "producer"],
    "admission": ["admission", "valve", "admit"],
    "open": ["open_bridge", "open_engine", "position_open"],
    "manage": ["position_manager", "manage", "skill_router", "exit_modifier"],
    "close": ["close_engine", "close_bridge", "touch_close"],
    "ledger_writer": ["ledger_writer", "measurement_writer", "persistent_single_event_writer"],
    "display_writer": ["display_adapter", "renderer", "binder", "mirror", "projector", "telegram_pos_adapter"],
}
NON_AUTHORITY = ["observer", "watchdog", "audit", "probe", "readonly", "read_only", "scoreboard", "monitor"]
START_EXCLUDE = ["paper", "live", "order", "telegram", "alimi", "display", "view", "observer", "watchdog", "audit", "probe", "writer", "binder", "mirror", "projector"]
BAD_PARITY = {"MISMATCH", "UNTRACKED_DEPLOYED_SOURCE", "MISSING_DEPLOYED_SOURCE", "AMBIGUOUS_REPO_BASENAME"}


def app_name(exec_start):
    match = re.search(r"argv\[\]=(.+?)(?:\s+;|\s*})", exec_start)
    if match:
        try:
            tokens = shlex.split(match.group(1))
        except ValueError:
            tokens = match.group(1).split()
        for token in tokens:
            if token.startswith("/") and Path(token).suffix.lower() in {".py", ".sh"}:
                return Path(token).name
    direct = re.search(r"(?:^|[\s{])path=([^ ;}\]]+)", exec_start)
    return Path(direct.group(1)).name if direct and Path(direct.group(1)).suffix.lower() in {".py", ".sh"} else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    records = data.get("systemd", {}).get("records", [])
    role_map = defaultdict(list)
    starts = []
    for row in records:
        if not row.get("is_active"):
            continue
        ident = (str(row.get("Id", "")) + " " + app_name(str(row.get("ExecStart", "")))).lower().replace("-", "_")
        row["corrected_authority_identity"] = ident
        if any(marker in ident for marker in NON_AUTHORITY):
            continue
        for role, markers in ROLES.items():
            if any(marker in ident for marker in markers):
                role_map[role].append(str(row.get("Id")))
        if "shadow" in ident and ("q4r3" in ident or "exact25" in ident) and not any(marker in ident for marker in START_EXCLUDE):
            starts.append(str(row.get("Id")))

    active = {role: sorted(set(role_map.get(role, []))) for role in ROLES}
    duplicates = {role: units for role, units in active.items() if len(units) > 1}
    parity = data.get("active_unit_source_parity", {})
    rows = parity.get("rows", [])
    parity["counts"] = dict(Counter(str(row.get("parity")) for row in rows))
    source_gaps = [row for row in rows if row.get("parity") in BAD_PARITY]

    axis = data.get("axes", {}).get("trade_lifecycle", {})
    blockers = [item for item in axis.get("blockers", []) if not item.startswith(("MULTIPLE_ACTIVE_AUTHORITIES", "SHADOW_START_AUTHORITY_COUNT", "ACTIVE_UNIT_SOURCE_PARITY_GAPS"))]
    if duplicates:
        blockers.append("MULTIPLE_ACTIVE_AUTHORITIES:" + ",".join(sorted(duplicates)))
    if len(set(starts)) != 1:
        blockers.append(f"SHADOW_START_AUTHORITY_COUNT_{len(set(starts))}")
    if source_gaps:
        blockers.append(f"ACTIVE_UNIT_SOURCE_PARITY_GAPS_{len(source_gaps)}")
    axis.update({
        "blockers": blockers,
        "active_authority_by_role": active,
        "duplicate_active_authority_roles": duplicates,
        "shadow_start_candidates": sorted(set(starts)),
        "active_source_parity_gaps": source_gaps,
        "grade": "D" if duplicates or len(set(starts)) != 1 or any(v.startswith("MISSING_LIFECYCLE") for v in blockers) else ("B" if source_gaps else "A"),
    })
    data["systemd"]["active_authority_by_role"] = active
    data["systemd"]["start_candidates"] = sorted(set(starts))
    data["official_stage"] = "R7.A0C2"
    data.setdefault("audit_correction", {})["authority_reclassification"] = "PASS"
    data["audit_correction"]["mutation_count"] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("R7A0C2_AUTHORITY_RECLASSIFICATION_COMPLETE")
    print("MUTATION_COUNT=0")
    print(f"TRADE_LIFECYCLE_GRADE={axis.get('grade')}")
    print(f"SHADOW_START_CANDIDATES={len(set(starts))}")
    print(f"DUPLICATE_ACTIVE_ROLES={len(duplicates)}")
    print(f"ACTIVE_SOURCE_PARITY_GAPS={len(source_gaps)}")
    print(f"EVIDENCE={args.output}")


if __name__ == "__main__":
    main()
