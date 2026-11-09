"""
ResQNet — tests/test_gbn_lab_scenarios.py
=========================================
Validation test suite for Go-Back-N Reliability & Error Recovery Simulation Lab.

Tests specified scenarios:
- Test A: No frame loss
- Test B: One frame lost
- Test C: Multiple frames lost
- Test D: Small window size (N=1)
- Test E: Window size larger than total frame count (N > M)
- Test F: Repeated transmission failure
- Test G: All frames successfully delivered after retransmission
- Full REST API integration tests (init, step, play, state, reset, stats)
- Flexible lost-frames input parsing
"""

import json
import pytest
from app import create_app
from app.routes import services
from app.algorithms.go_back_n import (
    GBNSimulator,
    GBNEventType,
    parse_lost_frames_input,
)


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    services.reset_all()
    with app.test_client() as client:
        yield client
    services.reset_all()


# =============================================================================
# SCENARIO TESTS (Tests A through G)
# =============================================================================

def test_scenario_a_no_frame_loss():
    """Test A: No frame loss -> 100% efficiency, exactly total_frames transmissions."""
    sim = GBNSimulator(total_frames=6, window_size=3, timeout_ticks=4, lost_frames=set())
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.delivered_in_order == [0, 1, 2, 3, 4, 5]
    assert result.total_transmissions == 6
    assert result.total_timeouts == 0
    assert analytics["lost_transmissions"] == 0
    assert analytics["retransmissions"] == 0
    assert analytics["channel_efficiency_pct"] == 100.0
    assert analytics["delivery_pct"] == 100.0
    assert all(att == 1 for att in analytics["attempts_per_frame"])


def test_scenario_b_one_frame_lost():
    """Test B: One frame lost -> timeout occurs, retransmission happens, all delivered."""
    sim = GBNSimulator(total_frames=5, window_size=5, timeout_ticks=4, lost_frames={(1, 1)})
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.delivered_in_order == [0, 1, 2, 3, 4]
    assert result.total_timeouts >= 1
    assert analytics["lost_transmissions"] == 1
    assert analytics["retransmissions"] >= 1
    assert analytics["attempts_per_frame"][1] == 2
    assert analytics["delivery_pct"] == 100.0


def test_scenario_c_multiple_frames_lost():
    """Test C: Multiple distinct frames lost -> recovers from both losses in sequence."""
    sim = GBNSimulator(total_frames=6, window_size=6, timeout_ticks=4, lost_frames={(1, 1), (3, 1)})
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.delivered_in_order == list(range(6))
    assert analytics["lost_transmissions"] == 2
    assert analytics["attempts_per_frame"][1] >= 2
    assert analytics["attempts_per_frame"][3] >= 2
    assert analytics["delivery_pct"] == 100.0


def test_scenario_d_small_window_size():
    """Test D: Small window size N=1 (Stop-and-Wait equivalent)."""
    sim = GBNSimulator(total_frames=4, window_size=1, timeout_ticks=3, lost_frames={(1, 1)})
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.window_size == 1
    assert result.modulus == 2
    assert result.delivered_in_order == [0, 1, 2, 3]
    # Modulo 2 wraps sequence numbers (0, 1, 0, 1), so frames with seq 1 are dropped on attempt 1
    assert analytics["lost_transmissions"] >= 1
    assert result.total_timeouts >= 1


def test_scenario_e_window_larger_than_total_frames():
    """Test E: Window size larger than the total frame count (e.g. N=8, M=4)."""
    sim = GBNSimulator(total_frames=4, window_size=8, timeout_ticks=4, lost_frames={(0, 1)})
    result = sim.run()

    assert result.window_size == 8
    assert result.delivered_in_order == [0, 1, 2, 3]
    assert result.total_timeouts >= 1


