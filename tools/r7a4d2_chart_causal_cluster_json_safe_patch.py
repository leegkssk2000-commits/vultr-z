#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "def json_safe(" in source:
        raise RuntimeError("SOURCE_ALREADY_JSON_SAFE_PATCHED")

    source = replace_once(
        source,
        '''def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


''',
        '''def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalar containers to JSON-native values."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if value is pd.NA:
        return None
    return value


''',
        "INSERT_JSON_SAFE_HELPER",
    )

    source = replace_once(
        source,
        '''    runner.atomic_json(output_dir / "causal_cluster_diagnose_v1.json", evidence)

    print("STATE=" + state)
''',
        '''    evidence = json_safe(evidence)
    runner.atomic_json(output_dir / "causal_cluster_diagnose_v1.json", evidence)

    print("STATE=" + state)
''',
        "NORMALIZE_EVIDENCE_BEFORE_ATOMIC_JSON",
    )

    source = replace_once(
        source,
        '''    print("BASELINE_CLUSTERS=" + json.dumps(baseline_cluster.get("clusters", []), ensure_ascii=False, sort_keys=True))
    print("BASELINE_CLUSTER_LOSO=" + json.dumps(baseline_loso, ensure_ascii=False, sort_keys=True))
    print("BASELINE_SYMBOL_DIAGNOSIS=" + json.dumps(evidence["baseline_symbol_diagnosis"], ensure_ascii=False, sort_keys=True))
''',
        '''    print("BASELINE_CLUSTERS=" + json.dumps(json_safe(baseline_cluster.get("clusters", [])), ensure_ascii=False, sort_keys=True))
    print("BASELINE_CLUSTER_LOSO=" + json.dumps(json_safe(baseline_loso), ensure_ascii=False, sort_keys=True))
    print("BASELINE_SYMBOL_DIAGNOSIS=" + json.dumps(json_safe(evidence["baseline_symbol_diagnosis"]), ensure_ascii=False, sort_keys=True))
''',
        "NORMALIZE_BASELINE_STDOUT_JSON",
    )

    source = replace_once(
        source,
        '''    print("VOL_COMPONENT_DECOMPOSITION=" + json.dumps(vol_components, ensure_ascii=False, sort_keys=True))
    print("REPAIR_PLAN=" + json.dumps(repair_plan, ensure_ascii=False, sort_keys=True))
''',
        '''    print("VOL_COMPONENT_DECOMPOSITION=" + json.dumps(json_safe(vol_components), ensure_ascii=False, sort_keys=True))
    print("REPAIR_PLAN=" + json.dumps(json_safe(repair_plan), ensure_ascii=False, sort_keys=True))
''',
        "NORMALIZE_REPAIR_STDOUT_JSON",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    patched = apply_patch(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)
    print("STATE=PASS_CHART_CAUSAL_CLUSTER_JSON_SAFE_PATCH")
    print("JSON_SAFE_NUMPY_SCALAR_RECURSION=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
