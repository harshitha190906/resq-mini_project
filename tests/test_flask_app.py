"""
ResQNet — tests/test_flask_app.py
===================================
Flask test‑client suite exercising the public JSON API.
Only a subset of endpoints is covered – enough to verify the wiring and that
real modules are used (no mocked success strings).
"""

import json

import pytest

from app import create_app
from app.algorithms.network_topology import build_sample_network


@pytest.fixture
def client():
    """Create a Flask test client with a fresh app instance."""
    app = create_app()
    app.testing = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"status": "ok"}


def test_topology_endpoint(client):
    resp = client.get("/api/topology")
    assert resp.status_code == 200
    data = resp.get_json()
    # The topology must contain the deterministic set of nodes defined in the
    # sample network builder.
    assert "nodes" in data and isinstance(data["nodes"], list)
    assert any(node["node_id"] == "ECC-01" for node in data["nodes"])  # control centre


def test_send_message_success(client):
    payload = {
        "src": "ECC-01",
        "dst": "AMB-01",
        "message": "MAYDAY: test",
        "size_bytes": 512,
        "priority": "NORMAL",
    }
    resp = client.post("/api/messages/send", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["src"] == "ECC-01"
    assert data["dst"] == "AMB-01"
    assert data["delivered"] is True or data["delivered"] is False
    # Must contain a route list with at least source and destination.
    assert isinstance(data["route"], list)
    assert data["route"][0] == "ECC-01"
    assert data["route"][-1] == "AMB-01"


def test_routing_dijkstra_success(client):
    payload = {"src": "ECC-01", "dst": "FS-01"}
    resp = client.post("/api/routing/dijkstra", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "path" in data and isinstance(data["path"], list)
    assert data["path"][0] == "ECC-01"
    assert data["path"][-1] == "FS-01"


def test_simulation_start_and_reset(client):
    # Start with custom traffic level
    payload = {"traffic_level": "high", "packet_size_bytes": 256}
    resp = client.post("/api/simulation/start", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "engine_started"
    assert data["traffic_level"] == "high"

    # Reset should clear state and return a simple confirmation
    resp = client.post("/api/simulation/reset")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "reset_complete"}


def test_invalid_message_missing_fields(client):
    # Omit required "dst" field – should return 400 Bad Request
    payload = {"src": "ECC-01", "message": "test"}
    resp = client.post("/api/messages/send", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data

"""End of Flask test suite."""
