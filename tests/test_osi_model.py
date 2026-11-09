"""
ResQNet — tests/test_osi_model.py
=================================
Unit tests for the educational OSI model simulation.

The tests cover:
* Successful end‑to‑end encapsulation/decapsulation.
* Correct layer ordering and numbering.
* CRC detection error handling (inject_crc_error).
* Physical link availability handling (disable link).
* Go‑Back‑N warning generation when a loss is forced.
"""

import pytest

from app.simulation.osi_model import (
    OSIStack,
    build_osi_network,
    LayerNumber,
    ProcessingStatus,
    Priority,
)

# Helper to extract layer numbers from a step list
def layer_numbers(steps):
    return [s.layer_number for s in steps]


@pytest.fixture
def network():
    return build_osi_network()


def test_successful_delivery(network):
    stack = OSIStack(network=network)
    result = stack.send(
        message="MAYDAY: fire at sector 7G",
        source_id="ECC-01",
        dest_id="AMB-01",
        priority="HIGH",
    )

    # Delivery flag
    assert result.delivered is True

    # All seven layers should appear in both directions
    assert len(result.send_steps) == 7
    assert len(result.receive_steps) == 7

    # Verify ordering (7 → 1 encapsulation)
    assert layer_numbers(result.send_steps) == [7, 6, 5, 4, 3, 2, 1]
    # Verify decapsulation ordering (1 → 7)
    assert layer_numbers(result.receive_steps) == [1, 2, 3, 4, 5, 6, 7]

    # No errors or warnings
    assert result.errors == []
    assert result.warnings == []

    # The path should be a non‑empty list and cost finite
    assert result.path
    assert result.total_cost < float("inf")


def test_crc_error_detection(network):
    stack = OSIStack(network=network, inject_crc_error=True)
    result = stack.send(
        message="MAYDAY: collapsed bridge",
        source_id="ECC-01",
        dest_id="FS-01",
        priority="CRITICAL",
    )

    # Delivery must fail due to CRC error
    assert result.delivered is False
    # The Data Link receive step should have status ERROR
    dl_receive = next(s for s in result.receive_steps if s.layer_number == LayerNumber.DATA_LINK)
    assert dl_receive.status == ProcessingStatus.ERROR
    # Error message should mention CRC
    assert "CRC" in dl_receive.error_message


def test_physical_link_unavailable(network):
    # Disable ALL outbound links from ECC-01 so that Dijkstra finds no path.
    # The OSI stack will abort at the Network layer (L3) before reaching L1.
    for neighbour in network.get_all_neighbours("ECC-01"):
        network.disable_link("ECC-01", neighbour)

    stack = OSIStack(network=network)
    result = stack.send(
        message="MAYDAY: evacuate area",
        source_id="ECC-01",
        dest_id="FT-01",
        priority="NORMAL",
    )

    assert result.delivered is False
    # Network layer send step must be ERROR (no route found)
    net_send = next(s for s in result.send_steps if s.layer_number == LayerNumber.NETWORK)
    assert net_send.status == ProcessingStatus.ERROR
    assert "NO ROUTE" in net_send.output_summary



def test_gbn_warning_on_loss(network):
    # Force loss of the first segment (seq 0, attempt 1)
    loss_set = {(0, 1)}
    stack = OSIStack(
        network=network,
        use_gbn=True,
        gbn_lost_frames=loss_set,
    )
    result = stack.send(
        message="MAYDAY: water main burst – urgent",
        source_id="ECC-01",
        dest_id="AMB-01",
        priority="HIGH",
    )

    # Delivery should still succeed (retransmission occurs)
    assert result.delivered is True
    # Transport layer should contain a warning about GBN timeouts
    transport = next(s for s in result.send_steps if s.layer_number == LayerNumber.TRANSPORT)
    assert transport.status == ProcessingStatus.WARNING
    assert "GBN" in transport.error_message
    # Warning should be bubbled up to the final OSIResult warnings list
    assert any("GBN" in w for w in result.warnings)
