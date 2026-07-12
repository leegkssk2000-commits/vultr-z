from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_missing_strategy_writer_trace.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_missing_strategy_writer_trace_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_normalize_and_variants() -> None:
    assert MODULE.normalize(" EMA-Ribbon Scalp ") == "ema_ribbon_scalp"
    variants = MODULE.token_variants("ema_ribbon_scalp")
    assert "ema_ribbon_scalp" in variants
    assert "emaribbonscalp" in variants
    assert "ema-ribbon-scalp" in variants


def test_alias_candidates_detect_close_name() -> None:
    candidates = MODULE.alias_candidates("supertrend_pullback", ["super_trend_pullback", "vwap_revert"])
    assert candidates
    assert candidates[0]["observed"] == "super_trend_pullback"


def test_diagnosis_alias_precedes_absent() -> None:
    scan = {"hit_count": 0, "classification_counts": {}}
    diagnosis, action = MODULE.diagnosis_for(scan, [{"observed": "rangefade", "ratio": 0.9, "token_overlap": 0.0}])
    assert diagnosis == "POSSIBLE_ALIAS_MISMATCH"
    assert "alias" in action


def test_diagnosis_registered_without_implementation() -> None:
    scan = {
        "hit_count": 2,
        "classification_counts": {"registry": 2, "implementation": 0, "writer": 0, "runtime_source": 0},
    }
    diagnosis, _ = MODULE.diagnosis_for(scan, [])
    assert diagnosis == "REGISTERED_WITHOUT_ACTIVE_IMPLEMENTATION"


def test_diagnosis_implementation_without_writer() -> None:
    scan = {
        "hit_count": 1,
        "classification_counts": {"registry": 0, "implementation": 1, "writer": 0, "runtime_source": 0},
    }
    diagnosis, _ = MODULE.diagnosis_for(scan, [])
    assert diagnosis == "IMPLEMENTATION_WITHOUT_REALIZED_R_WRITER_REFERENCE"


def test_sensitive_excerpt_is_redacted() -> None:
    text = "strategy foo api_key=abcdef realized_r=1.0"
    excerpt = MODULE.context_excerpt(text, text.index("foo"))
    assert excerpt == "[REDACTED_SENSITIVE_CONTEXT]"


def test_sanitized_handoff_excludes_excerpts_and_raw_rows() -> None:
    trace = {
        "coverage_summary": {
            "expected_strategy_count": 25,
            "covered_expected_strategy_count": 14,
            "canonical_row_count": 1278,
        },
        "diagnosis_counts": {"ABSENT_FROM_SCANNED_CODE_AND_RUNTIME": 1},
        "writer_sources": [{"path": "runtime/ledger.json", "accepted_rows": 10, "strategies": ["alpha"]}],
        "strategies": [
            {
                "strategy": "missing_one",
                "diagnosis": "ABSENT_FROM_SCANNED_CODE_AND_RUNTIME",
                "next_action": "locate archived branch",
                "candidate_aliases": [],
                "scan": {
                    "hit_count": 1,
                    "classification_counts": {"registry": 1},
                    "hits": [{"path": "config/registry.json", "excerpt": "must not publish"}],
                },
            }
        ],
    }
    decision = {
        "status": "PASS",
        "verdict": "READY",
        "action": "HOLD",
        "next_modules": [],
        "authority": {"order_authority": "blocked"},
    }
    handoff = MODULE.sanitize_handoff(trace, decision)
    serialized = str(handoff)
    assert "must not publish" not in serialized
    assert handoff["safety"]["raw_trade_rows_included"] is False
    assert handoff["missing_strategy_count"] == 1
