#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "zel.legacy_strategy25.baseline_smoke.v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def run(root: Path, identity_path: Path) -> dict[str, Any]:
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("state") != "PASS_STRATEGY25_IDENTITY_25_OF_25" or identity.get("identity_gate_pass") is not True:
        raise RuntimeError("IDENTITY_25_OF_25_REQUIRED")
    rows = identity.get("rows") or []
    if len(rows) != 25:
        raise RuntimeError("IDENTITY_ROW_COUNT")
    results = []
    for row in rows:
        name = str(row.get("legacy_name") or "")
        candidates = row.get("direct_source_candidates") or []
        if row.get("state") != "SOURCE_IDENTITY_UNIQUE" or len(candidates) != 1:
            raise RuntimeError(f"IDENTITY_NOT_UNIQUE:{name}")
        src = candidates[0]
        rel = str(src.get("path") or "")
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"SOURCE_MISSING:{name}:{rel}")
        actual_sha = sha256_file(path)
        if actual_sha != str(src.get("sha256") or ""):
            raise RuntimeError(f"SOURCE_SHA_MISMATCH:{name}:{rel}")
        data = path.read_bytes()
        try:
            compile(data, rel, "exec", dont_inherit=True)
            compile_ok = True
            error = None
        except Exception as exc:
            compile_ok = False
            error = f"{type(exc).__name__}:{str(exc)[:240]}"
        results.append({
            "legacy_name": name,
            "source_path": rel,
            "source_sha256": actual_sha,
            "compile_ok": compile_ok,
            "compile_error": error,
        })
    failures = [r for r in results if not r["compile_ok"]]
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_STRATEGY25_BASELINE_SMOKE_25_OF_25" if not failures else "HOLD_STRATEGY25_BASELINE_SMOKE_FAILURE",
        "identity_receipt_sha256": identity.get("receipt_sha256"),
        "strategy_count": len(results),
        "source_sha_parity_count": len(results),
        "compile_pass_count": len(results) - len(failures),
        "compile_fail_count": len(failures),
        "results": results,
        "replay_performed": False,
        "market_values_read": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_mutated": False,
        "service_state_mutated": False,
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--identity", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.root.resolve(), args.identity.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "compile_pass_count": result["compile_pass_count"],
        "compile_fail_count": result["compile_fail_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
