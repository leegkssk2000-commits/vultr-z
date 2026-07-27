from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_ALPHA_COST_AWARE_GATE_CAUSAL_AUDIT_V1"
EXPECTED_KEYS = {
    "expected_return", "expected_return_pct", "forecast_return", "forecast_return_pct",
    "expected_r", "forecast_r", "predicted_return", "predicted_return_pct",
    "edge", "edge_pct", "signal_score", "expected_alpha", "expected_alpha_pct",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def iter_trades(profile: Mapping[str, Any]):
    for doc in profile.get("documents", []):
        payload = doc.get("payload") if isinstance(doc, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        for trade in payload.get("trades", []):
            if isinstance(trade, Mapping):
                yield trade


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemini-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.gemini_root).resolve()
    out = Path(args.out).resolve()

    summary_path = root / "summary.json"
    queue_path = root / "repair_queue.json"
    red_path = root / "red_team.json"
    analysis_path = root / "strategy_analysis" / "A.json"
    profile_path = root / "profiles" / "A.json"

    summary = load(summary_path)
    queue = load(queue_path)
    red = load(red_path)
    analysis = load(analysis_path)
    profile = load(profile_path)

    if summary.get("state") != "PASS" or summary.get("GEMINI_USED") is not True:
        raise RuntimeError("GEMINI_AUTHORITY_INVALID")
    if summary.get("free_only") is not True:
        raise RuntimeError("FREE_ONLY_VIOLATION")
    if summary.get("approved_hypothesis_count") != 0:
        raise RuntimeError("LATEST_APPROVED_COUNT_UNEXPECTED")
    if queue.get("state") != "HOLD" or queue.get("rows") != []:
        raise RuntimeError("LATEST_REPAIR_QUEUE_UNEXPECTED")

    hypotheses = [
        h for h in analysis.get("candidate_hypotheses", [])
        if isinstance(h, Mapping) and h.get("change_type") == "feature_gate"
    ]
    target = next(
        (h for h in hypotheses if "MIN_EXPECTED_R_THRESHOLD" in " ".join(map(str, h.get("bounded_parameter_space", [])))),
        None,
    )
    if target is None:
        raise RuntimeError("ALPHA_COST_AWARE_HYPOTHESIS_MISSING")

    trades = list(iter_trades(profile))
    feature_rows = []
    supported = 0
    nonempty_features = 0
    keys_seen: set[str] = set()
    for trade in trades:
        features = trade.get("features")
        if isinstance(features, Mapping) and features:
            nonempty_features += 1
            keys = {str(k) for k in features.keys()}
            keys_seen.update(keys)
            matched = sorted(keys & EXPECTED_KEYS)
        else:
            matched = []
        if matched:
            supported += 1
        feature_rows.append({
            "trade_id": trade.get("trade_id"),
            "symbol": trade.get("symbol"),
            "window_id": trade.get("window_id"),
            "matched_expected_return_keys": matched,
        })

    complete_pct = 0.0 if not trades else supported / len(trades) * 100.0
    causal_audit_pass = bool(trades) and supported == len(trades)
    blockers = []
    if not trades:
        blockers.append("ALPHA_TRADE_EVIDENCE_MISSING")
    if supported == 0:
        blockers.append("EXPECTED_RETURN_FEATURE_ABSENT")
    elif supported < len(trades):
        blockers.append("EXPECTED_RETURN_FEATURE_INCOMPLETE")
    if summary.get("approved_hypothesis_count") == 0:
        blockers.append("RED_TEAM_APPROVED_QUEUE_EMPTY")

    state = "PASS_TO_ISOLATED_REPLAY" if causal_audit_pass and not blockers else "HOLD"
    next_step = (
        "CREATE_ISOLATED_ENTRY_COST_GATE_REPLAY"
        if state == "PASS_TO_ISOLATED_REPLAY"
        else "WAIT_NEW_CAUSAL_EVIDENCE_OR_W1_FEATURE_LINEAGE"
    )

    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "strategy_id": "alpha_combo",
        "source_authority": {
            "pr": 222,
            "run_id": 30302007460,
            "artifact": "s11-gemini-active-research-v3-1-30302007460-attempt-1",
            "summary_sha256": sha(summary_path),
            "repair_queue_sha256": sha(queue_path),
            "red_team_sha256": sha(red_path),
            "strategy_analysis_sha256": sha(analysis_path),
            "profile_sha256": sha(profile_path),
        },
        "hypothesis": target,
        "audit": {
            "trade_count": len(trades),
            "trades_with_nonempty_features": nonempty_features,
            "trades_with_expected_return_feature": supported,
            "expected_return_feature_completeness_pct": complete_pct,
            "feature_keys_seen": sorted(keys_seen),
            "required_feature_keys": sorted(EXPECTED_KEYS),
            "causal_audit_pass": causal_audit_pass,
        },
        "blockers": blockers,
        "next": next_step,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    write(out / "feature_lineage_rows.json", {"rows": feature_rows})
    print(json.dumps({"state": state, "trades": len(trades), "supported": supported, "blockers": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
