from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/q4r3_team_advisor_r061_bot_boundary_adjudication.py"
spec = importlib.util.spec_from_file_location("r061", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_each_bot_has_exact_core_path() -> None:
    assert module.CORE_PATHS == {
        "LBot": "/home/z/z/backend/bots/lbot.py",
        "MBot": "/home/z/z/backend/bots/mbot.py",
        "OBot": "/home/z/z/backend/bots/obot.py",
        "SBot": "/home/z/z/backend/bots/sbot.py",
    }


def test_team_ranking_is_not_mbot_core() -> None:
    value, _ = module.boundary("MBot", "/usr/local/bin/zel_alimi_teambot_ranking_p6_4.py")
    assert value == "TEAM_RANKING"


def test_lbot_router_and_runtime_are_not_core() -> None:
    assert module.boundary("LBot", "/home/z/z/backend/routers/lbot_api.py")[0] == "ROUTER_ADAPTER"
    assert module.boundary("LBot", "/home/z/z/backend/engine/lbot_runtime.py")[0] == "PERSISTENCE_ADAPTER"
    assert module.boundary("LBot", "/home/z/z/backend/engine/lbot_core.py")[0] == "LEGACY_ORCHESTRATOR"


def test_lbot_models_are_contract_only() -> None:
    assert module.boundary("LBot", "/home/z/z/backend/engine/lbot_models.py")[0] == "CONTRACT_MODEL"


def test_unknown_candidate_is_unresolved() -> None:
    assert module.boundary("SBot", "/home/z/z/misc/sbot_unknown.py")[0] == "UNRESOLVED"
