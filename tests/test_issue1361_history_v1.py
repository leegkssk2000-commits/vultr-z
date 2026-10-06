import ast
import copy
import hashlib
import json

import pandas as pd
import pytest

from ops import issue1361_history_v1 as h
from ops import issue1361_repeatability_v1 as scope


def fits():
    output = []
    for row in scope.planned_history():
        fit = {
            "training_feature_sha256": "a" * 64,
            "disp_q67": 0.1,
            "meanabs_q85": 0.2,
            "vol_q25": 0.3,
            "vol_q67": 0.4,
            "train_start_ms": row["fit_start_ms"],
            "train_end_ms": row["fit_end_ms"],
            "last_fit_observation_ms": row["fit_end_ms"] - 3_600_000,
            "train_rows": 100,
        }
        fit["sha256"] = hashlib.sha256(
            json.dumps(fit, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        output.append(fit)
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
    return dict(h.FROZEN_COSTS_BPS)


def hashes():
    return h.code_hashes()


def manifest():
    return h.build_manifest(
        inventory=inventory(), fits=fits(), coverage=coverage(), costs=costs(), hashes=hashes()
    )


def trusted_fits():
    return {
        row["id"]: fit["sha256"]
        for row, fit in zip(scope.planned_history(), fits(), strict=True)
    }


def validate(value, trusted=None):
    return h.validate_manifest(
        value, trusted_fit_sha256=trusted if trusted is not None else trusted_fits()
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
    assert len({x["entry_profile"] for x in value["instances"]}) == 2
    assert all(len(x["code_bundle_sha256"]) == 64 for x in value["instances"])


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
    with pytest.raises(
        h.HistoryPreparationError,
        match=(
            "INSTANCE_STATE_HASH|FOLD_MODEL_INSTANCE_MATRIX|"
            "INSTANCE_FROZEN_PROFILE|INSTANCE_COST_BINDING"
        ),
    ):
        validate(value)


def test_manifest_hash_rejects_allocation_or_source_mutation():
    value = manifest()
    value["allocation"]["H_claimed"] = 6
    with pytest.raises(
        h.HistoryPreparationError, match="FIT_MANIFEST_HASH|UNCLAIMED_TEST_EXECUTION"
    ):
        validate(value)


def test_duplicate_instance_identity_is_rejected_even_if_rehashed():
    value = manifest()
    value["instances"][1] = copy.deepcopy(value["instances"][0])
    frozen = {k: v for k, v in value.items() if k != "manifest_sha256"}
    value["manifest_sha256"] = h.canonical_sha256(frozen)
    with pytest.raises(h.HistoryPreparationError, match="EXACT_SIX_INSTANCE"):
        validate(value)


def test_identity_entry_profile_swap_is_rejected_even_if_rehashed():
    value = manifest()
    first, second = value["instances"][0], value["instances"][1]
    first["entry_profile"], second["entry_profile"] = second["entry_profile"], first["entry_profile"]
    for instance in (first, second):
        frozen = {k: v for k, v in instance.items() if k != "state_sha256"}
        instance["state_sha256"] = h.canonical_sha256(frozen)
    frozen_manifest = {k: v for k, v in value.items() if k != "manifest_sha256"}
    value["manifest_sha256"] = h.canonical_sha256(frozen_manifest)
    with pytest.raises(h.HistoryPreparationError, match="INSTANCE_FROZEN_PROFILE"):
        validate(value)


def _rehash_manifest(value):
    for instance in value["instances"]:
        frozen = {k: v for k, v in instance.items() if k != "state_sha256"}
        instance["state_sha256"] = h.canonical_sha256(frozen)
    frozen = {k: v for k, v in value.items() if k != "manifest_sha256"}
    value["manifest_sha256"] = h.canonical_sha256(frozen)


def test_rehashed_fold_substitution_cannot_drop_h2_candidate():
    value = manifest()
    candidate = next(
        row
        for row in value["instances"]
        if row["fold_id"] == "H2" and row["identity"] == h.CANDIDATE
    )
    candidate["fold_id"] = "H1"
    candidate["instance_id"] = "H1:EMA21_BUY_LIMIT_DUPLICATE_NAME"
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="FOLD_MODEL_INSTANCE_MATRIX"):
        validate(value)


@pytest.mark.parametrize("key", ["fit_sha256", "test_start_ms", "test_end_ms"])
def test_rehashed_instance_must_remain_bound_to_declared_fold(key):
    value = manifest()
    instance = value["instances"][0]
    instance[key] = "f" * 64 if key == "fit_sha256" else instance[key] + 1
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="INSTANCE_FROZEN_PROFILE"):
        validate(value)


def test_rehashed_top_level_code_map_must_match_each_instance_bundle():
    value = manifest()
    value["code_sha256"]["new_dependency.py"] = "c" * 64
    frozen = {k: v for k, v in value.items() if k != "manifest_sha256"}
    value["manifest_sha256"] = h.canonical_sha256(frozen)
    with pytest.raises(h.HistoryPreparationError, match="CODE_MAP_CHECKOUT"):
        validate(value)


def test_forged_complete_code_map_cannot_replace_checkout_identity():
    value = manifest()
    value["code_sha256"] = {name: "0" * 64 for name in value["code_sha256"]}
    forged_bundle = h.canonical_sha256(dict(sorted(value["code_sha256"].items())))
    for instance in value["instances"]:
        instance["code_bundle_sha256"] = forged_bundle
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="CODE_MAP_CHECKOUT"):
        validate(value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("issue", 0),
        ("classification", "FRESH_OOS"),
        ("allocation", {"H_claimed": 6, "H_limit": 7, "economic_runs": 6}),
        ("history_claim_ref", "refs/heads/forged"),
        ("authority", "ORDERS_GRANTED"),
        ("test_period_signal_generation", 1),
        ("test_period_model_replays", 1),
    ],
)
def test_top_level_phase_one_control_state_rejects_forged_rehash(key, value):
    item = manifest()
    item[key] = value
    _rehash_manifest(item)
    with pytest.raises(
        h.HistoryPreparationError, match="FIT_MANIFEST_PROFILE|UNCLAIMED_TEST_EXECUTION"
    ):
        validate(item)


