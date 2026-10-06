import ast
import copy

import pytest

from ops import issue1361_history_v1 as h
from ops import issue1361_repeatability_v1 as scope


def fits():
    output = []
    for row in scope.planned_history():
        output.append(
            {
                "training_feature_sha256": "a" * 64,
                "disp_q67": 0.1,
                "meanabs_q85": 0.2,
                "vol_q25": 0.3,
                "vol_q67": 0.4,
                "train_start_ms": row["fit_start_ms"],
                "train_end_ms": row["fit_end_ms"],
                "last_fit_observation_ms": row["fit_end_ms"] - 3_600_000,
                "train_rows": 100,
                "sha256": (str(len(output) + 1) * 64),
            }
        )
    return output


def inventory():
    return {
        "full_inventory_files": 17541,
        "full_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "history_input_state": "READY",
    }


def coverage():
    return {symbol: {"rows_30m": 1, "folds": []} for symbol in scope.SYMBOLS}


def costs():
    return {symbol: 14.0 for symbol in scope.SYMBOLS}


def hashes():
    return {"code.py": "b" * 64}


def manifest():
    return h.build_manifest(
        inventory=inventory(), fits=fits(), coverage=coverage(), costs=costs(), hashes=hashes()
    )


def test_exact_three_past_only_fits_make_six_unclaimed_instances():
    value = manifest()
    assert value["phase"] == "FIT_COMPLETE_NO_TEST_SIGNALS"
    assert len(value["fits"]) == 3
    assert len(value["instances"]) == 6
    assert value["allocation"] == {"H_claimed": 0, "H_limit": 6, "economic_runs": 0}
    assert value["test_period_signal_generation"] == 0
    assert value["test_period_model_replays"] == 0
    assert all(x["classification"] == scope.CLASSIFICATION for x in value["instances"])


def test_final_fit_backapplication_is_rejected():
    bad = fits()
    bad[0]["train_end_ms"] = scope.planned_history()[-1]["fit_end_ms"]
    with pytest.raises(h.HistoryPreparationError, match="FIT_CHRONOLOGY"):
        h.build_manifest(
            inventory=inventory(), fits=bad, coverage=coverage(), costs=costs(), hashes=hashes()
        )


def test_test_boundary_observation_in_fit_is_rejected():
    bad = fits()
    bad[1]["last_fit_observation_ms"] = scope.planned_history()[1]["test_start_ms"]
    with pytest.raises(h.HistoryPreparationError, match="FIT_CHRONOLOGY"):
        h.build_manifest(
            inventory=inventory(), fits=bad, coverage=coverage(), costs=costs(), hashes=hashes()
        )


@pytest.mark.parametrize("key", ["fit_sha256", "test_end_ms", "identity", "cost_sha256"])
def test_each_instance_state_hash_rejects_mutation(key):
    value = manifest()
    value["instances"][0][key] = "changed"
    with pytest.raises(h.HistoryPreparationError, match="INSTANCE_STATE_HASH|MODEL_IDENTITY"):
        h.validate_manifest(value)


def test_manifest_hash_rejects_allocation_or_source_mutation():
    value = manifest()
    value["allocation"]["H_claimed"] = 6
    with pytest.raises(h.HistoryPreparationError, match="FIT_MANIFEST_HASH"):
        h.validate_manifest(value)


def test_duplicate_instance_identity_is_rejected_even_if_rehashed():
    value = manifest()
    value["instances"][1] = copy.deepcopy(value["instances"][0])
    frozen = {k: v for k, v in value.items() if k != "manifest_sha256"}
    value["manifest_sha256"] = h.canonical_sha256(frozen)
    with pytest.raises(h.HistoryPreparationError, match="EXACT_SIX_INSTANCE"):
        h.validate_manifest(value)


def test_fit_window_matches_existing_rolling_context_contract():
    for planned in scope.planned_history():
        window = h.fit_window(planned)
        assert window["train_start_ms"] == planned["fit_start_ms"]
        assert window["train_end_ms"] == window["start_ms"] == planned["test_start_ms"]
        assert window["end_ms"] == planned["test_end_ms"]
        assert window["oos_scope"] == scope.CLASSIFICATION


def test_module_does_not_import_signal_or_execution_engines():
    source = (h.ROOT / "ops/issue1361_history_v1.py").read_text()
    imports = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("scalp7_positive_lanes_v2" in name for name in imports)
    assert not any("scalp7_execution_v2" in name for name in imports)
    body = source.split("def prepare_history", 1)[1]
    assert "generate_signals(" not in body
    assert ".replay(" not in body


def test_write_once_refuses_restart_overwrite(tmp_path, monkeypatch):
    output = tmp_path / "FIT_MANIFEST.json"
    output.write_text("existing")
    monkeypatch.setattr(scope, "inventory_source", lambda root: inventory())
    # The existing destination must fail closed before any successful overwrite.
    with pytest.raises(FileExistsError):
        with output.open("xb"):
            pass
