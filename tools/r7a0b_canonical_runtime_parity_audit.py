#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

MAX_TEXT_BYTES = 2_000_000
TEXT_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh", ".md", ".txt", ".rst"}
PRODUCTION_PREFIXES = ("backend/", "tools/", "config/", "scripts/", "systemd/", "services/")
TEST_PREFIXES = ("tests/", "test/")

CAPABILITY_ALIASES: dict[str, tuple[str, ...]] = {
    "replay": ("replay", "event_replay", "replay_router"),
    "simulation": ("simulation", "simulate", "simulator", "counterfactual"),
    "fee": ("fee_r", "fee_bps", "trading_fee", "commission"),
    "slippage": ("slippage_r", "slippage_bps", "slippage"),
    "funding": ("funding_r", "funding_8h", "funding_rate"),
    "latency": ("latency_ms", "latency_penalty", "execution_latency"),
    "mfe": ("mfe_r", "maximum_favorable_excursion"),
    "mae": ("mae_r", "maximum_adverse_excursion"),
    "drawdown": ("max_drawdown", "drawdown_r", "dd_total", "dd_day"),
    "lookahead_guard": ("lookahead", "point_in_time", "completed_bar_only", "no_future_bar", "no_same_bar_lookahead"),
    "walk_forward": ("walk_forward", "walkforward"),
    "purged_cv": ("purged_cv", "purged_cross_validation", "purged_kfold"),
    "embargo": ("embargo",),
    "monte_carlo": ("monte_carlo", "bootstrap_paths", "path_resampling"),
    "parameter_perturbation": ("parameter_perturbation", "parameter_jitter", "sensitivity_grid"),
    "regime_stress": ("regime_stress", "stress_regime", "regime_grid"),
    "cvar": ("cvar", "expected_shortfall"),
}


