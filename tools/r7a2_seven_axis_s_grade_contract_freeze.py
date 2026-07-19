#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh", ".md", ".txt", ".rst"}
SCAN_PREFIXES = ("backend/", "tools/", "services/", "systemd/", "config/", "scripts/", "tests/")


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths: list[str]) -> dict[str, str | None]:
    return {path: sha256(Path(path)) for path in paths}


def resolve_commit(root: Path, target_sha: str) -> str:
    cp = run(["git", "-C", str(root), "rev-parse", f"{target_sha}^{{commit}}"])
    if cp.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED")
    return cp.stdout.strip()


def git_inventory(root: Path, commit: str) -> dict[str, str]:
    cp = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "--long", commit],
        capture_output=True,
        timeout=120,
    )
    if cp.returncode != 0:
        raise RuntimeError("GIT_TREE_LIST_FAILED")
    paths: list[str] = []
    blobs: list[str] = []
    for raw in cp.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, raw_path = raw.split(b"\t", 1)
            fields = meta.decode(errors="replace").split()
            blob, size = fields[2], int(fields[3])
            path = raw_path.decode(errors="replace")
        except Exception:
            continue
        if not path.startswith(SCAN_PREFIXES):
            continue
        if Path(path).suffix.lower() not in TEXT_SUFFIXES or size > 2_000_000:
            continue
        paths.append(path)
        blobs.append(blob)
    batch = "".join(f"{blob}\n" for blob in blobs).encode()
    cat = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=batch,
        capture_output=True,
        timeout=180,
    )
    if cat.returncode != 0:
        raise RuntimeError("GIT_CAT_FILE_BATCH_FAILED")
    out: dict[str, str] = {}
    buf, cursor = cat.stdout, 0
    for path in paths:
        end = buf.find(b"\n", cursor)
        if end < 0:
            raise RuntimeError("GIT_CAT_FILE_TRUNCATED")
        header = buf[cursor:end].decode(errors="replace").split()
        cursor = end + 1
        size = int(header[2])
        raw = buf[cursor:cursor + size]
        cursor += size + 1
        out[path] = raw.decode("utf-8", errors="ignore")
    return out


def relevant_systemd() -> dict[str, Any]:
    units = run(["systemctl", "list-units", "--all", "--no-legend", "--no-pager"], timeout=90)
    names = []
    rx = re.compile(r"(zel|zops|q4r3|exact25|alimi|telegram|shadow)", re.I)
    for line in units.stdout.splitlines():
        parts = line.split()
        if parts and rx.search(parts[0]):
            names.append(parts[0])
    records = []
    for offset in range(0, len(names), 40):
        batch = names[offset:offset + 40]
        cmd = ["systemctl", "show", *batch]
        for prop in ("Id", "ActiveState", "SubState", "FragmentPath", "ExecStart", "MainPID"):
            cmd += ["-p", prop]
        cp = run(cmd, timeout=90)
        cur: dict[str, str] = {}
        for line in cp.stdout.splitlines() + [""]:
            if not line.strip():
                if cur.get("Id"):
                    records.append(cur)
                cur = {}
            elif "=" in line:
                key, value = line.split("=", 1)
                cur[key] = value
    return {"count": len(records), "records": records}


