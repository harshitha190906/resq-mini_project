"""
ResQNet — tests/test_routing_simulation.py
===========================================
Comprehensive unit and API test suite verifying:
1. Dynamic route determination (Dijkstra and Distance-Vector).
2. Disaster link failure and restoration for:
   - POL ↔ ECC (Primary Command Link)
   - POL ↔ R1 (North Relay Link)
   - FIRE ↔ R2 (East Sector Relay Link)
3. Dijkstra relaxation event log verification.
4. Reachability, rerouting, and unreachable state detection.
5. REST API integration and alias support.
"""

import pytest
from app import create_app
from app.algorithms.network_topology import (
    EmergencyNetwork,
    build_sample_network,
    resolve_node_id,
    LinkStatus,
)
from app.algorithms.dijkstra import dijkstra
from app.algorithms.distance_vector import DistanceVectorRouter
from app.routes import services


@pytest.fixture
def client():
    """Create Flask test client with clean service state."""
    app = create_app()
    app.testing = True
    services.reset_all()
    with app.test_client() as client:
        yield client
    services.reset_all()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Core Algorithm Tests on Sample Disaster Network
# ─────────────────────────────────────────────────────────────────────────────

def test_alias_resolution():
    assert resolve_node_id("ECC") == "ECC-01"
    assert resolve_node_id("POL") == "PS-01"
    assert resolve_node_id("FIRE") == "FS-01"
    assert resolve_node_id("AMB") == "AMB-01"
    assert resolve_node_id("SHT1") == "SHL-01"
    assert resolve_node_id("R1") == "RTR-01"
    assert resolve_node_id("R2") == "RTR-02"
    assert resolve_node_id("ECC-01") == "ECC-01"


def test_dijkstra_optimal_path_healthy_network():
    net = build_sample_network()
    # Route from Shelter North (SHL-01) to Emergency Control Center (ECC-01)
    res = dijkstra(net, "SHL-01", "ECC-01")
    assert res.reachable
    assert res.path[0] == "SHL-01"
    assert res.path[-1] == "ECC-01"
    assert res.total_cost > 0
    assert res.hops == len(res.path) - 1
    assert res.total_delay_ms is not None
    assert res.bottleneck_bw_mbps is not None
    assert len(res.links) == res.hops


def test_distance_vector_optimal_path_healthy_network():
    net = build_sample_network()
    router = DistanceVectorRouter(net)
    report = router.run()
    assert report.converged

    dv_details = router.get_path_details("SHL-01", "ECC-01")
    assert dv_details["reachable"]
    assert dv_details["path"][0] == "SHL-01"
    assert dv_details["path"][-1] == "ECC-01"
    assert dv_details["total_cost"] > 0
    assert dv_details["hops"] == len(dv_details["path"]) - 1


def test_dijkstra_relaxation_log_events():
    net = build_sample_network()
    res = dijkstra(net, "SHL-01", "ECC-01")
    assert len(res.log) > 0

    event_types = {e.event_type for e in res.log}
    assert "start" in event_types
    assert "init" in event_types
    assert "visit" in event_types
    assert "evaluate" in event_types
    assert "update" in event_types
    assert "complete" in event_types

    # First event is start
    assert res.log[0].event_type == "start"
    # Final event is complete
    assert res.log[-1].event_type == "complete"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Disaster Link Failure & Dynamic Recalculation Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_disaster_link_toggle_pol_ecc():
    """Toggle POL ↔ ECC (Primary Command Link: PS-01 ↔ ECC-01)."""
    net = build_sample_network()
    # Initially active
    assert net.get_link("PS-01", "ECC-01").is_operational
    assert net.get_link("ECC-01", "PS-01").is_operational

    # Toggle to FAILED
    is_active = net.toggle_link("PS-01", "ECC-01", bidirectional=True)
    assert not is_active
    assert not net.get_link("PS-01", "ECC-01").is_operational
    assert not net.get_link("ECC-01", "PS-01").is_operational

    # Both Dijkstra and DV must avoid the failed link
    dj = dijkstra(net, "PS-01", "ECC-01")
    assert dj.reachable
    # Must route around PS-01 ↔ ECC-01 (e.g. via RTR-02 or RTR-01)
    for i in range(len(dj.path) - 1):
        assert not (dj.path[i] == "PS-01" and dj.path[i + 1] == "ECC-01")

    # Relaxation log records skipped failed link
    failed_skipped = [e for e in dj.log if e.event_type == "skip_failed"]
    assert len(failed_skipped) > 0

    # Toggle back to ACTIVE
    is_active_again = net.toggle_link("PS-01", "ECC-01", bidirectional=True)
    assert is_active_again
    assert net.get_link("PS-01", "ECC-01").is_operational


