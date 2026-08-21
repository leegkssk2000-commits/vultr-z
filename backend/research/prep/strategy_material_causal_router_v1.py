from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "backend/research/rebuild/a1_exact25_v3_causal_registry_v1.json"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def evaluate(material: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    if material.get("state") != "PASS_STRATEGY_MATERIALS_CLASSIFIED":
        raise RuntimeError("MATERIAL_CLASSIFICATION_REQUIRED")
    if registry.get("state") != "ACTIVE_CAUSAL_DISPOSITION_REGISTRY":
        raise RuntimeError("CAUSAL_REGISTRY_REQUIRED")
    causal = registry.get("strategies") if isinstance(registry.get("strategies"), Mapping) else {}
    out = json.loads(json.dumps(material))
    rerouted: list[str] = []
    for row in out.get("rows") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("strategy_id") or "")
        c = causal.get(cid) if isinstance(causal, Mapping) else None
        if not isinstance(c, Mapping):
            continue
        row["causal_control_state"] = c.get("state")
        row["causal_registry_row_sha256"] = c.get("row_sha256")
        if c.get("state") == "CAUSAL_CONTROL_FAIL":
            if row.get("material_disposition") == "A3_PROMOTION_QUEUE":
                row["material_disposition"] = "SYNTHESIS_UPGRADE"
            row["upgrade_axis"] = "ENTRY_CAUSALITY_REDESIGN_NEW_IDENTITY"
            row["synthesis_value_state"] = "CAUSAL_CONTROL_FAIL_REDESIGN_REQUIRED"
            row["same_identity_a3_reentry_forbidden"] = True
            row["promotion_authority_from_material_grade"] = False
            rerouted.append(cid)
        elif c.get("state") == "CAUSAL_CONTROL_PASS":
            row["same_identity_causal_retest_required"] = False
        row["row_sha256"] = sha({k: v for k, v in row.items() if k != "row_sha256"})

    dispositions = [
        "A3_PROMOTION_QUEUE", "SYNTHESIS_CORE", "SYNTHESIS_UPGRADE", "SYNTHESIS_EXPERIMENTAL",
        "HOLD_DATA", "DISCARD_PENDING_ABLATION", "DISCARD_CONFIRMED",
    ]
    out["buckets"] = {name: [r["strategy_id"] for r in out.get("rows") or [] if r.get("material_disposition") == name] for name in dispositions}
    out["causal_registry_sha256"] = sha(registry)
    out["causal_fail_rerouted"] = sorted(set(rerouted))
    out["causal_fail_rerouted_count"] = len(set(rerouted))
    out["state"] = "PASS_STRATEGY_MATERIALS_CAUSAL_ROUTED"
    out["receipt_sha256"] = sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def self_test() -> int:
    m={"state":"PASS_STRATEGY_MATERIALS_CLASSIFIED","rows":[{"strategy_id":"x","material_disposition":"A3_PROMOTION_QUEUE","upgrade_axis":"CAUSAL_CONTROL_HARDENING"}]}
    r={"state":"ACTIVE_CAUSAL_DISPOSITION_REGISTRY","strategies":{"x":{"state":"CAUSAL_CONTROL_FAIL","row_sha256":"a"}}}
    out=evaluate(m,r)
    assert out["rows"][0]["material_disposition"] == "SYNTHESIS_UPGRADE"
    assert out["rows"][0]["upgrade_axis"] == "ENTRY_CAUSALITY_REDESIGN_NEW_IDENTITY"
    assert out["buckets"]["A3_PROMOTION_QUEUE"] == []
    print("PASS_STRATEGY_MATERIAL_CAUSAL_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--material",type=Path)
    ap.add_argument("--registry",type=Path,default=DEFAULT_REGISTRY)
    ap.add_argument("--output",type=Path,default=Path("out/strategy_material_causal_routed_v1.json"))
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.material:raise SystemExit("--material required")
    result=evaluate(read(args.material),read(args.registry));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"a3_queue":result["buckets"]["A3_PROMOTION_QUEUE"],"causal_fail_rerouted":result["causal_fail_rerouted"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