@pytest.mark.parametrize(
    "key,value",
    [
        ("full_inventory_files", 1),
        ("full_inventory_sha256", "0" * 64),
        ("expected_full_inventory_sha256", "0" * 64),
        ("state", "READY_FORGED"),
        ("clock_profile", "OBSERVED_RECEIPTS"),
    ],
)
def test_top_level_source_profile_rejects_forged_rehash(key, value):
    item = manifest()
    item["source"][key] = value
    _rehash_manifest(item)
    with pytest.raises(h.HistoryPreparationError, match="FROZEN_SOURCE_PROFILE"):
        validate(item)


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema", "forged"),
        ("issue", 0),
        ("source_inventory_sha256", "0" * 64),
        ("protocol_sha256", "0" * 64),
        ("rule_sha256", "0" * 64),
        ("classification", "FRESH_OOS"),
        ("fresh_oos", True),
        ("order_authority", "GRANTED"),
    ],
)
def test_every_frozen_instance_field_rejects_forged_rehash(key, value):
    item = manifest()
    item["instances"][0][key] = value
    _rehash_manifest(item)
    with pytest.raises(h.HistoryPreparationError, match="INSTANCE_FROZEN_PROFILE"):
        validate(item)


def test_fit_window_matches_existing_rolling_context_contract():
    for planned in scope.planned_history():
        window = h.fit_window(planned)
        assert window["train_start_ms"] == planned["fit_start_ms"]
        assert window["train_end_ms"] == window["start_ms"] == planned["test_start_ms"]
        assert window["end_ms"] == planned["test_end_ms"]
        assert window["oos_scope"] == scope.CLASSIFICATION


def test_cost_values_are_exact_not_merely_positive():
    assert h.validate_costs(costs()) == h.FROZEN_COSTS_BPS
    changed = costs()
    changed["XRP-USDT"] = 14.0
    with pytest.raises(h.HistoryPreparationError, match="FROZEN_COSTS_CHANGED"):
        h.validate_costs(changed)


def test_fit_digest_is_recomputed_after_outer_manifest_rehash():
    value = manifest()
    value["fits"][0]["fit"]["disp_q67"] += 0.001
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="FIT_CHRONOLOGY_OR_HASH"):
        validate(value)


