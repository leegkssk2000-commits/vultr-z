#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
RELEVANT_UNIT_RE = re.compile(r"(?:^|[-_.])(zel|zos|z-os|alimi|zbot|zico|zlice|lico)(?:[-_.]|$)", re.I)
SCRIPT_PATH_RE = re.compile(r"(/[A-Za-z0-9_+.,/@%:=~-]+(?:/[A-Za-z0-9_+.,@%:=~-]+)*\.(?:py|sh|js|mjs))")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def file_sha(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


def decode_env_json(name: str) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        raise ValueError(f"missing {name}")
    return json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))


def run(args: list[str], *, binary: bool = False) -> tuple[int, str | bytes]:
    try:
        p = subprocess.run(args, text=not binary, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=30)
        return p.returncode, p.stdout
    except Exception:
        return 99, b"" if binary else ""


def git_value(*args: str) -> str | None:
    rc, out = run(["git", "-C", str(ROOT), *args])
    assert isinstance(out, str)
    return out.strip() if rc == 0 and out.strip() else None


def git_master_ref() -> str | None:
    for ref in ("origin/master", "master"):
        rc, _ = run(["git", "-C", str(ROOT), "rev-parse", "--verify", ref])
        if rc == 0:
            return ref
    return None


def git_blob_sha256(ref: str | None, rel: str) -> str | None:
    if not ref or rel.startswith("external:"):
        return None
    rc, out = run(["git", "-C", str(ROOT), "show", f"{ref}:{rel}"], binary=True)
    if rc != 0 or not isinstance(out, bytes):
        return None
    return sha256_bytes(out)


def resolve_pin_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return Path(source_path[len("external:"):])
    return ROOT / source_path


def module_bundle_rows(pin: dict[str, Any], master_ref: str | None) -> tuple[list[dict[str, Any]], int, int, int]:
    rows: list[dict[str, Any]] = []
    missing_total = 0
    mismatch_total = 0
    drift_file_total = 0
    for module in pin.get("modules", []):
        module_id = str(module.get("module_id") or "")
        source_paths = [str(x) for x in module.get("source_paths", [])]
        file_rows: list[dict[str, Any]] = []
        missing: list[str] = []
        runtime_payload: list[dict[str, str]] = []
        master_payload: list[dict[str, str]] = []
        drift_paths: list[str] = []
        for source_path in sorted(source_paths):
            path = resolve_pin_path(source_path)
            digest = file_sha(path)
            exists = digest is not None
            if not exists:
                missing.append(source_path)
            else:
                runtime_payload.append({"path": source_path, "sha256": digest})
            master_digest = None if source_path.startswith("external:") else git_blob_sha256(master_ref, source_path)
            if master_digest is not None:
                master_payload.append({"path": source_path, "sha256": master_digest})
            if master_digest is not None and digest != master_digest:
                drift_paths.append(source_path)
            file_rows.append({
                "source_path": source_path,
                "exists": exists,
                "runtime_sha256": digest,
                "master_sha256": master_digest,
                "runtime_matches_master": (digest == master_digest) if master_digest is not None else None,
            })
        computed = stable_sha(runtime_payload) if len(runtime_payload) == len(source_paths) and source_paths else None
        internal_paths = [p for p in source_paths if not p.startswith("external:")]
        master_computed = stable_sha(master_payload) if internal_paths and len(master_payload) == len(internal_paths) and len(internal_paths) == len(source_paths) else None
        # For external-only/mixed bundles, the committed source-pin remains the authority; master bundle comparison is intentionally unavailable.
        expected = str(module.get("source_bundle_sha256") or "") or None
        match = bool(expected and computed and expected == computed and not missing)
        expected_matches_master = bool(expected and master_computed and expected == master_computed) if master_computed else None
        missing_total += len(missing)
        drift_file_total += len(drift_paths)
        if not match:
            mismatch_total += 1
        if match:
            diagnosis = "MATCH_PIN"
        elif missing and all((x.get("master_sha256") is not None) for x in file_rows if x["source_path"] in missing):
            diagnosis = "RUNTIME_MISSING_FILE_PRESENT_ON_MASTER"
        elif drift_paths and expected_matches_master:
            diagnosis = "RUNTIME_SOURCE_DRIFT_FROM_PINNED_MASTER"
        elif missing:
            diagnosis = "RUNTIME_SOURCE_MISSING"
        elif drift_paths:
            diagnosis = "RUNTIME_SOURCE_DRIFT_OR_PIN_STALE"
        else:
            diagnosis = "PIN_MISMATCH_UNCLASSIFIED"
        rows.append({
            "module_id": module_id,
            "expected_source_bundle_sha256": expected,
            "computed_source_bundle_sha256": computed,
            "master_bundle_sha256": master_computed,
            "expected_matches_master_bundle": expected_matches_master,
            "source_bundle_match": match,
            "source_file_count": len(source_paths),
            "missing_source_paths": missing,
            "runtime_vs_master_drift_paths": drift_paths,
            "diagnosis": diagnosis,
            "files": file_rows,
        })
    return rows, missing_total, mismatch_total, drift_file_total


