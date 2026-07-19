from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4c2_environment_binding_canary.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4c2", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeBase:
    DEPLOYED_SOURCE = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")

    @staticmethod
    def sha256_file(path):
        return "sha:" + str(path)


def test_scoped_snapshot_excludes_only_volatile_view_contract(tmp_path):
    result = MODULE.scoped_protected_snapshot(tmp_path, FakeBase)
    assert set(result) == {"formal_ledger", "shadow_snapshot", "deployed_source"}
    assert "view_contract" not in result


def test_scoped_snapshot_keeps_ledger_shadow_and_deployed_source(tmp_path):
    result = MODULE.scoped_protected_snapshot(tmp_path, FakeBase)
    assert result["formal_ledger"].endswith("formal_exact5_measurement/forward_r_ledger.jsonl")
    assert result["shadow_snapshot"].endswith("shadow_aggregate_snapshot/latest.json")
    assert result["deployed_source"].endswith("zel_q4r3_telegram_pos_adapter_v2.py")
