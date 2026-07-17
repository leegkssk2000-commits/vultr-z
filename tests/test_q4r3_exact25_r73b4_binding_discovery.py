from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4_binding_discovery.py"
SPEC = importlib.util.spec_from_file_location("binding_discovery", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_port_discovery_from_exec_and_environment() -> None:
    assert module.discover_ports("python api.py --port 8210 API_PORT=8211") == [8210, 8211]


def test_route_discovery_from_fastapi_source() -> None:
    source = '@app.get("/view")\ndef view(): pass\n'
    assert module.discover_routes(source) == ["/view"]


def test_environment_relative_artifact_resolution(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    working = root / "backend"
    expected = working / "runtime" / "telegram_state.json"
    paths = module.candidate_paths(
        'STATE_FILE="$STATE_FILE"', root=root, working_directory=working,
        source_parent=None, env={"STATE_FILE": "runtime/telegram_state.json"},
    )
    assert expected.resolve(strict=False) in paths


def test_direct_ledger_requires_explicit_marker(tmp_path: Path) -> None:
    ledger = tmp_path / "forward_r_ledger.jsonl"
    assert module.explicit_ledger_binding(f'LEDGER="{ledger}"', ledger) is True
    assert module.explicit_ledger_binding("unrelated adapter", ledger) is False
