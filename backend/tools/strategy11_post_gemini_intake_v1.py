from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

VERSION = "STRATEGY11_POST_GEMINI_INTAKE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "canonical_mutated": False,
    "registry_mutated": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "runtime_bound": False,
    "order_authority": "BLOCKED",
}
EXPECTED_STRATEGY_COUNT = 24
EXPECTED_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"}


def read_json(path: Path) -> dict[str, Any]:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_safety(row: Mapping[str, Any], label: str) -> None:
    for key, expected in SAFETY.items():
        if key in row and row[key] != expected:
            raise ValueError(f"SAFETY_MISMATCH:{label}:{key}:{row[key]}:{expected}")


def classify(args: argparse.Namespace) -> int:
    summary = read_json(Path(args.summary))
    artifact = read_json(Path(args.gemini_artifact))
    ai_filter = read_json(Path(args.ai_filter))
    replay = read_json(Path(args.replay_final))
    for label, row in (("summary", summary), ("artifact", artifact), ("ai_filter", ai_filter), ("replay", replay)):
        require_safety(row, label)
    if summary.get("GEMINI_USED") is not True or int(summary.get("reviewed_strategy_count") or 0) != EXPECTED_STRATEGY_COUNT:
        raise ValueError("GEMINI_REVIEW_AUTHORITY_INVALID")
    response = artifact.get("response")
    if not isinstance(response, Mapping):
        raise ValueError("GEMINI_RESPONSE_MISSING")
    reviews = [dict(row) for row in response.get("strategy_reviews", []) if isinstance(row, Mapping)]
    if len(reviews) != EXPECTED_STRATEGY_COUNT or len({str(row.get('strategy_id')) for row in reviews}) != EXPECTED_STRATEGY_COUNT:
        raise ValueError(f"REVIEW_COVERAGE:{len(reviews)}")
    approved = set(str(value) for value in ai_filter.get("accepted_strategy_ids", []))
    rejected = {str(row.get("strategy_id")): dict(row) for row in ai_filter.get("rejected_rows", []) if isinstance(row, Mapping)}
    replay_pass = {str(row.get("strategy_id")): dict(row) for row in replay.get("discovery_pass_rows", []) if isinstance(row, Mapping)}
    terminal_policy = str(response.get("terminal_hold_reason") or "")
    rows: list[dict[str, Any]] = []
    for review in sorted(reviews, key=lambda row: str(row.get("strategy_id"))):
        sid = str(review.get("strategy_id") or "")
        verdict = str(review.get("verdict") or "NO_ACTION")
        candidate_id = review.get("selected_candidate_id")
        if sid in replay_pass:
            category, reason = "PASS_DISCOVERY", "DETERMINISTIC_REPLAY_PASS"
        elif verdict == "NEW_CHILD_REQUIRED":
            category, reason = "NEW_CHILD_REQUIRED", str(review.get("causal_reason") or verdict)
        elif sid in rejected:
            category, reason = "ECONOMIC_REJECT", str(rejected[sid].get("reason") or rejected[sid].get("status") or "AI_GATE_REJECT")
        elif sid in approved:
            category, reason = "QUALITY_IMPROVED_HOLD", "AI_APPROVED_BUT_NO_DISCOVERY_PASS"
        elif verdict == "SELECT_REPLAY":
            category, reason = "RESEARCH_HYPOTHESIS_HOLD", terminal_policy or "NOT_AI_APPROVED"
        else:
            category, reason = "NO_CHANGE", str(review.get("causal_reason") or verdict)
        rows.append({"strategy_id": sid, "category": category, "gemini_verdict": verdict, "candidate_id": candidate_id, "reason": reason, "overfit_risk": review.get("overfit_risk"), "video_source_indexes": review.get("video_source_indexes", [])})
    counts = dict(sorted(Counter(row["category"] for row in rows).items()))
    output = {"schema_version": "1.0", "version": VERSION, "state": "PASS_POST_GEMINI_CLASSIFICATION", "source_run_id": artifact.get("run_id"), "source_input_sha": artifact.get("input_sha"), "source_response_sha": artifact.get("response_sha"), "source_artifact_sha256": file_sha(Path(args.gemini_artifact)), "reviewed_strategy_count": len(rows), "category_counts": counts, "rows": rows, "terminal_selection_policy_reason": terminal_policy or None, "w1_authority_required": True, **SAFETY}
    output["receipt_sha256"] = stable_sha(output)
    write_json(Path(args.out), output)
    print(json.dumps({"state": output["state"], "counts": counts, "sha": output["receipt_sha256"]}, sort_keys=True))
    return 0


