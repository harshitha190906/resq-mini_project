"""
ResQNet — tests/test_simulation.py
===================================
Unit tests for the deterministic discrete‑event simulation engine
(`app.simulation.engine`) and its accompanying metrics module
(`app.simulation.metrics`).

The tests verify:
* Zero‑traffic scenario.
* Successful end‑to‑end delivery.
* Correct handling of a disabled link (failure).
* Queue‑overflow detection (congestion).
* Metrics calculations for a mixed batch.
* Go‑Back‑N retransmission accounting.
"""

import pytest

from app.simulation.engine import SimulationEngine, TrafficLevel
from app.simulation.metrics import SimulationMetrics
from app.algorithms.network_topology import build_sample_network


@pytest.fixture
def engine():
    """Provide a fresh engine with the deterministic sample network for each test."""
    return SimulationEngine(network=build_sample_network(), traffic_level=TrafficLevel.LOW)


def test_zero_traffic_metrics():
    eng = SimulationEngine(network=build_sample_network(), traffic_level=TrafficLevel.LOW)
    # No packets are sent.
    metrics = SimulationMetrics(events=eng.events)
    assert metrics.total_sent == 0
    assert metrics.delivery_ratio == 0.0
    assert metrics.loss_ratio == 0.0
    assert metrics.throughput_bps == 0.0
    assert metrics.average_end_to_end_delay == 0.0
    assert metrics.retransmission_rate == 0.0


def test_successful_delivery_and_basic_metrics(engine):
    # Send a single packet from the control centre to an ambulance unit.
    ev = engine.send_packet(src="ECC-01", dst="AMB-01", message="MAYDAY: fire")
    assert ev.delivered is True
    assert ev.loss_reason is None
    # Route should contain at least the source and destination.
    assert ev.route[0] == "ECC-01"
    assert ev.route[-1] == "AMB-01"
    # Timestamps must be monotonic.
    assert ev.timestamps == sorted(ev.timestamps)

    # Compute metrics – only one packet in the list.
    metrics = SimulationMetrics(events=engine.events)
    assert metrics.total_sent == 1
    assert metrics.total_delivered == 1
    assert metrics.delivery_ratio == 1.0
    assert metrics.loss_ratio == 0.0
    # Throughput: packet size (default 1024 bytes) = 8192 bits.
    # Duration equals the last timestamp (since first = 0).
    expected_throughput = 8192 / metrics.simulation_duration
    assert pytest.approx(metrics.throughput_bps) == expected_throughput
    assert metrics.average_end_to_end_delay > 0.0
    assert metrics.retransmission_rate == 0.0


def test_link_failure_results_in_loss(engine):
    # Disable ALL outbound links from ECC-01 so the destination is unreachable
    # regardless of which route Dijkstra selects.
    for neighbour in engine.network.get_all_neighbours("ECC-01"):
        engine.network.disable_link("ECC-01", neighbour)

    ev = engine.send_packet(src="ECC-01", dst="FS-01", message="MAYDAY: flood")
    assert ev.delivered is False
    assert ev.loss_reason in ("link_failed", "no_path")
    # Metrics should reflect a loss.
    metrics = SimulationMetrics(events=engine.events)
    assert metrics.total_sent == 1
    assert metrics.total_delivered == 0
    assert metrics.loss_ratio == 1.0


def test_queue_overflow_congestion(engine):
    # Force a queue overflow by setting capacity to zero on ALL outbound links
    # from ECC-01 so that any route chosen will hit a full queue.
    for neighbour in engine.network.get_all_neighbours("ECC-01"):
        engine.network.get_link("ECC-01", neighbour).queue_capacity = 0

    ev = engine.send_packet(src="ECC-01", dst="FS-01", message="MAYDAY: overload")
    assert ev.delivered is False
    assert ev.loss_reason == "queue_overflow"

    metrics = SimulationMetrics(events=engine.events)
    assert metrics.total_lost == 1
    assert metrics.loss_ratio == 1.0


def test_batch_metrics_and_gbn_retransmissions():
    # Enable Go‑Back‑N with a deterministic loss on the first hop (seq 0, attempt 1).
    engine = SimulationEngine(
        network=build_sample_network(),
        traffic_level=TrafficLevel.MEDIUM,
        enable_gbn=True,
        gbn_lost_frames={(0, 1)},  # lose the first transmission attempt.
    )
    # Send a batch of three packets.
    events = engine.send_batch(count=3, src="ECC-01", dst="FT-01", message="MAYDAY: test")
    assert len(events) == 3
    # All packets should eventually be delivered because GBN retries.
    assert all(ev.delivered for ev in events)
    # At least one packet must have incurred a retransmission.
    total_retx = sum(ev.retransmissions for ev in events)
    assert total_retx >= 1

    metrics = SimulationMetrics(events=engine.events)
    assert metrics.total_sent == 3
    assert metrics.total_delivered == 3
    assert metrics.retransmission_rate == pytest.approx(total_retx / 3)
    # Delivery ratio should be 1.0 and loss ratio 0.0.
    assert metrics.delivery_ratio == 1.0
    assert metrics.loss_ratio == 0.0

"""End of test suite."""
