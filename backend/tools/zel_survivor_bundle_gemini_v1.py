from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tools import zel_manual_multiaxis_gemini_v2 as helper

VERSION = "ZEL_SURVIVOR_BUNDLE_GEMINI_V1"
AXES = {
    "TRADE_METHODS",
    "BEST_SINGLE_SKILL",
    "TEAM_POLICY",
    "ZBOT_ADVICE",
    "LICO_EXECUTION",
    "ZICO_OMS",
    "ZLICE_LINEAGE",
}
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "action": "hold",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def prompt(plan: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]) -> str:
    usable = [dict(row) for row in receipts if row.get("status") == "USE"]
    schema = {
        "status": "PASS|HOLD",
        "hypotheses": [
            {
                "axis": "TRADE_METHODS|BEST_SINGLE_SKILL|TEAM_POLICY|ZBOT_ADVICE|LICO_EXECUTION|ZICO_OMS|ZLICE_LINEAGE",
                "parameter": "one exact parameter",
                "values": ["one to four bounded values"],
                "causal_mechanism": "one mechanism only",
                "falsification_test": "one deterministic exact replay test",
                "source_indexes": [1, 2],
                "overfit_risk": "LOW|MEDIUM|HIGH"
            }
        ],
        "interactions": [
            {
                "left_axis": "one axis",
                "right_axis": "one different axis",
                "causal_mechanism": "why combined delta may differ from additive main effects",
                "falsification_test": "four-cell BASE/A/B/A+B replay test",
                "source_indexes": [1, 2],
                "overfit_risk": "LOW|MEDIUM|HIGH"
            }
        ],
        "rejected_claims": ["unsupported or non-falsifiable claims"]
    }
    return (
        "You are a skeptical quantitative trading systems reviewer. Use only the independently generated direct-video receipts and the exact experiment plan. "
        "The strategy creates raw edge; trade methods and skills can change payoff; TeamBot and ZBot can change admission; Lico can change implementation shortfall; Zico can change OMS tail loss; Zlice must have zero direct economic effect. "
        "Do not claim that a component improves PnL without replay evidence. Return at most four single-axis hypotheses and at most two pair interactions. "
        "Every hypothesis must use one parameter, one causal mechanism, one deterministic falsification test, and at least two independent USE source indexes. "
        "Do not propose Failure Learning or ML-Light for runtime use before fourth Shadow 300C and the independent holdout. They are observer-only after that gate. "
        "Use HOLD if the plan is blocked or evidence is weak. Return strict JSON only.\n"
        f"DIRECT_VIDEO_RECEIPTS={canonical(usable)}\n"
        f"EXACT_STRATEGY_BUNDLE_PLAN={canonical(plan)}\n"
        f"OUTPUT_SCHEMA={canonical(schema)}"
    )


def clean_indexes(raw: Any, usable: set[int]) -> list[int]:
    if not isinstance(raw, list):
        return []
    indexes: set[int] = set()
    for value in raw:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index in usable:
            indexes.add(index)
    return sorted(indexes)


