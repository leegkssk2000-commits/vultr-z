from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6_deployment_parity_command_smoke.py"
SPEC = importlib.util.spec_from_file_location("r7a1a6", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_report_semantics_accepts_read_only_runtime():
    ok, blockers = MODULE.report_semantics({
        "status": "PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING",
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
    })
    assert ok is True
    assert blockers == []


def test_report_semantics_rejects_execution_authority():
    ok, blockers = MODULE.report_semantics({
        "status": "PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING",
        "order_authority": "blocked",
        "execution_authority": "paper",
        "real_order_enabled": False,
    })
    assert ok is False
    assert "EXECUTION_AUTHORITY_NOT_NONE" in blockers


def test_writer_counts_reads_nested_writers7_contract():
    configured, active = MODULE.writer_counts({
        "surface": {
            "writers7": {
                "configured_writer_count": 7,
                "active_writer_count": 0,
            }
        }
    })
    assert configured == 7
    assert active == 0


def test_collect_key_values_finds_nested_safety_values():
    payload = {
        "header": {"order_authority": "blocked"},
        "summary": [{"execution_authority": "none"}],
    }
    assert MODULE.collect_key_values(payload, {"order_authority"}) == ["blocked"]
    assert MODULE.collect_key_values(payload, {"execution_authority"}) == ["none"]


def test_json_from_bytes_rejects_non_object():
    assert MODULE.json_from_bytes(b"[]") == {}