def run(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def safe_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def safe_json_file(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def path_is_excluded(path: str, excluded_parts: set[str]) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    return bool(parts & excluded_parts)


def production_path(path: str) -> bool:
    low = path.lower()
    return low.startswith(PRODUCTION_PREFIXES) and not low.startswith(TEST_PREFIXES)


def test_path(path: str) -> bool:
    low = path.lower()
    return low.startswith(TEST_PREFIXES) or "/test" in low or low.endswith("_test.py") or "/tests/" in low


def contract_or_doc_path(path: str) -> bool:
    low = path.lower()
    return "/contracts/" in low or low.startswith("docs/") or Path(low).suffix in {".md", ".txt", ".rst"}


def git_inventory(repo: Path, target_sha: str, excluded_parts: set[str]) -> tuple[str, dict[str, dict[str, Any]]]:
    resolved = run(["git", "-C", str(repo), "rev-parse", f"{target_sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError("TARGET_SHA_NOT_RESOLVED:" + resolved.stderr[-400:])
    commit = resolved.stdout.strip()
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--long", commit],
        capture_output=True,
        timeout=90,
    )
    if listing.returncode != 0:
        raise RuntimeError("GIT_TREE_LIST_FAILED")

    entries: list[tuple[str, str, int]] = []
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, raw_path = raw.split(b"\t", 1)
            fields = meta.decode("utf-8", errors="replace").split()
            blob_sha = fields[2]
            size = int(fields[3]) if fields[3].isdigit() else 0
            path = raw_path.decode("utf-8", errors="replace")
        except Exception:
            continue
        if path_is_excluded(path, excluded_parts):
            continue
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if size > MAX_TEXT_BYTES:
            continue
        entries.append((path, blob_sha, size))

    batch_input = "".join(f"{blob}\n" for _, blob, _ in entries)
    cat = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input=batch_input.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    if cat.returncode != 0:
        raise RuntimeError("GIT_CAT_FILE_BATCH_FAILED")

    buffer = cat.stdout
    cursor = 0
    inventory: dict[str, dict[str, Any]] = {}
    for path, expected_blob, listed_size in entries:
        line_end = buffer.find(b"\n", cursor)
        if line_end < 0:
            raise RuntimeError("GIT_CAT_FILE_TRUNCATED_HEADER")
        header = buffer[cursor:line_end].decode("utf-8", errors="replace")
        cursor = line_end + 1
        header_parts = header.split()
        if len(header_parts) < 3 or header_parts[1] != "blob":
            raise RuntimeError(f"GIT_CAT_FILE_INVALID:{path}:{header}")
        size = int(header_parts[2])
        raw = buffer[cursor:cursor + size]
        cursor += size + 1
        inventory[path] = {
            "blob_sha": expected_blob,
            "size": listed_size,
            "sha256": sha256_bytes(raw),
            "text": raw.decode("utf-8", errors="ignore"),
        }
    return commit, inventory


def scan_deployed(repo: Path, excluded_parts: set[str], allowed_extensions: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for top in ("backend", "tools", "config", "scripts", "systemd", "services"):
        base = repo / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = str(path.relative_to(repo))
            if path_is_excluded(rel, excluded_parts):
                continue
            if path.suffix.lower() not in allowed_extensions:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > MAX_TEXT_BYTES:
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            result[rel] = {
                "path": str(path),
                "size": size,
                "sha256": sha256_bytes(raw),
                "text": raw.decode("utf-8", errors="ignore"),
            }
    return result


def deployment_parity(repo_files: dict[str, dict[str, Any]], deployed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tracked_prod = {path: data for path, data in repo_files.items() if production_path(path) and Path(path).suffix.lower() in {".py", ".json", ".yaml", ".yml", ".toml", ".service", ".sh"}}
    match: list[str] = []
    mismatch: list[dict[str, str]] = []
    missing: list[str] = []
    for path, data in tracked_prod.items():
        actual = deployed.get(path)
        if actual is None:
            missing.append(path)
        elif actual["sha256"] == data["sha256"]:
            match.append(path)
        else:
            mismatch.append({"path": path, "git_sha256": data["sha256"], "deployed_sha256": actual["sha256"]})
    untracked = sorted(set(deployed) - set(tracked_prod))
    return {
        "tracked_production_count": len(tracked_prod),
        "match_count": len(match),
        "mismatch_count": len(mismatch),
        "missing_count": len(missing),
        "untracked_deployed_count": len(untracked),
        "mismatches": mismatch[:300],
        "missing": missing[:300],
        "untracked_deployed": untracked[:500],
    }


def parse_systemctl_show(raw: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            current[key] = value
    if current:
        blocks.append(current)
    return blocks


def systemd_inventory(contract: dict[str, Any]) -> dict[str, Any]:
    unit_files_raw = run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"], timeout=60)
    active_raw = run(["systemctl", "list-units", "--type=service", "--state=active", "--no-legend", "--no-pager"], timeout=60)
    active_names = {line.split()[0] for line in active_raw.stdout.splitlines() if line.split()}
    states: dict[str, str] = {}
    names: list[str] = []
    relevant_rx = re.compile(r"(zel|zops|q4r3|exact25|alimi|shadow|telegram)", re.I)
    for line in unit_files_raw.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        name = fields[0]
        if not relevant_rx.search(name):
            continue
        names.append(name)
        states[name] = fields[1] if len(fields) > 1 else "unknown"

    records: list[dict[str, Any]] = []
    props = ["Id", "ActiveState", "SubState", "UnitFileState", "FragmentPath", "ExecStart", "MainPID", "ExecMainStartTimestamp"]
    for offset in range(0, len(names), 40):
        batch = names[offset:offset + 40]
        command = ["systemctl", "show", *batch]
        for prop in props:
            command += ["-p", prop]
        shown = run(command, timeout=60)
        for block in parse_systemctl_show(shown.stdout):
            unit = block.get("Id", "")
            if not unit:
                continue
            record: dict[str, Any] = dict(block)
            record["InstalledState"] = states.get(unit, "unknown")
            record["is_active"] = unit in active_names or block.get("ActiveState") == "active"
            joined = f"{unit} {block.get('ExecStart','')} {block.get('FragmentPath','')}".lower()
            record["is_non_authority"] = any(marker in joined for marker in contract["non_authority_markers"])
            record["is_legacy_named"] = any(marker in joined for marker in contract["legacy_markers"])
            records.append(record)

    role_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        joined = f"{record.get('Id','')} {record.get('ExecStart','')}".lower().replace("-", "_")
        for role, markers in contract["lifecycle_roles"].items():
            if any(marker in joined for marker in markers):
                role_map[role].append({
                    "unit": record.get("Id"),
                    "active": record.get("is_active"),
                    "non_authority": record.get("is_non_authority"),
                    "legacy_named": record.get("is_legacy_named"),
                    "exec_start": record.get("ExecStart"),
                    "fragment": record.get("FragmentPath"),
                })

    active_authority_by_role: dict[str, list[str]] = {}
    for role, items in role_map.items():
        active_authority_by_role[role] = sorted({str(item["unit"]) for item in items if item["active"] and not item["non_authority"]})

    start_candidates: list[str] = []
    for record in records:
        joined = f"{record.get('Id','')} {record.get('ExecStart','')}".lower()
        if "shadow" not in joined or not ("q4r3" in joined or "exact25" in joined):
            continue
        if any(token in joined for token in ("paper", "live", "order", "telegram", "alimi", "display", "view", "observer", "watchdog", "audit", "probe", "writer", "binder", "mirror", "projector")):
            continue
        start_candidates.append(str(record.get("Id")))

    active_risk_units = sorted({
        str(record.get("Id")) for record in records
        if record.get("is_active") and re.search(r"(paper|live|order|oms|execution|bingx)", f"{record.get('Id','')} {record.get('ExecStart','')}", re.I)
    })
    return {
        "records": records,
        "role_map": dict(role_map),
        "active_authority_by_role": active_authority_by_role,
        "start_candidates": sorted(set(start_candidates)),
        "active_risk_units": active_risk_units,
        "installed_relevant_count": len(records),
        "active_relevant_count": sum(1 for row in records if row.get("is_active")),
        "active_legacy_named_units": sorted(str(row.get("Id")) for row in records if row.get("is_active") and row.get("is_legacy_named")),
    }


def extract_exec_paths(exec_start: str) -> list[str]:
    paths = set(re.findall(r"path=([^ ;}\]]+)", exec_start))
    paths.update(re.findall(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9_./+@:-]+(?:\.py|\.sh|\.service))", exec_start))
    return sorted(paths)


def unit_file_parity(systemd: dict[str, Any], repo: Path, repo_files: dict[str, dict[str, Any]], deployed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_basename: dict[str, list[str]] = defaultdict(list)
    for path in repo_files:
        by_basename[Path(path).name].append(path)
    rows: list[dict[str, Any]] = []
    for record in systemd["records"]:
        if not record.get("is_active"):
            continue
        for raw_path in extract_exec_paths(str(record.get("ExecStart", ""))):
            path = Path(raw_path)
            if not path.is_file():
                rows.append({"unit": record.get("Id"), "source": raw_path, "parity": "MISSING_DEPLOYED_SOURCE"})
                continue
            actual_sha = sha256_file(path)
            candidates: list[str] = []
            try:
                candidates.append(str(path.relative_to(repo)))
            except ValueError:
                candidates.extend(by_basename.get(path.name, []))
            candidates = [candidate for candidate in candidates if candidate in repo_files]
            candidates = sorted(set(candidates))
            if len(candidates) == 1:
                expected = repo_files[candidates[0]]["sha256"]
                parity = "MATCH" if expected == actual_sha else "MISMATCH"
                rows.append({"unit": record.get("Id"), "source": raw_path, "repo_path": candidates[0], "parity": parity, "git_sha256": expected, "deployed_sha256": actual_sha})
            elif len(candidates) > 1:
                rows.append({"unit": record.get("Id"), "source": raw_path, "parity": "AMBIGUOUS_REPO_BASENAME", "repo_candidates": candidates})
            else:
                rows.append({"unit": record.get("Id"), "source": raw_path, "parity": "UNTRACKED_DEPLOYED_SOURCE", "deployed_sha256": actual_sha})
    counts = Counter(row["parity"] for row in rows)
    return {"rows": rows, "counts": dict(counts)}


def json_objects(repo_files: dict[str, dict[str, Any]], deployed: dict[str, dict[str, Any]], runtime_root: Path, excluded_parts: set[str]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for source_kind, inventory in (("git", repo_files), ("deployed", deployed)):
        for path, item in inventory.items():
            if Path(path).suffix.lower() != ".json":
                continue
            obj = safe_json_text(item["text"])
            if obj is not None:
                objects.append({"source": source_kind, "path": path, "object": obj})
    if runtime_root.exists():
        for path in runtime_root.rglob("*.json"):
            try:
                rel = str(path.relative_to(runtime_root))
            except ValueError:
                continue
            if path_is_excluded(rel, excluded_parts - {"runtime"}):
                continue
            try:
                if path.stat().st_size > MAX_TEXT_BYTES:
                    continue
            except OSError:
                continue
            obj = safe_json_file(path)
            if obj is not None:
                objects.append({"source": "runtime", "path": str(path), "object": obj})
    return objects


def list_ids(value: Any, id_keys: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            for key in id_keys:
                if isinstance(item.get(key), str):
                    result.append(item[key])
                    break
    return result


def recursive_list_candidates(obj: Any, path: str = "$") -> Iterable[tuple[str, list[Any]]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}"
            if isinstance(value, list):
                yield child, value
            yield from recursive_list_candidates(value, child)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from recursive_list_candidates(value, f"{path}[{index}]")


def discover_strategy_manifest(objects: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for record in objects:
        for json_path, value in recursive_list_candidates(record["object"]):
            ids = list_ids(value, ("strategy_id", "id", "name"))
            unique = sorted({str(item).strip() for item in ids if str(item).strip()})
            if len(unique) < 5:
                continue
            descriptor = f"{record['path']} {json_path}".lower()
            score = 0
            if len(unique) == expected_count:
                score += 100
            score -= abs(len(unique) - expected_count) * 3
            if "strategy" in descriptor:
                score += 20
            if "exact25" in descriptor or "exact_25" in descriptor:
                score += 30
            if "canonical" in descriptor or "registry" in descriptor:
                score += 15
            if record["source"] == "git":
                score += 8
            candidates.append({"source": record["source"], "path": record["path"], "json_path": json_path, "count": len(unique), "ids": unique, "score": score})
    candidates.sort(key=lambda row: (row["score"], row["source"] == "git"), reverse=True)
    exact = [row for row in candidates if row["count"] == expected_count]
    selected = exact[0] if exact else None
    ambiguity = False
    if len(exact) > 1 and exact[0]["score"] == exact[1]["score"] and exact[0]["ids"] != exact[1]["ids"]:
        ambiguity = True
    return {"selected": selected, "ambiguous": ambiguity, "candidates": candidates[:50]}


def exact_references(identifier: str, repo_files: dict[str, dict[str, Any]], skip_paths: set[str]) -> dict[str, list[str]]:
    code: list[str] = []
    tests: list[str] = []
    contracts: list[str] = []
    needle = identifier.lower()
    for path, item in repo_files.items():
        if path in skip_paths or needle not in item["text"].lower():
            continue
        if test_path(path):
            tests.append(path)
        elif contract_or_doc_path(path):
            contracts.append(path)
        elif production_path(path):
            code.append(path)
    return {"code": sorted(set(code)), "tests": sorted(set(tests)), "contracts": sorted(set(contracts))}


def audit_strategy_axis(matrix: dict[str, Any], manifest: dict[str, Any], repo_files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = int(matrix.get("dependency_contract", {}).get("exact_strategy_count", 0) or 0)
    selected = manifest.get("selected")
    per_strategy: list[dict[str, Any]] = []
    implemented_count = 0
    tested_count = 0
    if selected:
        for strategy_id in selected["ids"]:
            refs = exact_references(strategy_id, repo_files, {selected["path"]})
            implemented = bool(refs["code"])
            tested = bool(refs["tests"])
            implemented_count += int(implemented)
            tested_count += int(tested)
            per_strategy.append({"strategy_id": strategy_id, "implemented": implemented, "tested": tested, "references": refs})
    blockers: list[str] = []
    if expected != 25:
        blockers.append(f"MATRIX_EXPECTED_STRATEGY_COUNT_{expected}")
    if not selected:
        blockers.append("CANONICAL_EXACT25_ID_MANIFEST_NOT_FOUND")
    elif selected["count"] != expected:
        blockers.append("CANONICAL_STRATEGY_COUNT_MISMATCH")
    if manifest.get("ambiguous"):
        blockers.append("MULTIPLE_CONFLICTING_EXACT25_MANIFESTS")
    if selected and implemented_count < expected:
        blockers.append(f"IMPLEMENTED_STRATEGY_COUNT_{implemented_count}_LT_{expected}")
    if blockers:
        grade = "D" if not selected or manifest.get("ambiguous") else "B"
    elif tested_count < expected:
        grade = "B"
    else:
        grade = "A"
    return {
        "grade": grade,
        "expected_count": expected,
        "manifest": manifest,
        "implemented_count": implemented_count,
        "tested_count": tested_count,
        "blockers": blockers,
        "per_strategy": per_strategy,
    }


def audit_exit_axis(matrix: dict[str, Any], repo_files: dict[str, dict[str, Any]], active_sources: str) -> dict[str, Any]:
    policies = matrix.get("exit_policy_lanes", []) if isinstance(matrix, dict) else []
    rows: list[dict[str, Any]] = []
    runtime_bound = 0
    implemented = 0
    ids: list[str] = []
    for policy in policies if isinstance(policies, list) else []:
        if not isinstance(policy, dict) or not isinstance(policy.get("exit_policy_id"), str):
            continue
        policy_id = policy["exit_policy_id"]
        ids.append(policy_id)
        refs = exact_references(policy_id, repo_files, set())
        code_refs = [path for path in refs["code"] if "ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX" not in path]
        is_implemented = bool(code_refs)
        is_runtime_bound = policy_id.lower() in active_sources.lower()
        implemented += int(is_implemented)
        runtime_bound += int(is_runtime_bound)
        rows.append({"exit_policy_id": policy_id, "target_r": policy.get("target_r"), "loss_cap_r": policy.get("loss_cap_r"), "implemented": is_implemented, "runtime_bound": is_runtime_bound, "references": refs})
    blockers: list[str] = []
    if len(ids) != 4 or len(set(ids)) != 4:
        blockers.append(f"EXIT_POLICY_COUNT_OR_DUPLICATE_{len(ids)}")
    if implemented < 4:
        blockers.append(f"EXIT_POLICY_IMPLEMENTED_{implemented}_LT_4")
    status = str(matrix.get("status", ""))
    if "NOT_BOUND" in status:
        blockers.append("MATRIX_CONTRACT_EXPLICITLY_NOT_BOUND")
    if len(ids) != 4:
        grade = "D"
    elif implemented == 0:
        grade = "C"
    elif runtime_bound < 4:
        grade = "B"
    else:
        grade = "A"
    return {"grade": grade, "count": len(ids), "implemented_count": implemented, "runtime_bound_count": runtime_bound, "matrix_status": status, "blockers": blockers, "policies": rows}


def audit_skill_axis(registry: dict[str, Any], repo_files: dict[str, dict[str, Any]], active_sources: str) -> dict[str, Any]:
    skills = registry.get("skills", []) if isinstance(registry, dict) else []
    required_fields = {"skill_id", "category", "state", "owner_layer", "required_inputs", "trigger_contract", "outputs", "dependencies", "conflicts", "max_fires_per_position"}
    rows: list[dict[str, Any]] = []
    ids: list[str] = []
    implemented = 0
    tested = 0
    runtime_bound = 0
    incomplete = 0
    for skill in skills if isinstance(skills, list) else []:
        if not isinstance(skill, dict) or not isinstance(skill.get("skill_id"), str):
            continue
        skill_id = skill["skill_id"]
        ids.append(skill_id)
        missing = sorted(required_fields - set(skill))
        incomplete += int(bool(missing))
        refs = exact_references(skill_id, repo_files, {"backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"})
        code_refs = [path for path in refs["code"] if "/contracts/" not in path]
        is_implemented = bool(code_refs)
        is_tested = bool(refs["tests"])
        is_runtime_bound = skill_id.lower() in active_sources.lower()
        implemented += int(is_implemented)
        tested += int(is_tested)
        runtime_bound += int(is_runtime_bound)
        rows.append({
            "skill_id": skill_id,
            "category": skill.get("category"),
            "state": skill.get("state"),
            "max_fires_per_position": skill.get("max_fires_per_position"),
            "missing_fields": missing,
            "implemented": is_implemented,
            "tested": is_tested,
            "runtime_bound": is_runtime_bound,
            "references": refs,
        })
    blockers: list[str] = []
    if len(ids) != 18 or len(set(ids)) != 18:
        blockers.append(f"SKILL_COUNT_OR_DUPLICATE_{len(ids)}_{len(set(ids))}")
    if incomplete:
        blockers.append(f"INCOMPLETE_SKILL_CONTRACTS_{incomplete}")
    if implemented < len(ids):
        blockers.append(f"SKILL_IMPLEMENTED_{implemented}_LT_{len(ids)}")
    if registry.get("activation_allowed") is False or registry.get("runtime_mutation_allowed") is False:
        blockers.append("SKILL_REGISTRY_EXPLICITLY_CANDIDATE_NOT_BOUND")
    if len(ids) != 18 or incomplete:
        grade = "D"
    elif implemented == 0 or runtime_bound == 0:
        grade = "C"
    elif runtime_bound < len(ids) or tested < len(ids):
        grade = "B"
    else:
        grade = "A"
    return {
        "grade": grade,
        "count": len(ids),
        "unique_count": len(set(ids)),
        "implemented_count": implemented,
        "tested_count": tested,
        "runtime_bound_count": runtime_bound,
        "incomplete_count": incomplete,
        "registry_status": registry.get("status"),
        "blockers": blockers,
        "skills": rows,
    }


def role_static_evidence(repo_files: dict[str, dict[str, Any]], role_markers: dict[str, list[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for role, markers in role_markers.items():
        paths: list[str] = []
        for path, item in repo_files.items():
            if not production_path(path) or contract_or_doc_path(path):
                continue
            joined = f"{path} {item['text']}".lower().replace("-", "_")
            if any(marker in joined for marker in markers):
                paths.append(path)
        result[role] = sorted(set(paths))
    return result


def audit_lifecycle_axis(systemd: dict[str, Any], repo_files: dict[str, dict[str, Any]], contract: dict[str, Any], unit_parity: dict[str, Any]) -> dict[str, Any]:
    static = role_static_evidence(repo_files, contract["lifecycle_roles"])
    active = systemd["active_authority_by_role"]
    duplicate_roles = {role: units for role, units in active.items() if len(units) > 1}
    missing_static = [role for role in ("candidate", "admission", "open", "manage", "close") if not static.get(role)]
    source_mismatches = [row for row in unit_parity["rows"] if row["parity"] in {"MISMATCH", "UNTRACKED_DEPLOYED_SOURCE", "MISSING_DEPLOYED_SOURCE", "AMBIGUOUS_REPO_BASENAME"}]
    blockers: list[str] = []
    if missing_static:
        blockers.append("MISSING_LIFECYCLE_IMPLEMENTATION:" + ",".join(missing_static))
    if duplicate_roles:
        blockers.append("MULTIPLE_ACTIVE_AUTHORITIES:" + ",".join(sorted(duplicate_roles)))
    if len(systemd["start_candidates"]) != 1:
        blockers.append(f"SHADOW_START_AUTHORITY_COUNT_{len(systemd['start_candidates'])}")
    if source_mismatches:
        blockers.append(f"ACTIVE_UNIT_SOURCE_PARITY_GAPS_{len(source_mismatches)}")
    if duplicate_roles or missing_static or len(systemd["start_candidates"]) != 1:
        grade = "D"
    elif source_mismatches:
        grade = "B"
    else:
        grade = "A"
    return {
        "grade": grade,
        "blockers": blockers,
        "static_role_evidence": static,
        "active_authority_by_role": active,
        "duplicate_active_authority_roles": duplicate_roles,
        "shadow_start_candidates": systemd["start_candidates"],
        "active_risk_units": systemd["active_risk_units"],
        "active_source_parity_gaps": source_mismatches,
    }


def audit_entities_axis(expected: list[str], repo_files: dict[str, dict[str, Any]], systemd: dict[str, Any], entity_type: str) -> dict[str, Any]:
    active_text = "\n".join(f"{row.get('Id','')} {row.get('ExecStart','')}" for row in systemd["records"] if row.get("is_active"))
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    runtime_bound = 0
    for entity in expected:
        refs = exact_references(entity, repo_files, set())
        code_refs = [path for path in refs["code"] if "/contracts/" not in path]
        implemented = bool(code_refs)
        bound = entity.lower() in active_text.lower()
        runtime_bound += int(bound)
        if not implemented:
            missing.append(entity)
        rows.append({"id": entity, "implemented": implemented, "runtime_bound": bound, "references": refs})
    blockers: list[str] = []
    if missing:
        blockers.append(f"MISSING_{entity_type.upper()}_IMPLEMENTATIONS:" + ",".join(missing))
    if runtime_bound < len(expected):
        blockers.append(f"{entity_type.upper()}_RUNTIME_BOUND_{runtime_bound}_LT_{len(expected)}")
    if missing:
        grade = "D"
    elif runtime_bound == 0:
        grade = "C"
    elif runtime_bound < len(expected):
        grade = "B"
    else:
        grade = "A"
    return {"grade": grade, "expected_count": len(expected), "runtime_bound_count": runtime_bound, "blockers": blockers, "entities": rows}


def python_symbols(text: str) -> set[str]:
    symbols: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            symbols.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 200:
            symbols.update(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+", node.value.lower()))
    return symbols


def audit_data_axis(repo_files: dict[str, dict[str, Any]], systemd: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    capability_files: dict[str, set[str]] = defaultdict(set)
    test_files: dict[str, set[str]] = defaultdict(set)
    active_sources = "\n".join(str(row.get("ExecStart", "")) for row in systemd["records"] if row.get("is_active"))
    runtime_bound: dict[str, bool] = {}
    for path, item in repo_files.items():
        if Path(path).suffix.lower() != ".py":
            continue
        symbols = python_symbols(item["text"])
        path_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+", path.lower()))
        combined = symbols | path_tokens
        for capability, aliases in CAPABILITY_ALIASES.items():
            if any(alias in combined for alias in aliases):
                if test_path(path):
                    test_files[capability].add(path)
                elif production_path(path) and not contract_or_doc_path(path):
                    capability_files[capability].add(path)
    for capability, files in capability_files.items():
        runtime_bound[capability] = any(Path(path).name in active_sources for path in files)
    core = list(contract["data_capabilities"]["core"])
    advanced = list(contract["data_capabilities"]["advanced"])
    missing_core = [cap for cap in core if not capability_files.get(cap)]
    missing_advanced = [cap for cap in advanced if not capability_files.get(cap)]
    untested_core = [cap for cap in core if not test_files.get(cap)]
    blockers: list[str] = []
    if missing_core:
        blockers.append("MISSING_CORE_DATA_CAPABILITIES:" + ",".join(missing_core))
    if untested_core:
        blockers.append("UNTESTED_CORE_DATA_CAPABILITIES:" + ",".join(untested_core))
    if missing_core:
        grade = "D"
    elif missing_advanced or untested_core:
        grade = "B"
    else:
        grade = "A"
    return {
        "grade": grade,
        "blockers": blockers,
        "missing_core": missing_core,
        "missing_advanced": missing_advanced,
        "untested_core": untested_core,
        "capabilities": {
            cap: {"implementation_files": sorted(capability_files.get(cap, set())), "test_files": sorted(test_files.get(cap, set())), "runtime_bound": bool(runtime_bound.get(cap))}
            for cap in sorted(CAPABILITY_ALIASES)
        },
    }


def first_value(obj: Any, keys: tuple[str, ...], default: Any = None) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
    return default


def normalize_surface(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    writers = obj.get("writers")
    writer_map: dict[str, str] = {}
    if isinstance(writers, list):
        for row in writers:
            if isinstance(row, dict) and row.get("writer_id"):
                writer_map[str(row["writer_id"])] = str(row.get("strategy", ""))
    elif isinstance(writers, dict):
        writer_map = {str(k): str(v) for k, v in writers.items()}
    return {
        "epoch": first_value(obj, ("epoch_id", "matrix_epoch_id", "epoch")),
        "closed": first_value(obj, ("closed_count", "closed")),
        "pnl_r": first_value(obj, ("pnl_r", "net_r", "total_r")),
        "recent_rows": first_value(obj, ("recent_rows", "rows")),
        "winrate_pct": first_value(obj, ("winrate_pct", "wr", "win_rate")),
        "ev_r": first_value(obj, ("ev_r", "ev", "expectancy_r")),
        "last_close": first_value(obj, ("last_close", "last_closed")),
        "writer_count": first_value(obj, ("writer_count", "configured_writer_count")),
        "active_writer_count": first_value(obj, ("active_writer_count", "active_writers")),
        "writers": writer_map,
        "runtime_active": first_value(obj, ("runtime_active",)),
        "formal_ledger_bound": first_value(obj, ("formal_ledger_bound",)),
        "order": first_value(obj, ("order", "order_authority")),
        "exec": first_value(obj, ("exec", "execution_authority")),
        "source": first_value(obj, ("source", "source_path", "src", "owner")),
    }


def fetch_alimi(url: str) -> tuple[int, Any]:
    command = ["curl", "-sS", "-L", "--max-time", "15", "-H", "Cache-Control: no-cache", "-w", "\n%{http_code}"]
    if url.startswith("https://alimi.z-os.vip/"):
        command += ["--resolve", "alimi.z-os.vip:443:127.0.0.1"]
    command.append(f"{url}{'&' if '?' in url else '?'}r7a0b={time.time_ns()}")
    result = run(command, timeout=20)
    body, _, code_raw = result.stdout.rpartition("\n")
    try:
        code = int(code_raw)
    except ValueError:
        code = 0
    return code, safe_json_text(body)


def comparable_mismatches(surfaces: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("epoch", "closed", "pnl_r", "recent_rows", "winrate_pct", "ev_r", "writer_count", "active_writer_count", "runtime_active", "formal_ledger_bound", "order", "exec")
    mismatches: list[dict[str, Any]] = []
    for key in keys:
        values = {name: surface.get(key) for name, surface in surfaces.items() if surface.get(key) is not None}
        normalized = {json.dumps(value, sort_keys=True, default=str) for value in values.values()}
        if len(normalized) > 1:
            mismatches.append({"field": key, "values": values})
    return mismatches


def audit_display_axis(contract: dict[str, Any], systemd: dict[str, Any]) -> dict[str, Any]:
    paths = {name: Path(path) for name, path in contract["runtime_files"].items()}
    snapshot_obj = safe_json_file(paths["shadow_snapshot"])
    telegram_obj = safe_json_file(paths["telegram_artifact"])
    alimi_status, alimi_obj = fetch_alimi(contract["alimi_endpoint"])
    surfaces = {
        "shadow": normalize_surface(snapshot_obj),
        "telegram": normalize_surface(telegram_obj),
        "alimi": normalize_surface(alimi_obj),
    }
    mismatches = comparable_mismatches(surfaces)
    expected_writers = {str(k): str(v) for k, v in contract["expected"]["writers"].items()}
    writer_sources = {name: surface["writers"] for name, surface in surfaces.items() if surface.get("writers")}
    writer_mismatches = {name: writers for name, writers in writer_sources.items() if writers != expected_writers}
    view_text = paths["view_index"].read_text(encoding="utf-8", errors="ignore") if paths["view_index"].is_file() else ""
    legacy_view_markers = [marker for marker in ("q4r3_shadow_closed_ledger_latest.json", "A/B/G/D team lane", "recent_rows=43", "last12=7.25") if marker in view_text]
    display_owners = systemd["active_authority_by_role"].get("display_writer", [])
    ledger_owners = systemd["active_authority_by_role"].get("ledger_writer", [])
    ledger_path = paths["formal_ledger"]
    ledger_lines = 0
    if ledger_path.is_file():
        try:
            with ledger_path.open("rb") as handle:
                ledger_lines = sum(1 for _ in handle)
        except OSError:
            ledger_lines = -1
    blockers: list[str] = []
    if alimi_status != 200:
        blockers.append(f"ALIMI_HTTP_{alimi_status}")
    if mismatches:
        blockers.append(f"SURFACE_PARITY_MISMATCHES_{len(mismatches)}")
    if writer_mismatches:
        blockers.append("WRITER_REGISTRY_MISMATCH:" + ",".join(writer_mismatches))
    if legacy_view_markers:
        blockers.append("LEGACY_VIEW_MARKERS:" + ",".join(legacy_view_markers))
    if len(display_owners) > 1:
        blockers.append(f"MULTIPLE_ACTIVE_DISPLAY_AUTHORITIES_{len(display_owners)}")
    if len(ledger_owners) > 1:
        blockers.append(f"MULTIPLE_ACTIVE_LEDGER_AUTHORITIES_{len(ledger_owners)}")
    if mismatches or writer_mismatches or len(display_owners) > 1 or len(ledger_owners) > 1:
        grade = "D"
    elif alimi_status != 200 or legacy_view_markers:
        grade = "B"
    else:
        grade = "A"
    return {
        "grade": grade,
        "blockers": blockers,
        "surfaces": surfaces,
        "surface_mismatches": mismatches,
        "writer_sources": writer_sources,
        "writer_mismatches": writer_mismatches,
        "expected_writers": expected_writers,
        "legacy_view_markers": legacy_view_markers,
        "active_display_authorities": display_owners,
        "active_ledger_authorities": ledger_owners,
        "alimi_http_status": alimi_status,
        "formal_ledger_sha256": sha256_file(ledger_path),
        "formal_ledger_line_count": ledger_lines,
    }


def schema_duplicates(repo_files: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path, item in repo_files.items():
        if Path(path).suffix.lower() != ".json" or test_path(path):
            continue
        obj = safe_json_text(item["text"])
        if isinstance(obj, dict) and isinstance(obj.get("schema"), str):
            groups[obj["schema"]].append(path)
    return {schema: paths for schema, paths in groups.items() if len(paths) > 1}


def grade_rank(grade: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "D": 3}.get(grade, 4)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# R7.A0B Canonical Runtime Parity Audit",
        "",
        f"- Audit execution: **{payload['audit_execution']['state']}**",
        f"- Runtime readiness: **{payload['runtime_readiness']['state']}**",
        f"- Target commit: `{payload['audit_execution']['target_commit']}`",
        f"- Mutation count: `{payload['audit_execution']['mutation_count']}`",
        "",
        "## Seven-axis grades",
        "",
        "| Axis | Grade | Blockers |",
        "|---|---:|---|",
    ]
    for name, axis in payload["axes"].items():
        blockers = axis.get("blockers", [])
        lines.append(f"| {name} | **{axis.get('grade')}** | {'; '.join(blockers[:5]) or 'none'} |")
    lines += ["", "## Critical gaps", ""]
    for gap in payload["runtime_readiness"]["critical_gaps"]:
        lines.append(f"- {gap}")
    lines += ["", "## Next sequence", ""]
    for index, item in enumerate(payload["next_plan"], 1):
        lines.append(f"{index}. {item}")
    lines += ["", "## Evidence", "", f"- JSON: `{payload['evidence_paths']['json']}`", f"- Markdown: `{payload['evidence_paths']['markdown']}`"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    contract = safe_json_file(args.contract)
    if not isinstance(contract, dict):
        raise SystemExit("INVALID_CONTRACT")
    repo = Path(contract["repo_root"]).resolve()
    runtime_root = Path(contract["runtime_root"]).resolve()
    excluded = {str(part).lower() for part in contract["excluded_path_parts"]}
    allowed_prod_ext = {str(ext).lower() for ext in contract["production_extensions"]}

    critical_paths = [Path(path) for path in contract["runtime_files"].values()]
    before_hashes = {str(path): sha256_file(path) for path in critical_paths}
    errors: list[str] = []

    try:
        target_commit, repo_files = git_inventory(repo, args.target_sha, excluded)
        deployed = scan_deployed(repo, excluded, allowed_prod_ext)
        parity = deployment_parity(repo_files, deployed)
        systemd = systemd_inventory(contract)
        unit_parity = unit_file_parity(systemd, repo, repo_files, deployed)
        objects = json_objects(repo_files, deployed, runtime_root, excluded)

        matrix_path = contract["canonical_files"]["matrix"]
        skill_path = contract["canonical_files"]["skill_registry"]
        matrix = safe_json_text(repo_files.get(matrix_path, {}).get("text", ""))
        registry = safe_json_text(repo_files.get(skill_path, {}).get("text", ""))
        if not isinstance(matrix, dict):
            errors.append("CANONICAL_MATRIX_MISSING_OR_INVALID")
            matrix = {}
        if not isinstance(registry, dict):
            errors.append("CANONICAL_SKILL_REGISTRY_MISSING_OR_INVALID")
            registry = {}

        active_sources = "\n".join(f"{row.get('Id','')} {row.get('ExecStart','')}" for row in systemd["records"] if row.get("is_active"))
        strategy_manifest = discover_strategy_manifest(objects, int(contract["expected"]["strategy_count"]))

        axes: dict[str, dict[str, Any]] = {}
        axes["strategy25"] = audit_strategy_axis(matrix, strategy_manifest, repo_files)
        axes["trade_lifecycle"] = audit_lifecycle_axis(systemd, repo_files, contract, unit_parity)
        axes["exit_policy4"] = audit_exit_axis(matrix, repo_files, active_sources)
        axes["skill18"] = audit_skill_axis(registry, repo_files, active_sources)
        bots = audit_entities_axis(list(contract["expected"]["team_bots"]), repo_files, systemd, "team_bot")
        advisors = audit_entities_axis(list(contract["expected"]["advisors"]), repo_files, systemd, "advisor")
        combined_grade = bots["grade"] if grade_rank(bots["grade"]) >= grade_rank(advisors["grade"]) else advisors["grade"]
        axes["teambots_and_advisors"] = {"grade": combined_grade, "blockers": bots["blockers"] + advisors["blockers"], "team_bots": bots, "advisors": advisors}
        axes["data_math_cost_replay"] = audit_data_axis(repo_files, systemd, contract)
        axes["display_ledger_observability"] = audit_display_axis(contract, systemd)

        duplicates = schema_duplicates(repo_files)
        critical_gaps: list[str] = list(errors)
        for name, axis in axes.items():
            if axis.get("grade") != "A":
                critical_gaps.append(f"{name}:grade={axis.get('grade')}:{'|'.join(axis.get('blockers', [])[:4])}")
        if parity["mismatch_count"] or parity["missing_count"]:
            critical_gaps.append(f"git_deployment_parity:mismatch={parity['mismatch_count']},missing={parity['missing_count']}")
        if unit_parity["counts"].get("MISMATCH", 0) or unit_parity["counts"].get("UNTRACKED_DEPLOYED_SOURCE", 0):
            critical_gaps.append("active_systemd_source_parity_not_proven")
        if duplicates:
            critical_gaps.append(f"duplicate_production_schemas={len(duplicates)}")

        next_plan: list[str] = []
        if parity["mismatch_count"] or parity["missing_count"] or unit_parity["counts"].get("MISMATCH", 0):
            next_plan.append("R7.A1A: lock one Git deployment baseline and reconcile only active-unit source mismatches")
        if axes["trade_lifecycle"]["grade"] == "D":
            next_plan.append("R7.A1B: produce candidate→admission→open→manage→close authority graph and retire duplicate active writers")
        if axes["strategy25"]["grade"] != "A":
            next_plan.append("R7.B: create immutable canonical Exact25 manifest, bind each ID to one implementation SHA, then S-Material upgrade")
        if axes["skill18"]["grade"] != "A":
            next_plan.append("R7.C: replace candidate Skill Registry v2 with S-grade v3 trigger/state/risk/replay contracts")
        if axes["exit_policy4"]["grade"] != "A" or axes["data_math_cost_replay"]["grade"] != "A":
            next_plan.append("R7.D: implement event replay, cost parity, walk-forward, purged CV, perturbation, Monte Carlo and regime stress")
        if axes["teambots_and_advisors"]["grade"] != "A":
            next_plan.append("R7.E: bind L/M/O/S and ZBot/ZICO/LiCo/Zlice as observer/advisor graph with no order-authority bypass")
        if axes["display_ledger_observability"]["grade"] != "A":
            next_plan.append("R7.F: enforce one display owner and one ledger owner with Telegram/ALIMI/View epoch-hash parity")
        next_plan.append("R7.G: rerun canonical audit; only all critical axes A/B-with-approved-gap may enter Replay and 0C preflight")

        after_hashes = {str(path): sha256_file(path) for path in critical_paths}
        changed = [path for path in before_hashes if before_hashes[path] != after_hashes[path]]
        execution_state = "PASS" if not changed and not errors else "HOLD"
        readiness_state = "PASS" if execution_state == "PASS" and not critical_gaps and all(axis.get("grade") == "A" for axis in axes.values()) else "HOLD"

        payload: dict[str, Any] = {
            "schema": "zos_r7a0b_canonical_runtime_parity_audit_status_v2",
            "audit_execution": {
                "state": execution_state,
                "target_sha_requested": args.target_sha,
                "target_commit": target_commit,
                "mutation_count": len(changed),
                "critical_file_changes": changed,
                "errors": errors,
            },
            "runtime_readiness": {
                "state": readiness_state,
                "critical_gap_count": len(critical_gaps),
                "critical_gaps": critical_gaps,
            },
            "axes": axes,
            "git_deployment_parity": parity,
            "systemd": {
                "installed_relevant_count": systemd["installed_relevant_count"],
                "active_relevant_count": systemd["active_relevant_count"],
                "active_legacy_named_units": systemd["active_legacy_named_units"],
                "active_risk_units": systemd["active_risk_units"],
                "start_candidates": systemd["start_candidates"],
                "active_authority_by_role": systemd["active_authority_by_role"],
                "records": systemd["records"],
            },
            "active_unit_source_parity": unit_parity,
            "duplicate_production_schemas": duplicates,
            "inventory_counts": {
                "git_text_files": len(repo_files),
                "deployed_text_files": len(deployed),
                "json_objects_examined": len(objects),
            },
            "next_plan": next_plan,
            "next_stage": contract["next_stage"],
            "evidence_paths": {"json": str(args.output), "markdown": str(args.report)},
        }
        atomic_json(args.output, payload)
        atomic_text(args.report, render_markdown(payload))

        print("R7A0B_CANONICAL_RUNTIME_PARITY_AUDIT_COMPLETE")
        print(f"AUDIT_EXECUTION_STATE={execution_state}")
        print(f"RUNTIME_READINESS_STATE={readiness_state}")
        print(f"TARGET_COMMIT={target_commit}")
        print(f"MUTATION_COUNT={len(changed)}")
        for name, axis in axes.items():
            print(f"AXIS_{name.upper()}_GRADE={axis.get('grade')}")
            print(f"AXIS_{name.upper()}_BLOCKERS={len(axis.get('blockers', []))}")
        print(f"GIT_DEPLOYMENT_MATCH={parity['match_count']}")
        print(f"GIT_DEPLOYMENT_MISMATCH={parity['mismatch_count']}")
        print(f"GIT_DEPLOYMENT_MISSING={parity['missing_count']}")
        print(f"UNTRACKED_DEPLOYED={parity['untracked_deployed_count']}")
        print(f"ACTIVE_RELEVANT_UNITS={systemd['active_relevant_count']}")
        print(f"SHADOW_START_CANDIDATES={len(systemd['start_candidates'])}")
        print(f"CRITICAL_GAP_COUNT={len(critical_gaps)}")
        print(f"NEXT_STAGE={contract['next_stage']}")
        print(f"EVIDENCE_JSON={args.output}")
        print(f"EVIDENCE_REPORT={args.report}")
        return 0 if execution_state == "PASS" else 2
    except Exception as exc:
        after_hashes = {str(path): sha256_file(path) for path in critical_paths}
        changed = [path for path in before_hashes if before_hashes[path] != after_hashes[path]]
        payload = {
            "schema": "zos_r7a0b_canonical_runtime_parity_audit_status_v2",
            "audit_execution": {"state": "HOLD", "target_sha_requested": args.target_sha, "mutation_count": len(changed), "critical_file_changes": changed, "errors": [str(exc)]},
            "runtime_readiness": {"state": "HOLD", "critical_gap_count": 1, "critical_gaps": [str(exc)]},
            "axes": {},
            "next_plan": ["Fix the audit execution blocker without changing runtime, then rerun R7.A0B"],
            "next_stage": "R7.A0B_EXECUTION_DIAGNOSIS",
            "evidence_paths": {"json": str(args.output), "markdown": str(args.report)},
        }
        atomic_json(args.output, payload)
        atomic_text(args.report, render_markdown(payload))
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
