from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

VERSION = "STRATEGY11_FAMOUS_INDICATOR_AUTONOMY_REPLAY_V1"


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
    extended = load_module("strategy11_extended_indicator_features_for_replay_v1", feature_path)
    replay = load_module("strategy11_famous_indicator_base_replay_v1", replay_path)

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

    strategies = tuple(value.strip() for value in known.expected_strategies.split(",") if value.strip())
    if not strategies:
        raise RuntimeError("EXPECTED_STRATEGIES_EMPTY")
    replay.VERSION = VERSION
    replay.CAPABILITY_MARKER = "FAMOUS_INDICATOR_AUTONOMOUS_REPLAY"
    replay.STRATEGIES = strategies
    replay.prior.STRATEGIES = strategies

    sys.argv = [sys.argv[0], *remaining]
    return replay.main()


if __name__ == "__main__":
    raise SystemExit(main())
