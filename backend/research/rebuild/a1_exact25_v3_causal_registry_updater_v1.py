from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def terminal_disposition(controls: Mapping[str, Any]) -> str | None:
    state = str(controls.get("state") or "")
    if state == "PASS_V3_UNIVERSAL_HARD_CONTROLS":
        return "CAUSAL_CONTROL_PASS"
    if state != "HOLD_V3_UNIVERSAL_HARD_CONTROLS":
        return None
    if list(controls.get("blockers") or []):
        return None
    hard = controls.get("hard_control_states") if isinstance(controls.get("hard_control_states"), Mapping) else {}
    return "CAUSAL_CONTROL_FAIL" if any(str(v) == "FAIL" for v in hard.values()) else None


def build_row(receipt: Mapping[str, Any], controls: Mapping[str, Any], run_id: str, head_sha: str) -> dict[str, Any] | None:
    disposition = terminal_disposition(controls)
    if disposition is None:
        return None
    cid = str(controls.get("candidate_id") or receipt.get("strategy_id") or "")
    if not cid or cid != str(receipt.get("strategy_id") or ""):
        raise RuntimeError("CAUSAL_REGISTRY_IDENTITY_MISMATCH")
    seed = controls.get("control_seed_lineage") if isinstance(controls.get("control_seed_lineage"), Mapping) else {}
    hard_names = [str(x) for x in (controls.get("hard_control_names") or [])]
    neg = controls.get("negative_controls") if isinstance(controls.get("negative_controls"), Mapping) else {}
    compact_controls: dict[str, Any] = {}
    for name in hard_names:
        value = neg.get(name)
        if isinstance(value, Mapping):
            compact_controls[name] = {k: value.get(k) for k in (
                "state", "trade_count", "candidate_net_R", "control_net_R",
                "candidate_minus_control_net_R", "p_value", "candidate_minus_control_ci_low_R",
                "frozen_cohort_sha256",
            ) if k in value}
    lineage = {
        "policy_sha": seed.get("policy_sha") or receipt.get("policy_sha"),
        "config_sha": seed.get("config_sha") or receipt.get("config_sha"),
        "boundary_utc": seed.get("boundary_utc") or receipt.get("boundary_utc"),
        "cohort_rule": controls.get("frozen_control_cohort_rule"),
        "frozen_control_trade_count": controls.get("frozen_control_trade_count"),
    }
    row = {
        "state": disposition,
        "terminal_for_policy_config_boundary_identity": True,
        "candidate_id": cid,
        "completed_trades_at_evaluation": int(controls.get("completed_trades") or 0),
        "lineage": lineage,
        "lineage_sha256": sha(lineage),
        "hard_control_states": dict(controls.get("hard_control_states") or {}),
        "hard_controls": compact_controls,
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "controls_receipt_sha256": controls.get("receipt_sha256"),
        "source_run_id": str(run_id),
        "source_head_sha": str(head_sha),
        "next_route": "A2_FORWARD" if disposition == "CAUSAL_CONTROL_PASS" else "ENTRY_CAUSALITY_REDESIGN_NEW_IDENTITY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
    }
    row["row_sha256"] = sha(row)
    return row


def evaluate(registry: Mapping[str, Any], candidates_dir: Path, run_id: str, head_sha: str) -> dict[str, Any]:
    if registry.get("state") != "ACTIVE_CAUSAL_DISPOSITION_REGISTRY":
        raise RuntimeError("CAUSAL_REGISTRY_NOT_ACTIVE")
    strategies = dict(registry.get("strategies") or {})
    added: list[str] = []
    verified_existing: list[str] = []
    for directory in sorted(p for p in candidates_dir.iterdir() if p.is_dir()):
        rp, cp = directory / "receipt.json", directory / "controls.json"
        if not rp.exists() or not cp.exists():
            continue
        row = build_row(read(rp), read(cp), run_id, head_sha)
        if row is None:
            continue
        cid = str(row["candidate_id"])
        prior = strategies.get(cid)
        if isinstance(prior, Mapping):
            if str(prior.get("lineage_sha256") or "") != str(row["lineage_sha256"]):
                raise RuntimeError(f"TERMINAL_CAUSAL_IDENTITY_LINEAGE_DRIFT:{cid}")
            if str(prior.get("state") or "") != str(row["state"]):
                raise RuntimeError(f"TERMINAL_CAUSAL_DISPOSITION_DRIFT:{cid}")
            verified_existing.append(cid)
            continue
        strategies[cid] = row
        added.append(cid)
    out = dict(registry)
    out["strategies"] = dict(sorted(strategies.items()))
    out["terminal_count"] = len(strategies)
    out["pass_count"] = sum(1 for x in strategies.values() if isinstance(x, Mapping) and x.get("state") == "CAUSAL_CONTROL_PASS")
    out["fail_count"] = sum(1 for x in strategies.values() if isinstance(x, Mapping) and x.get("state") == "CAUSAL_CONTROL_FAIL")
    out["last_merge"] = {"source_run_id": str(run_id), "source_head_sha": str(head_sha), "added": added, "verified_existing": verified_existing}
    out["receipt_sha256"] = sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def self_test() -> int:
    assert terminal_disposition({"state": "WAIT_V3_CONTROL_SAMPLE"}) is None
    assert terminal_disposition({"state": "PASS_V3_UNIVERSAL_HARD_CONTROLS"}) == "CAUSAL_CONTROL_PASS"
    assert terminal_disposition({"state": "HOLD_V3_UNIVERSAL_HARD_CONTROLS", "blockers": [], "hard_control_states": {"x": "FAIL"}}) == "CAUSAL_CONTROL_FAIL"
    print("PASS_A1_EXACT25_V3_CAUSAL_REGISTRY_UPDATER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--candidates-dir", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = evaluate(read(args.registry), args.candidates_dir, args.run_id, args.head_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"terminal_count": result["terminal_count"], "pass_count": result["pass_count"], "fail_count": result["fail_count"], "last_merge": result["last_merge"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