def alpha_receipt(args: argparse.Namespace) -> int:
    artifact = read_json(Path(args.gemini_artifact))
    require_safety(artifact, "gemini_artifact")
    alpha = artifact.get("alpha_fresh_only")
    if not isinstance(alpha, Mapping):
        raise ValueError("ALPHA_FRESH_RECEIPT_MISSING")
    if alpha.get("strategy_id") != "alpha_combo" or alpha.get("authority") != "TIME54_TIME60_W1_FRESH_ONLY":
        raise ValueError("ALPHA_AUTHORITY_INVALID")
    hypotheses = [dict(row) for row in alpha.get("hypotheses", []) if isinstance(row, Mapping)]
    if not 0 <= len(hypotheses) <= 2:
        raise ValueError("ALPHA_HYPOTHESIS_COUNT")
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(hypotheses):
        axis = str(row.get("axis") or "").strip()
        parameter = str(row.get("parameter") or "").strip()
        values = row.get("values")
        if not axis or not parameter or not isinstance(values, list) or not 1 <= len(values) <= 4:
            raise ValueError(f"ALPHA_SINGLE_AXIS_SCHEMA:{index}")
        if any(token in parameter for token in (",", "+", "/", "&")):
            raise ValueError(f"ALPHA_COMPOSITE_PARAMETER:{index}")
        normalized.append({"label": row.get("label"), "axis": axis, "parameter": parameter, "values": values, "single_cause_change": row.get("single_cause_change"), "falsification_test": row.get("falsification_test"), "hypothesis_sha256": stable_sha(row)})
    output = {"schema_version": "1.0", "version": VERSION, "state": "WAIT_ALPHA_W1_FRESH", "strategy_id": "alpha_combo", "control_family": ["TIME54", "TIME60"], "mutually_exclusive_controls": True, "same_archive_replay_forbidden": True, "w1_fresh_only": True, "hypothesis_count": len(normalized), "hypotheses": normalized, "source_run_id": artifact.get("run_id"), "source_input_sha": artifact.get("input_sha"), "source_prompt_sha": artifact.get("prompt_sha"), "source_response_sha": artifact.get("response_sha"), "source_video_registry_sha256": stable_sha(artifact.get("public_urls", [])), "next": "WAIT_NATIVE_W1_AND_COMPARE_TIME54_TIME60_BEFORE_EXTERNAL_AXIS", **SAFETY}
    output["receipt_sha256"] = stable_sha(output)
    write_json(Path(args.out), output)
    print(json.dumps({"state": output["state"], "hypotheses": len(normalized), "sha": output["receipt_sha256"]}, sort_keys=True))
    return 0


