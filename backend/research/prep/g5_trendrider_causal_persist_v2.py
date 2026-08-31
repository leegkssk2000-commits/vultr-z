#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def norm(value: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    out = dict(value)
    out.pop("receipt_sha256", None)
    for key in drop:
        out.pop(key, None)
    return out


def copy_if_semantic_delta(candidate: Path, target: Path, drop: tuple[str, ...] = ()) -> bool:
    candidate_value = load(candidate)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, target)
        return True
    old = load(target)
    if norm(old, drop) == norm(candidate_value, drop):
        return False
    shutil.copyfile(candidate, target)
    return True


def apply(
    forensic_candidate: Path,
    forensic_target: Path,
    screen_candidate: Path,
    screen_target: Path,
    research_candidate: Path,
    research_target: Path,
) -> dict[str, Any]:
    fnew = load(forensic_candidate)
    if forensic_target.exists():
        fold = load(forensic_target)
        new_t = int(fnew.get("w2_observed_T") or 0)
        old_t = int(fold.get("w2_observed_T") or 0)
        if new_t < old_t:
            raise RuntimeError("FORENSIC_T_REGRESSION")
        if new_t == old_t:
            old_parent = str(fold.get("parent_receipt_sha256") or "")
            new_parent = str(fnew.get("parent_receipt_sha256") or "")
            if old_parent and new_parent and old_parent != new_parent:
                raise RuntimeError("FORENSIC_SAME_T_PARENT_REWRITE")

    changed = {
        "forensic": copy_if_semantic_delta(forensic_candidate, forensic_target),
        "screen": copy_if_semantic_delta(screen_candidate, screen_target),
        "research": copy_if_semantic_delta(
            research_candidate,
            research_target,
            drop=("last_refresh_utc", "provider_call_this_run", "cache_hit"),
        ),
    }
    return {"state": "PASS_G5_CAUSAL_CHAIN_SEMANTIC_PERSIST_PREP_V2", "changed": changed}


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fc, ft = root / "fc.json", root / "ft.json"
        sc, st = root / "sc.json", root / "st.json"
        rc, rt = root / "rc.json", root / "rt.json"
        fc.write_text(json.dumps({"w2_observed_T": 8, "parent_receipt_sha256": "p", "receipt_sha256": "a"}), encoding="utf-8")
        sc.write_text(json.dumps({"state": "x", "receipt_sha256": "b"}), encoding="utf-8")
        rc.write_text(json.dumps({"state": "y", "provider_call_this_run": True, "cache_hit": False, "receipt_sha256": "c"}), encoding="utf-8")
        first = apply(fc, ft, sc, st, rc, rt)
        assert all(first["changed"].values())
        rc.write_text(json.dumps({"state": "y", "provider_call_this_run": False, "cache_hit": True, "receipt_sha256": "d"}), encoding="utf-8")
        second = apply(fc, ft, sc, st, rc, rt)
        assert second["changed"]["research"] is False
        bad = root / "bad.json"
        bad.write_text(json.dumps({"w2_observed_T": 7, "parent_receipt_sha256": "p"}), encoding="utf-8")
        try:
            apply(bad, ft, sc, st, rc, rt)
        except RuntimeError as exc:
            assert str(exc) == "FORENSIC_T_REGRESSION"
        else:
            raise AssertionError("FORENSIC_T_REGRESSION_REQUIRED")
    print("PASS_G5_TRENDRIDER_CAUSAL_PERSIST_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forensic-candidate", type=Path)
    ap.add_argument("--forensic-target", type=Path)
    ap.add_argument("--screen-candidate", type=Path)
    ap.add_argument("--screen-target", type=Path)
    ap.add_argument("--research-candidate", type=Path)
    ap.add_argument("--research-target", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    required = [
        args.forensic_candidate, args.forensic_target, args.screen_candidate,
        args.screen_target, args.research_candidate, args.research_target,
    ]
    if any(x is None for x in required):
        raise SystemExit("ALL_PERSIST_PATHS_REQUIRED")
    result = apply(*required)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
