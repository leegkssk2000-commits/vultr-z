from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

VERSION = "STRATEGY11_UNATTENDED_IMPROVEMENT_REPLAY_V2"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--compute-root", required=True)
    parser.add_argument("--expected-strategies", required=True)
    known, remaining = parser.parse_known_args()

    control_root = Path(__file__).resolve().parents[2]
    compute_root = Path(known.compute_root).resolve()
    replay_path = compute_root / "backend/tools/r7a4d_strategy11_multimodal_l090_replay_v1.py"
    feature_path = control_root / "backend/strategy25/strategy11_extended_indicator_features_v1.py"
    if not replay_path.exists() or not feature_path.exists():
        raise RuntimeError("REPLAY_OR_FEATURE_AUTHORITY_MISSING")

    sys.path.insert(0, str(compute_root))
    extended = load_module("strategy11_extended_indicator_features_for_unattended_v2", feature_path)
    replay = load_module("strategy11_unattended_improvement_base_replay_v2", replay_path)

    exact_modules = []
    for candidate in (
        getattr(replay, "exact", None),
        getattr(getattr(replay, "p", None), "exact", None),
        getattr(getattr(getattr(replay, "repair", None), "p", None), "exact", None),
    ):
        if candidate is not None and candidate not in exact_modules:
            exact_modules.append(candidate)

    for exact in exact_modules:
        original_compute = exact.compute_feature_frame

        def extended_compute(frame, _original=original_compute):
            return extended.extend_feature_frame(frame, _original(frame))

        exact.compute_feature_frame = extended_compute
        exact.feature_snapshot = lambda row: extended.all_scalar_snapshot(dict(row))

    original_resolve = replay.resolve_candidate

    def resolve_candidate(
        strategy_id: str,
        candidate_id: str,
        spec: Mapping[str, Any],
        base_gate: Any,
        base_exit: Any,
        base_surgery: Any,
        symbols: tuple[str, ...],
    ) -> tuple[Any, Any, Any, tuple[str, ...], dict[str, Any]]:
        kind = str(spec["kind"])
        if kind in {"GATE", "EXIT", "SYMBOL"}:
            return original_resolve(
                strategy_id,
                candidate_id,
                spec,
                base_gate,
                base_exit,
                base_surgery,
                symbols,
            )
        gate, exit_spec, surgery, selected_symbols = base_gate, base_exit, base_surgery, symbols
        if kind == "SYMBOL_SET":
            selected_symbols = tuple(map(str, spec.get("symbols") or []))
            if not selected_symbols or len(selected_symbols) != len(set(selected_symbols)):
                raise RuntimeError(f"SYMBOL_SET_INVALID:{strategy_id}:{candidate_id}")
        elif kind == "SURGERY_DISABLE":
            surgery = None
        else:
            raise RuntimeError(f"UNKNOWN_CANDIDATE_KIND:{kind}")
        config = {
            "strategy_id": strategy_id,
            "candidate_id": candidate_id,
            "axis": spec["axis"],
            "kind": kind,
            "gate": asdict(gate),
            "exit": asdict(exit_spec),
            "surgery": asdict(surgery) if surgery is not None else None,
            "symbols": list(selected_symbols),
        }
        return gate, exit_spec, surgery, selected_symbols, config

    replay.resolve_candidate = resolve_candidate
    strategies = tuple(value.strip() for value in known.expected_strategies.split(",") if value.strip())
    if not strategies:
        raise RuntimeError("EXPECTED_STRATEGIES_EMPTY")
    replay.VERSION = VERSION
    replay.CAPABILITY_MARKER = "LANE_AWARE_UNATTENDED_IMPROVEMENT_REPLAY_V2"
    replay.STRATEGIES = strategies
    replay.prior.STRATEGIES = strategies

    sys.argv = [sys.argv[0], *remaining]
    return replay.main()


if __name__ == "__main__":
    raise SystemExit(main())