def legacy25_rows(inv: dict[str, Any], master_ref: str | None) -> tuple[list[dict[str, Any]], int, int]:
    names = [str(x) for x in inv.get("historical_implementation_inventory_25", [])]
    rows: list[dict[str, Any]] = []
    missing = 0
    drift = 0
    for name in names:
        candidates = [ROOT / "backend" / "strategies" / f"{name}.py", ROOT / "strategies" / f"{name}.py"]
        path = next((p for p in candidates if p.is_file()), None)
        rel = f"backend/strategies/{name}.py"
        master_digest = git_blob_sha256(master_ref, rel)
        if path is None:
            missing += 1
            rows.append({"strategy": name, "present": False, "path": None, "runtime_sha256": None, "master_sha256": master_digest, "runtime_matches_master": False if master_digest else None})
        else:
            try:
                rel = path.relative_to(ROOT).as_posix()
            except ValueError:
                rel = str(path)
            digest = file_sha(path)
            master_digest = git_blob_sha256(master_ref, rel)
            matches = (digest == master_digest) if master_digest else None
            if matches is False:
                drift += 1
            rows.append({"strategy": name, "present": True, "path": rel, "runtime_sha256": digest, "master_sha256": master_digest, "runtime_matches_master": matches})
    return rows, missing, drift


def parse_systemctl_show(unit: str) -> dict[str, str]:
    props = ["Id", "ActiveState", "SubState", "MainPID", "FragmentPath", "WorkingDirectory", "ExecStart"]
    args = ["systemctl", "show", unit, "--no-pager"]
    for prop in props:
        args.extend(["-p", prop])
    rc, out = run(args)
    result: dict[str, str] = {}
    if rc != 0 or not isinstance(out, str):
        return result
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k] = v
    return result


def active_service_rows() -> tuple[list[dict[str, Any]], set[int]]:
    rc, out = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
    if rc != 0 or not isinstance(out, str):
        return [], set()
    rows: list[dict[str, Any]] = []
    main_pids: set[int] = set()
    for line in out.splitlines():
        unit = line.split()[0] if line.split() else ""
        if not unit or not RELEVANT_UNIT_RE.search(unit):
            continue
        props = parse_systemctl_show(unit)
        exec_start = props.get("ExecStart", "")
        paths = sorted(set(SCRIPT_PATH_RE.findall(exec_start)))
        entry_rows = []
        for raw_path in paths:
            p = Path(raw_path)
            entry_rows.append({"path": raw_path, "exists": p.is_file(), "sha256": file_sha(p)})
        try:
            pid = int(props.get("MainPID", "0") or 0)
        except ValueError:
            pid = 0
        if pid > 0:
            main_pids.add(pid)
        fragment = props.get("FragmentPath") or None
        working = props.get("WorkingDirectory") or None
        rows.append({
            "unit": unit,
            "active_state": props.get("ActiveState"),
            "sub_state": props.get("SubState"),
            "main_pid": pid,
            "fragment_path": fragment,
            "fragment_exists": bool(fragment and Path(fragment).is_file()),
            "working_directory": working,
            "working_directory_exists": bool(working and Path(working).is_dir()) if working else None,
            "entry_paths": entry_rows,
        })
    return rows, main_pids


