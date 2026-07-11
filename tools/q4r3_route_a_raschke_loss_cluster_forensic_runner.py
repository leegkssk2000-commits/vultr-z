from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

OVERLAY_ROOT = Path(
    os.environ.get(
        "Q4R3_ROUTE_A_OVERLAY_ROOT",
        "/tmp/q4r3-route-a-loss-forensic",
    )
)
TARGET = OVERLAY_ROOT / "tools" / "q4r3_route_a_raschke_loss_cluster_forensic.py"


def load_target() -> Any:
    spec = importlib.util.spec_from_file_location(
        "q4r3_raschke_loss_cluster_forensic_base",
        TARGET,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"LOSS_FORENSIC_IMPORT_SPEC_FAILED:{TARGET}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_target()


def resolved_raw_path(window: str, symbol: str) -> Path:
    if window == "prior_holdout_90d":
        return BASE.PRIOR_RAW_DIR / f"{symbol}_1m_90d_pre30d.json"
    if window == "second_holdout_90d":
        return BASE.SECOND_RAW_DIR / f"{symbol}_1m_90d_pre90d.json"
    raise KeyError(f"UNKNOWN_FORENSIC_WINDOW:{window}")


def main() -> None:
    BASE.raw_path = resolved_raw_path
    BASE.main()


if __name__ == "__main__":
    main()
