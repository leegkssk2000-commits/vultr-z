from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "ZEL_ALPHA_GEMINI_GOVERNANCE_V1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def call_model(model: str, role: str, instruction: str, evidence: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    payload = {
        "contents": [{
            "parts": [{
                "text": f"You are {role}. {instruction} EVIDENCE="
                + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        body = json.load(response)
    return json.loads(body["candidates"][0]["content"]["parts"][0]["text"])


def call_pool(models: list[str], role: str, instruction: str, evidence: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    last = ""
    for model in models:
        try:
            return model, call_model(model, role, instruction, evidence)
        except Exception as exc:  # fail closed after bounded fallbacks
            last = f"{type(exc).__name__}:{exc}"
            time.sleep(2)
    raise RuntimeError("GEMINI_MODEL_POOL_FAILED:" + last)


def selected_delta(result: dict[str, Any]) -> tuple[float | None, float | None]:
    control = result.get("control") if isinstance(result.get("control"), dict) else {}
    selected = result.get("selected_improvement") if isinstance(result.get("selected_improvement"), dict) else {}
    if not selected:
        return None, None
    try:
        delta = float(selected.get("net_return_pct_sum")) - float(control.get("net_return_pct_sum"))
    except (TypeError, ValueError):
        delta = None
    gate = selected.get("candidate_gate") if isinstance(selected.get("candidate_gate"), dict) else {}
    try:
        retention = float(gate.get("retention_pct"))
    except (TypeError, ValueError):
        retention = None
    return delta, retention


def govern(
    governance: dict[str, Any],
    result: dict[str, Any],
    state: dict[str, Any],
    source: dict[str, Any],
    compute_minutes: float | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = governance["gemini_contract"]
    designer_pool = list(contract["designer_models"])
    redteam_pool = list(contract["redteam_models"])
    if set(designer_pool) & set(redteam_pool):
        raise RuntimeError("GEMINI_MODEL_POOLS_NOT_DISJOINT")
    allowed = set(str(v) for v in (result.get("remaining_axis_ids") or []))
    allowed.discard(str(result.get("axis_id") or ""))
    deterministic = str(result.get("deterministic_next_axis_id") or "")
    evidence = {
        "state": result.get("state"),
        "epoch": result.get("epoch"),
        "current_axis": result.get("axis_id"),
        "control": result.get("control"),
        "candidates": result.get("candidates"),
        "selected_improvement": result.get("selected_improvement"),
        "champion_found": result.get("champion_found"),
        "converged": result.get("converged"),
        "allowed_next_axes": sorted(allowed),
        "deterministic_next_axis": deterministic,
        "result_receipt_sha256": result.get("receipt_sha256"),
        "source_owner_receipt_sha256": source.get("receipt_sha256"),
        "constraints": {
            "one_axis_only": True,
            "raw_canonical_exact25_control_forbidden": True,
            "deterministic_gate_overrides_ai": True,
            "no_production_authority": True,
        },
    }
    terminal = bool(result.get("champion_found") or result.get("converged"))
    api_calls = 0
    proposed: str | None = None
    designer_model: str | None = None
    redteam_model: str | None = None
    designer_response: dict[str, Any] = {"verdict": "STOP", "reason": "terminal state"}
    redteam_response: dict[str, Any] = {"verdict": "ACCEPT", "reason": "terminal state", "hidden_failure": "none"}
    accepted = terminal
    selected: str | None = None
    failure: str | None = None

    if not terminal:
        try:
            designer_model, designer_response = call_pool(
                designer_pool,
                "the bounded causal next-axis designer",
                "Return JSON verdict TEST or HOLD, next_axis, reason, and falsification. next_axis must be exactly one allowed value.",
                evidence,
            )
            api_calls += 1
            proposed = str(designer_response.get("next_axis") or "") or None
        except Exception as exc:
            failure = f"DESIGNER_FAILED:{type(exc).__name__}:{exc}"
        designer_valid = (
            str(designer_response.get("verdict") or "").upper() == "TEST"
            and proposed in allowed
        )
        if designer_valid:
            try:
                redteam_model, redteam_response = call_pool(
                    redteam_pool,
                    "the independent red-team",
                    "Return JSON verdict ACCEPT, REJECT, or MORE_EVIDENCE plus reason and hidden_failure. Reject leakage, repeated-axis mining, unsupported metric logic, or relative-only profitability.",
                    {**evidence, "proposed_next_axis": proposed},
                )
                api_calls += 1
            except Exception as exc:
                failure = f"REDTEAM_FAILED:{type(exc).__name__}:{exc}"
                redteam_response = {
                    "verdict": "MORE_EVIDENCE",
                    "reason": failure,
                    "hidden_failure": "red-team unavailable",
                }
            accepted = str(redteam_response.get("verdict") or "").upper() in {
                str(v).upper() for v in contract["accepted_verdicts"]
            }
        selected = proposed if designer_valid and accepted else deterministic
        if selected not in set(str(v) for v in (result.get("remaining_axis_ids") or [])):
            selected = None
        if selected:
            state["next_axis_id"] = selected

    review_state = (
        "PASS_GEMINI_NEXT_AXIS_ACCEPTED"
        if terminal or (accepted and proposed == selected)
        else "HOLD_GEMINI_FALLBACK_TO_DETERMINISTIC_AXIS"
    )
    review = {
        "schema_version": "zel.alpha.gemini.governance.review.v1",
        "version": VERSION,
        "state": review_state,
        "designer": {"model": designer_model, "response": designer_response},
        "redteam": {"model": redteam_model, "response": redteam_response},
        "ai_proposed_axis": proposed,
        "deterministic_axis": deterministic or None,
        "selected_next_axis": state.get("next_axis_id"),
        "accepted": accepted,
        "failure": failure,
        "evidence_receipt_sha256": result.get("receipt_sha256"),
        "source_owner_receipt_sha256": source.get("receipt_sha256"),
        "raw_trade_rows_sent": False,
        "raw_prices_sent": False,
        "private_code_sent": False,
        "credentials_sent": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    review["receipt_sha256"] = stable_sha(review)
    state["gemini_last_axis_accepted"] = accepted
    state["gemini_last_review_sha256"] = review["receipt_sha256"]
    state_without_sha = {k: v for k, v in state.items() if k != "receipt_sha256"}
    state["receipt_sha256"] = stable_sha(state_without_sha)

    delta, retention = selected_delta(result)
    ledger = {
        "schema_version": "zel.ai.value_ledger.row.v1",
        "version": VERSION,
        "epoch_id": f"alpha_combo:{result.get('epoch')}:{result.get('receipt_sha256')}",
        "strategy_id": "alpha_combo",
        "axis_id": result.get("axis_id"),
        "designer_model": designer_model,
        "redteam_model": redteam_model,
        "ai_proposed_axis": proposed,
        "deterministic_axis": deterministic or None,
        "selected_axis": state.get("next_axis_id"),
        "redteam_verdict": redteam_response.get("verdict"),
        "global_delta_net_return_pct_sum": delta,
        "w1_delta_net_R": None,
        "w2_delta_net_R": None,
        "w3_delta_net_R": None,
        "window_delta_status": "HOLD_WINDOW_METRICS_NOT_EXPOSED_BY_ALPHA_V3_RECEIPT",
        "retention_pct": retention,
        "compute_minutes": compute_minutes,
        "api_calls": api_calls,
        "survivor": bool(result.get("champion_found")),
        "false_positive": bool(accepted and proposed and result.get("selected_improvement") is None),
        "review_receipt_sha256": review["receipt_sha256"],
        "result_receipt_sha256": result.get("receipt_sha256"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    ledger["receipt_sha256"] = stable_sha(ledger)
    return review, ledger, state


def self_test() -> int:
    governance = {
        "gemini_contract": {
            "designer_models": ["designer"],
            "redteam_models": ["redteam"],
            "accepted_verdicts": ["ACCEPT"],
        }
    }
    result = {
        "state": "WAIT_NEW_DATA_FINGERPRINT_ALPHA_CHAMPION_NOT_FOUND",
        "epoch": 21,
        "axis_id": "TIME_STOP",
        "champion_found": False,
        "converged": True,
        "remaining_axis_ids": ["TIME_STOP"],
        "deterministic_next_axis_id": "TIME_STOP",
        "receipt_sha256": "a" * 64,
    }
    state = {"next_axis_id": "TIME_STOP", "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "action": "hold"}
    source = {"receipt_sha256": "b" * 64}
    review, ledger, updated = govern(governance, result, state, source, 1.0)
    assert review["state"] == "PASS_GEMINI_NEXT_AXIS_ACCEPTED"
    assert ledger["api_calls"] == 0
    assert updated["receipt_sha256"]
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--governance", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compute-minutes", type=float)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (args.governance, args.result, args.state, args.source_owner, args.out)
    if any(v is None for v in required):
        parser.error("all paths are required")
    governance = read_json(args.governance)
    result = read_json(args.result)
    state = read_json(args.state)
    source = read_json(args.source_owner)
    review, ledger, state = govern(governance, result, state, source, args.compute_minutes)
    write_json(args.out / "gemini_review.json", review)
    write_json(args.out / "ai_value_ledger_row.json", ledger)
    write_json(args.state, state)
    print(json.dumps({"state": review["state"], "selected_axis": review["selected_next_axis"], "api_calls": ledger["api_calls"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
