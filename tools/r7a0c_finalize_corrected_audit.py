#!/usr/bin/env python3
import argparse, json
from pathlib import Path

AXES = ["strategy25", "trade_lifecycle", "exit_policy4", "skill18", "teambots_and_advisors", "data_math_cost_replay", "display_ledger_observability"]
BAD_PARITY = ["MISMATCH", "UNTRACKED_DEPLOYED_SOURCE", "MISSING_DEPLOYED_SOURCE", "AMBIGUOUS_REPO_BASENAME"]


def equal(values):
    if len(values) < 2:
        return True
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return max(float(v) for v in values) - min(float(v) for v in values) <= 1e-12
    return all(v == values[0] for v in values[1:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    axis = data.get("axes", {}).get("display_ledger_observability", {})
    surfaces = axis.get("surfaces", {})
    for surface in surfaces.values():
        writers = surface.get("writers") or {}
        legacy = surface.pop("writer_count", None)
        configured = surface.get("configured_writer_count")
        active = surface.get("active_writer_count")
        if configured is None and isinstance(writers, dict) and writers:
            configured = len(writers)
        if legacy is not None:
            try:
                legacy_num = int(float(legacy))
            except (TypeError, ValueError):
                legacy_num = legacy
            if isinstance(writers, dict) and writers and legacy_num == len(writers):
                configured = configured if configured is not None else legacy_num
            elif active is None:
                active = legacy_num
        surface["configured_writer_count"] = configured
        surface["active_writer_count"] = active
        surface["legacy_writer_count"] = legacy

    fields = ["epoch", "closed", "pnl_r", "recent_rows", "winrate_pct", "ev_r", "configured_writer_count", "active_writer_count", "runtime_active", "formal_ledger_bound", "order", "exec"]
    mismatches = []
    for field in fields:
        values = {name: row.get(field) for name, row in surfaces.items() if row.get(field) is not None}
        if not equal(list(values.values())):
            mismatches.append({"field": field, "values": values})
    blockers = [item for item in axis.get("blockers", []) if not item.startswith("SURFACE_PARITY_MISMATCHES")]
    if mismatches:
        blockers.append(f"SURFACE_PARITY_MISMATCHES_{len(mismatches)}")
    writer_mismatch = axis.get("writer_mismatches", {})
    display_owners = axis.get("active_display_authorities", [])
    ledger_owners = axis.get("active_ledger_authorities", [])
    if mismatches or writer_mismatch or len(display_owners) > 1 or len(ledger_owners) > 1:
        grade = "D"
    elif axis.get("alimi_http_status") != 200 or axis.get("legacy_view_markers"):
        grade = "B"
    else:
        grade = "A"
    axis.update({"surfaces": surfaces, "surface_mismatches": mismatches, "blockers": blockers, "grade": grade, "writer_count_semantics": "CONFIGURED_AND_ACTIVE_SPLIT"})

    old = data.get("runtime_readiness", {}).get("critical_gaps", [])
    gaps = [gap for gap in old if not any(str(gap).startswith(name + ":") for name in AXES) and gap != "active_systemd_source_parity_not_proven"]
    for name in AXES:
        item = data.get("axes", {}).get(name, {})
        if item.get("grade") != "A":
            gaps.append(f"{name}:grade={item.get('grade')}:{'|'.join(item.get('blockers', [])[:4])}")
    counts = data.get("active_unit_source_parity", {}).get("counts", {})
    if any(counts.get(key, 0) for key in BAD_PARITY):
        gaps.append("active_systemd_source_parity_not_proven")
    readiness = "PASS" if not gaps and all(data["axes"][name].get("grade") == "A" for name in AXES) else "HOLD"
    data["runtime_readiness"] = {"state": readiness, "critical_gap_count": len(gaps), "critical_gaps": gaps}
    data["schema"] = "zos_r7a0c_corrected_runtime_parity_audit_status_v1"
    data["official_stage"] = "R7.A0C"
    data.setdefault("audit_correction", {}).update({"state": "PASS", "writer_semantics_split": True, "readiness_recomputed": True, "mutation_count": 0})
    data["next_stage"] = "R7.A1_CANONICAL_GAP_AND_AUTHORITY_PLAN"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = ["# R7.A0C Corrected Audit", "", f"- Runtime readiness: **{readiness}**", "", "| Axis | Grade | Blockers |", "|---|---:|---|"]
    for name in AXES:
        item = data.get("axes", {}).get(name, {})
        lines.append(f"| {name} | **{item.get('grade')}** | {'; '.join(item.get('blockers', [])) or 'none'} |")
    lines += ["", "## Critical gaps", ""] + [f"- {gap}" for gap in gaps]
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("R7A0C_CORRECTED_AUDIT_COMPLETE")
    print(f"AUDIT_EXECUTION_STATE={data.get('audit_execution', {}).get('state')}")
    print("AUDIT_CORRECTION_STATE=PASS")
    print(f"RUNTIME_READINESS_STATE={readiness}")
    print("MUTATION_COUNT=0")
    for name in AXES:
        item = data.get("axes", {}).get(name, {})
        print(f"AXIS_{name.upper()}_GRADE={item.get('grade')}")
        print(f"AXIS_{name.upper()}_BLOCKERS={len(item.get('blockers', []))}")
    print(f"SURFACE_PARITY_MISMATCHES={len(mismatches)}")
    print(f"CRITICAL_GAP_COUNT={len(gaps)}")
    print("NEXT_STAGE=R7.A1_CANONICAL_GAP_AND_AUTHORITY_PLAN")
    print(f"EVIDENCE_JSON={args.output}")
    print(f"EVIDENCE_REPORT={args.report}")


if __name__ == "__main__":
    main()