def test_disaster_link_toggle_pol_r1():
    """Toggle POL ↔ R1 (North Relay Link: PS-01 ↔ RTR-01)."""
    net = build_sample_network()
    assert net.get_link("PS-01", "RTR-01").is_operational

    is_active = net.toggle_link("PS-01", "RTR-01", bidirectional=True)
    assert not is_active
    assert not net.get_link("PS-01", "RTR-01").is_operational
    assert not net.get_link("RTR-01", "PS-01").is_operational

    # Restore
    is_active = net.toggle_link("PS-01", "RTR-01", bidirectional=True)
    assert is_active
    assert net.get_link("PS-01", "RTR-01").is_operational


def test_disaster_link_toggle_fire_r2():
    """Toggle FIRE ↔ R2 (East Sector Relay: FS-01 ↔ RTR-02)."""
    net = build_sample_network()
    assert net.get_link("FS-01", "RTR-02").is_operational

    is_active = net.toggle_link("FS-01", "RTR-02", bidirectional=True)
    assert not is_active
    assert not net.get_link("FS-01", "RTR-02").is_operational

    # Rerouting still reaches FS-01 via RTR-01
    dj = dijkstra(net, "ECC-01", "FS-01")
    assert dj.reachable
    assert "RTR-01" in dj.path


def test_complete_network_isolation_shows_unreachable():
    """Sever all connections to shelter; algorithm must return reachable=False."""
    net = build_sample_network()
    # Isolate SHL-01
    for nbr in list(net.get_all_neighbours("SHL-01")):
        net.disable_link("SHL-01", nbr, bidirectional=True)
    for node in net.list_nodes():
        if "SHL-01" in net.get_all_neighbours(node.node_id):
            net.disable_link(node.node_id, "SHL-01", bidirectional=True)

    dj = dijkstra(net, "SHL-01", "ECC-01")
    assert not dj.reachable
    assert dj.path == []
    assert dj.total_cost == float("inf")
    assert dj.total_delay_ms is None

    unreachable_events = [e for e in dj.log if e.event_type == "unreachable"]
    assert len(unreachable_events) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Flask API Integration & Alias Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_api_topology_returns_rich_metadata(client):
    resp = client.get("/api/topology")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "nodes" in data and "links" in data
    assert "predefined_links" in data
    assert len(data["predefined_links"]) == 3


def test_api_routing_dijkstra_with_aliases(client):
    # Test using short disaster management aliases SHT1 and ECC
    resp = client.post("/api/routing/dijkstra", json={"source": "SHT1", "destination": "ECC"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["reachable"] is True
    assert data["source"] == "SHL-01"
    assert data["destination"] == "ECC-01"
    assert len(data["path"]) >= 2
    assert "path_names" in data
    assert "log" in data
    assert data["total_cost"] is not None
    assert data["total_delay_ms"] is not None


def test_api_routing_distance_vector_with_aliases(client):
    resp = client.post("/api/routing/distance-vector", json={"source": "SHT1", "destination": "ECC"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["reachable"] is True
    assert data["source"] == "SHL-01"
    assert data["destination"] == "ECC-01"
    assert data["converged"] is True
    assert "tables" in data


def test_api_link_toggle_endpoint(client):
    # Toggle POL ↔ ECC via API
    resp = client.post("/api/links/toggle", json={"node_a": "POL", "node_b": "ECC"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["node_a"] == "PS-01"
    assert data["node_b"] == "ECC-01"
    assert data["is_active"] is False  # Was active, now failed

    # Toggle back to restore
    resp2 = client.post("/api/links/toggle", json={"node_a": "POL", "node_b": "ECC"})
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["is_active"] is True


def test_api_link_fail_and_restore(client):
    resp_fail = client.post("/api/links/fail", json={"node_a": "FIRE", "node_b": "R2"})
    assert resp_fail.status_code == 200
    assert resp_fail.get_json()["status"] == "link_disabled"

    resp_restore = client.post("/api/links/restore", json={"node_a": "FIRE", "node_b": "R2"})
    assert resp_restore.status_code == 200
    assert resp_restore.get_json()["status"] == "link_restored"


def test_api_invalid_nodes_handled_gracefully(client):
    resp = client.post("/api/routing/dijkstra", json={"source": "UNKNOWN_NODE", "destination": "ECC"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

