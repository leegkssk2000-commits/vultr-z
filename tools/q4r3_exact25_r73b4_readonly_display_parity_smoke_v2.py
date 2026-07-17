#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).parent
collector = load("r73b4_collector_base", HERE / "q4r3_exact25_r73b4_readonly_display_parity_smoke.py")
collector.metrics = load("r73b4_metrics_v2", HERE / "q4r3_exact25_r73b4_metric_helpers_v2.py")

if __name__ == "__main__":
    raise SystemExit(collector.main())
