from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate(payload: dict[str, Any]) -> None:
    for key, expected in SAFETY.items():
        if payload.get(key) != expected:
            raise ValueError(f"SAFETY_MISMATCH:{key}")
    required = {"candidate_set_sha", "correlation_artifact_sha", "materials", "policy"}
    if not required.issubset(payload):
        raise ValueError("INPUT_FIELDS_MISSING")
    materials = payload["materials"]
    if not isinstance(materials, list) or not 2 <= len(materials) <= 5:
        raise ValueError("MATERIAL_COUNT_OUT_OF_RANGE")


def govern(payload: dict[str, Any]) -> dict[str, Any]:
    validate(payload)
    policy = payload["policy"]
    materials = payload["materials"]
    total_budget = float(policy["total_risk_budget"])
    max_weight = float(policy["max_material_weight"])
    min_weight = float(policy["min_material_weight"])

    raw: list[tuple[str, float]] = []
    for material in materials:
        if material["classification"] not in {"CORE", "SYNTHESIS"}:
            raise ValueError("MATERIAL_CLASS_INVALID")
        if material.get("material_sealed") is not True:
            raise ValueError("MATERIAL_NOT_SEALED")
        independent_edge = max(float(material["net_after_cost"]), 0.0)
        conviction = max(float(material["confidence"]) - float(material["uncertainty"]), 0.01)
        risk = max(
            float(material["dd_pct"])
            + float(material["joint_tail_dd_pct"])
            + float(material["cost_pct"]),
            0.01,
        )
        capacity = min(max(float(material["capacity_score"]), 0.0), 1.0)
        raw.append((str(material["material_id"]), independent_edge * conviction * capacity / risk))

    total_raw = sum(value for _, value in raw)
    if total_raw <= 0:
        raise ValueError("NO_POSITIVE_RISK_ADJUSTED_EDGE")
    weights = {key: value / total_raw for key, value in raw}

    for _ in range(10):
        bounded = {key: min(max(value, min_weight), max_weight) for key, value in weights.items()}
        total = sum(bounded.values())
        weights = {key: value / total for key, value in bounded.items()}

    turnover = sum(
        abs(weights[str(material["material_id"])] - float(material.get("incumbent_weight", 0.0)))
        for material in materials
    )
    blockers: list[str] = []
    if turnover > float(policy["max_turnover"]):
        blockers.append("TURNOVER_LIMIT")
    if max(weights.values()) > max_weight + 1e-9:
        blockers.append("CONCENTRATION_LIMIT")

    target_risk_weights = {
        key: round(value * total_budget, 10) for key, value in sorted(weights.items())
    }
    return {
        "schema_version": "strategy11.portfolio_governor.v1",
        "status": "HOLD_PORTFOLIO_GOVERNOR" if blockers else "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS",
        "candidate_set_sha": payload["candidate_set_sha"],
        "correlation_artifact_sha": payload["correlation_artifact_sha"],
        "input_sha": sha256(payload),
        "policy_sha": sha256(policy),
        "target_risk_weights": target_risk_weights,
        "turnover": round(turnover, 10),
        "blockers": blockers,
        "shadow_only": True,
        "rollback": {
            "mode": "RETAIN_INCUMBENT_WEIGHTS",
            "triggers": ["DD_BREACH", "COST_BREACH", "CORRELATION_SPIKE", "LINEAGE_MISMATCH"],
        },
        **SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = govern(read_json(args.input))
        write_json(args.output, result)
        print(result["status"])
        return 0 if result["status"].startswith("PASS_") else 1
    except Exception as exc:
        write_json(args.output, {
            "schema_version": "strategy11.portfolio_governor.v1",
            "status": "HOLD_PORTFOLIO_GOVERNOR",
            "blockers": [str(exc)[:1000]],
            "shadow_only": True,
            **SAFETY,
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
