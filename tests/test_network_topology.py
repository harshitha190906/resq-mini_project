"""
ResQNet — tests/test_network_topology.py
=========================================
Unit tests for app.algorithms.network_topology.

Run with:
    python -m pytest tests/test_network_topology.py -v
"""

import sys
import os

# Allow running tests from the project root without installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.algorithms.network_topology import (
    Node,
    NodeType,
    Link,
    LinkStatus,
    EmergencyNetwork,
    build_sample_network,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def two_node_net() -> EmergencyNetwork:
    """Minimal network: two routers with one directed link A→B."""
    net = EmergencyNetwork()
    net.add_node(Node("A", "Alpha Router", NodeType.ROUTER))
    net.add_node(Node("B", "Beta Router",  NodeType.ROUTER))
    net.add_link(Link("A", "B", cost=1, bandwidth_mbps=100,
                      latency_ms=5, queue_capacity=64))
    return net


@pytest.fixture
def sample_net() -> EmergencyNetwork:
    """Full deterministic sample network."""
    return build_sample_network()


# ─────────────────────────────────────────────────────────────────────────────
# Node tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNode:
    def test_node_creation_stores_fields(self):
        n = Node("ECC-01", "Central Control", NodeType.EMERGENCY_CONTROL_CENTER)
        assert n.node_id   == "ECC-01"
        assert n.name      == "Central Control"
        assert n.node_type == NodeType.EMERGENCY_CONTROL_CENTER

    def test_node_to_dict_keys(self):
        n = Node("PS-01", "Police HQ", NodeType.POLICE_STATION)
        d = n.to_dict()
        assert set(d.keys()) == {"node_id", "name", "node_type"}
        assert d["node_type"] == NodeType.POLICE_STATION.value

    def test_blank_node_id_raises(self):
        with pytest.raises(ValueError, match="node_id"):
            Node("", "Name", NodeType.ROUTER)

    def test_blank_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            Node("R1", "   ", NodeType.ROUTER)

    def test_invalid_node_type_raises(self):
        with pytest.raises(TypeError):
            Node("X", "X", "not_a_node_type")  # type: ignore[arg-type]

    @pytest.mark.parametrize("ntype", list(NodeType))
    def test_all_node_types_accepted(self, ntype):
        n = Node(f"ID-{ntype.name}", ntype.value, ntype)
        assert n.node_type == ntype


# ─────────────────────────────────────────────────────────────────────────────
# Link tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLink:
    def test_link_defaults_to_operational(self):
        lnk = Link("A", "B", cost=2, bandwidth_mbps=50, latency_ms=10, queue_capacity=32)
        assert lnk.status == LinkStatus.OPERATIONAL
        assert lnk.is_operational is True

    def test_self_loop_raises(self):
        with pytest.raises(ValueError, match="Self-loops"):
            Link("A", "A", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError, match="cost"):
            Link("A", "B", cost=-1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)

    def test_zero_bandwidth_raises(self):
        with pytest.raises(ValueError, match="bandwidth_mbps"):
            Link("A", "B", cost=1, bandwidth_mbps=0, latency_ms=1, queue_capacity=8)

    def test_negative_latency_raises(self):
        with pytest.raises(ValueError, match="latency_ms"):
            Link("A", "B", cost=1, bandwidth_mbps=10, latency_ms=-1, queue_capacity=8)

    def test_negative_queue_capacity_raises(self):
        with pytest.raises(ValueError, match="queue_capacity"):
            Link("A", "B", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=-1)

    def test_disable_changes_status(self):
        lnk = Link("A", "B", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)
        lnk.disable()
        assert lnk.status == LinkStatus.DISABLED
        assert lnk.is_operational is False

    def test_restore_changes_status_back(self):
        lnk = Link("A", "B", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)
        lnk.disable()
        lnk.restore()
        assert lnk.status == LinkStatus.OPERATIONAL
        assert lnk.is_operational is True

    def test_link_to_dict_contains_all_keys(self):
        lnk = Link("A", "B", cost=3, bandwidth_mbps=200, latency_ms=8, queue_capacity=64)
        d = lnk.to_dict()
        expected = {"source_id", "target_id", "cost", "bandwidth_mbps",
                    "latency_ms", "queue_capacity", "status"}
        assert set(d.keys()) == expected

    def test_zero_cost_allowed(self):
        """Zero cost is valid (e.g. loopback or virtual link)."""
        lnk = Link("A", "B", cost=0, bandwidth_mbps=10, latency_ms=0, queue_capacity=0)
        assert lnk.cost == 0


# ─────────────────────────────────────────────────────────────────────────────
# EmergencyNetwork — node management
# ─────────────────────────────────────────────────────────────────────────────

