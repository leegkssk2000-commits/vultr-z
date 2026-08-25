#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "zel.pipeline_hygiene_audit.v4"
WORKFLOW_SUFFIXES = {".yml", ".yaml"}
VOLATILE_OUTPUT_RE = re.compile(r"[A-Za-z0-9_./${}:-]*latest\.json")
CRON_RE = re.compile(r"cron:\s*['\"]([^'\"]+)['\"]")
RETENTION_RE = re.compile(r"retention-days:\s*(\d+)")
TIMEOUT_RE = re.compile(r"timeout-minutes:\s*(\d+)")
NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.M)
FILE_VERSION_RE = re.compile(r"(?:^|[-_])v(\d+)(?:\.(?:ya?ml))$", re.I)
NAME_VERSION_RE = re.compile(r"\bV(\d+)\b", re.I)
FETCH_DEPTH_ZERO_RE = re.compile(r"fetch-depth:\s*0\b")
SHELL_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(?:['\"])?([^'\"\n]+?)(?:['\"])?\s*$", re.M)
PY_PATH_WRITE_RE = re.compile(
    r"Path\(\s*['\"]([^'\"]*latest\.json)['\"]\s*\)\s*\.\s*(?:write_text|write_bytes)\s*\("
)
PY_OPEN_WRITE_RE = re.compile(
    r"open\(\s*['\"]([^'\"]*latest\.json)['\"]\s*,\s*['\"][wax][^'\"]*['\"]"
)
CANONICAL_LATEST_PREFIXES = (
    "backend/",
    "runtime_results/",
    "results/runtime_results/",
    "results-branch/runtime_results/",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _cron_minute(expr: str) -> str:
    parts = expr.split()
    return parts[0] if len(parts) >= 5 else "INVALID"


def _top_level_concurrency_group(text: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "concurrency:" or line[:1].isspace():
            continue
        for child in lines[idx + 1:]:
            if child and not child[:1].isspace():
                break
            match = re.match(r"^\s+group:\s*(.+?)\s*$", child)
            if match:
                value = match.group(1).strip().strip("'\"")
                return value or None
        return None
    inline = re.search(r"(?m)^concurrency:\s*\{[^\n}]*\bgroup:\s*([^,}]+)", text)
    if inline:
        value = inline.group(1).strip().strip("'\"")
        return value or None
    return None


def _static_serialization_group(group: str | None) -> bool:
    if not group:
        return False
    lowered = group.lower()
    return "${{" not in group and "github." not in lowered and "matrix." not in lowered and "inputs." not in lowered


def _clean_shell_token(token: str) -> str:
    return token.strip().strip("'\";,()")


def _resolve_shell_ref(token: str, assignments: dict[str, str]) -> str:
    token = _clean_shell_token(token)
    m = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?(/.*)?", token)
    if not m:
        return token
    base = assignments.get(m.group(1))
    if not base:
        return token
    suffix = m.group(2) or ""
    return base.rstrip("/") + suffix


def _write_target_tokens(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("- run:"):
        stripped = stripped[len("- run:"):].strip()
    elif stripped.startswith("run:"):
        stripped = stripped[len("run:"):].strip()
    if not stripped or stripped.startswith("#"):
        return []
    targets: list[str] = []
    cmd = re.search(r"(?:^|[;&|]\s*)(?:cp|mv|install)\s+([^\n]+)$", stripped)
    if cmd:
        parts = cmd.group(1).split()
        if parts:
            targets.append(parts[-1])
    for match in re.finditer(r"\btee(?:\s+-a)?\s+([^\s|;&]+)", stripped):
        targets.append(match.group(1))
    for match in re.finditer(r"(?:>>|>)\s*([^\s|;&]+)", stripped):
        targets.append(match.group(1))
    return targets


def _written_latest_refs(text: str) -> list[str]:
    assignments = {name: value.strip() for name, value in SHELL_ASSIGN_RE.findall(text)}
    written: set[str] = set()
    for line in text.splitlines():
        for token in _write_target_tokens(line):
            ref = _resolve_shell_ref(token, assignments)
            if ref.endswith("latest.json"):
                written.add(ref)
    written.update(PY_PATH_WRITE_RE.findall(text))
    written.update(PY_OPEN_WRITE_RE.findall(text))
    return sorted(written)


def _is_canonical_latest_ref(ref: str) -> bool:
    if not ref or ref.startswith(("$", "/tmp/", "out/", "../out/")):
        return False
    return ref.startswith(CANONICAL_LATEST_PREFIXES)


def _workflow_row(path: Path, root: Path) -> dict[str, Any]:
    text = _read(path)
    rel = path.relative_to(root).as_posix()
    name_match = NAME_RE.search(text)
    display_name = (name_match.group(1).strip() if name_match else path.stem).strip("'\"")
    crons = CRON_RE.findall(text)
    retentions = [int(x) for x in RETENTION_RE.findall(text)]
    timeouts = [int(x) for x in TIMEOUT_RE.findall(text)]
    contents_write = bool(re.search(r"contents:\s*write", text))
    git_push = bool(re.search(r"\bgit\s+push\b", text))
    git_commit = bool(re.search(r"\bgit\s+commit\b", text))
    cancel_false = bool(re.search(r"cancel-in-progress:\s*false", text))
    cancel_true = bool(re.search(r"cancel-in-progress:\s*true", text))
    pip_install = bool(re.search(r"python\s+-m\s+pip\s+install|\bpip\s+install", text))
    no_cache_pip = bool(re.search(r"pip\s+install[^\n]*--no-cache-dir", text))
    workflow_run_trigger = bool(re.search(r"\bworkflow_run\s*:", text))
    workflow_dispatch = bool(re.search(r"\bworkflow_dispatch\s*:", text))
    fetch_depth_zero = bool(FETCH_DEPTH_ZERO_RE.search(text))
    concurrency_group = _top_level_concurrency_group(text)
    latest_refs = sorted(set(VOLATILE_OUTPUT_RE.findall(text)))
    canonical_latest_refs = sorted(x for x in latest_refs if _is_canonical_latest_ref(x))
    written_latest_refs = _written_latest_refs(text)
    canonical_written_latest_refs = sorted(x for x in written_latest_refs if _is_canonical_latest_ref(x))
    canonical_read_only_mentions = sorted(set(canonical_latest_refs) - set(canonical_written_latest_refs))

    file_v_match = FILE_VERSION_RE.search(path.name)
    name_v_match = NAME_VERSION_RE.search(display_name)
    file_version = int(file_v_match.group(1)) if file_v_match else None
    name_version = int(name_v_match.group(1)) if name_v_match else None
    version_mismatch = bool(file_version is not None and name_version is not None and file_version != name_version)

    risk = 0
    reasons: list[str] = []
    if crons and contents_write:
        risk += 3; reasons.append("SCHEDULED_CONTENTS_WRITE")
    if git_push:
        risk += 3; reasons.append("GIT_PUSH_WRITER")
    if crons and git_push:
        risk += 2; reasons.append("SCHEDULED_GIT_WRITER")
    if cancel_false and crons:
        risk += 1; reasons.append("SCHEDULED_CANCEL_FALSE")
    if any(x > 30 for x in retentions):
        risk += 2; reasons.append("ARTIFACT_RETENTION_GT30D")
    if pip_install and crons:
        risk += 1; reasons.append("REPEATED_DEP_INSTALL")
    if no_cache_pip and crons:
        risk += 1; reasons.append("NO_CACHE_PIP_ON_SCHEDULE")
    if any(x >= 60 for x in timeouts) and crons:
        risk += 1; reasons.append("LONG_SCHEDULED_TIMEOUT")
    if fetch_depth_zero:
        risk += 1; reasons.append("FULL_HISTORY_CHECKOUT")
    if version_mismatch:
        risk += 1; reasons.append("WORKFLOW_VERSION_NAME_MISMATCH")

    return {
        "path": rel,
        "name": display_name,
        "crons": crons,
        "cron_minutes": [_cron_minute(x) for x in crons],
        "contents_write": contents_write,
        "git_commit": git_commit,
        "git_push": git_push,
        "cancel_in_progress_false": cancel_false,
        "cancel_in_progress_true": cancel_true,
        "concurrency_group": concurrency_group,
        "concurrency_group_static": _static_serialization_group(concurrency_group),
        "pip_install": pip_install,
        "no_cache_pip": no_cache_pip,
        "workflow_run_trigger": workflow_run_trigger,
        "workflow_dispatch": workflow_dispatch,
        "fetch_depth_zero": fetch_depth_zero,
        "artifact_retentions_days": retentions,
        "max_artifact_retention_days": max(retentions) if retentions else 0,
        "timeout_minutes_max": max(timeouts) if timeouts else 0,
        "latest_json_refs": latest_refs,
        "canonical_latest_json_refs": canonical_latest_refs,
        "written_latest_json_refs": written_latest_refs,
        "canonical_written_latest_json_refs": canonical_written_latest_refs,
        "canonical_read_only_latest_mentions": canonical_read_only_mentions,
        "file_version": file_version,
        "display_name_version": name_version,
        "version_mismatch": version_mismatch,
        "risk_score": risk,
        "risk_reasons": reasons,
    }


def audit(repo_root: Path) -> dict[str, Any]:
    wf_root = repo_root / ".github" / "workflows"
    if not wf_root.is_dir():
        raise RuntimeError(f"WORKFLOW_DIR_MISSING:{wf_root}")
    paths = sorted(p for p in wf_root.iterdir() if p.is_file() and p.suffix.lower() in WORKFLOW_SUFFIXES)
    rows = [_workflow_row(p, repo_root) for p in paths]
    row_by_path = {row["path"]: row for row in rows}

    cron_minutes: Counter[str] = Counter()
    broad_latest_writers: dict[str, list[str]] = defaultdict(list)
    canonical_latest_writers: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for minute in row["cron_minutes"]:
            cron_minutes[minute] += 1
        if row["git_push"]:
            for ref in row["written_latest_json_refs"]:
                broad_latest_writers[ref].append(row["path"])
            for ref in row["canonical_written_latest_json_refs"]:
                canonical_latest_writers[ref].append(row["path"])

    duplicate_latest_writers = {
        ref: sorted(set(writer_paths))
        for ref, writer_paths in broad_latest_writers.items()
        if len(set(writer_paths)) > 1
    }
    all_duplicate_canonical_writers = {
        ref: sorted(set(writer_paths))
        for ref, writer_paths in canonical_latest_writers.items()
        if len(set(writer_paths)) > 1
    }
    serialized_canonical_writers: dict[str, dict[str, Any]] = {}
    unsafe_duplicate_canonical_writers: dict[str, list[str]] = {}
    for ref, writer_paths in all_duplicate_canonical_writers.items():
        groups = {row_by_path[path].get("concurrency_group") for path in writer_paths}
        same_static_group = (
            len(groups) == 1
            and None not in groups
            and all(row_by_path[path].get("concurrency_group_static") is True for path in writer_paths)
        )
        if same_static_group:
            group = next(iter(groups))
            serialized_canonical_writers[ref] = {
                "writers": writer_paths,
                "concurrency_group": group,
                "race_prevented_by_shared_static_concurrency": True,
            }
        else:
            unsafe_duplicate_canonical_writers[ref] = writer_paths

    scheduled = [x for x in rows if x["crons"]]
    git_writers = [x for x in rows if x["git_push"]]
    scheduled_git_writers = [x for x in rows if x["crons"] and x["git_push"]]
    long_retention = [x for x in rows if x["max_artifact_retention_days"] > 30]
    version_mismatch = [x for x in rows if x["version_mismatch"]]
    full_history_checkout = [x for x in rows if x["fetch_depth_zero"]]
    high_risk = sorted(rows, key=lambda x: (-x["risk_score"], x["path"]))[:25]
    canonical_write_workflows = [x for x in rows if x["git_push"] and x["canonical_written_latest_json_refs"]]
    canonical_read_only_mentions = sum(len(x["canonical_read_only_latest_mentions"]) for x in rows)

    recommendations: list[str] = []
    if scheduled_git_writers:
        recommendations.append("COALESCE_SCHEDULED_STATE_WRITES_OR_SERIALIZE_CANONICAL_WRITERS")
    if unsafe_duplicate_canonical_writers:
        recommendations.append("ELIMINATE_UNSAFE_DUPLICATE_CANONICAL_LATEST_JSON_WRITERS")
    if serialized_canonical_writers:
        recommendations.append("DOCUMENT_SERIALIZED_CANONICAL_MULTIWRITER_OWNERSHIP")
    if long_retention:
        recommendations.append("REDUCE_EPHEMERAL_HOURLY_ARTIFACT_RETENTION_TO_30D_OR_LESS")
    if any(x["pip_install"] for x in scheduled):
        recommendations.append("CACHE_OR_PIN_REPEATED_SCHEDULED_DEPENDENCY_INSTALLS")
    if full_history_checkout:
        recommendations.append("REPLACE_UNNECESSARY_FETCH_DEPTH_ZERO_WITH_SHALLOW_TARGETED_CHECKOUT")
    if version_mismatch:
        recommendations.append("ALIGN_WORKFLOW_DISPLAY_VERSIONS_WITH_ACTIVE_IMPLEMENTATION")

    state = "HOLD_PIPELINE_HYGIENE_RISKS_PRESENT" if (
        unsafe_duplicate_canonical_writers or any(x["risk_score"] >= 8 for x in rows)
    ) else "PASS_PIPELINE_HYGIENE_NO_CRITICAL_RISK"

    return {
        "schema_version": SCHEMA,
        "state": state,
        "repo_root": str(repo_root),
        "metrics": {
            "workflow_count": len(rows),
            "scheduled_workflow_count": len(scheduled),
            "contents_write_workflow_count": sum(1 for x in rows if x["contents_write"]),
            "git_push_writer_count": len(git_writers),
            "scheduled_git_push_writer_count": len(scheduled_git_writers),
            "scheduled_cancel_false_count": sum(1 for x in scheduled if x["cancel_in_progress_false"]),
            "scheduled_pip_install_count": sum(1 for x in scheduled if x["pip_install"]),
            "artifact_retention_gt30d_count": len(long_retention),
            "workflow_version_mismatch_count": len(version_mismatch),
            "fetch_depth_zero_workflow_count": len(full_history_checkout),
            "canonical_latest_writer_workflow_count": len(canonical_write_workflows),
            "canonical_latest_read_only_mention_count": canonical_read_only_mentions,
            "duplicate_latest_json_writer_count_broad": len(duplicate_latest_writers),
            "duplicate_canonical_latest_json_writer_count_total": len(all_duplicate_canonical_writers),
            "duplicate_canonical_latest_json_writer_count": len(unsafe_duplicate_canonical_writers),
            "serialized_canonical_latest_json_multiwriter_count": len(serialized_canonical_writers),
        },
        "cron_minute_density": dict(sorted(cron_minutes.items(), key=lambda kv: (-kv[1], kv[0]))),
        "duplicate_latest_json_writers_broad": duplicate_latest_writers,
        "all_duplicate_canonical_latest_json_writers": all_duplicate_canonical_writers,
        "duplicate_canonical_latest_json_writers": unsafe_duplicate_canonical_writers,
        "serialized_canonical_latest_json_multiwriters": serialized_canonical_writers,
        "canonical_latest_writer_workflows": [
            {"path": x["path"], "targets": x["canonical_written_latest_json_refs"], "concurrency_group": x["concurrency_group"]}
            for x in canonical_write_workflows
        ],
        "full_history_checkout_workflows": [x["path"] for x in full_history_checkout],
        "long_artifact_retention": [
            {"path": x["path"], "days": x["max_artifact_retention_days"]} for x in long_retention
        ],
        "workflow_version_mismatches": [
            {"path": x["path"], "name": x["name"], "file_version": x["file_version"], "display_name_version": x["display_name_version"]}
            for x in version_mismatch
        ],
        "high_risk_workflows": high_risk,
        "recommendations": recommendations,
        "read_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="zel-pipeline-hygiene-") as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        common_prefix = (
            "on:\n  schedule:\n    - cron: '17 * * * *'\npermissions:\n  contents: write\n"
        )
        common_jobs = (
            "jobs:\n  x:\n    timeout-minutes: 70\n    steps:\n"
            "      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n"
            "      - run: python -m pip install --no-cache-dir groq\n      - run: git commit -m x && git push origin master\n"
            "      - uses: actions/upload-artifact@v4\n        with:\n          retention-days: 90\n"
        )
        shared = "concurrency:\n  group: shared-static-writer\n  cancel-in-progress: false\n"
        (wf / "alpha-v1.yml").write_text(
            "name: Alpha V2\n" + common_prefix + shared + common_jobs +
            "      - run: |\n          target=backend/research/x_latest.json\n          cp out/x.json \"$target\"\n",
            encoding="utf-8",
        )
        (wf / "beta-v1.yml").write_text(
            "name: Beta V1\n" + common_prefix +
            "concurrency:\n  group: beta-only\n  cancel-in-progress: false\n" + common_jobs +
            "      - run: python tool.py --input backend/research/x_latest.json --output out/beta.json\n",
            encoding="utf-8",
        )
        (wf / "gamma-v1.yml").write_text(
            "name: Gamma V1\n" + common_prefix + shared + common_jobs +
            "      - run: cp out/z.json backend/research/x_latest.json\n",
            encoding="utf-8",
        )
        (wf / "delta-v1.yml").write_text(
            "name: Delta V1\n" + common_prefix +
            "concurrency:\n  group: delta-only\n  cancel-in-progress: false\n" + common_jobs +
            "      - run: cp out/y.json backend/research/y_latest.json\n",
            encoding="utf-8",
        )
        (wf / "epsilon-v1.yml").write_text(
            "name: Epsilon V1\n" + common_prefix +
            "concurrency:\n  group: epsilon-only\n  cancel-in-progress: false\n" + common_jobs +
            "      - run: cp out/y.json backend/research/y_latest.json\n",
            encoding="utf-8",
        )
        r = audit(root)
        assert r["metrics"]["workflow_count"] == 5, r
        assert r["metrics"]["scheduled_git_push_writer_count"] == 5, r
        assert r["metrics"]["artifact_retention_gt30d_count"] == 5, r
        assert r["metrics"]["workflow_version_mismatch_count"] == 1, r
        assert r["metrics"]["fetch_depth_zero_workflow_count"] == 5, r
        assert r["metrics"]["duplicate_canonical_latest_json_writer_count_total"] == 2, r
        assert r["metrics"]["serialized_canonical_latest_json_multiwriter_count"] == 1, r
        assert r["metrics"]["duplicate_canonical_latest_json_writer_count"] == 1, r
        assert r["metrics"]["canonical_latest_read_only_mention_count"] >= 1, r
        assert r["serialized_canonical_latest_json_multiwriters"]["backend/research/x_latest.json"]["concurrency_group"] == "shared-static-writer", r
        assert r["duplicate_canonical_latest_json_writers"]["backend/research/y_latest.json"] == [
            ".github/workflows/delta-v1.yml", ".github/workflows/epsilon-v1.yml"
        ], r
        assert r["read_only"] is True and r["protected_mutations"] == 0, r
    print("PASS_ZEL_PIPELINE_HYGIENE_AUDIT_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("out/zel_pipeline_hygiene_audit_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = audit(args.repo_root.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], **result["metrics"], "recommendations": result["recommendations"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