def contract_valid(contract: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if contract.get("official_stage") != "R7.A2":
        blockers.append("OFFICIAL_STAGE_INVALID")
    if contract.get("read_only") is not True or contract.get("runtime_mutation_allowed") is not False:
        blockers.append("READ_ONLY_BOUNDARY_INVALID")
    axes = contract.get("axes")
    if not isinstance(axes, list) or len(axes) != 7:
        blockers.append("AXIS_COUNT_NOT_7")
        return False, blockers
    required = set(contract.get("required_axis_fields") or [])
    ids = []
    for axis in axes:
        if not isinstance(axis, dict):
            blockers.append("AXIS_NOT_OBJECT")
            continue
        ids.append(str(axis.get("axis_id")))
        missing = sorted(required - set(axis))
        if missing:
            blockers.append(f"AXIS_FIELDS_MISSING:{axis.get('axis_id')}:{','.join(missing)}")
        comps = axis.get("required_components")
        if not isinstance(comps, list) or not comps:
            blockers.append(f"AXIS_COMPONENTS_EMPTY:{axis.get('axis_id')}")
    if len(set(ids)) != 7:
        blockers.append("AXIS_IDS_NOT_UNIQUE")
    funnel = contract.get("material_funnel") or {}
    expected = {
        "immutable_originals": 25,
        "first_survivors_min": 10,
        "first_survivors_max": 15,
        "s_material_min": 6,
        "s_material_max": 10,
        "standalone_s_min": 4,
        "standalone_s_max": 7,
        "s_ensemble_min": 3,
        "s_ensemble_max": 5,
        "controls_min": 2,
        "controls_max": 3,
        "shadow_lanes_min": 9,
        "shadow_lanes_max": 15,
    }
    if any(funnel.get(key) != value for key, value in expected.items()):
        blockers.append("MATERIAL_FUNNEL_MISMATCH")
    return not blockers, blockers


def prior_gate(root: Path, contract: dict[str, Any]) -> tuple[bool, dict[str, Any], list[str]]:
    receipts = contract.get("prior_receipts") or {}
    c6b = load_json(root / str(receipts.get("c6b", "")))
    c6c = load_json(root / str(receipts.get("c6c", "")))
    blockers = []
    if not (
        c6b.get("state") == "PASS"
        and int(c6b.get("blocker_count", -1)) == 0
        and c6b.get("next_stage") == "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE"
    ):
        blockers.append("C6B_PASS_RECEIPT_INVALID")
    if not (
        c6c.get("result") == "PASS_R7A1A6C6C_CLOSED"
        and c6c.get("telegram_contract_pass") is True
        and c6c.get("next_stage") == "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE"
    ):
        blockers.append("C6C_PASS_RECEIPT_INVALID")
    return not blockers, {"c6b": c6b, "c6c": c6c}, blockers


def find_refs(patterns: list[str], inventory: dict[str, str], limit: int = 30) -> list[str]:
    regexes = []
    for pattern in patterns:
        try:
            regexes.append(re.compile(pattern, re.I))
        except re.error:
            regexes.append(re.compile(re.escape(pattern), re.I))
    hits = []
    for path, text in inventory.items():
        if any(rx.search(path) or rx.search(text) for rx in regexes):
            hits.append(path)
    return sorted(set(hits))[:limit]


def freeze_axes(contract: dict[str, Any], inventory: dict[str, str], systemd: dict[str, Any]) -> list[dict[str, Any]]:
    active_text = "\n".join(
        f"{row.get('Id', '')} {row.get('ExecStart', '')} {row.get('FragmentPath', '')}"
        for row in systemd.get("records", [])
        if row.get("ActiveState") == "active"
    )
    rows = []
    for axis in contract["axes"]:
        components = []
        gap_count = 0
        runtime_bound_count = 0
        for component in axis["required_components"]:
            refs = find_refs([str(item) for item in component["patterns"]], inventory)
            runtime_bound = any(re.search(pattern, active_text, re.I) for pattern in component["patterns"])
            if runtime_bound:
                runtime_bound_count += 1
            if not refs:
                gap_count += 1
            components.append({
                "component_id": component["id"],
                "git_reference_count": len(refs),
                "git_references": refs,
                "runtime_bound_candidate": runtime_bound,
                "proof_state": "STATIC_PRESENT" if refs else "GAP_NO_GIT_REFERENCE",
            })
        rows.append({
            "axis_id": axis["axis_id"],
            "next_stage": axis["next_stage"],
            "contract_frozen": True,
            "component_count": len(components),
            "static_gap_count": gap_count,
            "runtime_bound_candidate_count": runtime_bound_count,
            "s_grade_promoted": False,
            "promotion_note": "A2 freezes the contract only; A3-A9 must prove runtime, replay, persistence and rollback.",
            "components": components,
            "authority_contract": axis["authority_contract"],
            "persistence_contract": axis["persistence_contract"],
            "receipt_contract": axis["receipt_contract"],
            "rollback_contract": axis["rollback_contract"],
            "activation_gate": axis["activation_gate"],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    status_path = root / str(contract.get(
        "status_path",
        "runtime/r7a2_seven_axis_s_grade_contract_freeze/status_latest.json",
    ))
    protected_before = snapshot([str(item) for item in contract.get("protected_paths", [])])
    blockers: list[str] = []
    valid, contract_blockers = contract_valid(contract)
    blockers += contract_blockers
    prior_ok, prior, prior_blockers = prior_gate(root, contract)
    blockers += prior_blockers
    commit = ""
    inventory: dict[str, str] = {}
    systemd: dict[str, Any] = {"count": 0, "records": []}
    try:
        commit = resolve_commit(root, args.target_sha)
        inventory = git_inventory(root, commit)
        systemd = relevant_systemd()
    except Exception as exc:
        blockers.append(f"INVENTORY_FAILED:{type(exc).__name__}:{exc}")
    axes = freeze_axes(contract, inventory, systemd) if inventory else []
    protected_after = snapshot([str(item) for item in contract.get("protected_paths", [])])
    changed = [path for path in protected_before if protected_before.get(path) != protected_after.get(path)]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED:" + ",".join(changed))
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "r7a2_seven_axis_s_grade_contract_freeze_status_v1",
        "official_stage": "R7.A2",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "read_only": True,
        "target_commit": commit,
        "prior_gate_valid": prior_ok,
        "contract_valid": valid,
        "axis_count": len(axes),
        "axis_contracts_frozen": sum(1 for axis in axes if axis.get("contract_frozen")),
        "s_grade_promoted_axis_count": 0,
        "axes": axes,
        "material_funnel": contract.get("material_funnel"),
        "systemd_relevant_unit_count": systemd.get("count", 0),
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "service_mutation_count": 0,
        "telegram_command_send_count": 0,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "next_stage": "R7.A3_STRATEGY25_S_GRADE" if state == "PASS" else "R7.A2_DIAGNOSE",
    }
    atomic_json(status_path, payload)
    print("R7A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE_COMPLETE")
    for key, value in [
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_GATE_VALID", str(prior_ok).lower()),
        ("CONTRACT_VALID", str(valid).lower()),
        ("AXIS_COUNT", len(axes)),
        ("AXIS_CONTRACTS_FROZEN", payload["axis_contracts_frozen"]),
        ("S_GRADE_PROMOTED_AXIS_COUNT", 0),
        ("PROTECTED_CHANGE_COUNT", len(changed)),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", payload["next_stage"]),
        ("EVIDENCE_JSON", str(status_path)),
        ("RC", 0 if state == "PASS" else 2),
    ]:
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
