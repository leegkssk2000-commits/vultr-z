from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r02_zico_secure_mirror.py"
spec = importlib.util.spec_from_file_location("r02_zico", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_source(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_safe_runtime_audit() -> None:
    path = Path("/tmp/q4r3_r02_test_safe.py")
    write_source(
        path,
        "CONTRACT_VERSION='zico-ceo-adapter/7.3.3.0'\n"
        "def refresh_once(): return {'decision_id':'d','event_id':'e'}\n",
    )
    result = module.audit_source(path)
    assert result["direct_order_calls"] == []
    assert result["sensitive_literals"] == []
    assert result["contract_versions"] == ["zico-ceo-adapter/7.3.3.0"]


def test_direct_order_surface_is_detected() -> None:
    path = Path("/tmp/q4r3_r02_test_order.py")
    write_source(
        path,
        "CONTRACT_VERSION='zico-ceo-adapter/7.3.3.0'\n"
        "def bad(exchange): return exchange.create_order('BTC-USDT')\n",
    )
    result = module.audit_source(path)
    assert result["direct_order_calls"][0]["call"] == "exchange.create_order"


def test_embedded_secret_literal_is_detected() -> None:
    path = Path("/tmp/q4r3_r02_test_secret.py")
    write_source(
        path,
        "CONTRACT_VERSION='zico-ceo-adapter/7.3.3.0'\n"
        "API_KEY='sk-1234567890abcdef1234567890'\n",
    )
    result = module.audit_source(path)
    assert result["sensitive_literals"]


def test_environment_reference_is_not_secret_literal() -> None:
    path = Path("/tmp/q4r3_r02_test_env.py")
    write_source(
        path,
        "import os\n"
        "CONTRACT_VERSION='zico-ceo-adapter/7.3.3.0'\n"
        "API_KEY=os.environ.get('ZICO_API_KEY')\n",
    )
    result = module.audit_source(path)
    assert result["sensitive_literals"] == []


def test_exact_byte_mirror_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    destination = tmp_path / "canonical/zico/adapter.py"
    manifest = tmp_path / "canonical/zico/manifest.json"
    evidence = tmp_path / "evidence.json"
    write_source(
        source,
        "CONTRACT_VERSION='zico-ceo-adapter/7.3.3.0'\n"
        "def refresh_once(): return True\n",
    )
    expected = module.sha256_bytes(source.read_bytes())
    args = module.argparse.Namespace(
        source=source,
        destination=destination,
        manifest=manifest,
        evidence=evidence,
        unit="zico-ceo-canonical-adapter.service",
        expected_sha256=expected,
        expected_contract_version="zico-ceo-adapter/7.3.3.0",
    )
    assert module.run(args) == 0
    assert destination.read_bytes() == source.read_bytes()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["canonical_name"] == "Zico"
    assert payload["byte_parity"] is True
    assert payload["runtime_mutation_performed"] is False
