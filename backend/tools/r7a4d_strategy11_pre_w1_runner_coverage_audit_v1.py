from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


PIPELINE_VERSION = "R7A4D_STRATEGY11_PRE_W1_RUNNER_COVERAGE_AUDIT_V1"
EXECUTABLE_ROOTS = (Path("backend/tools"), Path(".github/workflows"))
EXECUTABLE_SUFFIXES = {".py", ".yml", ".yaml"}
SELF_EXCLUDES = {
    "backend/tools/r7a4d_strategy11_pre_w1_runner_coverage_audit_v1.py",
    ".github/workflows/r7a4d-strategy11-pre-w1-runner-coverage-audit-v1.yml",
}


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def stable_sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def executable_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative_root in EXECUTABLE_ROOTS:
        base = root / relative_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in EXECUTABLE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if relative in SELF_EXCLUDES:
                continue
            files.append(path)
    return sorted(files)


def locate_markers(root: Path, files: Sequence[Path], markers: Sequence[str]) -> list[str]:
    normalized = [str(marker).casefold() for marker in markers if str(marker).strip()]
    if not normalized:
        return []

    matches: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").casefold()
        except OSError:
            continue
        if all(marker in text for marker in normalized):
            matches.append(path.relative_to(root).as_posix())
    return matches


def audit_capability(root: Path, files: Sequence[Path], row: Mapping[str, Any]) -> dict[str, Any]:
    capability_id = str(row["capability_id"])
    order = int(row["order"])
    external = row.get("external_authority")
    markers = [str(value) for value in row.get("required_markers", [])]

    if isinstance(external, Mapping):
        return {
            "capability_id": capability_id,
            "order": order,
            "status": "PASS_DECLARED_EXTERNAL_AUTHORITY",
            "external_authority": dict(external),
            "required_markers": markers,
            "matches": [],
            "implementation_required": False,
            "verification_note": "GitHub PR/run/head authority must be rechecked by the control plane before execution.",
        }

    matches = locate_markers(root, files, markers)
    implemented = bool(matches)
    return {
        "capability_id": capability_id,
        "order": order,
        "status": "PASS_EXECUTABLE_FOUND" if implemented else "IMPLEMENTATION_REQUIRED",
        "required_markers": markers,
        "matches": matches,
        "implementation_required": not implemented,
    }


def write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    rows = payload["capabilities"]
    lines = [
        "# Strategy11 pre-W1 runner coverage audit",
        "",
        f"- State: **{payload['state']}**",
        f"- Head: `{payload['head_sha']}`",
        f"- Required capabilities: `{payload['required_count']}`",
        f"- Covered: `{payload['covered_count']}`",
        f"- Missing: `{payload['missing_count']}`",
        f"- Next: `{payload['next']}`",
        "",
        "| Order | Capability | Status | Evidence |",
        "|---:|---|---|---|",
    ]
    for row in rows:
        evidence = ", ".join(row.get("matches", []))
        if not evidence and row.get("external_authority"):
            authority = row["external_authority"]
            evidence = f"PR #{authority.get('pr_number')} / {authority.get('head_sha')}"
        lines.append(
            f"| {row['order']} | `{row['capability_id']}` | `{row['status']}` | {evidence or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- canonical_mutated=false",
            "- registry_mutated=false",
            "- protected_mutations=0",
            "- execution_allowed=false",
            "- order_authority=BLOCKED",
            "- promotion_authority=false",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract_path = Path(args.contract).resolve()
    out = Path(args.out).resolve()
    contract = strict_json(contract_path)

    capabilities_source = contract.get("capabilities")
    if not isinstance(capabilities_source, list) or not capabilities_source:
        raise RuntimeError("CAPABILITY_CONTRACT_EMPTY")

    files = executable_files(root)
    capabilities = [audit_capability(root, files, row) for row in capabilities_source]
    capabilities.sort(key=lambda row: (int(row["order"]), str(row["capability_id"])))

    missing = [row for row in capabilities if row["implementation_required"]]
    covered = [row for row in capabilities if not row["implementation_required"]]
    state = "IMPLEMENTATION_REQUIRED" if missing else "PASS_COVERAGE"
    next_stage = str(missing[0]["capability_id"]) if missing else "W1_READY_WAIT_DATA"

    payload = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "state": state,
        "blockers": [],
        "head_sha": git_head(root),
        "contract_sha256": stable_sha(contract),
        "scanned_executable_file_count": len(files),
        "required_count": len(capabilities),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "missing_capability_ids": [str(row["capability_id"]) for row in missing],
        "next": next_stage,
        "required_action": "CREATE_MINIMUM_READ_ONLY_CHILD" if missing else "WAIT_FOR_W1_EXACT_BOUNDARY",
        "capabilities": capabilities,
        "parent_authority": contract.get("parent_authority", {}),
        "policy": contract.get("policy", {}),
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "merge_performed": False,
    }

    atomic_json(out / "status.json", payload)
    atomic_json(out / "coverage.json", {"capabilities": capabilities})
    write_markdown(out / "coverage.md", payload)

    print(
        json.dumps(
            {
                "state": state,
                "covered": len(covered),
                "missing": len(missing),
                "next": next_stage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
