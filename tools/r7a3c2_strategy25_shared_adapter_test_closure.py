#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def load(path: Path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sha(path: Path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("r7a3c2_shared_strategy_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    contract = load(Path(args.contract))
    blockers = []
    protected_paths = [Path(path) for path in contract.get("protected_paths", [])]
    protected_before = {str(path): sha(path) for path in protected_paths}

    a3c1 = load(root / contract["prior_a3c1_status_path"])
    a3 = load(root / contract["prior_a3_status_path"])
    if not (
        a3c1.get("state") == "PASS"
        and a3c1.get("next_stage") == "R7.A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_AND_TEST_PATCH"
    ):
        blockers.append("PRIOR_A3C1_INVALID")

    rows = a3.get("strategies", [])
    if not isinstance(rows, list) or len(rows) != 25:
        blockers.append("A3_STRATEGY_COUNT_NOT_25")

    adapter_path = root / contract["adapter_path"]
    test_path = root / contract["test_path"]
    if not adapter_path.is_file():
        blockers.append("ADAPTER_MISSING")
    if not test_path.is_file():
        blockers.append("TEST_MISSING")

    diagnosis = {"ok": False, "failures": [{"error": "ADAPTER_NOT_LOADED"}]}
    if adapter_path.is_file() and isinstance(rows, list) and len(rows) == 25:
        try:
            adapter = load_adapter(adapter_path)
            diagnosis = adapter.diagnose_bindings_from_a3_status(root / contract["prior_a3_status_path"])
        except Exception as exc:
            diagnosis = {"ok": False, "failures": [{"error": f"{type(exc).__name__}:{exc}"}]}
    if not diagnosis.get("ok"):
        blockers.append(f"ENTRYPOINT_RESOLUTION_FAILED:{len(diagnosis.get('failures', []))}")

    completed = subprocess.run(
        ["python3", "-m", "pytest", "-q", str(test_path)],
        cwd=root,
        text=True,
        capture_output=True,
    )
    pytest_output = (completed.stdout + completed.stderr)[-12000:]
    if completed.returncode != 0:
        blockers.append("REAL_ENTRYPOINT_TEST_FAILED")

    protected_after = {str(path): sha(path) for path in protected_paths}
    protected_changes = [
        {"path": path, "before": protected_before.get(path), "after": protected_after.get(path)}
        for path in protected_before
        if protected_before.get(path) != protected_after.get(path)
    ]
    if protected_changes:
        blockers.append("PROTECTED_PATH_CHANGED")

    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "official_stage": "R7.A3C2",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(rows) if isinstance(rows, list) else 0,
        "binding_diagnosis": diagnosis,
        "adapter_sha": sha(adapter_path),
        "test_sha": sha(test_path),
        "pytest_rc": completed.returncode,
        "pytest_output": pytest_output,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "runtime_mutation_count": 0,
        "performance_s_promoted_count": 0,
        "market_quality_s_grade_deferred": True,
        "next_stage": contract["next_stage_on_pass"] if not blockers else contract["next_stage_on_fail"],
    }
    atomic(root / contract["status_path"], payload)

    print("R7A3C2_STRATEGY25_SHARED_ADAPTER_TEST_CLOSURE_COMPLETE")
    for key in ("state", "blocker_count", "strategy_count", "pytest_rc", "protected_change_count", "next_stage"):
        print(f"{key.upper()}={payload[key]}")
    print("ENTRYPOINT_FAILURES=" + json.dumps(diagnosis.get("failures", []), ensure_ascii=False))
    print("PYTEST_OUTPUT_BEGIN")
    print(pytest_output)
    print("PYTEST_OUTPUT_END")
    rc = 0 if not blockers else 2
    print(f"RC={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