def proc_extra_rows(systemd_main_pids: set[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    proc = Path("/proc")
    for child in proc.iterdir():
        if not child.name.isdigit():
            continue
        pid = int(child.name)
        if pid in systemd_main_pids:
            continue
        try:
            cmd = (child / "cmdline").read_bytes().split(b"\0")
            strings = [x.decode("utf-8", "replace") for x in cmd if x]
            cwd = str((child / "cwd").resolve())
            exe = str((child / "exe").resolve())
        except (OSError, PermissionError):
            continue
        script_paths = [x for x in strings if x.startswith("/") and re.search(r"\.(?:py|sh|js|mjs)$", x)]
        relevant = cwd.startswith(str(ROOT)) or any(x.startswith(str(ROOT)) or x.startswith("/opt/zico") for x in script_paths)
        if not relevant:
            continue
        rows.append({
            "pid": pid,
            "cwd": cwd,
            "exe": exe,
            "script_paths": [{"path": x, "exists": Path(x).is_file(), "sha256": file_sha(Path(x))} for x in sorted(set(script_paths))],
        })
    return rows


def owner_conflicts(service_rows: list[dict[str, Any]], proc_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    owners: dict[str, list[str]] = defaultdict(list)
    for row in service_rows:
        for item in row.get("entry_paths", []):
            path = item.get("path")
            if path:
                owners[str(path)].append(f"service:{row['unit']}")
    for row in proc_rows:
        for item in row.get("script_paths", []):
            path = item.get("path")
            if path:
                owners[str(path)].append(f"process:{row['pid']}")
    conflicts = [{"owner_path": path, "active_owners": sorted(set(ids))} for path, ids in sorted(owners.items()) if len(set(ids)) > 1]
    return conflicts, len(conflicts)


def unresolved_active_refs(service_rows: list[dict[str, Any]], proc_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in service_rows:
        if row.get("fragment_path") and not row.get("fragment_exists"):
            rows.append({"owner": f"service:{row['unit']}", "kind": "missing_fragment", "path": row.get("fragment_path")})
        if row.get("working_directory") and not row.get("working_directory_exists"):
            rows.append({"owner": f"service:{row['unit']}", "kind": "missing_working_directory", "path": row.get("working_directory")})
        for item in row.get("entry_paths", []):
            if not item.get("exists"):
                rows.append({"owner": f"service:{row['unit']}", "kind": "missing_entry_path", "path": item.get("path")})
    for row in proc_rows:
        for item in row.get("script_paths", []):
            if not item.get("exists"):
                rows.append({"owner": f"process:{row['pid']}", "kind": "missing_script_path", "path": item.get("path")})
    return rows


def git_path_sets(master_ref: str | None) -> dict[str, Any]:
    tracked_dirty = git_value("status", "--porcelain", "--untracked-files=no") or ""
    dirty_paths = []
    for line in tracked_dirty.splitlines():
        if len(line) >= 4:
            dirty_paths.append(line[3:].split(" -> ")[-1])
    committed_diff = ""
    if master_ref:
        committed_diff = git_value("diff", "--name-only", f"{master_ref}...HEAD") or ""
    return {
        "tracked_dirty_line_count": len(tracked_dirty.splitlines()),
        "tracked_dirty_paths": sorted(set(dirty_paths)),
        "head_vs_master_committed_diff_paths": sorted(set(x for x in committed_diff.splitlines() if x)),
    }


def main() -> int:
    blockers: list[str] = []
    try:
        pin = decode_env_json("EXPECTED_PIN_B64")
        inv = decode_env_json("LEGACY25_B64")
    except Exception as exc:
        pin, inv = {}, {}
        blockers.append(f"EXPECTED_INPUT_INVALID:{type(exc).__name__}")

    root_ok = ROOT.is_dir()
    git_ok = (ROOT / ".git").exists()
    if not root_ok:
        blockers.append("RUNTIME_ROOT_MISSING")
    if root_ok and not git_ok:
        blockers.append("RUNTIME_ROOT_NOT_GIT")

    master_ref = git_master_ref() if git_ok else None
    module_rows, source_missing, module_mismatch, source_drift_files = module_bundle_rows(pin, master_ref) if root_ok else ([], 0, 0, 0)
    strategy_rows, strategy_missing, strategy_drift = legacy25_rows(inv, master_ref) if root_ok else ([], 0, 0)
    service_rows, main_pids = active_service_rows()
    proc_rows = proc_extra_rows(main_pids) if root_ok else []
    conflicts, duplicate_count = owner_conflicts(service_rows, proc_rows)
    unresolved = unresolved_active_refs(service_rows, proc_rows)

    if source_missing:
        blockers.append("PINNED_SOURCE_FILE_MISSING")
    if module_mismatch:
        blockers.append("PINNED_MODULE_SOURCE_MISMATCH")
    if strategy_missing:
        blockers.append("LEGACY25_SOURCE_MISSING")
    if duplicate_count:
        blockers.append("DUPLICATE_ACTIVE_OWNER")
    if unresolved:
        blockers.append("UNRESOLVED_ACTIVE_REFERENCE")
    if git_ok and master_ref is None:
        blockers.append("MASTER_REF_UNAVAILABLE")

    git_paths = git_path_sets(master_ref) if git_ok else {"tracked_dirty_line_count": 0, "tracked_dirty_paths": [], "head_vs_master_committed_diff_paths": []}
    receipt: dict[str, Any] = {
        "schema_version": "zel.g0.runtime_census.v2",
        "state": "PASS_G0_RUNTIME_CENSUS" if not blockers else "HOLD_G0_RUNTIME_CENSUS",
        "root": str(ROOT),
        "runtime_root_exists": root_ok,
        "runtime_root_git": git_ok,
        "runtime_git_head": git_value("rev-parse", "HEAD") if git_ok else None,
        "runtime_git_branch": git_value("rev-parse", "--abbrev-ref", "HEAD") if git_ok else None,
        "runtime_master_ref": master_ref,
        **git_paths,
        "expected_module_count": len(pin.get("modules", [])),
        "module_source_rows": module_rows,
        "module_source_match_count": sum(1 for x in module_rows if x.get("source_bundle_match")),
        "module_source_mismatch_count": module_mismatch,
        "pinned_source_missing_count": source_missing,
        "runtime_vs_master_source_drift_file_count": source_drift_files,
        "legacy25_expected_count": len(inv.get("historical_implementation_inventory_25", [])),
        "legacy25_present_count": sum(1 for x in strategy_rows if x.get("present")),
        "legacy25_missing_count": strategy_missing,
        "legacy25_runtime_vs_master_drift_count": strategy_drift,
        "legacy25_rows": strategy_rows,
        "active_relevant_services": service_rows,
        "extra_relevant_processes": proc_rows,
        "active_owner_conflicts": conflicts,
        "duplicate_active_owner_count": duplicate_count,
        "unresolved_active_references": unresolved,
        "unresolved_active_reference_count": len(unresolved),
        "blockers": sorted(set(blockers)),
        "runtime_mutated": False,
        "destructive_cleanup_authority": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    material = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    receipt["receipt_sha256"] = sha256_bytes(material)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
