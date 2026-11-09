"""
ResQNet – tests/test_congestion_analytics_history.py
=====================================================
Integration tests for the three new ResQNet modules:
  1. Congestion Control (Leaky Bucket)
  2. Performance Analytics
  3. Simulation History (SQLite)
"""

import pytest
import json
import io
import tempfile
import os
from app import create_app


@pytest.fixture(scope="module")
def client():
    """Flask test client shared across all tests in this module."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# =============================================================================
# MODULE 1: CONGESTION CONTROL (Leaky Bucket)
# =============================================================================

class TestCongestionControl:

    def test_simulate_default_params(self, client):
        """POST /api/congestion/simulate with default params returns valid response."""
        resp = client.post(
            "/api/congestion/simulate",
            data=json.dumps({}),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "metrics" in data
        metrics = data["metrics"]
        assert "total_incoming" in metrics
        assert "total_transmitted" in metrics
        assert "total_dropped" in metrics
        assert metrics["total_incoming"] >= 0
        assert metrics["total_transmitted"] >= 0

    def test_simulate_overflow(self, client):
        """With tiny capacity and high arrivals, dropped > 0."""
        payload = {
            "capacity": 5,
            "leak_rate": 2,
            "arrivals": [10, 10, 10]
        }
        resp = client.post(
            "/api/congestion/simulate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["total_dropped"] > 0

    def test_simulate_no_overflow(self, client):
        """With large capacity, no packets are dropped."""
        payload = {
            "capacity": 100,
            "leak_rate": 10,
            "arrivals": [5, 5, 5, 5]
        }
        resp = client.post(
            "/api/congestion/simulate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["total_dropped"] == 0

    def test_different_leak_rates_affect_output(self, client):
        """Higher leak rate → more transmitted (fewer dropped) with same arrivals."""
        arrivals = [8, 8, 8, 8]

        resp_slow = client.post(
            "/api/congestion/simulate",
            data=json.dumps({"capacity": 10, "leak_rate": 2, "arrivals": arrivals}),
            content_type="application/json"
        )
        resp_fast = client.post(
            "/api/congestion/simulate",
            data=json.dumps({"capacity": 10, "leak_rate": 8, "arrivals": arrivals}),
            content_type="application/json"
        )
        assert resp_slow.status_code == 200
        assert resp_fast.status_code == 200

        slow_metrics = resp_slow.get_json()["metrics"]
        fast_metrics = resp_fast.get_json()["metrics"]

        # Use the actual key names returned by the API
        slow_tx = slow_metrics.get("total_transmitted") or slow_metrics.get("total_admitted") or 0
        fast_tx = fast_metrics.get("total_transmitted") or fast_metrics.get("total_admitted") or 0
        # Faster leak rate must result in at least as much transmitted traffic
        assert fast_tx >= slow_tx

    def test_congestion_reset(self, client):
        """POST /api/congestion/reset returns reset confirmation."""
        resp = client.post("/api/congestion/reset", content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") in ("reset", "reset_complete", "ok")

    def test_congestion_status(self, client):
        """GET /api/congestion/status returns status object."""
        resp = client.get("/api/congestion/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data or "has_data" in data or "last_simulation" in data

    def test_simulate_events_present(self, client):
        """Simulate returns tick-by-tick event list."""
        payload = {
            "capacity": 10,
            "leak_rate": 3,
            "arrivals": [5, 5, 5]
        }
        resp = client.post(
            "/api/congestion/simulate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data
        assert len(data["events"]) > 0
        # Each event should have tick, arriving, leaked fields
        evt = data["events"][0]
        assert "tick" in evt or "arriving" in evt or "queue_after" in evt


# =============================================================================
# MODULE 2: PERFORMANCE ANALYTICS
# =============================================================================

class TestPerformanceAnalytics:

    def test_analytics_overview_returns_has_data(self, client):
        """GET /api/analytics/overview returns has_data field."""
        resp = client.get("/api/analytics/overview")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "has_data" in data
        assert "total_sent" in data
        assert "delivered" in data
        assert "lost" in data
        assert "delivery_ratio_pct" in data
        assert "loss_ratio_pct" in data
        assert "avg_delay_ms" in data
        assert "throughput_kbps" in data

    def test_analytics_performance_shape(self, client):
        """GET /api/analytics/performance returns loads, table, curves with 6 entries."""
        resp = client.get("/api/analytics/performance")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "loads" in data
        assert "table" in data
        assert "curves" in data
        assert len(data["loads"]) == 6
        assert len(data["table"]) == 6
        expected_loads = [10, 20, 40, 60, 80, 100]
        assert data["loads"] == expected_loads

    def test_analytics_comparison_curves_keys(self, client):
        """Performance response contains all 6 curve arrays."""
        resp = client.get("/api/analytics/performance")
        data = resp.get_json()
        curves = data["curves"]
        for key in ("unc_delay", "ctrl_delay", "unc_throughput", "ctrl_throughput", "unc_loss", "ctrl_loss"):
            assert key in curves, f"Missing curve key: {key}"
            assert len(curves[key]) == 6

    def test_analytics_table_structure(self, client):
        """Each comparison table row has expected fields."""
        resp = client.get("/api/analytics/performance")
        data = resp.get_json()
        for row in data["table"]:
            assert "load_pps" in row
            assert "uncontrolled" in row
            assert "controlled" in row
            for side in ("uncontrolled", "controlled"):
                assert "delivery_ratio_pct" in row[side]
                assert "loss_ratio_pct" in row[side]
                assert "avg_delay_ms" in row[side]
                assert "throughput_kbps" in row[side]

    def test_analytics_compare_post(self, client):
        """POST /api/analytics/compare also returns comparison data."""
        resp = client.post(
            "/api/analytics/compare",
            data=json.dumps({}),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "loads" in data

    def test_analytics_export_csv(self, client):
        """GET /api/analytics/export returns 200 with text/csv content type."""
        resp = client.get("/api/analytics/export")
        assert resp.status_code == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/csv" in content_type
        body = resp.data.decode("utf-8")
        assert "RESQNET" in body or "Delivery" in body or "Throughput" in body

    def test_analytics_controlled_less_loss_than_uncontrolled(self, client):
        """Under high load, controlled loss should be <= uncontrolled loss."""
        resp = client.get("/api/analytics/performance")
        data = resp.get_json()
        # Check high-load rows (60, 80, 100 pkts/s) where congestion is visible
        for row in data["table"]:
            if row["load_pps"] >= 60:
                ctrl_loss = row["controlled"]["loss_ratio_pct"]
                unc_loss  = row["uncontrolled"]["loss_ratio_pct"]
                assert ctrl_loss <= unc_loss, (
                    f"At load {row['load_pps']}: controlled loss {ctrl_loss} > uncontrolled loss {unc_loss}"
                )


# =============================================================================
# MODULE 3: SIMULATION HISTORY (SQLite persistent audit trail)
# =============================================================================

class TestSimulationHistory:

    def test_history_list_returns_simulations_and_summary(self, client):
        """GET /api/history returns simulations array and summary with counts."""
        resp = client.get("/api/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "simulations" in data
        assert "summary" in data
        assert isinstance(data["simulations"], list)
        summary = data["summary"]
        assert "total_simulations" in summary
        # Seeded data should provide at least 1 record
        assert summary["total_simulations"] >= 1

    def test_history_summary_fields(self, client):
        """Summary contains all required KPI fields."""
        resp = client.get("/api/history")
        data = resp.get_json()
        summary = data["summary"]
        required_keys = [
            "total_simulations", "successful_simulations", "failed_simulations",
            "total_packets", "avg_delivery_ratio", "avg_throughput_kbps"
        ]
        for key in required_keys:
            assert key in summary, f"Missing summary key: {key}"

    def test_history_records_have_required_fields(self, client):
        """Each history record contains all required columns."""
        resp = client.get("/api/history")
        data = resp.get_json()
        if not data["simulations"]:
            pytest.skip("No history records available")
        sim = data["simulations"][0]
        for field in ("id", "timestamp", "algorithm", "packets_sent", "packets_delivered",
                      "packets_lost", "avg_delay_ms", "throughput_kbps", "status"):
            assert field in sim, f"Missing field in simulation record: {field}"

    def test_history_filter_by_algorithm(self, client):
        """GET /api/history?algorithm=Dijkstra returns only Dijkstra records."""
        resp = client.get("/api/history?algorithm=Dijkstra")
        assert resp.status_code == 200
        data = resp.get_json()
        for sim in data["simulations"]:
            assert "dijkstra" in sim["algorithm"].lower() or "routing" in sim["algorithm"].lower(), \
                f"Unexpected algorithm in filtered result: {sim['algorithm']}"

    def test_history_filter_by_status_success(self, client):
        """GET /api/history?status=SUCCESS returns only SUCCESS records."""
        resp = client.get("/api/history?status=SUCCESS")
        assert resp.status_code == 200
        data = resp.get_json()
        for sim in data["simulations"]:
            assert sim["status"].upper() == "SUCCESS"

    def test_history_sort_newest(self, client):
        """GET /api/history?sort=newest returns records in reverse-chronological order."""
        resp = client.get("/api/history?sort=newest")
        assert resp.status_code == 200
        data = resp.get_json()
        timestamps = [s["timestamp"] for s in data["simulations"]]
        assert timestamps == sorted(timestamps, reverse=True) or len(timestamps) <= 1

    def test_history_sort_oldest(self, client):
        """GET /api/history?sort=oldest returns records in chronological order."""
        resp = client.get("/api/history?sort=oldest")
        assert resp.status_code == 200
        data = resp.get_json()
        timestamps = [s["timestamp"] for s in data["simulations"]]
        assert timestamps == sorted(timestamps) or len(timestamps) <= 1

    def test_history_detail_found(self, client):
        """GET /api/history/<id> returns full record for a seeded simulation."""
        # First get the list to find a valid ID
        resp_list = client.get("/api/history")
        sims = resp_list.get_json().get("simulations", [])
        if not sims:
            pytest.skip("No history records available")
        sim_id = sims[0]["id"]

        resp = client.get(f"/api/history/{sim_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == sim_id
        assert "parameters" in data
        assert "details" in data

    def test_history_detail_not_found(self, client):
        """GET /api/history/<invalid_id> returns 404."""
        resp = client.get("/api/history/NON-EXISTENT-ID-XYZ")
        assert resp.status_code == 404

    def test_history_delete_and_verify(self, client):
        """DELETE /api/history/<id> removes the record and subsequent GET returns 404."""
        # Insert a fresh record via the simulation start endpoint (use lowercase traffic_level)
        sim_resp = client.post(
            "/api/simulation/start",
            data=json.dumps({"num_packets": 10, "traffic_level": "low"}),
            content_type="application/json"
        )
        assert sim_resp.status_code == 200

        # Find the most recently created record
        list_resp = client.get("/api/history?sort=newest&limit=1")
        list_data = list_resp.get_json()
        if not list_data["simulations"]:
            pytest.skip("No records to delete")
        sim_id = list_data["simulations"][0]["id"]

        # Delete it
        del_resp = client.delete(f"/api/history/{sim_id}")
        assert del_resp.status_code == 200
        del_data = del_resp.get_json()
        assert del_data.get("status") == "deleted"

        # Verify it's gone
        get_resp = client.get(f"/api/history/{sim_id}")
        assert get_resp.status_code == 404

    def test_history_export_csv(self, client):
        """GET /api/history/export returns CSV with correct content type."""
        resp = client.get("/api/history/export")
        assert resp.status_code == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/csv" in content_type
        body = resp.data.decode("utf-8")
        # Must contain header row
        assert "Simulation ID" in body or "id" in body.lower()

    def test_history_clear_then_list_empty(self, client):
        """DELETE /api/history/clear removes all records; subsequent list is empty."""
        # First ensure some record exists
        client.post(
            "/api/simulation/start",
            data=json.dumps({"num_packets": 5, "traffic_level": "LOW"}),
            content_type="application/json"
        )

        # Clear all
        clear_resp = client.delete("/api/history/clear")
        assert clear_resp.status_code == 200
        clear_data = clear_resp.get_json()
        assert clear_data.get("status") in ("cleared", "ok", "deleted")

        # Verify empty
        list_resp = client.get("/api/history")
        list_data = list_resp.get_json()
        assert list_data["summary"]["total_simulations"] == 0

    def test_auto_recording_on_simulation_start(self, client):
        """Running /api/simulation/start creates a new history record."""
        # Get count before
        before = client.get("/api/history").get_json()["summary"]["total_simulations"]

        # Run simulation
        client.post(
            "/api/simulation/start",
            data=json.dumps({"num_packets": 10, "traffic_level": "LOW"}),
            content_type="application/json"
        )

        # Get count after
        after = client.get("/api/history").get_json()["summary"]["total_simulations"]
        assert after == before + 1

    def test_history_query_search(self, client):
        """GET /api/history?query=<id> returns matching records."""
        # Get the first record's ID
        resp_list = client.get("/api/history")
        sims = resp_list.get_json().get("simulations", [])
        if not sims:
            pytest.skip("No history records for search test")

        sim_id = sims[0]["id"]
        # Search by partial ID
        partial = sim_id[:10]
        resp_search = client.get(f"/api/history?query={partial}")
        assert resp_search.status_code == 200
        search_sims = resp_search.get_json()["simulations"]
        # At least one result should match
        assert any(partial in s["id"] for s in search_sims)
