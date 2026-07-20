#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

DIAGNOSTIC_TOKENS = (
    "audit", "smoke", "bootstrap", "display", "readiness", "probe",
    "diagnose", "verifier", "verification", "migration", "report",
)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256(path: str) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate.get("implementation_path") or ""),
        str(candidate.get("callable") or ""),
        str(candidate.get("binding_kind") or ""),
    )


def diagnostic_path(path: str) -> bool:
    low = path.lower()
    if low.startswith(("tests/", "test/", "docs/")) or "/tests/" in low:
        return True
    return any(token in low for token in DIAGNOSTIC_TOKENS)


def runtime_inventory() -> list[dict[str, str]]:
    listed = subprocess.run(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if listed.returncode != 0:
        return []
    units = [line.split()[0] for line in listed.stdout.splitlines() if line.split()]
    result: list[dict[str, str]] = []
    for start in range(0, len(units), 40):
        chunk = units[start:start + 40]
        shown = subprocess.run(
            ["systemctl", "show", *chunk, "-p", "Id", "-p", "ExecStart", "-p", "FragmentPath"],
            text=True,
            capture_output=True,
            timeout=60,
        )
        if shown.returncode != 0:
            continue
        current: dict[str, str] = {}
        for line in shown.stdout.splitlines() + [""]:
            if not line.strip():
                if current:
                    result.append(current)
                    current = {}
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                current[key] = value
    return result


def runtime_refs(candidate: dict[str, Any], inventory: list[dict[str, str]]) -> list[dict[str, str]]:
    path = str(candidate.get("implementation_path") or "")
    callable_name = str(candidate.get("callable") or "")
    basename = Path(path).name
    needles = [value for value in (path, basename, callable_name) if value]
    matches = []
    for row in inventory:
        haystack = " ".join(row.values())
        if any(needle in haystack for needle in needles):
            matches.append(row)
    return matches[:20]


def binding_refs(mapping: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    path, callable_name, _ = candidate_key(candidate)
    refs = []
    for row in mapping.get("evidence", []):
        if not isinstance(row, dict):
            continue
        row_paths = {str(row.get("source_path") or ""), str(row.get("target_path") or "")}
        row_callables = {
            str(row.get("callable") or ""),
            str(row.get("target_callable") or ""),
            *[str(x) for x in row.get("shared_engine_candidates", []) if isinstance(x, str)],
        }
        config_keys = row.get("config_keys") if isinstance(row.get("config_keys"), list) else []
        path_match = path in row_paths
        callable_match = not callable_name or callable_name in row_callables
        if path_match and callable_match:
            refs.append({
                "kind": row.get("kind"),
                "source_path": row.get("source_path"),
                "target_path": row.get("target_path"),
                "callable": row.get("callable") or row.get("target_callable"),
                "line": row.get("line"),
                "json_path": row.get("json_path"),
                "config_keys": config_keys,
                "explicit_config_binding": len(config_keys) >= 2,
                "source_blob_sha": row.get("source_blob_sha"),
            })
    return refs[:30]


def choose_model(
    strategy_id: str,
    candidates: list[dict[str, Any]],
    prior_mapping: dict[str, Any],
    prevalence: Counter[tuple[str, str, str]],
    runtime: list[dict[str, str]],
    shared_min: int,
) -> dict[str, Any]:
    enriched = []
    for candidate in candidates:
        key = candidate_key(candidate)
        path, callable_name, binding_kind = key
        refs = binding_refs(prior_mapping, candidate)
        active_refs = runtime_refs(candidate, runtime)
        explicit_binding = any(ref.get("explicit_config_binding") for ref in refs)
        direct_name_match = binding_kind == "direct" and normalize(Path(path).stem) == normalize(strategy_id)
        shared = prevalence[key] >= shared_min
        valid_production = bool(path and callable_name and not diagnostic_path(path))
        authority_score = 0
        reasons = []
        for condition, points, label in (
            (direct_name_match, 120, "direct_name"),
            (bool(active_refs), 90, "active_runtime"),
            (explicit_binding, 60, "explicit_binding"),
            (shared, 30, "shared_prevalence"),
            (valid_production, 30, "production_path"),
            (bool(prior_mapping.get("test_refs")), 10, "test_refs"),
        ):
            if condition:
                authority_score += points
                reasons.append(f"{label}:+{points}")
        if diagnostic_path(path):
            authority_score -= 150
            reasons.append("diagnostic:-150")
        enriched.append({
            **candidate,
            "global_strategy_prevalence": prevalence[key],
            "direct_name_match": direct_name_match,
            "shared_engine_candidate": shared,
            "valid_production_path": valid_production,
            "explicit_binding": explicit_binding,
            "binding_refs": refs,
            "active_runtime_refs": active_refs,
            "authority_score": authority_score,
            "authority_reasons": reasons,
        })
    enriched.sort(
        key=lambda row: (row["authority_score"], row.get("score", 0), row.get("implementation_path", "")),
        reverse=True,
    )

    direct = [row for row in enriched if row["direct_name_match"] and row["valid_production_path"]]
    shared = [
        row for row in enriched
        if row["shared_engine_candidate"] and row["explicit_binding"] and row["valid_production_path"]
    ]
    factory = [
        row for row in enriched
        if row.get("binding_kind") in {"git_path", "registry_or_shared"}
        and row["explicit_binding"] and row["valid_production_path"]
        and not row["shared_engine_candidate"]
    ]

    model = "UNRESOLVED"
    selected = None
    if len(direct) == 1:
        model, selected = "DIRECT_MODULE", direct[0]
    elif len(shared) == 1:
        model, selected = "SHARED_ENGINE_CONFIG", shared[0]
    elif len(factory) == 1:
        model, selected = "FACTORY_BINDING", factory[0]

    return {
        "strategy_id": strategy_id,
        "execution_model": model,
        "resolved": selected is not None,
        "canonical_mapping_proposal": selected,
        "candidate_count": len(enriched),
        "direct_candidate_count": len(direct),
        "shared_engine_candidate_count": len(shared),
        "factory_candidate_count": len(factory),
        "top_candidates": enriched[:6],
        "unresolved_reason": None if selected else "NO_UNIQUE_AUTHORITY_BOUND_EXECUTION_MODEL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load(Path(args.contract))
    a3d = load(root / contract["prior_a3d_status_path"])
    a3d2 = load(root / contract["prior_a3d2_plan_path"])
    expected = int(contract.get("expected_strategy_count", 25))
    blockers = []
    if not (a3d.get("state") == "PASS" and a3d.get("strategy_count") == expected):
        blockers.append("PRIOR_A3D_INVALID")
    if not (
        a3d2.get("strategy_count") == expected
        and a3d2.get("explicit_mapping_required_count") == expected
    ):
        blockers.append("PRIOR_A3D2_EXPLICIT_PLAN_INVALID")

    before = {path: sha256(path) for path in contract.get("protected_paths", [])}
    prior_by_id = {
        str(row.get("strategy_id")): row
        for row in a3d.get("mappings", []) if isinstance(row, dict)
    }
    plans = [row for row in a3d2.get("mappings", []) if isinstance(row, dict)]
    prevalence: Counter[tuple[str, str, str]] = Counter()
    for plan in plans:
        for candidate in plan.get("top_candidates", []):
            if isinstance(candidate, dict):
                prevalence[candidate_key(candidate)] += 1

    runtime = runtime_inventory()
    proposals = []
    for plan in plans:
        strategy_id = str(plan.get("strategy_id") or "")
        proposals.append(choose_model(
            strategy_id,
            [row for row in plan.get("top_candidates", []) if isinstance(row, dict)],
            prior_by_id.get(strategy_id, {}),
            prevalence,
            runtime,
            int(contract.get("shared_engine_min_strategy_count", 20)),
        ))

    resolved = sum(row["resolved"] for row in proposals)
    model_counts = Counter(row["execution_model"] for row in proposals)
    shared_clusters = [
        {
            "implementation_path": key[0],
            "callable": key[1],
            "binding_kind": key[2],
            "strategy_prevalence": count,
        }
        for key, count in prevalence.most_common()
        if count >= int(contract.get("shared_engine_min_strategy_count", 20))
    ]
    proposal = {
        "schema": "r7a3d3_strategy25_explicit_mapping_proposal_v1",
        "official_stage": "R7.A3D3",
        "read_only": True,
        "strategy_count": len(proposals),
        "resolved_mapping_count": resolved,
        "unresolved_mapping_count": len(proposals) - resolved,
        "execution_model_counts": dict(sorted(model_counts.items())),
        "shared_engine_clusters": shared_clusters,
        "active_runtime_unit_count": len(runtime),
        "mappings": proposals,
    }
    atomic(root / contract["proposal_path"], proposal)

    after = {path: sha256(path) for path in contract.get("protected_paths", [])}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        blockers.append("PROTECTED_PATH_CHANGED")
    state = "PASS" if not blockers else "HOLD"
    if blockers:
        next_stage = contract["next_stage_fail"]
    elif resolved == expected:
        next_stage = contract["next_stage_all_resolved"]
    else:
        next_stage = contract["next_stage_unresolved"]

    status = {
        "official_stage": "R7.A3D3",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(proposals),
        "resolved_mapping_count": resolved,
        "unresolved_mapping_count": len(proposals) - resolved,
        "execution_model_counts": dict(sorted(model_counts.items())),
        "shared_engine_cluster_count": len(shared_clusters),
        "active_runtime_unit_count": len(runtime),
        "canonical_mapping_mutation_count": 0,
        "protected_change_count": len(changed),
        "runtime_mutation_count": 0,
        "performance_s_promoted_count": 0,
        "proposal_path": str(root / contract["proposal_path"]),
        "next_stage": next_stage,
    }
    atomic(root / contract["status_path"], status)
    for key in (
        "state", "blocker_count", "strategy_count", "resolved_mapping_count",
        "unresolved_mapping_count", "shared_engine_cluster_count",
        "active_runtime_unit_count", "canonical_mapping_mutation_count",
        "protected_change_count", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("EXECUTION_MODEL_COUNTS=" + json.dumps(status["execution_model_counts"], ensure_ascii=False))
    print("UNRESOLVED=" + json.dumps([
        {"strategy_id": row["strategy_id"], "candidate_count": row["candidate_count"]}
        for row in proposals if not row["resolved"]
    ], ensure_ascii=False))
    print("PROPOSAL_JSON=" + status["proposal_path"])
    print("RC=" + str(0 if state == "PASS" else 2))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
