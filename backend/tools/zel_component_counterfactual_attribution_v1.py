from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

COMPONENTS = ("STRATEGY", "TRADE_METHOD", "SKILL", "TEAM_BOT", "ZBOT", "LICO", "ZICO", "ZLICE")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"JSONL_OBJECT_REQUIRED:{line_number}")
        rows.append(value)
    return rows


def key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("opportunity_id") or row.get("event_id") or ""),
        str(row.get("timestamp") or row.get("entry_ts") or ""),
        str(row.get("symbol") or ""),
        str(row.get("regime") or "unknown"),
    )


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)


def analyze(base_path: Path, variants_path: Path) -> dict[str, Any]:
    base_rows = load_jsonl(base_path)
    variant_rows = load_jsonl(variants_path)
    base = {key(row): row for row in base_rows if all(key(row)[:3])}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    violations: list[dict[str, Any]] = []

    for row in variant_rows:
        component = str(row.get("component") or "").upper()
        if component not in COMPONENTS:
            violations.append({"reason": "UNKNOWN_COMPONENT", "component": component or None})
            continue
        match = base.get(key(row))
        if match is None:
            violations.append({"reason": "UNPAIRED_VARIANT", "component": component, "key": key(row)})
            continue
        same_context = (
            match.get("cost_model_sha256") == row.get("cost_model_sha256")
            and match.get("risk_budget") == row.get("risk_budget")
            and match.get("data_manifest_sha256") == row.get("data_manifest_sha256")
        )
        if not same_context:
            violations.append({"reason": "COUNTERFACTUAL_CONTEXT_MISMATCH", "component": component, "key": key(row)})
            continue
        before = safe_float(match.get("net_R", match.get("realized_R")))
        after = safe_float(row.get("net_R", row.get("realized_R")))
        if before is None or after is None:
            violations.append({"reason": "R_VALUE_MISSING", "component": component, "key": key(row)})
            continue
        delta = after - before
        if component == "ZLICE" and abs(delta) > 1e-12:
            violations.append({"reason": "ZLICE_DIRECT_PNL_DELTA_FORBIDDEN", "component": component, "delta_R": delta, "key": key(row)})
            continue
        grouped[component].append({
            "opportunity_id": key(row)[0],
            "timestamp": key(row)[1],
            "symbol": key(row)[2],
            "regime": key(row)[3],
            "before_R": before,
            "after_R": after,
            "component_delta_R": delta,
            "counterfactual_id": row.get("counterfactual_id"),
            "bundle_sha256": row.get("bundle_sha256"),
        })

    summaries = {}
    total_pairs = 0
    for component in COMPONENTS:
        rows = grouped.get(component, [])
        values = [row["component_delta_R"] for row in rows]
        total_pairs += len(rows)
        summaries[component] = {
            "paired_count": len(rows),
            "delta_net_R": sum(values),
            "delta_expectancy_R": statistics.fmean(values) if values else None,
            "delta_median_R": statistics.median(values) if values else None,
            "positive_delta_pct": (sum(value > 0 for value in values) / len(values) * 100.0) if values else None,
            "direct_alpha_claim_allowed": component not in {"LICO", "ZICO", "ZLICE"},
        }

    state = "PASS_COMPONENT_COUNTERFACTUAL_ATTRIBUTION" if total_pairs and not violations else "HOLD_COMPONENT_COUNTERFACTUAL_ATTRIBUTION_INCOMPLETE"
    return {
        "schema_version": "zel.component.counterfactual_attribution.receipt.v1",
        "generated_at": now_iso(),
        "state": state,
        "base_sha256": sha256_path(base_path),
        "variants_sha256": sha256_path(variants_path),
        "base_count": len(base_rows),
        "variant_count": len(variant_rows),
        "paired_count": total_pairs,
        "violation_count": len(violations),
        "violations": violations[:200],
        "components": summaries,
        "causal_rules": {
            "same_opportunity_required": True,
            "same_cost_model_required": True,
            "same_risk_budget_required": True,
            "same_data_manifest_required": True,
            "zlice_direct_pnl_delta_zero": True,
            "zico_alpha_claim_forbidden": True,
            "lico_gross_alpha_claim_forbidden": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_binding_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        base = root / "base.jsonl"
        variants = root / "variants.jsonl"
        context = {
            "opportunity_id": "o1",
            "timestamp": "2026-01-01T00:00:00Z",
            "symbol": "BTCUSDT",
            "regime": "trend",
            "cost_model_sha256": "c",
            "risk_budget": "1R",
            "data_manifest_sha256": "d",
        }
        base.write_text(json.dumps({**context, "net_R": 0.5}) + "\n")
        variants.write_text(json.dumps({**context, "component": "SKILL", "net_R": 1.0, "counterfactual_id": "cf1"}) + "\n")
        result = analyze(base, variants)
        assert result["state"] == "PASS_COMPONENT_COUNTERFACTUAL_ATTRIBUTION"
        assert result["components"]["SKILL"]["delta_net_R"] == 0.5
    print(json.dumps({"state": "PASS_SELF_TEST"}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--variants")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.base or not args.variants or not args.out:
        parser.error("base, variants and out are required")
    result = analyze(Path(args.base), Path(args.variants))
    atomic_json(Path(args.out), result)
    print(json.dumps({"state": result["state"], "paired_count": result["paired_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