class TestEmergencyNetworkNodes:
    def test_add_and_list_nodes(self, two_node_net):
        ids = [n.node_id for n in two_node_net.list_nodes()]
        assert "A" in ids and "B" in ids

    def test_get_node_returns_correct_node(self, two_node_net):
        node = two_node_net.get_node("A")
        assert node.name == "Alpha Router"

    def test_get_nonexistent_node_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.get_node("Z")

    def test_duplicate_node_raises(self, two_node_net):
        with pytest.raises(ValueError, match="already exists"):
            two_node_net.add_node(Node("A", "Another A", NodeType.ROUTER))

    def test_add_non_node_raises(self, two_node_net):
        with pytest.raises(TypeError):
            two_node_net.add_node("not-a-node")  # type: ignore[arg-type]

    def test_list_nodes_returns_list(self, two_node_net):
        assert isinstance(two_node_net.list_nodes(), list)


# ─────────────────────────────────────────────────────────────────────────────
# EmergencyNetwork — link management
# ─────────────────────────────────────────────────────────────────────────────

class TestEmergencyNetworkLinks:
    def test_add_and_get_link(self, two_node_net):
        lnk = two_node_net.get_link("A", "B")
        assert lnk.source_id == "A"
        assert lnk.target_id == "B"
        assert lnk.bandwidth_mbps == 100

    def test_list_links_count(self, two_node_net):
        assert len(two_node_net.list_links()) == 1

    def test_get_nonexistent_link_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.get_link("B", "A")   # reverse not added

    def test_link_to_unknown_source_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.add_link(
                Link("Z", "A", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)
            )

    def test_link_to_unknown_target_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.add_link(
                Link("A", "Z", cost=1, bandwidth_mbps=10, latency_ms=1, queue_capacity=8)
            )

    def test_add_non_link_raises(self, two_node_net):
        with pytest.raises(TypeError):
            two_node_net.add_link({"source": "A", "target": "B"})  # type: ignore[arg-type]

    def test_overwrite_link_replaces_it(self, two_node_net):
        """Adding a link on an existing pair overwrites the previous entry."""
        two_node_net.add_link(
            Link("A", "B", cost=99, bandwidth_mbps=1, latency_ms=100, queue_capacity=1)
        )
        assert two_node_net.get_link("A", "B").cost == 99
        assert len(two_node_net.list_links()) == 1  # still one link


# ─────────────────────────────────────────────────────────────────────────────
# EmergencyNetwork — validate_connection
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateConnection:
    def test_operational_link_is_valid(self, two_node_net):
        valid, msg = two_node_net.validate_connection("A", "B")
        assert valid is True
        assert "operational" in msg.lower()

    def test_missing_link_is_invalid(self, two_node_net):
        valid, msg = two_node_net.validate_connection("B", "A")
        assert valid is False
        assert "No link" in msg

    def test_disabled_link_is_invalid(self, two_node_net):
        two_node_net.disable_link("A", "B")
        valid, msg = two_node_net.validate_connection("A", "B")
        assert valid is False
        assert "disabled" in msg.lower()

    def test_restored_link_is_valid_again(self, two_node_net):
        two_node_net.disable_link("A", "B")
        two_node_net.restore_link("A", "B")
        valid, _ = two_node_net.validate_connection("A", "B")
        assert valid is True

    def test_unknown_source_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.validate_connection("Z", "B")

    def test_unknown_target_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.validate_connection("A", "Z")


# ─────────────────────────────────────────────────────────────────────────────
# EmergencyNetwork — get_available_neighbours
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAvailableNeighbours:
    def test_operational_neighbour_returned(self, two_node_net):
        assert two_node_net.get_available_neighbours("A") == ["B"]

    def test_no_neighbours_when_link_disabled(self, two_node_net):
        two_node_net.disable_link("A", "B")
        assert two_node_net.get_available_neighbours("A") == []

    def test_neighbour_returns_after_restore(self, two_node_net):
        two_node_net.disable_link("A", "B")
        two_node_net.restore_link("A", "B")
        assert two_node_net.get_available_neighbours("A") == ["B"]

    def test_unknown_node_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.get_available_neighbours("Z")

    def test_result_is_sorted(self):
        """Neighbours must be returned in sorted order."""
        net = EmergencyNetwork()
        for nid in ["HUB", "C", "A", "B"]:
            net.add_node(Node(nid, nid, NodeType.ROUTER))
        for tgt in ["C", "A", "B"]:
            net.add_link(Link("HUB", tgt, cost=1, bandwidth_mbps=10,
                              latency_ms=1, queue_capacity=8))
        assert net.get_available_neighbours("HUB") == ["A", "B", "C"]


# ─────────────────────────────────────────────────────────────────────────────
# EmergencyNetwork — disable / restore
# ─────────────────────────────────────────────────────────────────────────────

class TestDisableRestore:
    def test_disable_nonexistent_link_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.disable_link("B", "A")

    def test_restore_nonexistent_link_raises(self, two_node_net):
        with pytest.raises(KeyError):
            two_node_net.restore_link("B", "A")

    def test_double_disable_stays_disabled(self, two_node_net):
        two_node_net.disable_link("A", "B")
        two_node_net.disable_link("A", "B")   # idempotent
        assert not two_node_net.get_link("A", "B").is_operational

    def test_double_restore_stays_operational(self, two_node_net):
        two_node_net.disable_link("A", "B")
        two_node_net.restore_link("A", "B")
        two_node_net.restore_link("A", "B")   # idempotent
        assert two_node_net.get_link("A", "B").is_operational


