from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def load_runner():
    root = Path(__file__).resolve().parents[1]
    os.environ["Q4R3_ROUTE_A_OVERLAY_ROOT"] = str(root)
    path = root / "tools" / "q4r3_route_a_raschke_loss_cluster_forensic_runner.py"
    spec = importlib.util.spec_from_file_location("test_raschke_loss_forensic_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_runner()


def test_prior_holdout_uses_pre30d_filename() -> None:
    path = MODULE.resolved_raw_path("prior_holdout_90d", "BTCUSDT")
    assert path.name == "BTCUSDT_1m_90d_pre30d.json"
    assert "oos_a2/frozen_pre30d" in str(path)


def test_second_holdout_uses_pre90d_filename() -> None:
    path = MODULE.resolved_raw_path("second_holdout_90d", "BTCUSDT")
    assert path.name == "BTCUSDT_1m_90d_pre90d.json"
    assert "oos_a3/raschke_second_holdout" in str(path)


def test_unknown_window_fails_closed() -> None:
    try:
        MODULE.resolved_raw_path("unknown", "BTCUSDT")
    except KeyError as exc:
        assert "UNKNOWN_FORENSIC_WINDOW" in str(exc)
    else:
        raise AssertionError("unknown window must fail closed")