def test_scenario_f_repeated_transmission_failure():
    """Test F: Repeated transmission failure on the same frame (attempt 1 and attempt 2 lost)."""
    sim = GBNSimulator(total_frames=5, window_size=3, timeout_ticks=4, lost_frames={(1, 1), (1, 2)})
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.delivered_in_order == [0, 1, 2, 3, 4]
    assert analytics["lost_transmissions"] == 2
    # Frame 1 needed 3 attempts to succeed
    assert analytics["attempts_per_frame"][1] == 3
    assert result.total_timeouts >= 2


def test_scenario_g_all_frames_successfully_delivered_after_retransmission():
    """Test G: All frames successfully delivered in sequential order after complex retransmissions."""
    sim = GBNSimulator(total_frames=10, window_size=4, timeout_ticks=4, lost_frames={(2, 1), (4, 1), (4, 2)})
    result = sim.run()
    analytics = result.compute_analytics()

    assert result.delivered_in_order == list(range(10))
    assert analytics["delivered_frames"] == 10
    assert analytics["delivery_pct"] == 100.0
    assert len(analytics["delay_per_frame"]) == 10
    assert all(d > 0 for d in analytics["delay_per_frame"])


# =============================================================================
# INPUT PARSING TESTS
# =============================================================================

def test_parse_lost_frames_formats():
    """Verify parse_lost_frames_input handles all common user string and list formats."""
    # Single number
    assert parse_lost_frames_input("1") == {(1, 1)}
    assert parse_lost_frames_input(2) == {(2, 1)}

    # Comma-separated single numbers
    assert parse_lost_frames_input("1, 3") == {(1, 1), (3, 1)}

    # Semicolon-separated pairs
    assert parse_lost_frames_input("1,1; 3,2") == {(1, 1), (3, 2)}
    assert parse_lost_frames_input("2:1, 4:2") == {(2, 1), (4, 2)}

    # Lists
    assert parse_lost_frames_input([1, 4]) == {(1, 1), (4, 1)}
    assert parse_lost_frames_input([[1, 1], [3, 2]]) == {(1, 1), (3, 2)}
    assert parse_lost_frames_input(None) == set()
    assert parse_lost_frames_input("") == set()


# =============================================================================
# FLASK API INTEGRATION TESTS
# =============================================================================

def test_api_gbn_init_and_step_lifecycle(client):
    """Verify /api/go-back-n/init, /api/go-back-n/step, and /api/go-back-n/state."""
    # 1. Initialize simulation session
    init_resp = client.post(
        "/api/go-back-n/init",
        data=json.dumps({"total_frames": 6, "window_size": 3, "timeout_ticks": 4, "lost_frames": "1"}),
        content_type="application/json"
    )
    assert init_resp.status_code == 200
    init_data = init_resp.get_json()
    assert init_data["status"] == "initialized"
    assert init_data["total_frames"] == 6
    assert init_data["window_size"] == 3
    assert init_data["total_events"] > 0
    assert "analytics" in init_data

    # 2. Check session state
    state_resp = client.get("/api/go-back-n/state")
    assert state_resp.status_code == 200
    state = state_resp.get_json()
    assert state["has_session"] is True
    assert state["current_step"] == 0

    # 3. Step forward
    step_resp = client.post("/api/go-back-n/step")
    assert step_resp.status_code == 200
    step_data = step_resp.get_json()
    assert step_data["status"] == "step_executed"
    assert "event" in step_data
    assert "tick" in step_data["event"]
    assert "event_type" in step_data["event"]

    # 4. Query stats
    stats_resp = client.get("/api/go-back-n/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.get_json()
    assert "total_frames" in stats
    assert "channel_efficiency_pct" in stats
    assert "timeline" in stats

    # 5. Play to completion
    play_resp = client.post("/api/go-back-n/play")
    assert play_resp.status_code == 200
    play_data = play_resp.get_json()
    assert play_data["status"] == "completed"

    # 6. Reset session
    reset_resp = client.post("/api/go-back-n/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.get_json() == {"status": "reset_complete"}

    # 7. State after reset
    empty_state = client.get("/api/go-back-n/state").get_json()
    assert empty_state["has_session"] is False
