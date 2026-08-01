from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import py_compile
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_MATERIAL_CHILD_BUILDER_V2"
AUTO_ENTRY_FINGERPRINTS = {
    "NO_SIGNAL_DORMANT",
    "LOW_SAMPLE_RARE_OR_OVERFILTERED",
    "THIN_SAMPLE",
}
UNSAFE_HINTS = {
    "stop", "stop_loss", "take_profit", "exit", "trail", "liquid", "leverage",
    "position_size", "qty", "quantity", "fee", "slippage", "funding", "order",
}
ENTRY_HINTS = {
    "entry", "signal", "trigger", "threshold", "score", "confidence", "rsi", "mfi",
    "macd", "slope", "volume", "vol", "atr", "breakout", "revert", "trend", "range",
    "distance", "deviation", "zscore", "momentum", "strength", "filter",
}


@dataclass(frozen=True)
class Candidate:
    lineno: int
    col_offset: int
    end_col_offset: int
    old_value: float
    new_value: float
    literal_text: str
    compare_text: str
    score: int
    reason: str


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def import_producer(source_root: Path, suffix: str) -> Any:
    path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    if not path.is_file():
        raise RuntimeError(f"PRODUCER_MISSING:{path}")
    name = f"zel_material_child_producer_{suffix}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PRODUCER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def strategy_card(diagnosis: Mapping[str, Any], strategy_id: str) -> dict[str, Any]:
    for row in diagnosis.get("strategies") or []:
        if isinstance(row, dict) and row.get("strategy_id") == strategy_id:
            return dict(row)
    raise RuntimeError(f"STRATEGY_NOT_IN_DIAGNOSIS:{strategy_id}")


def ensure_relative_owner_path(source_root: Path, raw: Any) -> tuple[Path, Path]:
    text = str(raw or "").strip()
    if not text:
        raise RuntimeError("OWNER_PATH_MISSING")
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"OWNER_PATH_UNSAFE:{text}")
    root = source_root.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"OWNER_PATH_ESCAPES_SOURCE_ROOT:{text}") from exc
    if not target.is_file():
        raise RuntimeError(f"OWNER_FILE_MISSING:{target}")
    return relative, target


def numeric_constant(node: ast.AST) -> ast.Constant | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)) and not isinstance(node.operand.value, bool):
            return node.operand
    return None


def relaxed_value(value: float, op: ast.cmpop, constant_on_right: bool) -> tuple[float, str] | None:
    if not math.isfinite(value) or abs(value) > 1_000_000_000:
        return None
    if isinstance(op, (ast.Gt, ast.GtE)):
        factor = 0.90 if constant_on_right else 1.10
        direction = "LOWER_MINIMUM" if constant_on_right else "RAISE_MAXIMUM"
    elif isinstance(op, (ast.Lt, ast.LtE)):
        factor = 1.10 if constant_on_right else 0.90
        direction = "RAISE_MAXIMUM" if constant_on_right else "LOWER_MINIMUM"
    else:
        return None
    if value == 0.0:
        new_value = 0.05 if factor > 1.0 else -0.05
    else:
        new_value = value * factor
    if float(value).is_integer() and abs(value) >= 2:
        new_value = float(max(1, round(new_value)))
    if new_value == value:
        new_value = value + (1.0 if factor > 1.0 else -1.0)
    return new_value, direction


def collect_candidates(path: Path) -> list[Candidate]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    found: list[Candidate] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        left_const = numeric_constant(node.left)
        right_const = numeric_constant(node.comparators[0])
        if (left_const is None) == (right_const is None):
            continue
        const = right_const if right_const is not None else left_const
        assert const is not None
        relaxed = relaxed_value(float(const.value), node.ops[0], right_const is not None)
        if relaxed is None or const.lineno != getattr(const, "end_lineno", const.lineno):
            continue
        compare_text = ast.get_source_segment(source, node) or ast.unparse(node)
        lowered = compare_text.lower()
        if any(hint in lowered for hint in UNSAFE_HINTS):
            continue
        hint_score = sum(1 for hint in ENTRY_HINTS if hint in lowered)
        if hint_score == 0:
            continue
        value = float(const.value)
        if abs(value) in {0.0, 1.0} and not any(hint in lowered for hint in {"rsi", "mfi", "ratio", "score", "confidence", "zscore"}):
            continue
        line = lines[const.lineno - 1]
        literal = line[const.col_offset:const.end_col_offset]
        if not literal.strip():
            continue
        new_value, reason = relaxed
        score = hint_score * 10
        if any(hint in lowered for hint in {"entry", "signal", "trigger", "threshold", "filter"}):
            score += 20
        if isinstance(node.ops[0], (ast.GtE, ast.LtE)):
            score += 2
        found.append(Candidate(
            lineno=const.lineno,
            col_offset=const.col_offset,
            end_col_offset=const.end_col_offset,
            old_value=value,
            new_value=new_value,
            literal_text=literal,
            compare_text=compare_text,
            score=score,
            reason=reason,
        ))
    unique: dict[tuple[int, int, int], Candidate] = {}
    for candidate in found:
        key = (candidate.lineno, candidate.col_offset, candidate.end_col_offset)
        if key not in unique or candidate.score > unique[key].score:
            unique[key] = candidate
    return sorted(unique.values(), key=lambda row: (-row.score, row.lineno, row.col_offset))


