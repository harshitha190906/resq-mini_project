"""
ResQNet — tests/test_dashboard_integration.py
=============================================
Integration test suite for ResQNet Dashboard:
- Automatic dashboard data loading endpoints (/api/health, /api/topology, /api/metrics)
- Network overview cards & initial unsimulated state
- Disaster simulation execution (/api/simulation/start) & metrics generation
- Time series telemetry generation for Chart.js charts
- Link failure effect on topology summary
- Simulation engine reset (/api/simulation/reset)
"""

import json
import pytest
from app import create_app
from app.routes import services


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    services.reset_all()
    with app.test_client() as client:
        yield client
    services.reset_all()


def test_dashboard_page_structure(client):
    """Verify dashboard HTML includes all NOC cards, SVG container, and canvas elements."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Core NOC dashboard elements
    assert "Network Operations Center" in html
    assert 'id="sim-status-badge"' in html
    assert 'id="total-nodes"' in html
    assert 'id="active-links"' in html
    assert 'id="failed-links"' in html
    assert 'id="val-total-nodes"' in html
    assert 'id="val-active-links"' in html
    assert 'id="val-failed-links"' in html

    # Topology preview container
    assert 'id="network-preview"' in html

    # Chart canvas elements
    assert 'id="deliveryChart"' in html
    assert 'id="lossChart"' in html
    assert 'id="delayThroughputChart"' in html

    # Empty chart state placeholders
    assert 'id="deliveryChart-empty"' in html
    assert 'id="lossChart-empty"' in html
    assert 'id="delayThroughputChart-empty"' in html
    assert "Run a simulation to generate performance data" in html

    # Control buttons
    assert 'id="start-sim"' in html
    assert 'id="reset-sim"' in html

    # Script links
    assert "api.js" in html
    assert "dashboard.js" in html


def test_initial_dashboard_endpoints_before_simulation(client):
    """Verify health, topology, and metrics endpoints before any simulation is executed."""
    # 1. Health check
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    assert health_resp.get_json() == {"status": "ok"}

    # 2. Topology check
    topo_resp = client.get("/api/topology")
    assert topo_resp.status_code == 200
    topo = topo_resp.get_json()
    assert topo["total_nodes"] == 8
    assert topo["total_links"] == 25
    assert topo["active_links"] == 25
    assert topo["failed_links"] == 0
    assert len(topo["nodes"]) == 8
    assert len(topo["links"]) == 25

    # 3. Metrics check (unsimulated state)
    metrics_resp = client.get("/api/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.get_json()
    assert metrics["has_data"] is False
    assert metrics["sent"] == 0
    assert metrics["delivered"] == 0
    assert metrics["lost"] == 0
    assert metrics["total_nodes"] == 8
    assert metrics["active_links"] == 25
    assert metrics["failed_links"] == 0
    assert metrics["time_series"]["labels"] == []


def test_simulation_start_generates_real_metrics_and_time_series(client):
    """Verify clicking start simulation generates deterministic metrics and chart telemetry."""
    # Trigger simulation start
    sim_resp = client.post(
        "/api/simulation/start",
        data=json.dumps({"count": 20, "traffic_level": "low"}),
        content_type="application/json"
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.get_json()
    assert sim_data["status"] == "engine_started"
    assert sim_data["packets_sent"] == 20

    # Query metrics endpoint after simulation
    metrics_resp = client.get("/api/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.get_json()

    assert metrics["has_data"] is True
    assert metrics["sent"] == 20
    assert metrics["delivered"] > 0
    assert metrics["delivery_ratio"] > 0.0
    assert metrics["avg_delay_ms"] > 0.0
    assert metrics["throughput_kbps"] > 0.0

    # Verify time-series data structures for all 3 charts
    ts = metrics["time_series"]
    assert len(ts["labels"]) == 20
    assert len(ts["delivery_cumulative"]) == 20
    assert len(ts["loss_cumulative"]) == 20
    assert len(ts["delay_ms"]) == 20
    assert len(ts["throughput_kbps"]) == 20

    # Check non-decreasing cumulative series
    assert ts["delivery_cumulative"][-1] == metrics["delivered"]
    assert ts["loss_cumulative"][-1] == metrics["lost"]


def test_link_failure_updates_topology_and_subsequent_metrics(client):
    """Verify disabling links directly updates topology counts and impacts simulated delivery."""
    # Toggle off link between POL and ECC
    toggle_resp = client.post(
        "/api/links/toggle",
        data=json.dumps({"node_a": "POL", "node_b": "ECC"}),
        content_type="application/json"
    )
    assert toggle_resp.status_code == 200
    toggle_data = toggle_resp.get_json()
    assert toggle_data["is_active"] is False

    # Check topology summary
    topo_resp = client.get("/api/topology")
    topo = topo_resp.get_json()
    # Bidirectional link toggle reduces active by 2 and increases failed by 2
    assert topo["failed_links"] == 2
    assert topo["active_links"] == 23

    # Run simulation with failed link
    sim_resp = client.post(
        "/api/simulation/start",
        data=json.dumps({"count": 20, "traffic_level": "low"}),
        content_type="application/json"
    )
    assert sim_resp.status_code == 200

    metrics_resp = client.get("/api/metrics")
    metrics = metrics_resp.get_json()
    assert metrics["has_data"] is True
    assert metrics["failed_links"] == 2
    assert metrics["active_links"] == 23


def test_simulation_reset_clears_metrics_and_returns_to_initial_state(client):
    """Verify resetting simulation restores metrics to clean unsimulated state."""
    # First run simulation
    client.post(
        "/api/simulation/start",
        data=json.dumps({"count": 15}),
        content_type="application/json"
    )
    m1 = client.get("/api/metrics").get_json()
    assert m1["has_data"] is True
    assert m1["sent"] == 15

    # Reset simulation
    reset_resp = client.post("/api/simulation/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.get_json() == {"status": "reset_complete"}

    # Verify metrics are clean
    m2 = client.get("/api/metrics").get_json()
    assert m2["has_data"] is False
    assert m2["sent"] == 0
    assert m2["delivered"] == 0
    assert m2["lost"] == 0
    assert m2["delivery_ratio"] == 0.0
    assert m2["time_series"]["labels"] == []
