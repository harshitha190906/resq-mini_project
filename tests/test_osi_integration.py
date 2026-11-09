"""
ResQNet – Additional integration tests for OSI model and CRC endpoint.
"""

import pytest
from app import create_app


@pytest.fixture
def client():
    """Create a fresh Flask test client for each test."""
    app = create_app()
    app.testing = True
    with app.test_client() as client:
        yield client


def test_osi_run_success(client):
    """Happy‑path OSI stack execution via the API.

    Sends a message through the full OSI pipeline and verifies that the
    ``last‑trace`` endpoint returns a populated result.
    """
    payload = {
        "message": "MAYDAY: test integration",
        "source_id": "ECC-01",
        "dest_id": "AMB-01",
        "priority": "HIGH",
    }
    resp = client.post("/api/osi/run", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "completed"
    assert isinstance(data["delivered"], bool)

    # Verify the trace is now available
    trace_resp = client.get("/api/osi/last-trace")
    assert trace_resp.status_code == 200
    trace = trace_resp.get_json()
    # Basic sanity checks – all expected keys present
    for key in ["delivered", "path", "total_cost", "send_steps", "receive_steps", "errors", "warnings"]:
        assert key in trace
    # At least one step should be recorded for each direction
    assert len(trace["send_steps"]) > 0
    assert len(trace["receive_steps"]) > 0


def test_osi_run_missing_fields(client):
    """Ensure the OSI endpoint validates required JSON fields.

    Omitting ``dest_id`` should trigger a 400 Bad Request response.
    """
    payload = {
        "message": "MAYDAY: incomplete",
        "source_id": "ECC-01",
        # "dest_id" is intentionally omitted
        "priority": "LOW",
    }
    resp = client.post("/api/osi/run", json=payload)
    assert resp.status_code == 400
    err = resp.get_json()
    assert "error" in err


def test_crc_endpoint_success(client):
    """Validate CRC computation and verification.

    Uses a short hexadecimal payload and the default CRC‑4 generator.
    """
    hex_data = "ABCD"
    generator = "10011"  # CRC‑4 as used by the Data Link layer
    resp = client.post(
        "/api/crc/check",
        json={"hex_data": hex_data, "generator": generator},
    )
    assert resp.status_code == 200
    result = resp.get_json()
    # ``crc`` should be a string of the same length as the generator minus 1
    assert isinstance(result["crc"], str)
    assert len(result["crc"]) == len(generator) - 1
    # ``valid`` indicates whether the appended CRC yields a zero syndrome
    assert isinstance(result["valid"], bool)


def test_crc_endpoint_invalid_payload(client):
    """Missing required fields should produce a 400 error."""
    resp = client.post("/api/crc/check", json={"hex_data": "1234"})
    assert resp.status_code == 400
    err = resp.get_json()
    assert "error" in err
