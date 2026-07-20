from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/r7a3d_strategy25_canonical_implementation_lineage_audit.py"
STRICT_PATH = ROOT / "tools/r7a3d_strict_lineage_postprocess.py"

spec = importlib.util.spec_from_file_location("r7a3d_lineage", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

strict_spec = importlib.util.spec_from_file_location("r7a3d_strict", STRICT_PATH)
assert strict_spec and strict_spec.loader
strict = importlib.util.module_from_spec(strict_spec)
sys.modules[strict_spec.name] = strict
strict_spec.loader.exec_module(strict)


def analyze(path: str, text: str, ids: list[str], tree=None):
    return module.analyze_python(
        path,
        text,
        "a" * 40,
        ids,
        tree or {path: {"blob_sha": "a" * 40, "size": len(text)}},
        ("evaluate", "generate_signal", "signal", "decide", "run"),
        {"implementation", "module", "path", "callable", "factory", "entrypoint", "handler"},
        ("registry", "factory", "strategy_map", "strategies"),
    )


def test_normalize_strategy_id():
    assert module.normalize_id("Trend-MA_MACD") == "trendmamacd"


def test_direct_strategy_module_is_strong():
    found = analyze("backend/strategies/trend_ma_macd.py", "def evaluate(context):\n    return {'signal':'hold'}\n", ["trend_ma_macd"])
    row = found["trend_ma_macd"][0]
    assert row["kind"] == "DIRECT_STRATEGY_MODULE"
    assert row["strength"] == "strong"
    assert row["target_callable"] == "evaluate"
    assert strict.eligible_strong(row) is True


def test_explicit_registry_callable_is_strong():
    text = """
def evaluate(context):
    return {'signal': 'hold'}
STRATEGIES = {'alpha_combo': evaluate}
"""
    found = analyze("backend/strategy_registry.py", text, ["alpha_combo"])
    row = next(row for row in found["alpha_combo"] if row["kind"] == "PYTHON_LITERAL_REGISTRY_KEY")
    assert row["strength"] == "strong"
    assert strict.eligible_strong(row) is True


def test_config_registry_requires_shared_engine():
    text = """
def evaluate(context):
    return {'signal': 'hold'}
STRATEGIES = {'range_fade': {'trigger': 'x', 'invalidation': 'y', 'risk': 'z'}}
"""
    found = analyze("backend/strategy_registry.py", text, ["range_fade"])
    row = next(row for row in found["range_fade"] if row["kind"] == "PYTHON_LITERAL_REGISTRY_KEY")
    assert row["strength"] == "strong"
    assert row["callable"] == "evaluate"
    assert strict.eligible_strong(row) is True


def test_arbitrary_string_mapping_is_downgraded():
    found = analyze("backend/strategy_registry.py", "STRATEGIES={'bb_revert':'active'}\n", ["bb_revert"])
    row = found["bb_revert"][0]
    assert row["strength"] == "strong"
    mapping = {"strategy_id": "bb_revert", "evidence": [row]}
    result = strict.strict_mapping(mapping)
    assert result["lineage_status"] == "PARTIAL"
    assert result["strict_downgraded_evidence_count"] == 1


def test_json_mentions_remain_partial():
    found = module.analyze_json(
        "config/strategy_registry.json",
        '{"strategies":{"vwap_revert":{"trigger":"x","risk":"y"}}}',
        "b" * 40,
        ["vwap_revert"],
        {"implementation", "module", "path", "callable", "factory", "entrypoint"},
    )
    assert found["vwap_revert"][0]["strength"] == "partial"
