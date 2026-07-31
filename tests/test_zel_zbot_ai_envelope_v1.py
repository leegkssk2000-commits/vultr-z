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
        "routing_flags": {"external_hypothesis": True},
        **SAFETY,
    }
    row = normalize(payload)
    assert row["changed_axes"] == ["ADVISOR_PROFILE"]
    assert row["hypothesis"]["axis"] == "ADVISOR_PROFILE"
    assert "component_axis" not in row["hypothesis"]
    assert "component_replay_contract" not in row
    assert row["routing_flags"]["internal_component_axis"] == "ZBOT_PROFILE"
    assert row["routing_flags"]["internal_advisor_role"] == "ZBot"
