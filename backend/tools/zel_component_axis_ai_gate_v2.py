from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_component_autonomy_v2 as core

VERSION = "ZEL_COMPONENT_AXIS_AI_GATE_V2"
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
AXIS_MODULE = {
    "BOT_POLICY": "bots",
    "TEAM_POLICY": "teams",
    "SKILL_PROFILE": "skills",
    "ADVISOR_PROFILE": "advisors",
}


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def axis_candidate(result: Mapping[str, Any], axis: str) -> tuple[Any, Mapping[str, Any], Mapping[str, Any]]:
    modules = result["module_results"]
    if axis == "BOT_POLICY":
        configuration = modules["bots"]["best_by_role"]
        material_rows = [row for row in configuration.values() if (row.get("evidence") or {}).get("material")]
        if not material_rows:
            raise ValueError("BOT_AXIS_NOT_MATERIAL")
        best = max(material_rows, key=lambda row: core.number((row.get("evidence") or {}).get("deltas", {}).get("net")))
        return configuration, best["stats"], best["evidence"]
    if axis == "TEAM_POLICY":
        best = modules["teams"]["best"]
        return {key: value for key, value in best.items() if key not in {"stats", "evidence"}}, best["stats"], best["evidence"]
    if axis == "SKILL_PROFILE":
        best = modules["skills"]["best"]
        if best.get("selection_eligible") is not True:
            raise ValueError("SKILL_AXIS_NOT_SELECTION_ELIGIBLE")
        return {key: value for key, value in best.items() if key not in {"stats", "evidence"}}, best["stats"], best["evidence"]
    if axis == "ADVISOR_PROFILE":
        material: dict[str, Any] = {}
        best_stats = None
        best_evidence = None
        for role in ("ZBOT", "ZICO", "LICO"):
            best = modules["advisors"][role]["best"]
            if (best.get("evidence") or {}).get("material"):
                material[role] = {key: value for key, value in best.items() if key not in {"stats", "evidence"}}
                if best_evidence is None or core.number(best["evidence"]["deltas"]["net"]) > core.number(best_evidence["deltas"]["net"]):
                    best_stats = best["stats"]
                    best_evidence = best["evidence"]
        if not material or best_stats is None or best_evidence is None:
            raise ValueError("ADVISOR_AXIS_NOT_MATERIAL")
        return material, best_stats, best_evidence
    raise ValueError(f"AXIS_INVALID:{axis}")


def prepare(result: Mapping[str, Any], out: Path) -> dict[str, Any]:
    active: list[str] = []
    skipped: dict[str, str] = {}
    for axis, eligible in (result.get("axis_review_eligibility") or {}).items():
        if not eligible:
            skipped[axis] = "SKIP_NOT_MATERIAL_OR_LOW_SAMPLE"
            continue
        configuration, candidate_stats, proof = axis_candidate(result, axis)
        deltas = dict(proof.get("deltas") or {})
        allowed_evidence = {
            "material": bool(proof.get("material")),
            "no_change": bool(proof.get("no_change")),
            "delta_net_pct_points": core.number(deltas.get("net")),
            "delta_profit_factor": core.number(deltas.get("pf")),
            "delta_drawdown_pct_points": core.number(deltas.get("dd_reduction")),
            "trade_retention": core.number(deltas.get("retention")),
        }
        payload = {
            "strategy_id": result["strategy_id"],
            "stage": "PRE_REPLAY_COMPONENT_AXIS",
            "component_epoch": result["epoch"],
            "changed_axes": [axis],
            "lineage_complete": True,
            "hypothesis": {
                "axis": axis,
                "generation": result["epoch"],
                "configuration": configuration,
                "description": "Evaluate one material component axis against the exact canonical trade ledger.",
            },
            "control": result["control"]["stats"],
            "candidate": candidate_stats,
            "evidence": allowed_evidence,
            "lineage": {
                "ledger_sha": result["source_authority"]["ledger_sha256"],
                "summary_sha": result["source_authority"]["summary_sha256"],
                "fingerprint": result["data_fingerprint"],
                "candidate_result_sha": result["result_sha256"],
            },
            **SAFE,
        }
        write(out / "inputs" / f"{axis}.json", payload)
        active.append(axis)
    index = {"state": "PASS_AXIS_INPUT_PREPARATION" if active else "SKIP_NO_MATERIAL_AXIS", "active_axes": active, "skipped_axes": skipped, **SAFE}
    index["index_sha256"] = core.stable_sha(index)
    write(out / "inputs" / "index.json", index)
    return index


