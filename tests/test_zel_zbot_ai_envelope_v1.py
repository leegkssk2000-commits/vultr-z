from backend.tools.zel_zbot_ai_envelope_v1 import SAFETY, normalize


def test_zbot_external_and_internal_axes_are_separated():
    payload = {
        "hypothesis": {
            "axis": "ZBOT_PROFILE",
            "target": "ZBot",
            "parameter": "disagreement_threshold",
            "values": [0.3, 0.4],
        },
        "changed_axes": ["ADVISOR_PROFILE"],
        **SAFETY,
    }
    row = normalize(payload)
    assert row["changed_axes"] == ["ADVISOR_PROFILE"]
    assert row["hypothesis"]["axis"] == "ADVISOR_PROFILE"
    assert row["hypothesis"]["component_axis"] == "ZBOT_PROFILE"
    assert row["component_replay_contract"]["internal_axis"] == "ZBOT_PROFILE"
    assert row["component_replay_contract"]["source_mutation_allowed"] is False
