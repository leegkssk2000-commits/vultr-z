from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_spec_v1.json"
DEFAULT_MAP = ROOT / "backend/research/architecture_factory/a1_external_research_exact25_map_v1.json"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate(spec: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    rows = spec.get("specs") or {}
    audit = mapping.get("parent_code_dedup_audit") or {}
    multicritic = audit.get("multicritic_evidence") or {}
    if int(multicritic.get("run_id") or 0) <= 0 or int(multicritic.get("reviewed_strategy_count") or 0) != 25:
        raise RuntimeError("IMMUTABLE_MULTICRITIC_EVIDENCE_REQUIRED")
    if not str(multicritic.get("artifact_digest") or "").startswith("sha256:"):
        raise RuntimeError("MULTICRITIC_ARTIFACT_DIGEST_REQUIRED")
    expected = {str(x) for x in (audit.get("novel_strategy_ids") or [])}
    if set(rows) != expected or len(rows) != 8:
        raise RuntimeError("EXACT8_CODE_NOVEL_SET_REQUIRED")
    children: set[str] = set()
    for strategy_id, row in rows.items():
        proposal = (mapping.get("strategies") or {}).get(strategy_id) or {}
        child = str(row.get("child_id") or "")
        if not child or child in children or child == strategy_id:
            raise RuntimeError(f"CHILD_IDENTITY_INVALID:{strategy_id}")
        children.add(child)
        if str(row.get("changed_axis") or "") != str(proposal.get("axis") or ""):
            raise RuntimeError(f"AXIS_MISMATCH:{strategy_id}")
        if set(row.get("source_ids") or []) != set(proposal.get("source_ids") or []):
            raise RuntimeError(f"SOURCE_LINEAGE_MISMATCH:{strategy_id}")
        if int(row.get("timeframe_ms") or 0) not in {300_000, 3_600_000}:
            raise RuntimeError(f"TIMEFRAME_INVALID:{strategy_id}")
        if len(str(row.get("operational_definition") or "")) < 80:
            raise RuntimeError(f"OPERATIONAL_DEFINITION_INCOMPLETE:{strategy_id}")
        if not row.get("required_data") or not str(row.get("parent_policy") or "").endswith(".py"):
            raise RuntimeError(f"SOURCE_OR_POLICY_MISSING:{strategy_id}")
    if spec.get("threshold_search") is not False or spec.get("holdout_outcomes_accessed") is not False:
        raise RuntimeError("OUTCOME_BLIND_CONTRACT_REQUIRED")
    if int(spec.get("effect_verified_count", -1)) != 0:
        raise RuntimeError("EFFECT_CANNOT_BE_PREVERIFIED")
    receipt = {
        "schema_version": "zel.a1_external_research_exact8_spec_validation.v1",
        "state": "PASS_EXACT8_OPERATIONAL_SPECS_READY_FOR_ADAPTERS",
        "strategy_count": len(rows),
        "strategy_ids": sorted(rows),
        "child_ids": sorted(children),
        "multicritic_evidence_run_id": int(multicritic["run_id"]),
        "multicritic_artifact_digest": str(multicritic["artifact_digest"]),
        "one_axis_all": True,
        "effect_verified_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    receipt = validate(read(args.spec), read(args.map))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
