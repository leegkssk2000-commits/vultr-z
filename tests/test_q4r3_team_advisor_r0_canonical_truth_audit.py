from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r0_canonical_truth_audit.py"
ALIASES_PATH = ROOT / "backend/config/q4r3_r0_candidate_aliases_v1.json"

spec = importlib.util.spec_from_file_location("r0_audit", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ALIASES = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))


def test_canonical_names() -> None:
    assert module.canonical_component("ZICO") == "Zico"
    assert module.canonical_component("zico") == "Zico"
    assert module.canonical_component("LiCo") == "Lico"
    assert module.canonical_component("LICO") == "Lico"


def test_lico_snapshot_bridge_is_not_contamination() -> None:
    bad, reason = module.path_is_contaminated(Path("/home/z/z/backend/lico_snapshot_bridge.py"))
    assert bad is False
    assert reason is None


def test_backup_directory_is_contamination() -> None:
    bad, reason = module.path_is_contaminated(Path("/home/z/z/backend/backups/lico.py"))
    assert bad is True
    assert reason == "directory:backups"


def test_explicit_backup_filename_is_contamination() -> None:
    bad, reason = module.path_is_contaminated(Path("/home/z/z/backend/lico_backup_20260715.py"))
    assert bad is True
    assert reason == "backup_filename"


def test_generic_strategy_does_not_become_lbot_owner() -> None:
    assert module.exact_path_identity(Path("/home/z/z/backend/strategies/trend.py"), "LBot", ALIASES) is False
    assert module.exact_path_identity(Path("/home/z/z/backend/bots/lbot.py"), "LBot", ALIASES) is True


def test_team_identity_requires_assignment_contract() -> None:
    plain = "Alpha trend result"
    structured = '{"team_id":"AlphaTeam","main_bot":"LBot","support_bot":"MBot","watchers":["OBot","SBot"]}'
    assert module.structured_team_identity(plain, "AlphaTeam", ALIASES) is False
    assert module.structured_team_identity(structured, "AlphaTeam", ALIASES) is True


def test_parse_exec_paths_and_interpreter_script() -> None:
    raw = "{ path=/home/z/z/.venv/bin/python ; argv[]=/home/z/z/.venv/bin/python /opt/zico/adapter.py --port 8787 ; }"
    paths = module.parse_exec_paths(raw)
    assert "/home/z/z/.venv/bin/python" in paths
    assert "/opt/zico/adapter.py" in paths
    assert module.choose_script_paths(paths) == ["/opt/zico/adapter.py"]


def test_symlink_chain(tmp_path: Path) -> None:
    target = tmp_path / "owner.py"
    target.write_text("print('ok')", encoding="utf-8")
    link = tmp_path / "owner-link.py"
    link.symlink_to(target)
    chain, error = module.symlink_chain(link)
    assert error is None
    assert len(chain) == 1
    assert str(link) in chain[0]


def test_active_binding_alone_does_not_prove_owner() -> None:
    candidate = {
        "identity_evidence": ["active_unit_binding"],
        "owner_kind": "runtime_core",
        "direct_order_calls": [],
        "sensitive_credential_access": [],
        "git": {"tracked": False},
        "contract_version": None,
    }
    assert module.owner_proof(candidate) is False
    candidate["identity_evidence"].append("exact_path_identity")
    assert module.owner_proof(candidate) is True


def test_structured_team_binding_can_prove_owner() -> None:
    candidate = {
        "identity_evidence": ["active_unit_binding", "structured_team_assignment"],
        "owner_kind": "runtime_core",
        "direct_order_calls": [],
        "sensitive_credential_access": [],
        "git": {"tracked": False},
        "contract_version": None,
    }
    assert module.owner_proof(candidate) is True


def test_direct_order_call_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "zbot.py"
    text = "def f(router):\n    return router.place_order('BTCUSDT')\n"
    path.write_text(text, encoding="utf-8")
    calls, credentials = module.authority_evidence(path, text)
    assert calls == [{"call": "router.place_order", "line": 2}]
    assert credentials == []


def test_sensitive_key_name_is_detected_without_value(tmp_path: Path) -> None:
    path = tmp_path / "lico.py"
    text = "import os\nKEY = os.getenv('BINGX_API_KEY')\n"
    path.write_text(text, encoding="utf-8")
    calls, credentials = module.authority_evidence(path, text)
    assert calls == []
    assert credentials[0]["key_name"] == "BINGX_API_KEY"


def test_unsafe_candidate_is_quarantined() -> None:
    recommendation, reason = module.classification({
        "owner_kind": "runtime_core",
        "identity_evidence": ["exact_path_identity"],
        "direct_order_calls": [{"call": "place_order", "line": 1}],
        "sensitive_credential_access": [],
    })
    assert recommendation == "QUARANTINE"
    assert "execution" in reason


def test_service_is_not_runtime_owner() -> None:
    assert module.file_kind(Path("/etc/systemd/system/zico.service")) == "service_wrapper"


def test_redaction_removes_inline_secret() -> None:
    value = module.redact("OPENAI_API_KEY=abc123 TOKEN=secret sk-abcdefghijklmnop")
    assert "abc123" not in value
    assert "abcdefghijklmnop" not in value


def test_zbot_policy_surface_detection() -> None:
    text = "dual_blind openai gemini daily_budget circuit_breaker input_hash output_hash"
    hits = module.surface_hits(text, module.ZBOT_SURFACES)
    assert hits["provider_router"] is True
    assert hits["openai_adapter"] is True
    assert hits["gemini_adapter"] is True
    assert hits["budget_policy"] is True
    assert hits["circuit_breaker_policy"] is True


def test_wrapper_reference_resolution(tmp_path: Path) -> None:
    child = tmp_path / "child.py"
    child.write_text("print('child')", encoding="utf-8")
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(f"#!/bin/sh\npython3 {child}\n", encoding="utf-8")
    references = module.wrapper_references(wrapper)
    assert str(child.resolve()) in references


def test_generated_scope_has_only_canonical_names() -> None:
    scope = [module.canonical_component(value) for value in ["ZICO", "LiCo", "ZBot", "LBot"]]
    assert scope == ["Zico", "Lico", "ZBot", "LBot"]
    assert "ZICO" not in scope
    assert "LiCo" not in scope
