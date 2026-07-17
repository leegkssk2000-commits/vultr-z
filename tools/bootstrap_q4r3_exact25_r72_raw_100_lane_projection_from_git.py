#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "q4r3-exact25-r72-raw-100-lane-shadow-projection-v1"
UNITS = {
    "ZICO_PID": "zico-ceo-canonical-adapter.service",
    "PRODUCER_PID": "q4r3-exact25-shadow-producer.service",
    "WRITER_PID": "q4r3-exact25-persistent-single-event-writer.service",
}
HOST_ZBOT = Path("/usr/local/bin/zel_alimi_w210_zbot_control_advisor.py")


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def unit_pids() -> dict[str, str]:
    return {
        name: output(["systemctl", "show", unit, "-p", "MainPID", "--value"])
        for name, unit in UNITS.items()
    }


def digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def python_bin(root: Path) -> str:
    for path in (
        root / ".venv/bin/python",
        root / "venv/bin/python",
        root / "backend/.venv/bin/python",
    ):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args()
    root = args.root.resolve()
    worktree = Path(f"/tmp/q4r3_exact25_r72_{args.sha[:12]}")
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    r71 = root / "runtime/exact25_edge_v1/exact25_r71_skill_adjusted_shadow_matrix_contract/status_latest.json"
    protected = {
        "HOST_ZBOT": HOST_ZBOT,
        "ACTIVE_SKILL_REGISTRY": root / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
        "ACTIVE_SKILL_RESOLVER": root / "backend/engine/skill_resolver.py",
        "R71_STATUS": r71,
    }
    for path in (ledger, r71):
        if not path.is_file():
            raise SystemExit(f"REQUIRED_INPUT_MISSING={path}")

    before_pids = unit_pids()
    before_hashes = {name: digest(path) for name, path in protected.items()}
    with tempfile.NamedTemporaryFile(prefix="q4r3_r72_ledger_", delete=False) as handle:
        ledger_copy = Path(handle.name)
    shutil.copyfile(ledger, ledger_copy)
    prefix_size = ledger_copy.stat().st_size
    passed = False
    try:
        if worktree.exists():
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
            shutil.rmtree(worktree, ignore_errors=True)
        run(["git", "-C", str(root), "worktree", "add", "--detach", str(worktree), args.sha])
        run(
            [
                python_bin(root),
                str(worktree / "tools/run_q4r3_exact25_r72_raw_100_lane_projection.py"),
                "--root",
                str(root),
                "--worktree",
                str(worktree),
            ]
        )

        after_pids = unit_pids()
        after_hashes = {name: digest(path) for name, path in protected.items()}
        if after_pids != before_pids:
            raise RuntimeError(f"SERVICE_PID_CHANGED:{before_pids}:{after_pids}")
        if after_hashes != before_hashes:
            raise RuntimeError(f"PROTECTED_SURFACE_CHANGED:{before_hashes}:{after_hashes}")
        with ledger.open("rb") as current, ledger_copy.open("rb") as previous:
            if current.read(prefix_size) != previous.read(prefix_size):
                raise RuntimeError("FORMAL_LEDGER_PREFIX_CHANGED")

        runtime_dir = root / "runtime/exact25_edge_v1/exact25_r72_raw_100_lane_shadow_projection"
        status = runtime_dir / "status_latest.json"
        projection = runtime_dir / "projection_latest.json"
        evidence_status = worktree / "evidence/q4r3_exact25_r72_raw_100_lane_shadow_projection_latest.json"
        evidence_projection = worktree / "evidence/q4r3_exact25_r72_raw_100_lane_shadow_projection_slots_latest.json"
        evidence_status.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(status, evidence_status)
        shutil.copyfile(projection, evidence_projection)
        run(
            [
                "git",
                "add",
                str(evidence_status.relative_to(worktree)),
                str(evidence_projection.relative_to(worktree)),
            ],
            cwd=worktree,
        )
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode != 0:
            run(
                [
                    "git",
                    "-c",
                    "user.name=ZEL Runtime Evidence",
                    "-c",
                    "user.email=zel-runtime-evidence@localhost",
                    "commit",
                    "-m",
                    "Record R7.2 raw 100-lane projection evidence",
                ],
                cwd=worktree,
            )
            run(["git", "push", "origin", f"HEAD:refs/heads/{args.branch}"], cwd=worktree)

        print("Q4R3_EXACT25_R72_BOOTSTRAP_PASS")
        print("OFFICIAL_STAGE=R7.2")
        for name, value in after_pids.items():
            print(f"{name}={value}")
        for name, value in after_hashes.items():
            print(f"{name}_SHA256={value}")
        print("LANE_TEMPLATE_COUNT=100")
        print("TEMPLATES_ARE_POSITIONS=false")
        print("RUNTIME_BINDING_ALLOWED=false")
        print("SOURCE_EVENT_SUBSCRIPTION_ALLOWED=false")
        print("FORMAL_LEDGER_WRITE_ALLOWED=false")
        print("PROVIDER_INVOCATION_ENABLED=false")
        print("EVIDENCE=evidence/q4r3_exact25_r72_raw_100_lane_shadow_projection_latest.json")
        passed = True
        return 0
    finally:
        ledger_copy.unlink(missing_ok=True)
        if passed:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], check=False)
        else:
            print(f"WORKTREE_PRESERVED_FOR_DIAGNOSIS={worktree}")


if __name__ == "__main__":
    raise SystemExit(main())