# ─────────────────────────────────────────────────────────────────────────────
# Sample network invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestSampleNetwork:
    """Validate deterministic properties of build_sample_network()."""

    EXPECTED_NODE_IDS = {
        "ECC-01", "PS-01", "FS-01", "AMB-01",
        "FT-01", "SHL-01", "RTR-01", "RTR-02",
    }

    def test_all_expected_nodes_present(self, sample_net):
        ids = {n.node_id for n in sample_net.list_nodes()}
        assert self.EXPECTED_NODE_IDS.issubset(ids)

    def test_node_types_correct(self, sample_net):
        assert sample_net.get_node("ECC-01").node_type == NodeType.EMERGENCY_CONTROL_CENTER
        assert sample_net.get_node("PS-01").node_type  == NodeType.POLICE_STATION
        assert sample_net.get_node("FS-01").node_type  == NodeType.FIRE_STATION
        assert sample_net.get_node("AMB-01").node_type == NodeType.AMBULANCE_UNIT
        assert sample_net.get_node("FT-01").node_type  == NodeType.FIELD_TEAM
        assert sample_net.get_node("SHL-01").node_type == NodeType.EMERGENCY_SHELTER
        assert sample_net.get_node("RTR-01").node_type == NodeType.ROUTER

    def test_ecc_has_at_least_two_operational_neighbours(self, sample_net):
        neighbours = sample_net.get_available_neighbours("ECC-01")
        assert len(neighbours) >= 2, (
            f"ECC-01 needs ≥2 operational neighbours for redundancy; got {neighbours}"
        )

    def test_two_routes_to_fire_station_via_different_routers(self, sample_net):
        """
        Route A: ECC-01 → RTR-01 → FS-01
        Route B: ECC-01 → PS-01  → RTR-02 → FS-01
        Both paths must be operational initially.
        """
        # Route A links
        a_links = [("ECC-01", "RTR-01"), ("RTR-01", "FS-01")]
        # Route B links
        b_links = [("ECC-01", "PS-01"), ("PS-01", "RTR-02"), ("RTR-02", "FS-01")]

        for src, tgt in a_links:
            valid, msg = sample_net.validate_connection(src, tgt)
            assert valid, f"Route A link {src}→{tgt} not valid: {msg}"

        for src, tgt in b_links:
            valid, msg = sample_net.validate_connection(src, tgt)
            assert valid, f"Route B link {src}→{tgt} not valid: {msg}"

    def test_two_routes_to_ambulance_via_different_paths(self, sample_net):
        """
        Route A: ECC-01 → RTR-01 → RTR-02 → AMB-01
        Route B: ECC-01 → PS-01  → AMB-01
        """
        a_links = [("ECC-01", "RTR-01"), ("RTR-01", "RTR-02"), ("RTR-02", "AMB-01")]
        b_links = [("ECC-01", "PS-01"), ("PS-01", "AMB-01")]

        for src, tgt in a_links:
            valid, msg = sample_net.validate_connection(src, tgt)
            assert valid, f"Route A link {src}→{tgt} not valid: {msg}"

        for src, tgt in b_links:
            valid, msg = sample_net.validate_connection(src, tgt)
            assert valid, f"Route B link {src}→{tgt} not valid: {msg}"

    def test_disabled_link_excluded_from_neighbours(self, sample_net):
        """Disabling ECC-01→RTR-01 must remove RTR-01 from ECC-01's neighbours."""
        before = sample_net.get_available_neighbours("ECC-01")
        assert "RTR-01" in before

        sample_net.disable_link("ECC-01", "RTR-01")
        after = sample_net.get_available_neighbours("ECC-01")
        assert "RTR-01" not in after

    def test_restore_link_re_adds_neighbour(self, sample_net):
        sample_net.disable_link("ECC-01", "RTR-01")
        sample_net.restore_link("ECC-01", "RTR-01")
        assert "RTR-01" in sample_net.get_available_neighbours("ECC-01")

    def test_all_links_start_operational(self, sample_net):
        for lnk in sample_net.list_links():
            assert lnk.is_operational, (
                f"Link {lnk.source_id}→{lnk.target_id} expected operational at startup."
            )

    def test_link_attributes_positive(self, sample_net):
        for lnk in sample_net.list_links():
            assert lnk.cost           >= 0, f"Negative cost on {lnk.source_id}→{lnk.target_id}"
            assert lnk.bandwidth_mbps >  0, f"Zero/negative BW on {lnk.source_id}→{lnk.target_id}"
            assert lnk.latency_ms     >= 0, f"Negative latency on {lnk.source_id}→{lnk.target_id}"
            assert lnk.queue_capacity >= 0, f"Negative queue on {lnk.source_id}→{lnk.target_id}"

    def test_to_dict_structure(self, sample_net):
        d = sample_net.to_dict()
        assert "nodes" in d and "links" in d
        assert len(d["nodes"]) == len(sample_net.list_nodes())
        assert len(d["links"]) == len(sample_net.list_links())

    def test_repr_contains_counts(self, sample_net):
        r = repr(sample_net)
        assert "nodes=" in r and "links=" in r
