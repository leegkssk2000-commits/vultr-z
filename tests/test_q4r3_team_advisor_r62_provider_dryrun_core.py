from __future__ import annotations

from q4r3_r62_fixture import evaluate


def test_provider_dryrun_fixture_passes() -> None:
    result = evaluate()
    assert result.state == "PASS"
    assert result.route_count == 4
    assert result.provider_packet_count == 7
    assert result.normalized_response_count == 7
    assert result.dual_provider_arbitration_count == 3
    assert result.network_call_count == 0
    assert result.credential_material_count == 0
    assert result.budget_preflight_ready is True
    assert result.idempotency_preflight_ready is True
    assert result.serialization_ready is True
    assert result.provider_isolation_ready is True
    assert result.response_normalization_ready is True
    assert result.arbitration_ready is True


def test_packets_are_deterministic_and_provider_isolated() -> None:
    first = evaluate()
    second = evaluate()
    first_packets = tuple(packet for route in first.route_results for packet in route.packets)
    second_packets = tuple(packet for route in second.route_results for packet in route.packets)
    assert tuple(packet.body_sha256 for packet in first_packets) == tuple(packet.body_sha256 for packet in second_packets)
    assert tuple(packet.dispatch_key for packet in first_packets) == tuple(packet.dispatch_key for packet in second_packets)
    assert len({packet.dispatch_key for packet in first_packets}) == 7
    assert {packet.endpoint_alias for packet in first_packets} == {
        "openai.responses",
        "gemini.generate_content",
    }
    assert all(packet.network_call_performed is False for packet in first_packets)
    assert all(packet.credential_material_present is False for packet in first_packets)


def test_single_provider_route_skips_dual_arbitration() -> None:
    result = evaluate()
    single = [route for route in result.route_results if route.packet_count == 1]
    assert len(single) == 1
    assert single[0].arbitration_state == "NOT_REQUIRED_SINGLE_PROVIDER"
    assert single[0].normalized_response_count == 1
    assert single[0].response_path_valid is True