def summarize(inputs: Path, reviews: Path, out: Path) -> dict[str, Any]:
    index = read(inputs / "index.json")
    axes: dict[str, Any] = {}
    accepted: list[str] = []
    for axis in index.get("active_axes", []):
        receipt = read(reviews / f"{axis}.json")
        provider_results = receipt.get("provider_results") or {}
        groq_artifact = ((provider_results.get("groq") or {}).get("artifact") or {})
        workers_artifact = ((provider_results.get("workers_ai") or {}).get("artifact") or {})
        groq = (groq_artifact.get("review") or {}).get("decision")
        workers = (workers_artifact.get("review") or {}).get("decision")
        if groq not in {"PASS_TO_REPLAY", "REJECT", "HOLD"} or workers not in {"PASS_TO_REPLAY", "REJECT", "HOLD"}:
            raise ValueError(f"PROVIDER_DECISION_INVALID:{axis}:{groq}:{workers}")
        passed = receipt.get("status") == "PASS_AI_REVIEW_ROUTER" and groq == "PASS_TO_REPLAY" and workers == "PASS_TO_REPLAY"
        axes[axis] = {
            "router_status": receipt.get("status"),
            "groq_decision": groq,
            "workers_decision": workers,
            "groq_response_sha": groq_artifact.get("response_sha"),
            "workers_response_sha": workers_artifact.get("response_sha"),
            "pass_to_next": passed,
        }
        if passed:
            accepted.append(axis)
    summary = {
        "state": "PASS_COMPONENT_AXIS_AI_GATE_V2" if accepted else "HOLD_NO_AI_APPROVED_COMPONENT_AXIS",
        "reviewed_axis_count": len(axes),
        "accepted_axis_count": len(accepted),
        "accepted_axes": accepted,
        "axes": axes,
        "skipped_axes": index.get("skipped_axes", {}),
        "next": "WAIT_COMPONENT_AXIS_REPLAY_BINDING" if accepted else "WAIT_NEW_EXACT_LEDGER_OR_W1",
        **SAFE,
    }
    summary["summary_sha256"] = core.stable_sha(summary)
    write(out, summary)
    return summary


def fixture(out: Path) -> int:
    result = {
        "strategy_id": "trend_ma_macd", "epoch": 1, "data_fingerprint": "f" * 64, "result_sha256": "r" * 64,
        "source_authority": {"ledger_sha256": "l" * 64, "summary_sha256": "s" * 64},
        "control": {"stats": {"trade_count": 24, "net_return_pct_sum": 1.0, "profit_factor": 1.4, "max_drawdown_pct": 2.0}},
        "axis_review_eligibility": {"BOT_POLICY": False, "TEAM_POLICY": True, "SKILL_PROFILE": False, "ADVISOR_PROFILE": False},
        "module_results": {
            "bots": {"best_by_role": {}},
            "teams": {"best": {"team": "AlphaTeam", "support_threshold": 0.55, "stats": {"trade_count": 20, "net_return_pct_sum": 1.5, "profit_factor": 1.7, "max_drawdown_pct": 1.6}, "evidence": {"material": True, "no_change": False, "deltas": {"net": 0.5, "pf": 0.3, "dd_reduction": 0.4, "retention": 0.83}}}},
            "skills": {"best": {}}, "advisors": {},
        },
    }
    index = prepare(result, out)
    payload = read(out / "inputs" / "TEAM_POLICY.json")
    assert set(payload["evidence"]) == {"material", "no_change", "delta_net_pct_points", "delta_profit_factor", "delta_drawdown_pct_points", "trade_retention"}
    assert index["active_axes"] == ["TEAM_POLICY"]
    print("PASS_COMPONENT_AXIS_AI_GATE_V2_FIXTURE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prep = subparsers.add_parser("prepare"); prep.add_argument("--result", required=True); prep.add_argument("--out", required=True)
    summary = subparsers.add_parser("summarize"); summary.add_argument("--inputs", required=True); summary.add_argument("--reviews", required=True); summary.add_argument("--out", required=True)
    test = subparsers.add_parser("fixture"); test.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "prepare": prepare(read(args.result), Path(args.out)); return 0
    if args.mode == "summarize": summarize(Path(args.inputs), Path(args.reviews), Path(args.out)); return 0
    return fixture(Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
