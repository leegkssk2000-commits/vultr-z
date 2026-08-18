from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_openai_critic_v1 import call_openai_critic

SCHEMA = "zel.a1_ai_multicritic_review.v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_WORKERS_MODEL = "@cf/meta/llama-3.1-8b-instruct"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def safe_error(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    for marker in ("sk-", "gsk_", "cfut_", "AIza"):
        if marker in text:
            return f"{type(exc).__name__}:REDACTED_SENSITIVE_ERROR"
    return f"{type(exc).__name__}:{text[:1200]}"


def extract_top_axis(prep: Mapping[str, Any]) -> dict[str, Any]:
    axes = prep.get("top3_axes")
    if not isinstance(axes, list) or not axes or not isinstance(axes[0], Mapping):
        raise RuntimeError("TOP_AXIS_MISSING")
    row = dict(axes[0])
    axis = str(row.get("axis") or "").strip()
    if not axis:
        raise RuntimeError("TOP_AXIS_ID_MISSING")
    return row


def build_semantic_payload(prep: Mapping[str, Any], prep_path: Path) -> dict[str, Any]:
    axis = extract_top_axis(prep)
    metrics = prep.get("metrics") if isinstance(prep.get("metrics"), Mapping) else {}
    fingerprint = prep.get("fingerprint") if isinstance(prep.get("fingerprint"), Mapping) else {}
    sources = prep.get("external_sources") if isinstance(prep.get("external_sources"), list) else []
    source_ids = [str(x.get("id") or "") for x in sources if isinstance(x, Mapping) and x.get("id")]
    axis_sources = [str(x) for x in (axis.get("source_ids") or [])]
    source_subset = [
        {
            "id": str(x.get("id") or ""),
            "tier": str(x.get("tier") or ""),
            "identifier": str(x.get("identifier") or ""),
            "claim": str(x.get("claim") or "")[:1200],
        }
        for x in sources
        if isinstance(x, Mapping) and str(x.get("id") or "") in set(axis_sources)
    ]
    payload = {
        "strategy_id": str(prep.get("strategy_id") or prep_path.stem),
        "classification": str(prep.get("classification") or ""),
        "failure_fingerprint": {
            "primary": fingerprint.get("primary"),
            "secondary": list(fingerprint.get("secondary") or []),
        },
        "changed_axes": [str(axis["axis"])],
        "candidate_axis": str(axis["axis"]),
        "hypothesis": {
            "axis": str(axis["axis"]),
            "mechanism": str(axis.get("mechanism") or ""),
            "expected_metric_direction": axis.get("expected_metric_direction") or {},
            "falsification": str(axis.get("falsification") or ""),
            "required_data": list(axis.get("required_data") or []),
            "forbidden_collateral_changes": list(axis.get("forbidden_collateral_changes") or []),
        },
        "evidence": {
            "metrics": {
                key: metrics.get(key)
                for key in (
                    "completed_trades", "gross_expectancy_bps", "net_expectancy_bps",
                    "net_pnl_bps", "profit_factor", "payoff", "win_rate",
                    "drawdown_bps", "verified_pretrade_cost_bps",
                )
                if key in metrics
            },
            "source_ids": source_ids,
            "axis_sources": axis_sources,
            "source_subset": source_subset,
        },
        "lineage_complete": bool(axis_sources) and all(x in source_ids for x in axis_sources),
        "lineage": {
            "prep_path": str(prep_path),
            "prep_sha256": hashlib.sha256(prep_path.read_bytes()).hexdigest(),
            "baseline_observation_sha": prep.get("baseline_observation_sha"),
            "source_ids": axis_sources,
        },
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    return payload


def proposer_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    h = payload.get("hypothesis") if isinstance(payload.get("hypothesis"), Mapping) else {}
    return {
        "status": "PASS",
        "proposals": [
            {
                "proposal_type": "FEATURE_AUGMENTATION",
                "family_id": str(payload.get("strategy_id") or "strategy")[:48] + "_review",
                "economic_mechanism": str(h.get("mechanism") or "")[:2000],
                "required_sources": list(payload.get("evidence", {}).get("axis_sources") or []),
                "causal_reason": "Review the single preregistered causal axis against its evidence and falsification rule.",
                "falsification_test": str(h.get("falsification") or "")[:2000],
                "expected_horizon": "frozen strategy-native horizon",
            }
        ],
    }


def run_cmd(cmd: list[str], env: Mapping[str, str]) -> tuple[int, str, str]:
    cp = subprocess.run(cmd, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return cp.returncode, cp.stdout[-2000:], cp.stderr[-2000:]


def review_groq(payload: Mapping[str, Any], work: Path) -> dict[str, Any]:
    if not os.environ.get("GROQ_API_KEY", "").strip():
        return {"state": "HOLD_GROQ_API_KEY_MISSING", "successful": False}
    inp = work / "groq_input.json"
    out = work / "groq_output.json"
    inp.write_text(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    env = os.environ.copy()
    env["GROQ_MODEL"] = env.get("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
    rc, _, err = run_cmd([sys.executable, "scripts/strategy11_groq_redteam.py", "--input", str(inp), "--output", str(out)], env)
    data = read_json(out) if out.is_file() else {}
    return {
        "state": data.get("status") or ("HOLD_GROQ_REVIEW" if rc else "UNKNOWN"),
        "successful": rc == 0 and data.get("status") == "PASS_GROQ_REDTEAM_CONNECTION" and data.get("GROQ_USED") is True,
        "model": data.get("actual_model"),
        "decision": (data.get("review") or {}).get("decision") if isinstance(data.get("review"), Mapping) else None,
        "blocker_codes": (data.get("review") or {}).get("blocker_codes") if isinstance(data.get("review"), Mapping) else [],
        "overfit_risk": (data.get("review") or {}).get("overfit_risk") if isinstance(data.get("review"), Mapping) else None,
        "reason": (data.get("review") or {}).get("reason") if isinstance(data.get("review"), Mapping) else None,
        "input_sha": data.get("input_sha"),
        "prompt_sha": data.get("prompt_sha"),
        "response_sha": data.get("response_sha"),
        "error": None if rc == 0 else (data.get("blocker_code") or err[:1000]),
    }


def review_workers(payload: Mapping[str, Any], work: Path) -> dict[str, Any]:
    if not os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip() or not os.environ.get("CLOUDFLARE_WORKERS_AI_TOKEN", "").strip():
        return {"state": "HOLD_WORKERS_AI_SECRET_MISSING", "successful": False}
    inp = work / "workers_input.json"
    out = work / "workers_output.json"
    inp.write_text(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    model = os.environ.get("WORKERS_AI_MODEL", "").strip() or DEFAULT_WORKERS_MODEL
    env = os.environ.copy()
    rc, _, err = run_cmd([
        sys.executable, "scripts/strategy11_workers_ai_guard.py",
        "--input", str(inp), "--output", str(out), "--model", model,
    ], env)
    data = read_json(out) if out.is_file() else {}
    review = data.get("review") if isinstance(data.get("review"), Mapping) else {}
    return {
        "state": data.get("status") or ("HOLD_WORKERS_AI_REVIEW" if rc else "UNKNOWN"),
        "successful": rc == 0 and data.get("status") == "PASS_WORKERS_AI_CONNECTION" and data.get("model_called") is True,
        "model": data.get("model") or model,
        "decision": review.get("decision"),
        "blocker_codes": review.get("blocker_codes") or [],
        "overfit_risk": review.get("overfit_risk"),
        "reason": review.get("reason"),
        "input_sha": data.get("input_sha"),
        "prompt_sha": data.get("prompt_sha"),
        "response_sha": data.get("response_sha"),
        "error": None if rc == 0 else (data.get("blocker_code") or err[:1000]),
    }


def openai_health() -> dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5-mini"
    if not key:
        return {"state": "HOLD_OPENAI_API_KEY_MISSING", "successful": False, "model": model}
    fixture = {
        "status": "PASS",
        "proposals": [{
            "proposal_type": "FEATURE_AUGMENTATION",
            "family_id": "health_fixture",
            "economic_mechanism": "Single pre-entry liquidity context gate.",
            "required_sources": ["ohlcv"],
            "causal_reason": "Connectivity-only fixture.",
            "falsification_test": "Reject if frozen control is not improved prospectively.",
            "expected_horizon": "native horizon",
        }],
    }
    try:
        actual, receipt = call_openai_critic(key, model, fixture, timeout_sec=45, max_output_tokens=600)
        return {
            "state": "PASS_OPENAI_CRITIC_CONNECTION",
            "successful": True,
            "model": actual,
            "decision": receipt.get("decision"),
            "blocker_codes": receipt.get("blocker_codes") or [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"state": "HOLD_OPENAI_CRITIC_CONNECTION", "successful": False, "model": model, "error": safe_error(exc)}


def review_openai(payload: Mapping[str, Any], health: Mapping[str, Any]) -> dict[str, Any]:
    model = str(health.get("model") or "gpt-5-mini")
    if health.get("successful") is not True:
        return {"state": str(health.get("state") or "HOLD_OPENAI_UNAVAILABLE"), "successful": False, "model": model, "error": health.get("error")}
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    try:
        actual, receipt = call_openai_critic(key, model, proposer_payload(payload), timeout_sec=45, max_output_tokens=800)
        return {
            "state": "PASS_OPENAI_CRITIC_CONNECTION",
            "successful": True,
            "model": actual,
            "decision": receipt.get("decision"),
            "blocker_codes": receipt.get("blocker_codes") or [],
            "reason": receipt.get("reason"),
            "input_sha": receipt.get("input_sha"),
            "prompt_sha": receipt.get("prompt_sha"),
            "response_sha": receipt.get("response_sha"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"state": "HOLD_OPENAI_CRITIC_CONNECTION", "successful": False, "model": model, "error": safe_error(exc)}


def gemini_status(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"state": "MISSING_RECEIPT", "successful": False}
    row = read_json(path)
    return {
        "state": str(row.get("state") or "UNKNOWN"),
        "successful": row.get("state") == "PASS_EXTERNAL_RESEARCH_EVIDENCE_READY" and row.get("ai_call_succeeded") is True,
        "ai_call_made": bool(row.get("ai_call_made")),
        "quota_class": row.get("quota_class"),
        "quota_retry_after_ms": row.get("quota_retry_after_ms"),
        "receipt_sha": row.get("receipt_sha256"),
        "updated_at_ms": row.get("updated_at_ms"),
    }


def run(prep_dir: Path, output: Path, gemini_receipt: Path | None) -> dict[str, Any]:
    paths = sorted(prep_dir.glob("*.json"))
    preps: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        try:
            row = read_json(path)
        except Exception:
            continue
        if row.get("state") == "EARLY_AI_PREP_READY" and row.get("baseline_mutated") is False:
            preps.append((path, row))

    gstatus = gemini_status(gemini_receipt)
    ohealth = openai_health()
    rows: list[dict[str, Any]] = []
    provider_success = {"gemini": 0, "openai": 0, "groq": 0, "workers_ai": 0}

    with tempfile.TemporaryDirectory(prefix="a1-ai-review-") as td:
        root = Path(td)
        for idx, (path, prep) in enumerate(preps):
            try:
                payload = build_semantic_payload(prep, path)
            except Exception as exc:  # noqa: BLE001
                rows.append({"strategy_id": str(prep.get("strategy_id") or path.stem), "state": "HOLD_PREP_INVALID", "error": safe_error(exc)})
                continue
            work = root / str(idx); work.mkdir()
            groq = review_groq(payload, work)
            workers = review_workers(payload, work)
            openai = review_openai(payload, ohealth)
            providers = {
                "gemini": dict(gstatus),
                "openai": openai,
                "groq": groq,
                "workers_ai": workers,
                "github_models": {"state": "RETIRED_HTTP_410_NON_REQUIRED", "successful": False, "blocking": False},
            }
            for key in provider_success:
                provider_success[key] += int(providers[key].get("successful") is True)
            successful_reviewers = [k for k in ("openai", "groq", "workers_ai") if providers[k].get("successful") is True]
            decisions = {k: providers[k].get("decision") for k in successful_reviewers}
            rows.append({
                "strategy_id": str(prep.get("strategy_id") or path.stem),
                "prep_path": str(path),
                "prep_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "top1_axis": payload["candidate_axis"],
                "axis_source_ids": list(payload["evidence"]["axis_sources"]),
                "payload_sha256": sha(payload),
                "lineage_complete": payload["lineage_complete"],
                "providers": providers,
                "successful_independent_reviewers": successful_reviewers,
                "review_decisions": decisions,
                "state": "AI_REVIEW_READY" if successful_reviewers else "HOLD_NO_LIVE_INDEPENDENT_REVIEWER",
                "baseline_mutated": False,
                "improvement_executed": False,
            })

    bottlenecks: list[str] = []
    if not gstatus.get("successful"):
        bottlenecks.append("GEMINI_UNAVAILABLE:" + str(gstatus.get("quota_class") or gstatus.get("state")))
    if not ohealth.get("successful"):
        bottlenecks.append("OPENAI_CHATGPT_UNAVAILABLE:" + str(ohealth.get("error") or ohealth.get("state"))[:500])
    if preps and provider_success["groq"] < len(preps):
        bottlenecks.append(f"GROQ_REVIEW_GAPS:{provider_success['groq']}/{len(preps)}")
    if preps and provider_success["workers_ai"] < len(preps):
        bottlenecks.append(f"WORKERS_AI_REVIEW_GAPS:{provider_success['workers_ai']}/{len(preps)}")

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_A1_AI_MULTICRITIC_REVIEW_READY" if rows and all(r.get("state") == "AI_REVIEW_READY" for r in rows) else "HOLD_A1_AI_MULTICRITIC_GAPS",
        "reviewed_strategy_count": len(rows),
        "provider_successful_strategy_counts": provider_success,
        "openai_health": ohealth,
        "gemini_health": gstatus,
        "bottlenecks": bottlenecks,
        "reviews": rows,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fixture = {
        "strategy_id": "fixture_strategy",
        "state": "EARLY_AI_PREP_READY",
        "classification": "PRELIMINARY_NOT_TERMINAL",
        "baseline_mutated": False,
        "baseline_observation_sha": "baseline-sha",
        "metrics": {"completed_trades": 10, "net_expectancy_bps": -1.0, "verified_pretrade_cost_bps": 14.0},
        "fingerprint": {"primary": "COST_INSUFFICIENT", "secondary": []},
        "external_sources": [{"id": "S1", "tier": "paper", "identifier": "doi:test", "claim": "fixture"}],
        "top3_axes": [{
            "rank": 1,
            "axis": "LIQUIDITY_CONTEXT",
            "mechanism": "one context gate",
            "source_ids": ["S1"],
            "expected_metric_direction": {"net_expectancy": "UP"},
            "falsification": "no prospective improvement",
            "required_data": ["ohlcv"],
            "forbidden_collateral_changes": ["stop", "fees"],
        }],
    }
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prep.json"
        p.write_text(json.dumps(fixture), encoding="utf-8")
        payload = build_semantic_payload(fixture, p)
        assert payload["changed_axes"] == ["LIQUIDITY_CONTEXT"]
        assert payload["lineage_complete"] is True
        assert payload["promotion_authority"] is False
        assert payload["order_authority"] == "BLOCKED"
        assert DEFAULT_GROQ_MODEL == "openai/gpt-oss-120b"
        assert DEFAULT_WORKERS_MODEL.startswith("@cf/")
    print("PASS_A1_AI_MULTICRITIC_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep-dir", type=Path, default=Path("backend/research/early_ai_prep"))
    ap.add_argument("--gemini-receipt", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_ai_multicritic_review.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.prep_dir, args.output, args.gemini_receipt)
    print(json.dumps({
        "state": result["state"],
        "reviewed_strategy_count": result["reviewed_strategy_count"],
        "provider_successful_strategy_counts": result["provider_successful_strategy_counts"],
        "bottlenecks": result["bottlenecks"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