def normalize(response: Mapping[str, Any], usable: set[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    status = str(response.get("status") or "HOLD").upper()
    if status not in {"PASS", "HOLD"}:
        raise RuntimeError(f"STATUS_INVALID:{status}")

    hypotheses: list[dict[str, Any]] = []
    seen_axes: set[str] = set()
    for raw in response.get("hypotheses") or []:
        if not isinstance(raw, Mapping):
            continue
        axis = str(raw.get("axis") or "").upper().strip()
        if axis not in AXES or axis in seen_axes:
            continue
        parameter = str(raw.get("parameter") or "").strip()
        values = raw.get("values")
        mechanism = str(raw.get("causal_mechanism") or "").strip()
        falsification = str(raw.get("falsification_test") or "").strip()
        indexes = clean_indexes(raw.get("source_indexes"), usable)
        if not parameter or any(token in parameter for token in (",", "+", "&")):
            continue
        if not isinstance(values, list) or not 1 <= len(values) <= 4:
            continue
        if not mechanism or not falsification or len(indexes) < 2:
            continue
        seen_axes.add(axis)
        hypotheses.append({
            "axis": axis,
            "parameter": parameter,
            "values": values,
            "causal_mechanism": mechanism,
            "falsification_test": falsification,
            "source_indexes": indexes,
            "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
        })
        if len(hypotheses) == 4:
            break

    interactions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for raw in response.get("interactions") or []:
        if not isinstance(raw, Mapping):
            continue
        left = str(raw.get("left_axis") or "").upper().strip()
        right = str(raw.get("right_axis") or "").upper().strip()
        if left not in AXES or right not in AXES or left == right:
            continue
        pair = tuple(sorted((left, right)))
        if pair in seen_pairs:
            continue
        mechanism = str(raw.get("causal_mechanism") or "").strip()
        falsification = str(raw.get("falsification_test") or "").strip()
        indexes = clean_indexes(raw.get("source_indexes"), usable)
        if not mechanism or not falsification or len(indexes) < 2:
            continue
        seen_pairs.add(pair)
        interactions.append({
            "left_axis": pair[0],
            "right_axis": pair[1],
            "causal_mechanism": mechanism,
            "falsification_test": falsification,
            "source_indexes": indexes,
            "overfit_risk": str(raw.get("overfit_risk") or "HIGH").upper(),
        })
        if len(interactions) == 2:
            break

    rejected = [str(value)[:1000] for value in response.get("rejected_claims") or []][:20]
    return hypotheses, interactions, rejected


def review_one(key: str, plan: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]], out: Path) -> dict[str, Any]:
    usable = {int(row["source_index"]) for row in receipts if row.get("status") == "USE"}
    channels = {str(row.get("channel") or "") for row in receipts if row.get("status") == "USE"}
    if len(usable) < 4 or len(channels) < 4:
        return {
            "schema_version": "zel.survivor_bundle.gemini_receipt.v1",
            "version": VERSION,
            "state": "HOLD_GEMINI_SOURCE_DIVERSITY_LOW",
            "strategy_id": plan.get("strategy_id"),
            "usable_source_count": len(usable),
            "independent_channel_count": len(channels),
            "hypotheses": [],
            "interactions": [],
            **SAFE,
        }
    research_prompt = prompt(plan, receipts)
    model, text = helper.call_generate(key, research_prompt, source=None, max_output_tokens=8192)
    try:
        response = helper.parse_json(text)
        hypotheses, interactions, rejected = normalize(response, usable)
    except Exception:
        repair = research_prompt + "\nYour prior response violated the schema. Return one strict JSON object only."
        model, text = helper.call_generate(key, repair, source=None, max_output_tokens=8192)
        response = helper.parse_json(text)
        hypotheses, interactions, rejected = normalize(response, usable)
    state = "PASS_GEMINI_SURVIVOR_BUNDLE_HYPOTHESES" if hypotheses or interactions else "HOLD_GEMINI_NO_FALSIFIABLE_HYPOTHESIS"
    receipt = {
        "schema_version": "zel.survivor_bundle.gemini_receipt.v1",
        "version": VERSION,
        "state": state,
        "strategy_id": plan.get("strategy_id"),
        "actual_model": model,
        "GEMINI_USED": True,
        "usable_source_count": len(usable),
        "independent_channel_count": len(channels),
        "hypotheses": hypotheses,
        "interactions": interactions,
        "rejected_claims": rejected,
        "plan_sha256": plan.get("plan_sha256"),
        "prompt_sha256": hashlib.sha256(research_prompt.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "replay_allowed": False,
        "next": "GROQ_AND_WORKERS_RED_TEAM_THEN_EXACT_REPLAY",
        **SAFE,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    write_json(out / "receipt.json", receipt)
    for index, hypothesis in enumerate(hypotheses, start=1):
        envelope = {
            "strategy_id": plan.get("strategy_id"),
            "stage": "PRE_REPLAY_EXTERNAL_HYPOTHESIS",
            "changed_axes": [hypothesis["axis"]],
            "hypothesis": hypothesis,
            "lineage_complete": True,
            "lineage": {
                "plan_sha256": plan.get("plan_sha256"),
                "gemini_receipt_sha256": receipt["receipt_sha256"],
            },
            "control": plan.get("source_metrics") or {},
            "candidate": {},
            **SAFE,
        }
        write_json(out / "hypotheses" / f"{index:02d}-{hypothesis['axis']}.json", envelope)
    return receipt


def run(args: argparse.Namespace) -> dict[str, Any]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    registry = read_json(args.registry)
    sources = [dict(row) for row in registry.get("sources") or [] if isinstance(row, Mapping)]
    out = Path(args.out)
    receipts = helper.analyze_sources(key, sources, out / "video_research")
    plans = sorted(Path(args.plans).glob("strategies/*/plan.json"))
    results = []
    for path in plans:
        plan = read_json(path)
        strategy_id = str(plan.get("strategy_id") or path.parent.name)
        results.append(review_one(key, plan, receipts, out / "strategies" / strategy_id))
    state = "PASS_GEMINI_SURVIVOR_BUNDLE_RESEARCH" if results and any(row.get("GEMINI_USED") for row in results) else "HOLD_NO_SURVIVOR_GEMINI_REVIEW"
    summary = {
        "schema_version": "zel.survivor_bundle.gemini_summary.v1",
        "version": VERSION,
        "state": state,
        "strategy_count": len(results),
        "strategies": results,
        "source_receipts": receipts,
        "failure_learning_ml_light_runtime_binding_allowed": False,
        **SAFE,
    }
    summary["summary_sha256"] = stable_sha(summary)
    write_json(out / "latest.json", summary)
    return summary


def self_test() -> None:
    usable = {1, 2, 3, 4}
    response = {
        "status": "PASS",
        "hypotheses": [{
            "axis": "TRADE_METHODS",
            "parameter": "base_tp_r",
            "values": [2.25, 2.5],
            "causal_mechanism": "exit capture differs by MFE distribution",
            "falsification_test": "replay the same entries under both targets",
            "source_indexes": [1, 2],
            "overfit_risk": "MEDIUM",
        }],
        "interactions": [{
            "left_axis": "TEAM_POLICY",
            "right_axis": "LICO_EXECUTION",
            "causal_mechanism": "stricter admission may select lower spread conditions",
            "falsification_test": "BASE, TEAM, LICO and TEAM+LICO four-cell replay",
            "source_indexes": [2, 3],
            "overfit_risk": "MEDIUM",
        }],
    }
    hypotheses, interactions, _ = normalize(response, usable)
    assert len(hypotheses) == 1
    assert len(interactions) == 1
    assert hypotheses[0]["axis"] == "TRADE_METHODS"
    assert interactions[0]["left_axis"] == "LICO_EXECUTION"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plans")
    parser.add_argument("--registry")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.plans or not args.registry or not args.out:
        parser.error("--plans, --registry and --out are required")
    summary = run(args)
    print(json.dumps({"state": summary["state"], "strategy_count": summary["strategy_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