def w1_preflight(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = read_json(manifest_path)
    contract = read_json(Path(args.overlay_contract))
    require_safety(contract.get("safety", {}), "overlay_contract")
    if manifest.get("state") != "PASS" or manifest.get("blockers") != []:
        raise ValueError("STREAM_MANIFEST_NOT_PASS")
    symbols = [dict(row) for row in manifest.get("symbols", []) if isinstance(row, Mapping)]
    symbol_ids = {str(row.get("symbol")) for row in symbols}
    if symbol_ids != EXPECTED_SYMBOLS:
        raise ValueError(f"STREAM_SYMBOL_PARITY:{sorted(symbol_ids)}")
    available = int(manifest.get("available_non_overlap_bars") or 0)
    missing = int(manifest.get("missing_to_w1_480") or 0)
    if any(int(row.get("rows") or -1) != available for row in symbols):
        raise ValueError("STREAM_ROW_PARITY")
    if any(not row.get("market_sha256") or not row.get("funding_sha256") for row in symbols):
        raise ValueError("STREAM_SHA_MISSING")
    exact_end = str(contract["upstream"]["w1_exact_end_utc"])
    latest = str(manifest.get("latest_closed_end") or "")
    ready = available == 480 and missing == 0 and manifest.get("w1_ready") is True and latest.replace("+00:00", "Z") >= exact_end
    state = "READY_NATIVE_W1_DISPATCH" if ready else "WAIT_W1_DATA"
    schedule = {"preflight_collector_utc": "2026-08-01T08:32:00Z", "final_collector_utc": "2026-08-01T08:47:00Z", "native_w1_utc": "2026-08-01T09:02:00Z", "v3_overlay_utc": "2026-08-01T09:29:00Z"}
    output = {"schema_version": "1.0", "version": VERSION, "state": state, "available_non_overlap_bars": available, "missing_to_w1_480": missing, "w1_ready": bool(manifest.get("w1_ready")), "latest_closed_end": latest, "required_exact_end": exact_end, "symbol_count": len(symbols), "manifest_sha256": file_sha(manifest_path), "market_sha_set_sha256": stable_sha({row["symbol"]: row["market_sha256"] for row in symbols}), "funding_sha_set_sha256": stable_sha({row["symbol"]: row["funding_sha256"] for row in symbols}), "sequence": schedule, "sequence_order_valid": list(schedule.values()) == sorted(schedule.values()), "native_completion_artifact": contract["upstream"]["native_completion_artifact"], "overlay_candidate": contract["candidate"], "next": "DISPATCH_NATIVE_W1" if ready else "WAIT_APPEND_ONLY_COLLECTOR", **SAFETY}
    if not output["sequence_order_valid"]:
        raise ValueError("W1_SEQUENCE_ORDER")
    output["receipt_sha256"] = stable_sha(output)
    write_json(Path(args.out), output)
    print(json.dumps({"state": state, "available": available, "missing": missing, "sha": output["receipt_sha256"]}, sort_keys=True))
    return 0


def shadow_intake(args: argparse.Namespace) -> int:
    classification = read_json(Path(args.classification))
    alpha = read_json(Path(args.alpha_receipt))
    w1 = read_json(Path(args.w1_preflight))
    for label, row in (("classification", classification), ("alpha", alpha), ("w1", w1)):
        require_safety(row, label)
    trend_w1 = read_json(Path(args.trend_w1)) if args.trend_w1 else None
    alpha_w1 = read_json(Path(args.alpha_w1)) if args.alpha_w1 else None
    staged = [{"family_id": "alpha_combo", "role": "CORE", "configs": ["TIME54", "TIME60"], "mutually_exclusive": True, "required_receipt": "ALPHA_W1_FRESH_PASS"}, {"family_id": "trend_ma_macd", "role": "CORE", "configs": ["INT3_MAX_CHASE_DIST_ATR_RELAX"], "mutually_exclusive": False, "required_receipt": "PASS_W1_V3_SURVIVOR_CONFIRMATION"}]
    admitted: list[dict[str, Any]] = []
    if alpha_w1 and alpha_w1.get("state") in {"PASS_ALPHA_W1_FRESH_CONFIRMATION", "PASS_W1_ALPHA_MULTIOBJECTIVE_CONFIRMATION"}:
        admitted.append(staged[0])
    if trend_w1 and trend_w1.get("state") == "PASS_W1_V3_SURVIVOR_CONFIRMATION":
        admitted.append(staged[1])
    upstream_ready = w1.get("state") == "READY_NATIVE_W1_DISPATCH"
    state = "READY_SHADOW_INTAKE_REVIEW" if upstream_ready and admitted else "WAIT_SHADOW_INTAKE_UPSTREAM"
    if len(staged) > 5 or len(admitted) > 3:
        raise ValueError("SHADOW_INTAKE_CAPACITY")
    output = {"schema_version": "1.0", "version": VERSION, "state": state, "staged_family_count": len(staged), "staged_families": staged, "admitted_family_count": len(admitted), "admitted_families": admitted, "shadow_family_capacity_max": 5, "simultaneous_active_max": 3, "shadow_start_allowed": False, "shadow_mutated": False, "w1_preflight_state": w1.get("state"), "classification_receipt_sha256": classification.get("receipt_sha256"), "alpha_receipt_sha256": alpha.get("receipt_sha256"), "w1_receipt_sha256": w1.get("receipt_sha256"), "next": "WAIT_W1_RESULTS" if state.startswith("WAIT") else "HUMAN_REVIEW_BEFORE_SHADOW20", **SAFETY}
    output["receipt_sha256"] = stable_sha(output)
    write_json(Path(args.out), output)
    print(json.dumps({"state": state, "staged": len(staged), "admitted": len(admitted), "sha": output["receipt_sha256"]}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("classify"); p.add_argument("--summary", required=True); p.add_argument("--gemini-artifact", required=True); p.add_argument("--ai-filter", required=True); p.add_argument("--replay-final", required=True); p.add_argument("--out", required=True); p.set_defaults(func=classify)
    p = sub.add_parser("alpha-receipt"); p.add_argument("--gemini-artifact", required=True); p.add_argument("--out", required=True); p.set_defaults(func=alpha_receipt)
    p = sub.add_parser("w1-preflight"); p.add_argument("--manifest", required=True); p.add_argument("--overlay-contract", required=True); p.add_argument("--out", required=True); p.set_defaults(func=w1_preflight)
    p = sub.add_parser("shadow-intake"); p.add_argument("--classification", required=True); p.add_argument("--alpha-receipt", required=True); p.add_argument("--w1-preflight", required=True); p.add_argument("--trend-w1"); p.add_argument("--alpha-w1"); p.add_argument("--out", required=True); p.set_defaults(func=shadow_intake)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
