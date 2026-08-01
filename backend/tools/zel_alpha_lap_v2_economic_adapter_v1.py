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
from typing import Any, Iterable, Mapping


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
        rows.append(value)
    return rows


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def bundle_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("bundles", "top3_bundles", "strategies", "candidates"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def lineage_hash(row: Mapping[str, Any]) -> str:
    fields = {
        key: row.get(key)
        for key in (
            "strategy_id", "strategy_sha256", "method_sha256", "skill_sha256",
            "team_sha256", "zbot_sha256", "lico_sha256", "zico_sha256",
            "zlice_sha256", "risk_model_sha256", "cost_model_sha256", "bundle_sha256",
        )
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def register_challengers(top3_path: Path, champions_path: Path | None) -> dict[str, Any]:
    top3 = load_json(top3_path)
    champions = load_json(champions_path) if champions_path else {"slots": []}
    champion_rows = champions.get("slots") if isinstance(champions.get("slots"), list) else []
    champion_by_slot = {
        str(row.get("slot_id")): row
        for row in champion_rows
        if isinstance(row, dict) and row.get("slot_id") is not None
    }

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    required_hashes = (
        "strategy_sha256", "method_sha256", "skill_sha256", "team_sha256",
        "zbot_sha256", "lico_sha256", "zico_sha256", "zlice_sha256",
        "risk_model_sha256", "cost_model_sha256", "bundle_sha256",
    )
    for row in bundle_rows(top3):
        missing = [key for key in required_hashes if not row.get(key)]
        strategy_id = str(row.get("strategy_id") or "")
        slot_id = str(row.get("slot_id") or strategy_id)
        if not strategy_id or missing:
            rejected.append({"strategy_id": strategy_id or None, "slot_id": slot_id or None, "reason": "LINEAGE_INCOMPLETE", "missing": missing})
            continue
        bundle_sha = str(row["bundle_sha256"])
        identity = f"{slot_id}:{bundle_sha}"
        if identity in seen:
            rejected.append({"strategy_id": strategy_id, "slot_id": slot_id, "reason": "DUPLICATE_CHALLENGER", "bundle_sha256": bundle_sha})
            continue
        seen.add(identity)
        champion = champion_by_slot.get(slot_id)
        if champion and champion.get("bundle_sha256") == bundle_sha:
            rejected.append({"strategy_id": strategy_id, "slot_id": slot_id, "reason": "IDENTICAL_TO_CHAMPION", "bundle_sha256": bundle_sha})
            continue
        candidate_id = hashlib.sha256(f"{slot_id}\0{bundle_sha}".encode()).hexdigest()[:24]
        candidates.append({
            "candidate_id": f"challenger.{candidate_id}",
            "slot_id": slot_id,
            "strategy_id": strategy_id,
            "parent_champion_bundle_sha256": champion.get("bundle_sha256") if champion else None,
            "bundle_sha256": bundle_sha,
            "lineage_sha256": lineage_hash(row),
            "rank_within_strategy": row.get("rank"),
            "source_receipt_sha256": sha256_path(top3_path),
            "state": "REGISTERED_RESEARCH_ONLY",
            "w2_state": "PENDING",
            "w3_state": "PENDING",
            "shadow_state": "PENDING",
            "paper_state": "PENDING",
            "promotion_state": "BLOCKED",
            "automatic_live_change": False,
        })

    state = "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED" if candidates else "HOLD_NO_VALID_ALPHA_LAP_CHALLENGERS"
    return {
        "schema_version": "zel.alpha_lap.v2.challenger_registry.receipt.v1",
        "generated_at": now_iso(),
        "state": state,
        "source_top3_path": str(top3_path),
        "source_top3_sha256": sha256_path(top3_path),
        "source_champion_sha256": sha256_path(champions_path) if champions_path and champions_path.is_file() else None,
        "candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "candidates": candidates,
        "rejected": rejected,
        "runtime_registry_write_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "automatic_live_change": False,
        "shadow_start_allowed": False,
        "paper_start_allowed": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def opportunity_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("opportunity_id") or row.get("event_id") or ""),
        str(row.get("timestamp") or row.get("entry_ts") or ""),
        str(row.get("symbol") or ""),
        str(row.get("regime") or "unknown"),
    )


def max_drawdown(values: Iterable[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def paired_compare(champion_path: Path, challenger_path: Path) -> dict[str, Any]:
    champion_rows = load_jsonl(champion_path)
    challenger_rows = load_jsonl(challenger_path)
    champion = {opportunity_key(row): row for row in champion_rows if all(opportunity_key(row)[:3])}
    challenger = {opportunity_key(row): row for row in challenger_rows if all(opportunity_key(row)[:3])}
    shared = sorted(set(champion) & set(challenger))
    pairs: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for key in shared:
        left = champion[key]
        right = challenger[key]
        checks = {
            "cost_model_sha256": left.get("cost_model_sha256") == right.get("cost_model_sha256"),
            "risk_budget": left.get("risk_budget") == right.get("risk_budget"),
            "market_time": str(left.get("timestamp") or left.get("entry_ts")) == str(right.get("timestamp") or right.get("entry_ts")),
            "symbol": left.get("symbol") == right.get("symbol"),
            "regime": str(left.get("regime") or "unknown") == str(right.get("regime") or "unknown"),
        }
        if not all(checks.values()):
            violations.append({"key": key, "checks": checks})
            continue
        before = safe_float(left.get("net_R", left.get("realized_R")))
        after = safe_float(right.get("net_R", right.get("realized_R")))
        if before is None or after is None:
            violations.append({"key": key, "checks": checks, "reason": "R_VALUE_MISSING"})
            continue
        pairs.append({
            "opportunity_id": key[0],
            "timestamp": key[1],
            "symbol": key[2],
            "regime": key[3],
            "champion_R": before,
            "challenger_R": after,
            "delta_R": after - before,
        })

    champion_values = [row["champion_R"] for row in pairs]
    challenger_values = [row["challenger_R"] for row in pairs]
    deltas = [row["delta_R"] for row in pairs]
    paired_count = len(pairs)
    state = "PASS_ALPHA_LAP_PAIRED_COMPARISON" if paired_count and not violations else "HOLD_ALPHA_LAP_PAIRED_COMPARISON_INCOMPLETE"
    return {
        "schema_version": "zel.alpha_lap.v2.paired_comparison.receipt.v1",
        "generated_at": now_iso(),
        "state": state,
        "champion_trace_sha256": sha256_path(champion_path),
        "challenger_trace_sha256": sha256_path(challenger_path),
        "champion_row_count": len(champion_rows),
        "challenger_row_count": len(challenger_rows),
        "paired_count": paired_count,
        "unpaired_champion_count": len(set(champion) - set(challenger)),
        "unpaired_challenger_count": len(set(challenger) - set(champion)),
        "contract_violation_count": len(violations),
        "contract_violations": violations[:100],
        "metrics": {
            "champion_net_R": sum(champion_values),
            "challenger_net_R": sum(challenger_values),
            "delta_net_R": sum(deltas),
            "delta_expectancy_R": statistics.fmean(deltas) if deltas else None,
            "delta_median_R": statistics.median(deltas) if deltas else None,
            "champion_max_drawdown_R": max_drawdown(champion_values),
            "challenger_max_drawdown_R": max_drawdown(challenger_values),
            "delta_max_drawdown_R": max_drawdown(challenger_values) - max_drawdown(champion_values),
            "challenger_pair_win_rate_pct": (sum(value > 0 for value in deltas) / paired_count * 100.0) if paired_count else None,
        },
        "promotion_gate_evaluated": False,
        "promotion_threshold_source_required": "Z_POLICY_V3_AND_SSOT",
        "same_market_time_required": True,
        "same_cost_model_required": True,
        "same_risk_budget_required": True,
        "selection_authority": False,
        "promotion_authority": False,
        "automatic_registry_switch": False,
        "automatic_live_change": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        top3 = root / "top3.json"
        champions = root / "champions.json"
        hashes = {key: key + "_sha" for key in (
            "strategy_sha256", "method_sha256", "skill_sha256", "team_sha256",
            "zbot_sha256", "lico_sha256", "zico_sha256", "zlice_sha256",
            "risk_model_sha256", "cost_model_sha256", "bundle_sha256",
        )}
        top3.write_text(json.dumps({"bundles": [{"strategy_id": "s1", "slot_id": "slot1", **hashes}]}))
        champions.write_text(json.dumps({"slots": [{"slot_id": "slot1", "bundle_sha256": "old"}]}))
        registered = register_challengers(top3, champions)
        assert registered["state"] == "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED"
        assert registered["candidate_count"] == 1

        champion_trace = root / "champion.jsonl"
        challenger_trace = root / "challenger.jsonl"
        base = {"opportunity_id": "o1", "timestamp": "2026-01-01T00:00:00Z", "symbol": "BTCUSDT", "regime": "trend", "cost_model_sha256": "cost", "risk_budget": "1R"}
        champion_trace.write_text(json.dumps({**base, "net_R": -0.5}) + "\n")
        challenger_trace.write_text(json.dumps({**base, "net_R": 1.0}) + "\n")
        comparison = paired_compare(champion_trace, challenger_trace)
        assert comparison["state"] == "PASS_ALPHA_LAP_PAIRED_COMPARISON"
        assert comparison["metrics"]["delta_net_R"] == 1.5
    print(json.dumps({"state": "PASS_SELF_TEST"}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("register", "compare"))
    parser.add_argument("--top3")
    parser.add_argument("--champions")
    parser.add_argument("--champion-trace")
    parser.add_argument("--challenger-trace")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.mode or not args.out:
        parser.error("mode and out are required")
    if args.mode == "register":
        if not args.top3:
            parser.error("top3 is required for register")
        result = register_challengers(Path(args.top3), Path(args.champions) if args.champions else None)
    else:
        if not args.champion_trace or not args.challenger_trace:
            parser.error("champion-trace and challenger-trace are required for compare")
        result = paired_compare(Path(args.champion_trace), Path(args.challenger_trace))
    atomic_json(Path(args.out), result)
    print(json.dumps({"state": result["state"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
