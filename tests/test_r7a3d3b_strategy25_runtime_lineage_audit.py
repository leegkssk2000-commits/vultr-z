from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7a3d3b_strategy25_runtime_lineage_audit.py"
spec = importlib.util.spec_from_file_location("r7a3d3b_runtime_lineage", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_relative_import_resolution():
    modules = {
        "backend.engine": "backend/engine.py",
        "backend.pkg.helper": "backend/pkg/helper.py",
    }
    assert module.resolve_import("backend/pkg/worker.py", "helper", 1, modules) == ["backend/pkg/helper.py"]


def test_shortest_path_is_bounded():
    graph = {"a.py": {"b.py"}, "b.py": {"c.py"}}
    assert module.shortest_path(graph, {"a.py"}, "c.py", 2) == ["a.py", "b.py", "c.py"]
    assert module.shortest_path(graph, {"a.py"}, "c.py", 1) is None


def test_source_reference_requires_exact_or_unique_basename(tmp_path: Path):
    paths = {"backend/a/run.py", "backend/b/run.py", "backend/c/unique.py"}
    by_name = defaultdict(list)
    for path in paths:
        by_name[Path(path).name].append(path)
    found = module.source_references("python unique.py run.py", tmp_path, paths, by_name)
    assert found == {"backend/c/unique.py"}


def test_active_import_plus_explicit_binding_is_hard_proof(tmp_path: Path):
    root = tmp_path
    paths = {"services/entry.py", "backend/strategies/alpha.py"}
    by_name = defaultdict(list)
    for path in paths:
        by_name[Path(path).name].append(path)
    candidate = {
        "implementation_path": "backend/strategies/alpha.py",
        "callable": "evaluate",
        "binding_kind": "registry_or_shared",
        "explicit_binding": True,
        "binding_refs": [],
    }
    proof = module.candidate_proof(
        candidate,
        "alpha",
        root,
        paths,
        by_name,
        {path: "a" * 40 for path in paths},
        {"services/entry.py": {"backend/strategies/alpha.py"}},
        {"services/entry.py"},
        [],
        4,
    )
    assert proof["hard_proven"] is True
    assert "ACTIVE_IMPORT_CHAIN_PLUS_EXPLICIT_BINDING" in proof["hard_proof_reasons"]


def test_no_runtime_lineage_fails_closed(tmp_path: Path):
    paths = {"backend/strategies/alpha.py"}
    by_name = {"alpha.py": ["backend/strategies/alpha.py"]}
    proof = module.candidate_proof(
        {"implementation_path": "backend/strategies/alpha.py", "callable": "evaluate"},
        "alpha",
        tmp_path,
        paths,
        by_name,
        {"backend/strategies/alpha.py": "a" * 40},
        {},
        set(),
        [],
        4,
    )
    assert proof["hard_proven"] is False