def format_literal(old_text: str, value: float) -> str:
    if any(marker in old_text.lower() for marker in ("e", ".")):
        return f"{value:.10g}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.10g}"


def mutate_one(path: Path, candidate: Candidate) -> tuple[str, str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    index = candidate.lineno - 1
    line = lines[index]
    actual = line[candidate.col_offset:candidate.end_col_offset]
    if actual != candidate.literal_text:
        raise RuntimeError(f"LITERAL_DRIFT:{path}:{candidate.lineno}")
    replacement = format_literal(actual, candidate.new_value)
    lines[index] = line[:candidate.col_offset] + replacement + line[candidate.end_col_offset:]
    updated = "".join(lines)
    ast.parse(updated, filename=str(path))
    path.write_text(updated, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return actual, replacement


def update_matching_hashes(value: Any, old_sha: str, new_sha: str) -> int:
    changed = 0
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if isinstance(item, str) and item.lower() == old_sha.lower() and any(token in key.lower() for token in ("sha", "hash", "digest")):
                value[key] = new_sha
                changed += 1
            else:
                changed += update_matching_hashes(item, old_sha, new_sha)
    elif isinstance(value, list):
        for item in value:
            changed += update_matching_hashes(item, old_sha, new_sha)
    return changed


def hold_report(strategy_id: str, fingerprint: str, state: str, reason: str, owner_path: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "zel.exact25.material_child_build.v2",
        "version": VERSION,
        "state": state,
        "strategy_id": strategy_id,
        "failure_fingerprint": fingerprint,
        "reason": reason,
        "owner_path": owner_path,
        "children": [],
        "replayable_child_count": 0,
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }


def build_children(source_root: Path, diagnosis_path: Path, strategy_id: str, out_root: Path, max_children: int) -> dict[str, Any]:
    source_root = source_root.resolve()
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root.parent / "replays").mkdir(parents=True, exist_ok=True)
    try:
        out_root.relative_to(source_root)
        raise RuntimeError("CHILD_OUTPUT_INSIDE_CANONICAL_SOURCE_FORBIDDEN")
    except ValueError:
        pass

    diagnosis = load_json(diagnosis_path)
    if diagnosis.get("state") != "PASS_EXACT25_MATERIAL_DIAGNOSIS_AND_QUEUE":
        raise RuntimeError(f"DIAGNOSIS_NOT_READY:{diagnosis.get('state')}")
    card = strategy_card(diagnosis, strategy_id)
    fingerprint = str(card.get("failure_fingerprint"))
    if fingerprint not in AUTO_ENTRY_FINGERPRINTS:
        return hold_report(
            strategy_id, fingerprint, "UNSUPPORTED_AUTOPATCH_HOLD",
            "ONLY_ZERO_OR_LOW_SAMPLE_ENTRY_SELECTIVITY_IS_AUTOPATCHED"
        )

    producer = import_producer(source_root, "canonical")
    _, registry = producer.load_registry(source_root)
    if strategy_id not in registry:
        raise RuntimeError(f"TARGET_NOT_IN_REGISTRY:{strategy_id}")
    owner_path, target = ensure_relative_owner_path(source_root, getattr(registry[strategy_id], "owner_path", ""))
    candidates = collect_candidates(target)[:max(1, min(max_children, 3))]
    if not candidates:
        return hold_report(
            strategy_id, fingerprint, "NO_SAFE_NUMERIC_ENTRY_SURFACE_HOLD",
            "NO_WHITELISTED_SINGLE_COMPARISON_THRESHOLD_FOUND", str(owner_path)
        )

    canonical_target_sha = sha256_path(target)
    canonical_manifest_path = source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    canonical_manifest_sha = sha256_path(canonical_manifest_path)
    children = []
    for index, candidate in enumerate(candidates, start=1):
        variant_id = f"{strategy_id}.ENTRY_RELAX.{index}"
        child_root = out_root / variant_id / "source"
        if child_root.exists():
            shutil.rmtree(child_root)
        shutil.copytree(source_root, child_root, symlinks=True)
        child_target = (child_root / owner_path).resolve()
        try:
            child_target.relative_to(child_root.resolve())
        except ValueError as exc:
            raise RuntimeError("CHILD_OWNER_PATH_ESCAPE") from exc
        old_text, new_text = mutate_one(child_target, candidate)
        child_target_sha = sha256_path(child_target)
        manifest_path = child_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
        manifest = load_json(manifest_path)
        manifest_hash_updates = update_matching_hashes(manifest, canonical_target_sha, child_target_sha)
        atomic_json(manifest_path, manifest)
        load_state = "PASS_CHILD_REGISTRY_LOAD"
        load_error = None
        try:
            child_producer = import_producer(child_root, hashlib.sha256(variant_id.encode()).hexdigest()[:10])
            _, child_registry = child_producer.load_registry(child_root)
            if strategy_id not in child_registry:
                raise RuntimeError("TARGET_MISSING_AFTER_CHILD_LOAD")
        except Exception as exc:
            load_state = "CHILD_REGISTRY_LOAD_HOLD"
            load_error = f"{type(exc).__name__}:{exc}"
        children.append({
            "variant_id": variant_id,
            "state": load_state,
            "load_error": load_error,
            "child_source_root": str(child_root),
            "owner_path": str(owner_path),
            "line": candidate.lineno,
            "compare_text": candidate.compare_text,
            "reason": candidate.reason,
            "old_literal": old_text,
            "new_literal": new_text,
            "old_value": candidate.old_value,
            "new_value": candidate.new_value,
            "source_sha256_before": canonical_target_sha,
            "source_sha256_after": child_target_sha,
            "manifest_sha256_before": canonical_manifest_sha,
            "manifest_sha256_after": sha256_path(manifest_path),
            "child_manifest_hash_updates": manifest_hash_updates,
            "changed_causal_axes": 1,
            "research_only": True,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        })

    replayable = sum(child["state"] == "PASS_CHILD_REGISTRY_LOAD" for child in children)
    canonical_source_after = sha256_path(target)
    canonical_manifest_after = sha256_path(canonical_manifest_path)
    if canonical_source_after != canonical_target_sha or canonical_manifest_after != canonical_manifest_sha:
        raise RuntimeError("CANONICAL_SOURCE_OR_MANIFEST_MUTATED")
    return {
        "schema_version": "zel.exact25.material_child_build.v2",
        "version": VERSION,
        "state": "PASS_CHILDREN_READY_FOR_TARGETED_REPLAY" if replayable else "CHILDREN_BUILT_BUT_REGISTRY_LOAD_HOLD",
        "strategy_id": strategy_id,
        "failure_fingerprint": fingerprint,
        "causal_axis": card.get("causal_axis"),
        "owner_path": str(owner_path),
        "candidate_count": len(candidates),
        "replayable_child_count": replayable,
        "children": children,
        "canonical_source_unchanged": True,
        "canonical_manifest_unchanged": True,
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }


def self_test() -> None:
    root = Path("/tmp/zel_material_child_builder_v2_selftest")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    path = root / "x.py"
    path.write_text("def f(rsi, volume):\n    return rsi > 70 and volume >= 1.5\n", encoding="utf-8")
    rows = collect_candidates(path)
    assert len(rows) == 2, rows
    mutate_one(path, rows[0])
    ast.parse(path.read_text(encoding="utf-8"))
    manifest = {"items": [{"sha256": "a" * 64}, {"nested": {"digest": "b" * 64}}]}
    assert update_matching_hashes(manifest, "a" * 64, "c" * 64) == 1
    assert manifest["items"][0]["sha256"] == "c" * 64
    try:
        ensure_relative_owner_path(root, "/tmp/escape.py")
    except RuntimeError as exc:
        assert "OWNER_PATH_UNSAFE" in str(exc)
    else:
        raise AssertionError("ABSOLUTE_OWNER_PATH_NOT_BLOCKED")
    print("PASS_SELF_TEST")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--diagnosis", type=Path)
    parser.add_argument("--strategy-id")
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--max-children", type=int, default=3)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not all((args.source_root, args.diagnosis, args.strategy_id, args.out_root, args.report)):
        parser.error("source-root, diagnosis, strategy-id, out-root and report are required")
    report = build_children(
        args.source_root, args.diagnosis, str(args.strategy_id), args.out_root, int(args.max_children)
    )
    atomic_json(args.report, report)
    print(report["state"], report.get("replayable_child_count", 0))


if __name__ == "__main__":
    main()
