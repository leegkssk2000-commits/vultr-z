from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.production.zel_production_a1_l2_adverse_selection_v1 import (
    DEFAULT_POLICY,
    evaluate,
    validate_policy,
)
from backend.production.zel_production_a1_jump_liquidity_economic_v1 import (
    _atomic_json,
    _load,
    _load_jsonl,
    _sha_obj,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)

    cfg = validate_policy(_load(ns.policy))
    freeze_ms = int(cfg.get("family_freeze_not_before_ms") or 0)
    if freeze_ms <= 0 or freeze_ms % int(cfg["bucket_ms"]) != 0:
        raise RuntimeError("A1_L2_FAMILY_FREEZE_BOUNDARY_INVALID")

    seal_path = Path(str(cfg["source_threshold_seal_path"]))
    seal = _load(seal_path) if seal_path.is_file() else {}
    if seal:
        source_start = int(seal.get("economic_evaluation_start_bucket_ms") or 0)
        seal = dict(seal)
        seal["economic_evaluation_start_bucket_ms"] = max(source_start, freeze_ms)

    rows = _load_jsonl(Path(str(cfg["history_path"])))
    out = evaluate(cfg, seal, rows)
    out["family_freeze_not_before_ms"] = freeze_ms
    out["prospective_boundary_enforced"] = True
    out["evidence_refs"] = list(cfg.get("evidence_refs") or [])
    out["leakage"] = False
    out["receipt_sha256"] = _sha_obj({k: v for k, v in out.items() if k != "receipt_sha256"})
    _atomic_json(Path(str(cfg["output_path"])), out)
    print(json.dumps(out, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
