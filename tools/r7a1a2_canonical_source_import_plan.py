#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, tempfile
from pathlib import Path
from typing import Any


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def load(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"NOT_OBJECT:{path}")
    return obj


def digest(path: Path) -> str:
    if not path.is_file(): return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent); os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(text, encoding="utf-8"); os.replace(tmp, path)
    finally: tmp.unlink(missing_ok=True)


def exists_in_git(root: Path, sha: str, path: str) -> bool:
    return run(["git","-C",str(root),"-c",f"safe.directory={root}","cat-file","-e",f"{sha}:{path}"]).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--target-sha", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()
    c = load(a.contract); root = Path(c["repo_root"]); parent = load(Path(c["parent_status"]))
    blockers: list[str] = []
    for key, expected in c["required_parent"].items():
        if parent.get(key) != expected: blockers.append(f"PARENT_{key.upper()}:{parent.get(key)}!={expected}")
    source_map = {row.get("source"): row for row in parent.get("sources", []) if isinstance(row, dict)}
    before = {t["source"]: digest(Path(t["source"])) for t in c["targets"]}
    plans = []
    for t in c["targets"]:
        row = source_map.get(t["source"], {}); scan = row.get("secret_scan") or {}
        hits = int(scan.get("hit_count", -1)); current = digest(Path(t["source"]))
        if not row: blockers.append("SOURCE_ROW_MISSING:" + t["source"])
        if row.get("unit") != t["unit"]: blockers.append("UNIT_MISMATCH:" + t["source"])
        if row.get("compile_ok") is not True: blockers.append("COMPILE_NOT_PROVEN:" + t["source"])
        if current != row.get("sha256"): blockers.append("SOURCE_HASH_DRIFT:" + t["source"])
        if row.get("exact_git_matches"): blockers.append("ALREADY_EXACT_TRACKED:" + t["source"])
        target_exists = exists_in_git(root, a.target_sha, t["canonical_path"])
        if target_exists: blockers.append("CANONICAL_TARGET_EXISTS:" + t["canonical_path"])
        if "expected_secret_hits" in t and hits != t["expected_secret_hits"]: blockers.append("SENSITIVE_HIT_UNEXPECTED:" + t["source"])
        if "expected_secret_hits_min" in t and hits < t["expected_secret_hits_min"]: blockers.append("SENSITIVE_HIT_TOO_LOW:" + t["source"])
        mode = "SANITIZED_COPY_ONLY" if hits > 0 else "BYTE_IDENTICAL_COPY"
        plans.append({
            "unit": t["unit"], "deployed_source": t["source"], "deployed_sha256": current,
            "canonical_path": t["canonical_path"], "canonical_target_exists": target_exists,
            "sensitive_hit_count": hits, "sensitive_categories": sorted((scan.get("categories") or {}).keys()),
            "import_mode": mode,
            "required_gate": "ZERO_SENSITIVE_HITS_AND_COMPILE_PASS" if hits > 0 else "CANONICAL_SHA_EQUALS_DEPLOYED_SHA"
        })
    wp = parent.get("writer_parity") or {}; shadow = wp.get("shadow") or {}; alimi = wp.get("alimi") or {}
    if shadow.get("configured_writer_count") is None and shadow.get("active_writer_count") is None and alimi.get("configured_writer_count") == 7 and alimi.get("active_writer_count") == 0:
        writer_class = "SHADOW_WRITER_SCHEMA_FIELDS_ABSENT"
    else: writer_class = "UNRESOLVED_WRITER_SCHEMA_STATE"
    if writer_class != c["writer_schema_expected"]["classification"]: blockers.append("WRITER_CLASS_UNEXPECTED:" + writer_class)
    after = {t["source"]: digest(Path(t["source"])) for t in c["targets"]}
    changed = [p for p in before if before[p] != after[p]]
    if changed: blockers.append("DEPLOYED_SOURCE_CHANGED_DURING_PLAN")
    ordered = [
        "Pin deployed SHA256 and rollback copies.",
        "Import ALIMI control API and position firewall byte-identically.",
        "Create a sanitized Telegram candidate without changing handler structure.",
        "Require zero sensitive hits, compile PASS and focused command tests.",
        "Add a release manifest; keep systemd on deployed paths until a separate canary.",
        "Then add configured_writer_count and active_writer_count at the Shadow snapshot owner; never patch ALIMI values directly."
    ]
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema":"zos_r7a1a2_canonical_source_import_plan_status_v1","official_stage":"R7.A1A2",
        "state":state,"blockers":blockers,"blocker_count":len(blockers),"mutation_count":len(changed),
        "source_plan_count":len(plans),"verbatim_import_count":sum(p["import_mode"]=="BYTE_IDENTICAL_COPY" for p in plans),
        "sanitized_import_count":sum(p["import_mode"]=="SANITIZED_COPY_ONLY" for p in plans),"source_plans":plans,
        "writer_schema":{"classification":writer_class,"shadow":shadow,"alimi":alimi,"repair_layer":"SHADOW_SNAPSHOT_OWNER_THEN_DISPLAY_PARITY","direct_alimi_patch_allowed":False},
        "ordered_plan":ordered,"next_stage":c["next_stage"],"evidence_paths":{"json":str(a.output),"markdown":str(a.report)}
    }
    write(a.output, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    md = ["# R7.A1A2 Canonical Source Import Plan","",f"- State: **{state}**",f"- Writer class: **{writer_class}**","","| Unit | Target | Hits | Mode |","|---|---|---:|---|"]
    md += [f"| {p['unit']} | `{p['canonical_path']}` | {p['sensitive_hit_count']} | {p['import_mode']} |" for p in plans]
    md += ["","## Order",""] + [f"{i}. {v}" for i,v in enumerate(ordered,1)]
    write(a.report, "\n".join(md) + "\n")
    print("R7A1A2_CANONICAL_SOURCE_IMPORT_PLAN_COMPLETE")
    print(f"STATE={state}\nBLOCKER_COUNT={len(blockers)}\nMUTATION_COUNT={len(changed)}")
    print(f"SOURCE_PLAN_COUNT={len(plans)}\nVERBATIM_IMPORT_COUNT={payload['verbatim_import_count']}\nSANITIZED_IMPORT_COUNT={payload['sanitized_import_count']}")
    for i,p in enumerate(plans,1): print(f"PLAN_{i}={p['unit']}|{p['canonical_path']}|hits={p['sensitive_hit_count']}|{p['import_mode']}")
    print(f"WRITER_SCHEMA_CLASS={writer_class}\nWRITER_REPAIR_LAYER={payload['writer_schema']['repair_layer']}\nNEXT_STAGE={c['next_stage']}")
    print(f"EVIDENCE_JSON={a.output}\nEVIDENCE_REPORT={a.report}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