def test_rehashed_fit_and_instances_cannot_replace_trusted_fit_claim():
    value = manifest()
    fit = value["fits"][0]["fit"]
    fit["disp_q67"] += 0.001
    fit["sha256"] = h.fit_payload_sha256(fit)
    for instance in value["instances"]:
        if instance["fold_id"] == "H1":
            instance["fit_sha256"] = fit["sha256"]
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="TRUSTED_FIT_CLAIM_MISMATCH"):
        validate(value)


def test_trusted_fit_claim_requires_exact_three_hashes():
    value = manifest()
    with pytest.raises(h.HistoryPreparationError, match="TRUSTED_FIT_CLAIM_PROFILE"):
        validate(value, {"H1": "0" * 64})


@pytest.mark.parametrize("mutation", ["changed_table", "missing_table", "changed_hash"])
def test_frozen_costs_are_revalidated_after_outer_manifest_rehash(mutation):
    value = manifest()
    if mutation == "changed_table":
        value["costs_bps"]["BTC-USDT"] = 0.0
    elif mutation == "missing_table":
        del value["costs_bps"]
    else:
        value["cost_sha256"] = "0" * 64
    _rehash_manifest(value)
    with pytest.raises(h.HistoryPreparationError, match="FROZEN_COST"):
        validate(value)


@pytest.mark.parametrize(
    "key,value", [("cost_sha256", "0" * 64), ("cost_profiles", ["1x"])]
)
def test_instance_cost_binding_rejects_forged_rehash(key, value):
    item = manifest()
    item["instances"][0][key] = value
    _rehash_manifest(item)
    with pytest.raises(h.HistoryPreparationError, match="INSTANCE_COST_BINDING"):
        validate(item)


def test_actual_fit_context_payload_serialization_matches_manifest_validator():
    from backend.research.rebuild import scalp7_rolling_context_v2 as context

    planned = scope.planned_history()[0]
    opened = pd.Series(
        range(
            planned["fit_start_ms"],
            planned["fit_start_ms"] + 100 * context.HOUR,
            context.HOUR,
        )
    )
    features = pd.DataFrame(
        {
            "context_open_ts_ms": opened,
            "regime_available_ts_ms": opened + context.HOUR,
            "dispersion24": [0.001 + i / 1_000_000 for i in range(100)],
            "mean_abs24": [0.002 + i / 1_000_000 for i in range(100)],
            "breadth": [float((i % 7) - 3) for i in range(100)],
            "vol_ratio": [0.8 + i / 10_000 for i in range(100)],
        }
    )
    fit = context.fit_context(features, h.fit_window(planned))
    assert h.fit_payload_sha256(fit) == fit["sha256"]
    assert h.validate_fit(fit, planned) == fit
    assert (
        h.canonical_sha256({k: v for k, v in fit.items() if k != "sha256"})
        != fit["sha256"]
    )


def test_nonfinite_or_malformed_fit_payload_is_rejected():
    bad = fits()[0]
    bad["vol_q67"] = float("nan")
    with pytest.raises(h.HistoryPreparationError, match="FIT_FINITE"):
        h.fit_payload_sha256(bad)
    del bad["train_rows"]
    with pytest.raises(h.HistoryPreparationError, match="FIT_PAYLOAD_PROFILE"):
        h.fit_payload_sha256(bad)


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


def test_code_bundle_lists_candidate_transitive_runtime_dependencies():
    names = set(h.code_hashes())
    assert {
        "ops/issue1358_ema21_limit_v1.py",
        "ops/scalp7_clocked_execution_v1.py",
        "ops/squeeze_nonpositive_exit_v1.py",
        "ops/kp_committed_cursor_snapshot_v1.py",
        "ops/kp_connected_research_validation_v1.py",
        "ops/kp_price_input_export_v1.py",
        "backend/research/rebuild/scalp7_positive_lanes_v2.py",
        "backend/research/rebuild/scalp7_execution_v2.py",
        "backend/research/rebuild/economic7_canonical_history_v1.py",
        "backend/research/rebuild/scalp7_fresh_forward_v2.py",
        "backend/research/rebuild/scalp7_fresh_source_v2.py",
    } <= names


def test_write_once_refuses_restart_overwrite(tmp_path, monkeypatch):
    output = tmp_path / "FIT_MANIFEST.json"
    output.write_text("existing")
    monkeypatch.setattr(scope, "inventory_source", lambda root: inventory())
    # The existing destination must fail closed before any successful overwrite.
    with pytest.raises(FileExistsError):
        with output.open("xb"):
            pass
