from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_W1_READINESS_AUDIT_V1"

REQUIRED = {
    "master_control": [
        ".github/workflows/r7a4d-strategy11-continuous-data-v1.yml",
        "backend/tools/r7a4d_strategy11_continuous_data_v1.py",
    ],
    "pool22_compute": [
        "backend/tools/r7a4d_strategy11_data_wait_pool_compute_v1.py",
    ],
    "alpha_authority": [
        "backend/tools/r7a4d_strategy11_alpha_multiobjective_auto_v1.py",
        "backend/research/alpha_multiobjective_auto_v1.json",
    ],
}

CAPABILITIES = {
    "PRIMARY_W1_MULTIOBJECTIVE_CONFIRMATION": ["primary_w1", "alpha", "multiobjective"],
    "TURTLE_PRIMARY_W1_CAUSAL_REPLAY": ["primary_w1", "turtle"],
    "EMA_PRIMARY_W1_CAUSAL_REPLAY": ["primary_w1", "ema"],
    "NEW_SEALED_GENERATOR": ["sealed", "generator"],
    "GLOBAL_CANDIDATE_CLASSIFIER": ["global", "classifier"],
    "ENSEMBLE_CORRELATION_ANALYZER": ["ensemble", "correlation"],
    "W1_VISUALIZATION_AUTO": ["w1", "visual"],
    "GEMINI_W1_DELTA": ["gemini", "w1", "delta"],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def all_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)


def detect(root: Path, tokens: list[str]) -> list[str]:
    out: list[str] = []
    for path in all_files(root):
        low = str(path.relative_to(root)).lower()
        if all(token in low for token in tokens):
            out.append(str(path.relative_to(root)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--pool22", required=True)
    ap.add_argument("--alpha", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    roots = {
        "master_control": Path(args.master).resolve(),
        "pool22_compute": Path(args.pool22).resolve(),
        "alpha_authority": Path(args.alpha).resolve(),
    }
    checks: dict[str, Any] = {}
    for group, paths in REQUIRED.items():
        root = roots[group]
        rows = []
        for rel in paths:
            p = root / rel
            rows.append({"path": rel, "exists": p.is_file(), "sha256": sha(p) if p.is_file() else None})
        checks[group] = rows

    stream = Path(args.stream).resolve() / "strategy11_stream_v1" / "manifest.json"
    manifest = json.loads(stream.read_text(encoding="utf-8"))
    stream_check = {
        "path": "strategy11_stream_v1/manifest.json",
        "exists": True,
        "sha256": sha(stream),
        "state": manifest.get("state"),
        "available_non_overlap_bars": manifest.get("available_non_overlap_bars"),
        "missing_to_w1_480": manifest.get("missing_to_w1_480"),
        "w1_ready": manifest.get("w1_ready"),
        "blockers": manifest.get("blockers"),
        "protected_mutations": manifest.get("protected_mutations"),
        "order_authority": manifest.get("order_authority"),
    }

    scan_root = Path(args.master).resolve()
    capabilities = {name: detect(scan_root, tokens) for name, tokens in CAPABILITIES.items()}
    missing = [name for name, matches in capabilities.items() if not matches]
    present = [name for name, matches in capabilities.items() if matches]

    base_ok = all(row["exists"] for rows in checks.values() for row in rows)
    safety_ok = (
        stream_check["state"] == "PASS"
        and stream_check["blockers"] == []
        and stream_check["protected_mutations"] == 0
        and stream_check["order_authority"] == "BLOCKED"
    )
    state = "PASS_W1_READINESS_AUDIT_IMPLEMENTATION_REQUIRED" if base_ok and safety_ok and missing else (
        "PASS_W1_READINESS_COMPLETE" if base_ok and safety_ok else "HOLD_W1_READINESS_AUDIT"
    )
    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "base_authorities": checks,
        "stream": stream_check,
        "capabilities": capabilities,
        "present_capabilities": present,
        "missing_capabilities": missing,
        "implementation_order": [
            "PRIMARY_W1_MULTIOBJECTIVE_CONFIRMATION",
            "TURTLE_PRIMARY_W1_CAUSAL_REPLAY",
            "EMA_PRIMARY_W1_CAUSAL_REPLAY",
            "NEW_SEALED_GENERATOR",
            "GLOBAL_CANDIDATE_CLASSIFIER",
            "W1_VISUALIZATION_AUTO",
            "GEMINI_W1_DELTA",
            "ENSEMBLE_CORRELATION_ANALYZER",
        ],
        "next": "CREATE_MINIMAL_READ_ONLY_CHILDREN_IN_ORDER" if missing else "WAIT_W1_480",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
        "blockers": [] if base_ok and safety_ok else ["BASE_OR_SAFETY_CHECK_FAILED"],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "next_stage_request.json").write_text(json.dumps({
        "state": "IMPLEMENTATION_REQUIRED" if missing else "WAIT_DATA",
        "missing_capabilities": missing,
        "implementation_order": result["implementation_order"],
        "same_w1_source_sha_required": True,
        "read_only_children_only": True,
        "promotion_authority": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "missing": missing, "next": result["next"]}, sort_keys=True))
    return 0 if base_ok and safety_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
