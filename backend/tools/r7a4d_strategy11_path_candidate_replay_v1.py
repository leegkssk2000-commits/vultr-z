from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_REPLAY_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
ALLOWED_EXIT_CHANGES = {
    "stop_mult",
    "target_mult",
    "breakeven_r",
    "partial_r",
    "partial_fraction",
    "runner_target_r",
    "trail_activate_r",
    "trail_atr_mult",
    "time_stop_bars",
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_research_module(research_root: Path) -> Any:
    research_root = research_root.resolve()
    sys.path.insert(0, str(research_root))
    path = research_root / "backend/tools/r7a4d_strategy11_multimodal_l090_replay_v1.py"
    spec = importlib.util.spec_from_file_location("strategy11_path_research_replay", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("RESEARCH_REPLAY_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_safety(value: Mapping[str, Any], name: str) -> None:
    for key, expected in SAFETY.items():
        if key in value and value.get(key) != expected:
            raise ValueError(f"SAFETY_MISMATCH:{name}:{key}")


def basis_summary(source_replay_root: Path, strategy_id: str, variant_id: str) -> dict[str, Any]:
    path = source_replay_root / strategy_id / variant_id / "summary.json"
    if not path.exists():
        raise ValueError(f"BASIS_SUMMARY_MISSING:{strategy_id}:{variant_id}")
    value = read_json(path)
    config = value.get("candidate_config")
    if not isinstance(config, Mapping):
        raise ValueError(f"BASIS_CONFIG_MISSING:{strategy_id}:{variant_id}")
    return value


def apply_exit_changes(base_exit: Any, changes: Mapping[str, Any]) -> Any:
    unknown = sorted(set(changes) - ALLOWED_EXIT_CHANGES)
    if unknown:
        raise ValueError(f"EXIT_CHANGE_UNKNOWN:{','.join(unknown)}")
    normalized: dict[str, Any] = {}
    for key, value in changes.items():
        if key == "time_stop_bars":
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"TIME_STOP_INVALID:{value}")
            normalized[key] = value
        elif value is None:
            normalized[key] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"EXIT_CHANGE_INVALID:{key}:{value}")
        else:
            normalized[key] = float(value)
    if "stop_mult" in normalized and not 0.5 <= normalized["stop_mult"] <= 1.5:
        raise ValueError("STOP_MULT_OUT_OF_BOUNDS")
    if "target_mult" in normalized and not 0.5 <= normalized["target_mult"] <= 1.5:
        raise ValueError("TARGET_MULT_OUT_OF_BOUNDS")
    if "partial_fraction" in normalized and not 0.0 < normalized["partial_fraction"] < 1.0:
        raise ValueError("PARTIAL_FRACTION_OUT_OF_BOUNDS")
    return replace(base_exit, **normalized)


def run(args: argparse.Namespace) -> dict[str, Any]:
    replay = load_research_module(args.research_root)
    plan = read_json(args.plan)
    assert_safety(plan, "replay_plan")
    if plan.get("state") != "PASS_PATH_AI_REVIEW_READY_TO_REPLAY":
        raise ValueError(f"REPLAY_PLAN_NOT_READY:{plan.get('state')}")
    plan_rows = plan.get("rows")
    if not isinstance(plan_rows, list) or not plan_rows:
        raise ValueError("REPLAY_PLAN_ROWS_REQUIRED")
    frames, features, funding, manifest = replay.p.load_fresh_data(args.fresh_root.resolve())
    quantiles = replay.p.funding_rate_quantiles(funding)
    market_shas = replay.repair.market_sha_map(manifest)
    registry = replay.base._load_registry(args.research_root.resolve())
    policy = read_json(args.policy)
    stage = policy["loss_ladder"][0]
    floors = policy["economic_floors"]
    output_rows = []

    for plan_row in plan_rows:
        strategy_id = str(plan_row.get("strategy_id") or "")
        basis_variant_id = str(plan_row.get("basis_variant_id") or "")
        candidate_ids = plan_row.get("candidate_ids")
        candidate_specs = plan_row.get("candidate_specs")
        if not strategy_id or not basis_variant_id or not isinstance(candidate_ids, list) or len(candidate_ids) != 1 or not isinstance(candidate_specs, Mapping):
            raise ValueError(f"PATH_REPLAY_ROW_SHAPE:{strategy_id}")
        candidate_id = str(candidate_ids[0])
        spec = candidate_specs.get(candidate_id)
        if not isinstance(spec, Mapping) or spec.get("kind") != "EXIT" or spec.get("axis") not in {
            "STOP", "TARGET", "BREAKEVEN", "PARTIAL", "MFE_TRAILING", "TIME_STOP"
        }:
            raise ValueError(f"PATH_REPLAY_SPEC_UNSUPPORTED:{strategy_id}:{candidate_id}")
        basis = basis_summary(args.source_replay_root.resolve(), strategy_id, basis_variant_id)
        basis_config = basis["candidate_config"]
        base_gate = replay.exact._gate_from(basis_config)
        base_exit = replay.exact._exit_from(basis_config)
        base_surgery = replay.p.surgery_from(basis_config.get("surgery"))
        symbols = tuple(str(value) for value in basis_config.get("symbols") or [])
        if not symbols:
            raise ValueError(f"BASIS_SYMBOLS_MISSING:{strategy_id}:{basis_variant_id}")
        registry_row = registry[strategy_id]
        strategy = replay.base._load_canonical_strategy(args.research_root.resolve(), strategy_id, registry_row)
        source_sha = str(registry_row["canonical_engine"]["source_sha256"])
        candidate_exit = apply_exit_changes(base_exit, spec.get("changes") or {})
        strategy_out = args.out.resolve() / strategy_id
        basis_control_config = {
            "strategy_id": strategy_id,
            "candidate_id": "NO_CHANGE_CONTROL",
            "axis": "NO_CHANGE",
            "kind": "CONTROL",
            "basis_variant_id": basis_variant_id,
            "basis_variant_sha": basis.get("candidate_config_sha256"),
            "gate": asdict(base_gate),
            "exit": asdict(base_exit),
            "surgery": asdict(base_surgery) if base_surgery is not None else None,
            "symbols": list(symbols),
        }
        control = replay.evaluate(
            variant_id="NO_CHANGE_CONTROL",
            config=basis_control_config,
            exit_spec=base_exit,
            strategy=strategy,
            gate=base_gate,
            surgery=base_surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            normal_cap_r=float(stage["normal_worst_net_loss_R_min"]),
            stress_cap_r=float(stage["stress_worst_net_loss_R_min"]),
            out=strategy_out,
        )
        candidate_config = {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "axis": spec["axis"],
            "kind": "EXIT",
            "basis_variant_id": basis_variant_id,
            "basis_variant_sha": basis.get("candidate_config_sha256"),
            "source_proposal_sha": spec.get("source_proposal_sha"),
            "gate": asdict(base_gate),
            "exit": asdict(candidate_exit),
            "surgery": asdict(base_surgery) if base_surgery is not None else None,
            "symbols": list(symbols),
        }
        candidate = replay.evaluate(
            variant_id=candidate_id,
            config=candidate_config,
            exit_spec=candidate_exit,
            strategy=strategy,
            gate=base_gate,
            surgery=base_surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            normal_cap_r=float(stage["normal_worst_net_loss_R_min"]),
            stress_cap_r=float(stage["stress_worst_net_loss_R_min"]),
            out=strategy_out,
        )
        candidate["ladder_check"] = replay.ladder_check(candidate, control, stage, floors)
        replay.atomic_json(strategy_out / candidate_id / "summary.json", candidate)
        winner = candidate_id if candidate["ladder_check"]["research_pass"] else None
        summary = {
            "schema_version": "1.0",
            "version": replay.VERSION,
            "capability_marker": replay.CAPABILITY_MARKER,
            "path_replay_version": VERSION,
            "state": "PASS_L090_RESEARCH_CANDIDATE" if winner else "NO_L090_CANDIDATE",
            "strategy_id": strategy_id,
            "basis_variant_id": basis_variant_id,
            "tested_candidate_ids": [candidate_id],
            "winner": winner,
            "variants": [control, candidate],
            "next": "L085_REFINEMENT" if winner else "NEXT_DISTINCT_CAUSAL_AXIS",
            "same_axis_generation_count": int((plan.get("accepted") or [{}])[0].get("generation") or 1),
            "same_axis_generation_limit": 2,
            "distinct_axis_reopen_allowed": True,
            "w1_confirmation_required": True,
            "new_sealed_required": True,
            "canonical_mutated": False,
            "registry_mutated": False,
            **SAFETY,
        }
        replay.atomic_json(strategy_out / "summary.json", summary)
        output_rows.append(summary)
    batch = {
        "schema_version": "strategy11.path_candidate_replay.batch.v1",
        "version": VERSION,
        "state": "PASS_PATH_CANDIDATE_REPLAY_BATCH",
        "strategy_count": len(output_rows),
        "rows": output_rows,
        **SAFETY,
    }
    write_json(args.out.resolve() / "batch.json", batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--source-replay-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    print(result["state"], "strategies=", result["strategy_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
